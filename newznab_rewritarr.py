#!/usr/bin/env python3
"""
NewznabRewritarr - Newznab Attribute Title Rewrite Proxy

A transparent HTTP forward proxy for Prowlarr that rewrites <title> elements
in newznab API responses using structured newznab:attr metadata.

Solves the problem where *arr apps (Lidarr, Readarr) only parse the <title>
field and ignore newznab:attr attributes, causing parse failures when indexers
use poorly formatted titles but provide correct metadata in attributes.

Architecture:
  Prowlarr -> [NewznabRewritarr proxy :5008] -> [optional UmlautAdaptarr :5006] -> Indexer
"""

import os
import re
import sys
import socket
import signal
import logging
import threading
import urllib.parse
import xml.etree.ElementTree as ET
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO

import requests

# ─── Configuration via Environment Variables ───────────────────────────────────

PROXY_PORT = int(os.environ.get("PROXY_PORT", "5008"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Upstream proxy (e.g., UmlautAdaptarr). Format: "host:port" or empty
UPSTREAM_PROXY = os.environ.get("UPSTREAM_PROXY", "")

# Feature toggles
REWRITE_MUSIC = os.environ.get("REWRITE_MUSIC", "true").lower() == "true"
REWRITE_BOOKS = os.environ.get("REWRITE_BOOKS", "true").lower() == "true"
REWRITE_AUDIOBOOKS = os.environ.get("REWRITE_AUDIOBOOKS", "true").lower() == "true"

# If true, also rewrites when only partial attrs are present (best-effort)
BEST_EFFORT = os.environ.get("BEST_EFFORT", "true").lower() == "true"

# If true, preserves original title as a comment attribute for debugging
DEBUG_ATTRS = os.environ.get("DEBUG_ATTRS", "false").lower() == "true"

# ─── Logging Setup ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="[%(asctime)s %(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("NewznabRewritarr")

# ─── Newznab Namespace ─────────────────────────────────────────────────────────

NEWZNAB_NS = "http://www.newznab.com/DTD/2010/feeds/attributes/"
NS_MAP = {"newznab": NEWZNAB_NS}

# Category ranges (newznab standard)
# https://inhies.github.io/Newznab-API/attributes/
AUDIO_CATEGORIES = {
    "3000", "3010", "3020", "3030", "3040", "3050", "3060",
}
AUDIOBOOK_CATEGORIES = {"3030"}  # Audiobook specifically
BOOK_CATEGORIES = {
    "7000", "7010", "7020", "7030", "7040", "7050", "7060",
    "7100", "7110", "7120", "7130",
    "8000", "8010", "8020",
}

# Quality keywords Lidarr recognizes
KNOWN_AUDIO_QUALITIES = {
    "FLAC", "MP3", "AAC", "OGG", "ALAC", "WMA", "WAV", "AIFF",
    "OPUS", "DSD", "DSD64", "DSD128", "DSD256",
    "16BIT", "24BIT", "16-BIT", "24-BIT",
    "V0", "V2", "320", "256", "192", "128",
    "LOSSLESS", "LOSSY", "WEB", "CD", "VINYL",
}

# Category → implied quality hints
CATEGORY_QUALITY_HINTS = {
    "3010": "WEB",
    "3040": "FLAC",
}

# If multiple categories are present, prefer "better/more specific" first
CATEGORY_QUALITY_PRIORITY = ["3040", "3010"]

# Deterministic scan order (sets are unordered); longest first avoids partial matches (DSD64 vs DSD)
QUALITY_SCAN_ORDER = sorted(KNOWN_AUDIO_QUALITIES, key=len, reverse=True)

# Quality keywords Readarr recognizes
KNOWN_BOOK_FORMATS = {
    "EPUB", "MOBI", "AZW3", "AZW", "PDF", "CBR", "CBZ", "FB2",
    "LIT", "LRF", "PDB", "DJVU", "DOC", "DOCX", "RTF", "TXT",
}

# ─── Title Rewrite Logic ──────────────────────────────────────────────────────

def extract_newznab_attrs(item_element: ET.Element) -> dict:
    """Extract all newznab:attr name/value pairs from an <item> element."""
    attrs = {}
    for attr_el in item_element.findall("newznab:attr", NS_MAP):
        name = attr_el.get("name", "")
        value = attr_el.get("value", "")
        if name and value:
            attrs[name.lower()] = value.strip()
    return attrs


def get_item_categories(item_element: ET.Element) -> set:
    """Get all category values for an item (from newznab:attr and <category>)."""
    cats = set()
    for attr_el in item_element.findall("newznab:attr", NS_MAP):
        if attr_el.get("name", "").lower() == "category":
            val = attr_el.get("value", "").strip()
            if val:
                cats.add(val)
    # Also check <category> elements
    for cat_el in item_element.findall("category"):
        if cat_el.text:
            cats.add(cat_el.text.strip())
    return cats


def detect_quality_from_title(title: str) -> str | None:
    """Try to extract a quality tag (FLAC, MP3, etc.) from an existing title."""
    upper = title.upper()
    for q in KNOWN_AUDIO_QUALITIES:
        # Match as whole word
        if re.search(rf'\b{re.escape(q)}\b', upper):
            return q
    return None

def find_known_audio_quality(text: str) -> str | None:
    """Return the first KNOWN_AUDIO_QUALITIES token found in text (case-insensitive)."""
    if not text:
        return None
    upper = text.upper()
    for q in QUALITY_SCAN_ORDER:
        if re.search(rf"\b{re.escape(q)}\b", upper):
            return q
    return None

def detect_quality(attrs: dict, original_title: str, categories: set[str]) -> str | None:
    """
    Quality precedence:
      1) newznab:attr audio (if it contains a known token)
      2) existing title (KNOWN_AUDIO_QUALITIES)
      3) category hint (3010→WEB, 3040→FLAC) if still missing
    """
    # 1) From newznab audio attribute (if present)
    q = find_known_audio_quality(attrs.get("audio", ""))
    if q:
        return q

    # 2) From original title
    q = detect_quality_from_title(original_title)
    if q:
        return q

    # 3) From category hint
    for cat in CATEGORY_QUALITY_PRIORITY:
        if cat in categories:
            return CATEGORY_QUALITY_HINTS.get(cat)

    # Also check any other category values present (in case you expand hints later)
    for cat in categories:
        hint = CATEGORY_QUALITY_HINTS.get(cat)
        if hint:
            return hint

    return None


def detect_book_format_from_title(title: str) -> str | None:
    """Try to extract a book format from an existing title."""
    upper = title.upper()
    for f in KNOWN_BOOK_FORMATS:
        if re.search(rf'\b{re.escape(f)}\b', upper):
            return f
    return None


def sanitize_field(value: str) -> str:
    """
    Sanitize a field value for use in a rewritten title.
    Replaces internal hyphens within a token (e.g. "Street-Legal" -> "Street Legal")
    to avoid confusing *arr parsers that split on '-'.
    """
    if not value:
        return ""

    # Normalize whitespace
    value = re.sub(r"\s+", " ", value).strip()

    # Replace hyphens/dashes that are BETWEEN word characters (letters/digits/_)
    # Examples: "Street-Legal" -> "Street Legal", "AC-DC" -> "AC DC"
    value = re.sub(r"(?<=\w)[-–—](?=\w)", " ", value)

    # Collapse whitespace again in case replacements introduced doubles
    value = re.sub(r"\s+", " ", value).strip()
    return value


def safe_hyphen_field(value: str) -> str:
    """
    Make a field safe for hyphen-delimited title format.
    Replaces standalone hyphens within the value so they don't break parsing.
    """
    # Replace " - " (spaced hyphen) with ": "
    value = value.replace(" - ", ": ")
    return value


def build_music_title(attrs: dict, original_title: str, categories: set[str]) -> str | None:
    """
    Build a Lidarr-compatible title from newznab attributes.

    Lidarr expects roughly: {Artist}-{Album}-{Quality}-{Year}
    or: {Artist} - {Album} [extra info]

    Key: Artist and Album must not contain bare hyphens that
    would be misinterpreted as field separators.
    """
    artist = attrs.get("artist", "")
    album = attrs.get("album", "")

    if not artist and not album:
        if not BEST_EFFORT:
            return None
        # Can't do anything without at least one
        return None

    artist = sanitize_field(artist)
    album = sanitize_field(album)

    # Make fields safe for hyphen-delimited parsing
    artist_safe = safe_hyphen_field(artist)
    album_safe = safe_hyphen_field(album)

    # Collect optional components
    track = attrs.get("track", "")
    if track:
        track = sanitize_field(safe_hyphen_field(track))

    # Quality: from attrs or from original title
    quality = detect_quality(attrs, original_title, categories)

    # Year: from attrs or original title
    year = attrs.get("year", "")
    if not year:
        # Try to extract 4-digit year from original title
        m = re.search(r'\b(19|20)\d{2}\b', original_title)
        if m:
            year = m.group(0)

    # Build the title
    parts = [artist_safe]

    if album:
        parts.append(album_safe)

    if track:
        parts.append(track)

    if quality:
        parts.append(quality)

    if year:
        parts.append(year)

    return "-".join(parts)


def build_book_title(attrs: dict, original_title: str) -> str | None:
    """
    Build a Readarr-compatible title from newznab attributes.

    Readarr expects roughly: {Author} - {Title} ({Year})
    """
    author = attrs.get("author", "")
    book_title = attrs.get("booktitle", "") or attrs.get("title", "") or attrs.get("album", "")

    if not author and not book_title:
        if not BEST_EFFORT:
            return None
        return None

    author = sanitize_field(author)
    book_title = sanitize_field(book_title)

    # Year
    year = attrs.get("year", "")
    if not year:
        m = re.search(r'\b(19|20)\d{2}\b', original_title)
        if m:
            year = m.group(0)

    # Book format
    fmt = detect_book_format_from_title(original_title)

    # Build
    if author and book_title:
        result = f"{author} - {book_title}"
    elif author:
        result = author
    else:
        result = book_title

    if year:
        result += f" ({year})"
    if fmt:
        result += f" {fmt}"

    return result


def build_audiobook_title(attrs: dict, original_title: str) -> str | None:
    """
    Build a Readarr-compatible audiobook title from newznab attributes.

    For audiobooks grabbed by Readarr, format:
    {Author} - {Title} ({Year})
    """
    author = attrs.get("author", "") or attrs.get("artist", "")
    title = (attrs.get("booktitle", "")
             or attrs.get("title", "")
             or attrs.get("album", ""))
    track = attrs.get("track", "")

    if not author and not title:
        return None

    author = sanitize_field(author)
    title = sanitize_field(title)

    if track:
        track = sanitize_field(track)
        # Append track info to title if it adds info
        if track.lower() not in title.lower():
            title = f"{title} {track}" if title else track

    year = attrs.get("year", "")
    if not year:
        m = re.search(r'\b(19|20)\d{2}\b', original_title)
        if m:
            year = m.group(0)

    if author and title:
        result = f"{author} - {title}"
    elif author:
        result = author
    else:
        result = title

    if year:
        result += f" ({year})"

    return result


# ─── XML Response Processing ──────────────────────────────────────────────────

def process_newznab_xml(xml_bytes: bytes) -> bytes:
    """
    Parse a newznab XML response, rewrite <title> elements using
    newznab:attr metadata, and return the modified XML.
    """
    try:
        # Register the newznab namespace to preserve it in output
        ET.register_namespace("newznab", NEWZNAB_NS)
        # Also register atom namespace if present
        ET.register_namespace("atom", "http://www.w3.org/2005/Atom")

        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        log.debug(f"Not valid XML, passing through unchanged: {e}")
        return xml_bytes

    # Check if this is a newznab response (has channel/item structure)
    channel = root.find(".//channel")
    if channel is None:
        log.debug("No <channel> element found, not a newznab response")
        return xml_bytes

    items = channel.findall("item")
    if not items:
        log.debug("No <item> elements found")
        return xml_bytes

    rewrite_count = 0

    for item in items:
        title_el = item.find("title")
        if title_el is None or not title_el.text:
            continue

        original_title = title_el.text
        attrs = extract_newznab_attrs(item)
        categories = get_item_categories(item)

        if not attrs:
            log.debug(f"No newznab:attr found for: {original_title}")
            continue

        new_title = None

        # Determine type and build rewritten title
        is_audiobook = bool(categories & AUDIOBOOK_CATEGORIES)
        is_audio = bool(categories & AUDIO_CATEGORIES)
        is_book = bool(categories & BOOK_CATEGORIES)

        if is_audiobook and REWRITE_AUDIOBOOKS:
            new_title = build_audiobook_title(attrs, original_title)
            media_type = "audiobook"
        elif is_book and REWRITE_BOOKS:
            new_title = build_book_title(attrs, original_title)
            media_type = "book"
        elif is_audio and REWRITE_MUSIC:
            new_title = build_music_title(attrs, original_title, categories)
            media_type = "music"
        else:
            log.debug(f"Categories {categories} not matched for rewrite: {original_title}")
            continue

        if new_title and new_title != original_title:
            title_el.text = new_title
            rewrite_count += 1
            log.info(f"[{media_type}] Title rewritten: '{original_title}' → '{new_title}'")

            # Optionally store original title for debugging
            if DEBUG_ATTRS:
                debug_attr = ET.SubElement(item, f"{{{NEWZNAB_NS}}}attr")
                debug_attr.set("name", "original_title")
                debug_attr.set("value", original_title)
        else:
            log.debug(f"No rewrite needed/possible for: {original_title}")

    if rewrite_count > 0:
        log.info(f"Rewrote {rewrite_count}/{len(items)} titles in response")

    # Serialize back to bytes
    return ET.tostring(root, encoding="unicode", xml_declaration=True).encode("utf-8")


# ─── HTTP Forward Proxy ───────────────────────────────────────────────────────

class ProxyHandler(BaseHTTPRequestHandler):
    """HTTP forward proxy handler for Prowlarr integration."""

    # Suppress default logging (we do our own)
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        """Handle regular HTTP GET requests (proxy mode)."""
        self._proxy_request("GET")

    def do_POST(self):
        """Handle HTTP POST requests."""
        self._proxy_request("POST")

    def do_CONNECT(self):
        """
        Handle HTTPS CONNECT tunneling.
        Warns that indexers should be set to http:// for rewriting to work.
        """
        host_port = self.path
        host = host_port.split(":")[0]

        # Known safe HTTPS hosts that don't need rewriting
        safe_hosts = {"prowlarr.servarr.com"}
        if host not in safe_hosts:
            log.warning(
                f"⚠️  HTTPS CONNECT to {host} — NewznabRewritarr cannot rewrite HTTPS traffic! "
                f"Set indexer URL to http:// in Prowlarr for rewriting to work."
            )

        # Establish tunnel
        try:
            port = int(host_port.split(":")[1]) if ":" in host_port else 443
            remote_sock = socket.create_connection((host, port), timeout=10)
            self.send_response(200, "Connection Established")
            self.end_headers()

            # Bidirectional relay
            self.connection.setblocking(False)
            remote_sock.setblocking(False)

            conns = [self.connection, remote_sock]
            import select
            while True:
                readable, _, exceptional = select.select(conns, [], conns, 30)
                if exceptional:
                    break
                for s in readable:
                    other = remote_sock if s is self.connection else self.connection
                    try:
                        data = s.recv(65536)
                        if not data:
                            return
                        other.sendall(data)
                    except (BlockingIOError, ConnectionError):
                        return
        except Exception as e:
            log.error(f"CONNECT tunnel error for {host_port}: {e}")
            self.send_error(502, f"Bad Gateway: {e}")
        finally:
            try:
                remote_sock.close()
            except Exception:
                pass

    def _proxy_request(self, method: str):
        """Forward an HTTP request, optionally through upstream proxy."""
        target_url = self.path

        # Validate it's an absolute URL (proxy request)
        if not target_url.startswith("http://") and not target_url.startswith("https://"):
            self.send_error(400, "Not a proxy request (relative URL)")
            return

        # Redact API key for logging
        log_url = redact_apikey(target_url)
        log.debug(f"Proxying {method} {log_url}")

        try:
            # Build headers (forward relevant ones)
            headers = {}
            for key in self.headers:
                lower = key.lower()
                if lower in ("host", "proxy-connection", "proxy-authorization"):
                    continue
                headers[key] = self.headers[key]

            # Read body if POST
            body = None
            if method == "POST":
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length > 0:
                    body = self.rfile.read(content_length)

            # Configure upstream proxy if set
            proxies = None
            if UPSTREAM_PROXY:
                proxies = {
                    "http": f"http://{UPSTREAM_PROXY}",
                    "https": f"http://{UPSTREAM_PROXY}",
                }
                log.debug(f"Using upstream proxy: {UPSTREAM_PROXY}")

            # Make the request
            resp = requests.request(
                method=method,
                url=target_url,
                headers=headers,
                data=body,
                proxies=proxies,
                timeout=60,
                allow_redirects=True,
                stream=False,
            )

            # Determine if this is a newznab XML response we should process
            content_type = resp.headers.get("Content-Type", "")
            response_body = resp.content

            is_xml = ("xml" in content_type or
                      "rss" in content_type or
                      response_body[:200].strip().startswith(b"<?xml") or
                      response_body[:200].strip().startswith(b"<rss"))

            is_newznab_api = ("t=" in target_url and
                              any(x in target_url for x in [
                                  "t=search", "t=tvsearch", "t=music",
                                  "t=book", "t=movie", "t=caps",
                              ]))

            if is_xml and is_newznab_api and "t=caps" not in target_url:
                log.debug(f"Processing newznab XML response ({len(response_body)} bytes)")
                try:
                    response_body = process_newznab_xml(response_body)
                except Exception as e:
                    log.error(f"XML processing error, returning original: {e}")

            # Send response
            self.send_response(resp.status_code)
            # Forward response headers
            skip_headers = {"transfer-encoding", "content-length", "content-encoding", "connection"}
            for key, value in resp.headers.items():
                if key.lower() not in skip_headers:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

        except requests.exceptions.Timeout:
            log.error(f"Timeout proxying: {log_url}")
            self.send_error(504, "Gateway Timeout")
        except requests.exceptions.ConnectionError as e:
            log.error(f"Connection error proxying {log_url}: {e}")
            self.send_error(502, f"Bad Gateway: {e}")
        except Exception as e:
            log.error(f"Error proxying {log_url}: {e}")
            self.send_error(500, f"Internal Server Error: {e}")


def redact_apikey(url: str) -> str:
    """Redact API key from URL for safe logging."""
    return re.sub(r'(apikey=)[^&]+', r'\1***', url, flags=re.IGNORECASE)


# ─── Server ───────────────────────────────────────────────────────────────────

class ThreadingHTTPServer(HTTPServer):
    """Threaded HTTP server for concurrent request handling."""
    allow_reuse_address = True
    daemon_threads = True

    def process_request(self, request, client_address):
        thread = threading.Thread(target=self._handle, args=(request, client_address))
        thread.daemon = True
        thread.start()

    def _handle(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


LOGO = r"""
 _   _                              _     ____                _ _
| \ | | _____      _______ _ __   _| |__ |  _ \ _____      _(_) |_ __ _ _ __ _ __
|  \| |/ _ \ \ /\ / /_  / '_ \ / _` | '_ \| |_) / _ \ \ /\ / / | __/ _` | '__| '__|
| |\  |  __/\ V  V / / /| | | | (_| | |_) |  _ <  __/\ V  V /| | || (_| | |  | |
|_| \_|\___| \_/\_/ /___|_| |_|\__,_|_.__/|_| \_\___| \_/\_/ |_|\__\__,_|_|  |_|
"""


def main():
    print(LOGO)
    log.info(f"NewznabRewritarr v1.0.0")
    log.info(f"Proxy port:       {PROXY_PORT}")
    log.info(f"Upstream proxy:   {UPSTREAM_PROXY or 'none (direct)'}")
    log.info(f"Rewrite music:    {REWRITE_MUSIC}")
    log.info(f"Rewrite books:    {REWRITE_BOOKS}")
    log.info(f"Rewrite audiobooks: {REWRITE_AUDIOBOOKS}")
    log.info(f"Best effort:      {BEST_EFFORT}")
    log.info(f"Debug attrs:      {DEBUG_ATTRS}")
    log.info(f"Log level:        {LOG_LEVEL}")
    log.info(f"─" * 60)

    server = ThreadingHTTPServer(("0.0.0.0", PROXY_PORT), ProxyHandler)

    def shutdown(sig, frame):
        log.info("Shutting down...")
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info(f"HTTP proxy listening on 0.0.0.0:{PROXY_PORT}")
    log.info("Configure in Prowlarr: Settings → Indexers → Add HTTP Proxy")
    log.info(f"  Host: newznabrewritarr (or container IP)")
    log.info(f"  Port: {PROXY_PORT}")
    log.info(f"  Tag:  newznabrewritarr")
    log.info(f"Then assign the tag to your indexers (set URL to http://)")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        log.info("Server stopped.")


if __name__ == "__main__":
    main()
