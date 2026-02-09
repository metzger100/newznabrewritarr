#!/usr/bin/env python3
"""
Tests for NewznabRewritarr title rewrite logic.
Run: python -m pytest test_rewrite.py -v
or:  python test_rewrite.py
"""

import xml.etree.ElementTree as ET
from newznab_rewritarr import (
    process_newznab_xml,
    build_music_title,
    build_book_title,
    build_audiobook_title,
    extract_newznab_attrs,
    detect_quality_from_title,
    safe_hyphen_field,
)

# ─── Sample newznab XML (based on user's real example) ─────────────────────────

SAMPLE_MUSIC_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">
  <channel>
    <title>Test Indexer</title>
    <item>
      <title>Beispiel-Firma GmbH-Cybercast-Folge 19: Securing an Austrian Silicon Fab-FLAC-2017</title>
      <guid>https://indexer.example.com/details/798d4debe1360a81ca03e4d54419ddfb</guid>
      <category>3000</category>
      <newznab:attr name="category" value="3000"/>
      <newznab:attr name="size" value="316887082"/>
      <newznab:attr name="guid" value="798d4debe1360a81ca03e4d54419ddfb"/>
      <newznab:attr name="sha1" value="59a8d58dc988b22715c6a861d840c9997cd4a714"/>
      <newznab:attr name="files" value="16"/>
      <newznab:attr name="season" value="-1"/>
      <newznab:attr name="episode" value="-1"/>
      <newznab:attr name="album" value="Cybercast"/>
      <newznab:attr name="artist" value="Tatjana Schaumberger"/>
      <newznab:attr name="publisher" value="Beispiel-Firma GmbH"/>
      <newznab:attr name="track" value="Folge 19: Securing an Austrian Silicon Fab"/>
      <newznab:attr name="coverurl" value=""/>
      <newznab:attr name="comments" value="0"/>
      <newznab:attr name="password" value="-1"/>
      <newznab:attr name="nfo" value="1"/>
      <newznab:attr name="info" value=""/>
    </item>
  </channel>
</rss>"""

SAMPLE_BOOK_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">
  <channel>
    <title>Test Indexer</title>
    <item>
      <title>Cybersecurity Report in automotive Industry</title>
      <guid>https://indexer.example.com/details/abc123</guid>
      <category>7020</category>
      <newznab:attr name="category" value="7020"/>
      <newznab:attr name="author" value="Max Mustermann"/>
      <newznab:attr name="booktitle" value="Cybersecurity Report in Automotive Industry"/>
      <newznab:attr name="year" value="2025"/>
    </item>
  </channel>
</rss>"""

SAMPLE_AUDIOBOOK_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">
  <channel>
    <title>Test Indexer</title>
    <item>
      <title>SomeBadTitle-Verlag-Mein Buch-2024</title>
      <guid>https://indexer.example.com/details/def456</guid>
      <category>3030</category>
      <newznab:attr name="category" value="3030"/>
      <newznab:attr name="artist" value="Anna Schmidt"/>
      <newznab:attr name="album" value="Das große Abenteuer"/>
      <newznab:attr name="track" value="Kapitel 1-20"/>
    </item>
  </channel>
</rss>"""

SAMPLE_MULTI_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:newznab="http://www.newznab.com/DTD/2010/feeds/attributes/">
  <channel>
    <title>Test Indexer</title>
    <item>
      <title>Bad-Title-Music-FLAC-2020</title>
      <category>3000</category>
      <newznab:attr name="category" value="3000"/>
      <newznab:attr name="artist" value="Die Toten Hosen"/>
      <newznab:attr name="album" value="Alles ohne Strom"/>
    </item>
    <item>
      <title>No attrs here just a normal title</title>
      <category>3000</category>
      <newznab:attr name="category" value="3000"/>
    </item>
    <item>
      <title>Some-Publisher-BookTitle-EPUB</title>
      <category>7020</category>
      <newznab:attr name="category" value="7020"/>
      <newznab:attr name="author" value="Friedrich Dürrenmatt"/>
      <newznab:attr name="booktitle" value="Der Besuch der alten Dame"/>
      <newznab:attr name="year" value="1956"/>
    </item>
  </channel>
</rss>"""


def test_music_rewrite_user_example():
    """Test the user's exact Lidarr problem case."""
    result = process_newznab_xml(SAMPLE_MUSIC_XML.encode("utf-8"))
    root = ET.fromstring(result)
    title = root.find(".//item/title").text

    print(f"  Music rewrite: '{title}'")

    # Must contain correct artist
    assert "Tatjana Schaumberger" in title
    # Must contain album
    assert "Cybercast" in title
    # Must contain track info
    assert "Folge 19" in title
    # Must contain quality
    assert "FLAC" in title
    # Must contain year
    assert "2017" in title
    # Must NOT have "Beispiel-Firma GmbH" confusing the parser
    assert "Beispiel-Firma GmbH" not in title

    print("  ✅ Music rewrite OK")


def test_book_rewrite():
    """Test Readarr book title rewrite."""
    result = process_newznab_xml(SAMPLE_BOOK_XML.encode("utf-8"))
    root = ET.fromstring(result)
    title = root.find(".//item/title").text

    print(f"  Book rewrite: '{title}'")

    assert "Max Mustermann" in title
    assert "Cybersecurity Report" in title
    assert "2025" in title

    print("  ✅ Book rewrite OK")


def test_audiobook_rewrite():
    """Test audiobook title rewrite."""
    result = process_newznab_xml(SAMPLE_AUDIOBOOK_XML.encode("utf-8"))
    root = ET.fromstring(result)
    title = root.find(".//item/title").text

    print(f"  Audiobook rewrite: '{title}'")

    assert "Anna Schmidt" in title
    assert "Das große Abenteuer" in title
    # Should NOT have broken title
    assert "SomeBadTitle" not in title

    print("  ✅ Audiobook rewrite OK")


def test_multi_item_processing():
    """Test that multiple items are processed correctly."""
    result = process_newznab_xml(SAMPLE_MULTI_XML.encode("utf-8"))
    root = ET.fromstring(result)
    items = root.findall(".//item")

    titles = [item.find("title").text for item in items]
    print(f"  Multi titles: {titles}")

    # First item (music) should be rewritten
    assert "Die Toten Hosen" in titles[0]
    assert "Alles ohne Strom" in titles[0]

    # Second item (no attrs) should be unchanged
    assert titles[1] == "No attrs here just a normal title"

    # Third item (book) should be rewritten
    assert "Friedrich Dürrenmatt" in titles[2]
    assert "Der Besuch der alten Dame" in titles[2]

    print("  ✅ Multi-item processing OK")


def test_non_xml_passthrough():
    """Test that non-XML content is passed through unchanged."""
    data = b"This is not XML at all"
    result = process_newznab_xml(data)
    assert result == data
    print("  ✅ Non-XML passthrough OK")


def test_safe_hyphen_field():
    """Test that internal hyphens are handled."""
    assert safe_hyphen_field("Beispiel-Firma GmbH") == "Beispiel-Firma GmbH"
    assert safe_hyphen_field("Some - Thing") == "Some: Thing"
    print("  ✅ safe_hyphen_field OK")


def test_quality_detection():
    """Test quality keyword detection from titles."""
    assert detect_quality_from_title("Something-FLAC-2020") == "FLAC"
    assert detect_quality_from_title("Something-MP3-320") == "MP3"
    assert detect_quality_from_title("No quality here") is None
    print("  ✅ Quality detection OK")


def test_build_music_title_basic():
    """Test music title construction."""
    attrs = {
        "artist": "Test Artist",
        "album": "Test Album",
    }
    result = build_music_title(attrs, "Original-Title-FLAC-2020")
    print(f"  Music title: '{result}'")
    assert result is not None
    assert "Test Artist" in result
    assert "Test Album" in result
    assert "FLAC" in result
    assert "2020" in result
    print("  ✅ build_music_title OK")


def test_build_book_title_basic():
    """Test book title construction."""
    attrs = {
        "author": "Test Author",
        "booktitle": "Test Book Title",
        "year": "2023",
    }
    result = build_book_title(attrs, "Original-EPUB")
    print(f"  Book title: '{result}'")
    assert result is not None
    assert "Test Author" in result
    assert "Test Book Title" in result
    assert "2023" in result
    assert "EPUB" in result
    print("  ✅ build_book_title OK")


if __name__ == "__main__":
    print("=" * 60)
    print("NewznabRewritarr — Unit Tests")
    print("=" * 60)

    tests = [
        test_music_rewrite_user_example,
        test_book_rewrite,
        test_audiobook_rewrite,
        test_multi_item_processing,
        test_non_xml_passthrough,
        test_safe_hyphen_field,
        test_quality_detection,
        test_build_music_title_basic,
        test_build_book_title_basic,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            print(f"\n🧪 {t.__name__}:")
            t()
            passed += 1
        except Exception as e:
            print(f"  ❌ FAILED: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed == 0:
        print("🎉 All tests passed!")
    else:
        print("⚠️  Some tests failed!")
        exit(1)
