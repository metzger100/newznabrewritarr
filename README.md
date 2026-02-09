# NewznabRewritarr

> Newznab Attribute Title Rewrite Proxy für Prowlarr / Lidarr / Readarr

**NewznabRewritarr** löst das Problem, dass Lidarr und Readarr nur das `<title>`-Feld aus Newznab-API-Antworten parsen und die `newznab:attr`-Metadaten (artist, album, author, booktitle, track, …) komplett ignorieren.  

Wenn der Indexer schlecht benannte Titel liefert, aber korrekte Metadaten in den `newznab:attr`-Attributen hat, baut NewznabRewritarr den Titel aus diesen Attributen neu zusammen — so dass die \*arrs ihn korrekt parsen können.

---

## Das Problem

```
# Indexer liefert diesen Titel:
Beispiel-Firma GmbH-Cybercast-Folge 19: Securing an Austrian Silicon Fab-FLAC-2017

# Lidarr versucht zu parsen:
ParsingService|Trying inexact company match for "Beispiel"
ParsingService|No matching company "Beispiel"
→ Release wird rejected!

# Aber die newznab:attr enthalten alle korrekten Infos:
<newznab:attr name="artist" value="Tatjana Schaumberger"/>
<newznab:attr name="album" value="Cybercast"/>
<newznab:attr name="track" value="Folge 19: Securing an Austrian Silicon Fab"/>
```

## Die Lösung

NewznabRewritarr schaltet sich als HTTP-Proxy zwischen Prowlarr und den Indexer und schreibt den Titel anhand der Attribute um:

```
# Vorher (vom Indexer):
Beispiel-Firma GmbH-Cybercast-Folge 19: Securing an Austrian Silicon Fab-FLAC-2017

# Nachher (von NewznabRewritarr):
Tatjana Schaumberger-Cybercast-Folge 19: Securing an Austrian Silicon Fab-FLAC-2017
                                         ↑ Lidarr erkennt jetzt Artist + Album korrekt!
```

Für **Bücher** (Readarr):
```
# Vorher: Cybersecurity Report in automotive Industry
# Nachher: Max Mustermann - Cybersecurity Report in Automotive Industry (2025)
```

---

## Features

| Feature | Status |
|---|---|
| Prowlarr HTTP-Proxy-Integration (Tag-basiert) | ✅ |
| Lidarr: Musik-Titel aus newznab:attr | ✅ |
| Readarr: Buch-Titel aus newznab:attr | ✅ |
| Readarr: Hörbuch-Titel aus newznab:attr | ✅ |
| Verkettung mit UmlautAdaptarr | ✅ |
| Qualitäts-Erkennung (FLAC, MP3, EPUB, …) | ✅ |
| Zero-Config Docker Compose | ✅ |
| Newznab + Torznab Support | ✅ |

---

## Installation

### Docker Compose

```yaml
services:
  newznab-rewritarr:
    build: .
    container_name: newznab-rewritarr
    restart: unless-stopped
    ports:
      - "5008:5008"
    environment:
      - TZ=Europe/Berlin
      - PROXY_PORT=5008
      # Verkettung mit UmlautAdaptarr (optional):
      - UPSTREAM_PROXY=umlautadaptarr:5006
      # Feature Toggles:
      - REWRITE_MUSIC=true
      - REWRITE_BOOKS=true
      - REWRITE_AUDIOBOOKS=true
      - LOG_LEVEL=INFO
```

### Ohne Docker

```bash
pip install requests
python newznab_rewritarr.py
```

---

## Konfiguration in Prowlarr

### Schritt 1: HTTP-Proxy anlegen

In Prowlarr: **Settings → Indexers → ➕ Add (HTTP Proxy)**

| Feld | Wert |
|---|---|
| Name | `NewznabRewritarr` |
| Host | `newznab-rewritarr` (oder Container-IP) |
| Port | `5008` |
| Tag | `newznab-rewritarr` |
| Username | *(leer lassen)* |
| Password | *(leer lassen)* |

### Schritt 2: Tag an Indexer zuweisen

Für jeden Indexer, bei dem die Titel umgeschrieben werden sollen:

1. Indexer bearbeiten
2. Tag `newznab-rewritarr` hinzufügen
3. **Wichtig:** URL von `https://` auf `http://` ändern (nötig damit der Proxy den Traffic lesen kann)
4. Speichern

### Schritt 3: Testen

1. "Test All Indexers" klicken
2. In den NewznabRewritarr-Logs sollte der Traffic sichtbar sein
3. Eine Suche in Lidarr/Readarr durchführen und die umgeschriebenen Titel prüfen

---

## Verkettung mit UmlautAdaptarr

NewznabRewritarr lässt sich nahtlos mit UmlautAdaptarr verketten. Der Request-Flow sieht dann so aus:

```
Prowlarr
  │
  ├─ HTTP Proxy Tag: "newznab-rewritarr"
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
  ▼ (Response fließt zurück)
  │
UmlautAdaptarr  ← Umlaut-Korrekturen, deutsche Titel
  │
NewznabRewritarr ← newznab:attr Title-Rewrite
  │
Prowlarr → Lidarr/Readarr ← korrekter Titel!
```

### Setup für die Verkettung:

1. **NewznabRewritarr** `docker-compose.yml`:
   ```yaml
   environment:
     - UPSTREAM_PROXY=umlautadaptarr:5006
   ```

2. In **Prowlarr**:
   - **Nur** den Tag `newznab-rewritarr` verwenden (nicht `umlautadaptarr`)
   - Der UmlautAdaptarr-Proxy-Eintrag kann bestehen bleiben, wird aber nicht mehr per Tag zugewiesen
   - Indexer-URLs auf `http://` setzen

3. **UmlautAdaptarr** bleibt unverändert konfiguriert (Sonarr/Lidarr/Readarr API-Keys, etc.)

> **Hinweis:** Wenn du UmlautAdaptarr nicht brauchst, einfach `UPSTREAM_PROXY` leer lassen oder entfernen. NewznabRewritarr funktioniert auch standalone.

---

## Umgebungsvariablen

| Variable | Default | Beschreibung |
|---|---|---|
| `PROXY_PORT` | `5008` | Port für den HTTP-Proxy |
| `UPSTREAM_PROXY` | *(leer)* | Upstream-Proxy, z.B. `umlautadaptarr:5006` |
| `REWRITE_MUSIC` | `true` | Musik-Titel umschreiben (Lidarr, Kategorie 3000+) |
| `REWRITE_BOOKS` | `true` | Buch-Titel umschreiben (Readarr, Kategorie 7000+) |
| `REWRITE_AUDIOBOOKS` | `true` | Hörbuch-Titel umschreiben (Kategorie 3030) |
| `BEST_EFFORT` | `true` | Auch bei unvollständigen Attributen umschreiben |
| `DEBUG_ATTRS` | `false` | Original-Titel als `newznab:attr` speichern |
| `LOG_LEVEL` | `INFO` | Log-Level: DEBUG, INFO, WARNING, ERROR |

---

## Unterstützte newznab:attr Attribute

### Musik (Lidarr)
| Attribut | Verwendung |
|---|---|
| `artist` | → Artist-Feld im Titel |
| `album` | → Album-Feld im Titel |
| `track` | → Track-Info im Titel |
| `year` | → Jahr im Titel |
| *(Quality aus Original-Titel)* | → FLAC, MP3, etc. |

### Bücher (Readarr)
| Attribut | Verwendung |
|---|---|
| `author` | → Author-Feld im Titel |
| `booktitle` / `title` | → Buchtitel |
| `year` | → Jahr in Klammern |
| *(Format aus Original-Titel)* | → EPUB, PDF, etc. |

### Hörbücher (Readarr)
| Attribut | Verwendung |
|---|---|
| `author` / `artist` | → Author-Feld |
| `album` / `booktitle` | → Titel |
| `track` | → Zusatzinfo (Kapitel, Folge) |
| `year` | → Jahr |

Vollständige Newznab-Attribut-Spezifikation: https://inhies.github.io/Newznab-API/attributes/

---

## Titel-Rewrite Beispiele

### Musik (Lidarr)
```
VORHER:  Beispiel-Firma GmbH-Cybercast-Folge 19: Securing an Austrian Silicon Fab-FLAC-2017
NACHHER: Tatjana Schaumberger-Cybercast-Folge 19: Securing an Austrian Silicon Fab-FLAC-2017

VORHER:  Bad-Title-Music-FLAC-2020
NACHHER: Die Toten Hosen-Alles ohne Strom-FLAC-2020
```

### Bücher (Readarr)
```
VORHER:  Cybersecurity Report in automotive Industry
NACHHER: Max Mustermann - Cybersecurity Report in Automotive Industry (2025)

VORHER:  Some-Publisher-BookTitle-EPUB
NACHHER: Friedrich Dürrenmatt - Der Besuch der alten Dame (1956) EPUB
```

### Hörbücher
```
VORHER:  SomeBadTitle-Verlag-Mein Buch-2024
NACHHER: Anna Schmidt - Das große Abenteuer Kapitel 1-20 (2024)
```

---

## Tests

```bash
python test_rewrite.py
```

```
🧪 test_music_rewrite_user_example:
  Music rewrite: 'Tatjana Schaumberger-Cybercast-Folge 19: ...-FLAC-2017'
  ✅ Music rewrite OK

🧪 test_book_rewrite:
  Book rewrite: 'Max Mustermann - Cybersecurity Report in Automotive Industry (2025)'
  ✅ Book rewrite OK

🎉 All tests passed!
```

---

## Troubleshooting

### Titel werden nicht umgeschrieben
1. Prüfe ob der Indexer in Prowlarr auf `http://` (nicht `https://`) steht
2. Prüfe ob der Tag `newznab-rewritarr` am Indexer zugewiesen ist
3. Setze `LOG_LEVEL=DEBUG` und prüfe die Container-Logs
4. Prüfe ob der Indexer überhaupt `newznab:attr` liefert (Prowlarr API-Link testen)

### UmlautAdaptarr-Verkettung funktioniert nicht
1. Prüfe ob beide Container im gleichen Docker-Netzwerk sind
2. Prüfe ob `UPSTREAM_PROXY=umlautadaptarr:5006` korrekt gesetzt ist
3. In Prowlarr: **Nur** den `newznab-rewritarr` Tag verwenden, nicht beide Tags

### Lidarr/Readarr rejected weiterhin
- Prüfe die Lidarr/Readarr-Logs: wird der umgeschriebene Titel jetzt korrekt geparst?
- `DEBUG_ATTRS=true` setzen und in der API-Antwort den `original_title` Attribut prüfen

---

## Lizenz

MIT
