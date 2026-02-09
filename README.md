# NewznabRewritarr

> Newznab Attribute Title Rewrite Proxy for Prowlarr / Lidarr / Readarr

**NewznabRewritarr** solves the problem that Lidarr and Readarr only parse the `<title>` field from Newznab API responses and completely ignore the `newznab:attr` metadata (artist, album, author, booktitle, track, …).

If an indexer returns poorly formatted titles but provides correct metadata in `newznab:attr` attributes, NewznabRewritarr rebuilds the title from those attributes so the *arr apps can parse it correctly. This is not a clean solution.

For Example in the case the quality is not available in the title or audio `newznab:attr` it puts WEB or FLAC in the Title based on the `newznab:attr` [category](https://inhies.github.io/Newznab-API/categories/). It is not guaranteed that the the quality is good. But at least you know if it is a LOSSLESS or a LOSSY Audio.

---

## The Problem

Indexer returns this title:
```
Example-Company GmbH-Cybercast-Episode 19: Securing an Austrian Silicon Fab-FLAC-2017
```

Lidarr tries to parse:
```
ParsingService|Trying inexact company match for "Example"
ParsingService|No matching company "Example"
```
→ Release is rejected!

But the newznab:attr contain all the correct info:
```
<newznab:attr name="artist" value="Tatjana Schaumberger"/>
<newznab:attr name="album" value="Cybercast"/>
<newznab:attr name="track" value="Episode 19: Securing an Austrian Silicon Fab"/>
```

## The Solution

NewznabRewritarr inserts itself as an HTTP proxy between Prowlarr and the indexer and rewrites the title based on the attributes:

```
# Before (from the indexer):
Example-Company GmbH-Cybercast-Episode 19: Securing an Austrian Silicon Fab-FLAC-2017

# After (from NewznabRewritarr):
Tatjana Schaumberger-Cybercast-Episode 19: Securing an Austrian Silicon Fab-FLAC-2017
                                      ↑ Lidarr now recognizes Artist + Album correctly!
```

For **books** (Readarr):

```
# Before: Cybersecurity Report in automotive Industry
# After:  Max Mustermann - Cybersecurity Report in Automotive Industry (2025)
```

---

## Features

| Feature                                              | Status |
| ---------------------------------------------------- | ------ |
| Prowlarr HTTP proxy integration (tag-based)          | ✅      |
| Lidarr: music title rewriting from newznab:attr      | ✅      |
| Readarr: book title rewriting from newznab:attr      | ✅      |
| Readarr: audiobook title rewriting from newznab:attr | ✅      |
| Chaining with UmlautAdaptarr                         | ✅      |
| Quality detection (FLAC, MP3, EPUB, …)               | ✅      |
| Zero-config Docker Compose                           | ✅      |
| Newznab support                                      | ✅      |

---

## Installation

### Docker Compose

```yaml
services:
  newznabrewritarr:
    build: . # Folder path to the Dockerfile
    container_name: newznabrewritarr
    restart: unless-stopped
    ports:
      - "5008:5008"
    environment:
      - TZ=Europe/Berlin
      - PROXY_PORT=5008
      # Chaining with UmlautAdaptarr (optional):
      - UPSTREAM_PROXY=umlautadaptarr:5006
      # Feature toggles:
      - REWRITE_MUSIC=true
      - REWRITE_BOOKS=true
      - REWRITE_AUDIOBOOKS=true
      - LOG_LEVEL=INFO
```

### Without Docker

```bash
pip install requests
python newznab_rewritarr.py
```

---

## Configuration in Prowlarr

### Step 1: Create an HTTP proxy entry

In Prowlarr: **Settings → Indexers → ➕ Add (HTTP Proxy)**

| Field    | Value                                |
| -------- | ------------------------------------ |
| Name     | `NewznabRewritarr`                   |
| Host     | `newznabrewritarr` (or container IP) |
| Port     | `5008`                               |
| Tag      | `newznabrewritarr`                   |
| Username | *(leave empty)*                      |
| Password | *(leave empty)*                      |

### Step 2: Assign the tag to indexers

For each indexer where titles should be rewritten:

1. Edit the indexer
2. Add the tag `newznabrewritarr`
3. **Important:** Change the URL from `https://` to `http://` (required so the proxy can read the traffic)
4. Save

### Step 3: Test

1. Click “Test All Indexers”
2. In the NewznabRewritarr logs you should see traffic
3. Run a search in Lidarr/Readarr and verify the rewritten titles

---

## Chaining with UmlautAdaptarr

NewznabRewritarr can be seamlessly chained with UmlautAdaptarr. The request flow looks like this:

```
Prowlarr
  │
  ├─ HTTP proxy tag: "newznabrewritarr"
  │
  ▼
NewznabRewritarr (:5008)
  │
  ├─ UPSTREAM_PROXY=umlautadaptarr:5006
  │
  ▼
UmlautAdaptarr (:5006)
  │
  ▼
Indexer (http://)
  │
  ▼ (response flows back)
  │
UmlautAdaptarr   ← umlaut fixes, German titles
  │
NewznabRewritarr  ← newznab:attr title rewrite
  │
Prowlarr → Lidarr/Readarr ← correct title!
```

### Setup for chaining

1. **NewznabRewritarr** `docker-compose.yml`:

   ```yaml
   environment:
     - UPSTREAM_PROXY=umlautadaptarr:5006
   ```

2. In **Prowlarr**:

   * Use **only** the tag `newznabrewritarr` (not `umlautadaptarr`)
   * The UmlautAdaptarr proxy entry may remain, but should no longer be assigned via tags
   * Set indexer URLs to `http://`

3. **UmlautAdaptarr** remains configured as before (Sonarr/Lidarr/Readarr API keys, etc.)

> **Note:** If you don’t need UmlautAdaptarr, just leave `UPSTREAM_PROXY` empty or remove it. NewznabRewritarr also works standalone.

---

## Environment variables

| Variable             | Default   | Description                                   |
| -------------------- | --------- | --------------------------------------------- |
| `PROXY_PORT`         | `5008`    | Port for the HTTP proxy                       |
| `UPSTREAM_PROXY`     | *(empty)* | Upstream proxy, e.g. `umlautadaptarr:5006`    |
| `REWRITE_MUSIC`      | `true`    | Rewrite music titles (Lidarr, category 3000+) |
| `REWRITE_BOOKS`      | `true`    | Rewrite book titles (Readarr, category 7000+) |
| `REWRITE_AUDIOBOOKS` | `true`    | Rewrite audiobook titles (category 3030)      |
| `BEST_EFFORT`        | `true`    | Rewrite even with incomplete attributes       |
| `DEBUG_ATTRS`        | `false`   | Store the original title as a `newznab:attr`  |
| `LOG_LEVEL`          | `INFO`    | Log level: DEBUG, INFO, WARNING, ERROR        |

---

## Supported newznab:attr attributes

### Music (Lidarr)

| Attribute                       | Usage                   |
| ------------------------------- | ----------------------- |
| `artist`                        | → artist field in title |
| `album`                         | → album field in title  |
| `track`                         | → track info in title   |
| `year`                          | → year in title         |
| `audio` or title or category    | → FLAC, MP3, etc.       |

### Books (Readarr)

| Attribute                      | Usage                   |
| ------------------------------ | ----------------------- |
| `author`                       | → author field in title |
| `booktitle` / `title`          | → book title            |
| `year`                         | → year in parentheses   |
| *(format from original title)* | → EPUB, PDF, etc.       |

### Audiobooks (Readarr)

| Attribute             | Usage                                |
| --------------------- | ------------------------------------ |
| `author` / `artist`   | → author field                       |
| `album` / `booktitle` | → title                              |
| `track`               | → additional info (chapter, episode) |
| `year`                | → year                               |

Full Newznab attribute specification: [https://inhies.github.io/Newznab-API/attributes/](https://inhies.github.io/Newznab-API/attributes/)

---

## Title rewrite examples

### Music (Lidarr)

```
BEFORE: Example-Company GmbH-Cybercast-Episode 19: Securing an Austrian Silicon Fab-FLAC-2017
AFTER:  Tatjana Schaumberger-Cybercast-Episode 19: Securing an Austrian Silicon Fab-FLAC-2017

BEFORE: Bad-Title-Music-2020
AFTER:  Die Toten Hosen-Alles ohne Strom-FLAC-2020
```

### Books (Readarr)

```
BEFORE: Some-Publisher-BookTitle-EPUB
AFTER:  Friedrich Dürrenmatt - The Visit (1956) EPUB
```

### Audiobooks

```
BEFORE: SomeBadTitle-Publisher-My Book-2024
AFTER:  Anna Schmidt - The Great Adventure Chapter 1-20 (2024)
```

---

## Troubleshooting

### Titles are not being rewritten

1. Verify the indexer in Prowlarr is set to `http://` (not `https://`)
2. Verify the tag `newznabrewritarr` is assigned to the indexer
3. Set `LOG_LEVEL=DEBUG` and check the container logs
4. Verify the indexer actually returns `newznab:attr` (test the Prowlarr API endpoint)

### UmlautAdaptarr chaining does not work

1. Verify both containers are in the same Docker network
2. Verify `UPSTREAM_PROXY=umlautadaptarr:5006` is set correctly
3. In Prowlarr: use **only** the `newznabrewritarr` tag, not both tags

### Lidarr/Readarr still rejects releases

* Check Lidarr/Readarr logs: is the rewritten title parsed correctly now?
* Set `DEBUG_ATTRS=true` and verify the `original_title` attribute in the API response

---
