# haystacked -- PoC Offline-Integration Spezifikation

**Fokus:** Offline-Demo-Betrieb - Airtable-Export, lokale DB, Matching-Engine, Frontend
**Version:** 1.5 (Mai 2026)
**Aenderungen vs. v1.4:** AP-D1 Data-Driven Matching Engine implementiert.
  Matching-Operatoren aus Python in AP0 xlsx ausgelagert. matching.py ist jetzt
  eine generische Rule Engine ohne Domaenwissen. Neue Industrien koennen durch
  eine neue AP0-Tabelle hinzugefuegt werden, ohne Python zu beruehren.
  vna_not_required-Flag durch KO_BOOL_EXCLUSIVE-Operator ersetzt.
**Aenderungen vs. v1.3:** LL-10 (VNA bidirektionale Exklusionslogik) eingefuegt;
  NULL-KO-Penalty fuer fehlende Pflichtfelder; navigation_type auf Cond. K.O. umgestellt.
**Aenderungen vs. v1.2:** navigation_type und infrastructure_required von KO → COND_KO;
  VNA-Fallback-Logik fuer fehlende lifting_height_mm dokumentiert;
  neues AP-C1 (Human-in-the-Loop Clarification Step) mit Testpfad eingefuegt.
**Aenderungen vs. v1.1:** Lessons Learned aus PoC v1 eingearbeitet (LLM-Pipeline, JSON-Parser,
  K.O.-Logik, Windows-ASCII, pandas entfernt, Keyword-Fallback, num_ctx)
**Fuer:** Claude Code Session
**Vertraulich**

---

## Abkuerzungsverzeichnis

- PoC = Proof of Concept
- AP = Arbeitspaket
- DB = Datenbank
- CSV = Comma-Separated Values
- UUID = Universally Unique Identifier
- K.O. = Knockout
- Cond. = Conditional (bedingt)
- AGV = Automated Guided Vehicle
- AMR = Autonomous Mobile Robot
- FK = Foreign Key
- PK = Primary Key
- LLM = Large Language Model
- UI = User Interface

---

## Warum SQLite?

- Keine Installation, kein Server -- eine einzige .db-Datei
- Kann kopiert, verschickt oder auf einem USB-Stick mitgebracht werden
- Python-nativ via sqlite3 (keine kompilierten Abhaengigkeiten -- kein pandas!)
- Bei 50-500 Suppliern: Matching unter 100 ms
- Cross-Platform: gleiche Datei laeuft auf Mac und Windows
- Post-PoC-Migration: PostgreSQL mit JSONB via UUID-Schluessel (verlustfrei)

---

## Lessons Learned aus PoC v1 -- Eingearbeitete Aenderungen

Diese Erkenntnisse sind direkt in die Spec eingeflossen. Claude Code muss sie
beim Implementieren kennen und beachten.

### LL-01: LLM und Kontextfenster

Qwen2.5 7B (4,7 GB) bleibt das Primaermodell -- stabiler als 3B bei JSON-Output
und Domaenenvokabular. Ollamas Default-Kontext (2048-4096 Token) ist IMMER zu
ueberschreiben. Jeder Ollama-API-Call muss enthalten:

```python
"options": {"num_ctx": 32768}
```

Alternativmodelle (falls Qwen Probleme macht):
- Gemma 3 4B (~3,3 GB): 128k Kontext, stark bei strukturierten Aufgaben
- Llama 3.1 8B: robustestes Deutsch + strukturierte Ausgaben, braucht ~8 GB VRAM

### LL-02: JSON-Parsing-Robustheit

Nie direkt json.loads() auf LLM-Output aufrufen. Immer repair_and_parse() verwenden.
Mehrstufige Reparatur-Pipeline (Reihenfolge einhalten):

```python
def repair_and_parse(raw: str) -> dict:
    # Stufe 1: direkt
    # Stufe 2: Markdown-Fences entfernen (```json ... ```)
    # Stufe 3: prosaischen Text vor/nach JSON entfernen
    # Stufe 4: String "null" -> null, "true"/"false" normalisieren
    # Stufe 5: unescapte Newlines in Strings fixen
    # Stufe 6: abgeschnittenes JSON reparieren (letztes vollstaendiges Feld nehmen)
    # Stufe 7: Regex-Fallback fuer einzelne Felder
```

### LL-03: Mehrstufige LLM-Pipeline

Kein Mega-Prompt. Jeder LLM-Call ist fokussiert auf einen Aufgabenbereich.
Kritische Steps haben Retry-Logik (3 Versuche, 2s Pause).

Pipeline fuer Matching-Engine:
1. Ausschreibungs-Extraktion (Pflichtfelder aus Buyer-Input)
2. AGV-Typ-Klassifizierung (mit regelbasiertem Keyword-Fallback -- siehe LL-05)
3. K.O.-Pruefung (regelbasiert, KEIN LLM-Aufruf -- zu unzuverlaessig)
4. Scoring-Erklaerung (LLM generiert die Begruendungstexte fuer das Ranking)

### LL-04: K.O.-Logik ist regelbasiert -- kein LLM

K.O.-Ausschluesse und Cond. K.O.-Filter werden IMMER im Python-Code berechnet,
nie vom LLM entschieden. LLM ist zu unzuverlaessig fuer Entscheidungen die ganze
Featurezweige steuern (Lesson 8 aus PoC v1).

LLM-Aufgaben im Matching:
- Freitext-Ausschreibung in strukturierte Felder uebersetzen
- Ranking-Erklaerungen auf Deutsch formulieren
- Unklare Felder beim Supplier-Import interpretieren

Kein LLM fuer:
- K.O.-Filterung
- Score-Berechnung
- Datenbankabfragen

### LL-05: Kritische Felder mit regelbasiertem Fallback absichern

AGV-Typ-Erkennung und andere Schluessel-Booleans immer doppelt absichern:
1. LLM-Extraktion (primaer)
2. Keyword-Fallback im Code (sekundaer, unabhaengig vom LLM)

Keyword-Fallback fuer AGV-Typ-Erkennung (prueft ersten 5.000 Zeichen):
```python
AGV_KEYWORDS = {
    "Forklift AGV": ["stapler", "forklift", "vna", "hubgeraet", "gabelstapler",
                     "reach truck", "schmalgangstapler", "hubhoe", "palette"],
    "Tugger AGV":   ["tugger", "schlepper", "zuege", "milk run", "routenzug",
                     "towing", "zug"],
    "Mobile AMR":   ["amr", "mobile robot", "unterfahrfahrzeug", "goods-to-person",
                     "picking robot", "lagerroboter", "regalbedien"]
}
```

### LL-06: CSV-Parsing

Niemals str.split() oder str.split(";") fuer CSV-Felder verwenden.
Immer das eingebaute csv-Modul nutzen:

```python
import csv
with open(path, encoding='utf-8', newline='') as f:
    reader = csv.DictReader(f, delimiter=',')
    for row in reader:
        ...
```

Multi-Select-Felder (pipe-separiert) werden NACH dem CSV-Parsing gesplittet:
```python
navigation = [v.strip() for v in row['navigation_type'].split('|') if v.strip()]
```

### LL-07: Windows-Kompatibilitaet -- ASCII-only in Shell-Skripten

Alle .bat-Dateien und Shell-Wrapper: nur 7-bit ASCII.
Keine Box-Drawing-Zeichen (keine Umlaute, keine Pfeile, keine Unicode-Symbole).
chcp 65001 schuetzt NICHT vor Parsing-Fehlern im eigenen .bat-Code.

Verboten in .bat:
  Umlaute (ae oe ue), Pfeile (->), Rahmenzeichen, Emojis, Sonderzeichen

Erlaubt:
  a-z A-Z 0-9 . - _ / \ : @ % ! " ' ( ) [ ] { } = + , ; Leerzeichen Zeilenumbruch

### LL-08: Externe Abhaengigkeiten minimieren

pandas ist verboten -- erfordert C-Compiler auf Windows (Visual Studio Build Tools).
numpy, scipy und andere kompilierte Pakete ebenfalls vermeiden.

Erlaubte Abhaengigkeiten (reine Python-Pakete, keine Kompilierung):
- requests (HTTP-Calls zu Airtable-API und Ollama)
- python-dotenv (optionale .env-Konfiguration)
- pytest (nur fuer Tests)

Alles andere: Python-Standardbibliothek (csv, sqlite3, json, pathlib, re, typing)

---

## Arbeitspakete -- Sequentielle Uebersicht

| AP  | Kurzname           | Beschreibung                                              | Aufwand    |
|-----|--------------------|-----------------------------------------------------------|------------|
| S0  | PoC sichern        | Aktuellen Stand kopieren (kein Git)                       | ~15 min    |
| D1  | Airtable-Sync      | Standalone-Skript: Airtable API => CSV => SQLite          | ~2-3h      |
| I1  | Schema-Interp.     | PoC liest lokale DB, Feldtypen korrekt geparst            | ~2h        |
| I2  | Industrie-Kontext  | Readme + AP0-Kommentare in Prompt-Kontext einbetten       | ~1-2h      |
| E1  | Backend-Evaluation | K.O.-Logik, Scoring-Trace, mehrstufige LLM-Pipeline       | ~2h        |
| E2  | Frontend-Eval.     | Demo-Ausschreibungen im UI, UX validieren                 | ~1h        |
| O1  | Frontend-Anpassung | Scoring-Anzeige, Cond. K.O.-Logik, Debug-Panel           | ~2-3h      |
| O2  | Scoring-Debug      | Gewichtungen testen, Demo-ready validieren                | ~1h        |

**Gesamtaufwand:** ~12-15 Stunden

---

## AP-S0 -- PoC sichern

### Ziel
Aktuellen PoC-Stand sichern. Kein Git vorhanden -- einfaches Kopieren.

### Erster Schritt vor allem anderen

Claude Code liest zu Beginn den gesamten bestehenden PoC-Ordner:
- Dateistruktur und alle Dateien inventarisieren
- Airtable-Token und Base-ID aus bestehendem Code extrahieren
- Bestehende Matching-Logik, CSV-Import und Frontend-Code verstehen
- Vorhandene Abhaengigkeiten (requirements.txt o.ae.) pruefen
- Die drei Ausschreibungsdateien (Dragonfly, CompanyX, Mama) lesen

Erst danach wird neuer Code angelegt. Nichts wird doppelt gebaut.
Was bereits existiert und funktioniert, wird wiederverwendet -- nicht ersetzt.

### Schritte
1. PoC-Ordner vollstaendig kopieren nach `haystacked_poc_backup_YYYYMMDD/`
   (im gleichen Elternverzeichnis)
2. Smoke-Test im Backup-Ordner: PoC einmal starten und pruefen

### Deliverable
- Backup-Ordner `haystacked_poc_backup_YYYYMMDD/` mit vollem Inhalt

---

## AP-D1 -- Airtable-Sync (Standalone-Skript)

### Ziel
Vollstaendig autonomes Python-Skript das:
- Ohne Claude-Session ausfuehrbar ist (Doppelklick oder Terminal)
- Auf Mac UND Windows laeuft (ein Skript, keine separate Bash-Variante)
- Airtable API => CSV => SQLite in einem Schritt durchfuehrt
- Jederzeit erneut ausfuehrbar wenn Airtable-Daten aktualisiert wurden
- Idempotent: mehrfaches Ausfuehren produziert identisches Ergebnis

### Datei: `sync_airtable.py`

Ablauf:
```
KONFIGURATION
  Laedt aus .env (falls vorhanden) oder aus hartcodierten Werten im Skript:
  AIRTABLE_TOKEN = "pat..."
  AIRTABLE_BASE_ID = "app..."
  Claude Code: Token und Base-ID aus bestehendem PoC-Code lesen

SCHRITT 1: Airtable-API-Abfrage (mit Pagination und Retry)
  GET /v0/{BASE_ID}/Companies              --> data/raw/companies.csv
  GET /v0/{BASE_ID}/Products               --> data/raw/products.csv
  GET /v0/{BASE_ID}/Base Model Extensions  --> data/raw/base_model_extensions.csv
  - Max. 100 Records pro Seite, automatische Pagination via offset-Parameter
  - 3 Versuche bei Netzwerkfehler, 2s Pause zwischen Versuchen
  - Verstaendliche Fehlermeldung bei fehlendem Netz (kein Python-Traceback)

SCHRITT 2: CSV-Schreiben
  - Immer csv-Modul, nie str.split() (Lesson LL-06)
  - encoding='utf-8', newline='' ueberall explizit
  - Alle Pfade via pathlib.Path (kein hartcodierter Slash)

SCHRITT 3: Validierung
  - Pflichtfelder vorhanden und nicht leer
  - UUID-Format korrekt (kein Auto-Increment)
  - Referenzielle Integritaet: FKs aufloesbar
  - Boolean-Werte: nur true/false/leer
  - Ausgabe: data/raw/export_validation_report.txt

SCHRITT 4: SQLite-Import
  - sqlite3 (Standardbibliothek) -- kein pandas (Lesson LL-08)
  - INSERT OR REPLACE (idempotent)
  - Boolean: true/True --> 1, false/False --> 0, leer/None --> NULL
  - Integer/Float: leer --> NULL (nie 0 -- Blank != Zero)
  - Multi-Select: pipe-separiert als Text stehen lassen
  - Ausgabe: data/haystacked.db

SCHRITT 5: Ergebnis
  Sync abgeschlossen: 12 Companies, 34 Products, 34 Extensions
  Datenbank: data/haystacked.db
```

### Windows-Wrapper `sync_airtable.bat` (reines 7-bit ASCII)

```batch
@echo off
python sync_airtable.py
pause
```

Keine Umlaute, keine Sonderzeichen, keine Box-Drawing-Zeichen (Lesson LL-07).

### Mac-Wrapper `sync_airtable.command`

```bash
#!/bin/bash
cd "$(dirname "$0")"
python3 sync_airtable.py
read -p "Druecke Enter zum Schliessen..."
```

### Konfigurationsdatei `.env`

```
AIRTABLE_TOKEN=pat...
AIRTABLE_BASE_ID=app...
```

Claude Code liest Token und Base-ID aus dem bestehenden PoC-Code.

### Deliverable
- `sync_airtable.py`
- `sync_airtable.bat` (ASCII-only)
- `sync_airtable.command`
- `docs/sync_anleitung.md` (Deutsch, fuer Laien)

### Validierung
- Laeuft auf Mac ohne Aenderungen
- Laeuft auf Windows ohne Aenderungen
- 2x ausfuehren: identisches Ergebnis (idempotent)
- Kein Netz: verstaendliche Fehlermeldung, kein Absturz

---

## Datenbankschema (SQLite)

Datei: `data/haystacked.db`

**Grundprinzip Blank != Zero (wird im gesamten Code durchgesetzt):**
NULL = unbekannt. 0 = explizit Null. Ein fehlender Wert loest NIE einen K.O.-Ausschluss aus.

```sql
CREATE TABLE IF NOT EXISTS companies (
    company_id              TEXT PRIMARY KEY,
    company_name            TEXT NOT NULL,
    country                 TEXT,
    hq_city                 TEXT,
    employee_count_range    TEXT,
    founding_year           INTEGER,
    website                 TEXT,
    certifications_generic  TEXT,
    languages_spoken        TEXT,
    export_capable          INTEGER,
    last_updated            TEXT
);

CREATE TABLE IF NOT EXISTS products (
    product_id              TEXT PRIMARY KEY,
    company_id              TEXT NOT NULL,
    base_model_id           TEXT NOT NULL,
    product_name            TEXT NOT NULL,
    agv_type                TEXT NOT NULL,
    product_description     TEXT,
    reference_count         INTEGER,
    min_project_value_eur   INTEGER,
    max_project_value_eur   INTEGER,
    lead_time_weeks         INTEGER,
    distribution_model      TEXT,
    is_oem_product          INTEGER,
    service_coverage        TEXT,
    active                  INTEGER,
    FOREIGN KEY (company_id) REFERENCES companies(company_id)
);

CREATE TABLE IF NOT EXISTS base_model_extensions (
    extension_id                    TEXT PRIMARY KEY,
    base_model_id                   TEXT NOT NULL,
    agv_type                        TEXT NOT NULL,
    -- SHARED: Navigation
    navigation_type                 TEXT,
    infrastructure_required         INTEGER,
    outdoor_capable                 INTEGER,
    autonomous_obstacle_bypass      INTEGER,
    omnidirectional_movement        INTEGER,
    -- SHARED: Load
    max_payload_kg                  REAL,
    load_type                       TEXT,
    multi_load_compatibility        INTEGER,
    -- SHARED: Environment
    max_speed_ms                    REAL,
    length_mm                       INTEGER,
    width_mm                        INTEGER,
    operating_temp_min_c            INTEGER,
    operating_temp_max_c            INTEGER,
    operating_humidity_max_pct      INTEGER,
    ingress_protection_rating       TEXT,
    cleanroom_class                 TEXT,
    max_gradient_pct                REAL,
    floor_flatness_req              TEXT,
    stop_accuracy_mm                INTEGER,
    -- SHARED: Power
    battery_type                    TEXT,
    battery_runtime_h               REAL,
    charge_time_min                 INTEGER,
    autonomous_charging             INTEGER,
    battery_swap_capable            INTEGER,
    -- SHARED: Safety
    safety_standard                 TEXT,
    functional_safety_level         TEXT,
    safety_coverage                 TEXT,
    -- SHARED: Fleet & Integration
    fleet_management_system         TEXT,
    fleet_control_architecture      TEXT,
    vda5050_compatible              INTEGER,
    max_fleet_size                  INTEGER,
    multi_fleet_capable             INTEGER,
    integration_capability          TEXT,
    installation_process            TEXT,
    modification_process            TEXT,
    station_applications            TEXT,
    manual_usage                    INTEGER,
    -- Forklift-spezifisch
    lifting_height_mm               INTEGER,
    min_total_height_mm             INTEGER,
    fork_type                       TEXT,
    fork_spread                     TEXT,
    mast_type                       TEXT,
    min_aisle_width_mm              INTEGER,
    vna_capable                     INTEGER,
    drive_type                      TEXT,
    drop_accuracy_lat_mm            INTEGER,
    drop_accuracy_dep_mm            INTEGER,
    drop_accuracy_angle_deg         INTEGER,
    pick_req_accuracy_lat_mm        INTEGER,
    pick_req_accuracy_dep_mm        INTEGER,
    pick_req_accuracy_angle_deg     INTEGER,
    forks_free_floating             INTEGER,
    stacking_capability             INTEGER,
    load_detection                  TEXT,
    barcode_readers                 INTEGER,
    stock_line_scanning             INTEGER,
    trailer_loading                 INTEGER,
    trailer_unloading               INTEGER,
    guidance                        TEXT,
    busbar_compatible               INTEGER,
    -- Tugger-spezifisch
    towing_capacity_kg              REAL,
    max_trailers                    INTEGER,
    coupling_type                   TEXT,
    auto_hitch                      INTEGER,
    auto_hitch_position_tolerance_mm INTEGER,
    train_configuration             TEXT,
    load_transfer                   TEXT,
    trailer_compatibility           TEXT,
    trailer_steering_technology     TEXT,
    route_type                      TEXT,
    route_programming               TEXT,
    intersection_management         INTEGER,
    tugger_min_aisle_width_mm       INTEGER,
    turning_radius_mm               INTEGER,
    -- Mobile AMR-spezifisch
    workflow_capability             TEXT,
    grid_required                   INTEGER,
    rotation_capable                INTEGER,
    picking_mechanism               TEXT,
    lift_height_mm                  INTEGER,
    min_ground_clearance_mm         INTEGER,
    rack_pin_compatible             INTEGER,
    free_lift_open_closed_pallet    INTEGER,
    top_module_type                 TEXT,
    cart_pickup_height_range_mm     TEXT,
    omnidirectional                 INTEGER,
    min_turning_radius_mm           INTEGER,
    pick_req_accuracy_lat_mm_amr    INTEGER,
    pick_req_accuracy_dep_mm_amr    INTEGER,
    pick_req_accuracy_angle_deg_amr INTEGER,
    drop_accuracy_lat_mm_amr        INTEGER,
    drop_accuracy_dep_mm_amr        INTEGER,
    drop_accuracy_angle_deg_amr     INTEGER,
    storage_system_type             TEXT,
    shelf_height_mm                 INTEGER,
    shelf_footprint_mm              TEXT,
    min_grid_area_m2                INTEGER,
    throughput_picks_per_hour       INTEGER,
    throughput_basis                TEXT,
    concurrent_robots_per_station   INTEGER,
    order_lines_per_run             INTEGER,
    task_interleaving               INTEGER,
    storage_density_factor          REAL,
    ergonomic_height_adjustable     INTEGER,
    onboard_ui                      INTEGER,
    onboard_container_type          TEXT,
    onboard_container_count         INTEGER,
    wms_integration_native          TEXT,
    extra_fields                    TEXT
);
```

---

## AP-I1 -- Schema-Interpretation im PoC

### Datei: `src/data_loader.py`

3-Wege-JOIN:
```sql
SELECT p.*, c.*, bme.*
FROM products p
JOIN companies c ON p.company_id = c.company_id
JOIN base_model_extensions bme ON p.base_model_id = bme.base_model_id
WHERE p.active = 1
```

Parsing-Regeln (aus Lesson LL-06):
- Multi-Select: csv-Modul fuer CSV, dann pipe-Split:
  `[v.strip() for v in cell.split('|') if v.strip()]`
- Leer oder NULL --> [] (leere Liste, nie None)
- Boolean: 1 --> True, 0 --> False, NULL --> None
- Numerisch leer --> None (nie 0)

### Datei: `config/field_levels.json`

```json
{
  "max_payload_kg":         "KO",
  "navigation_type":        "COND_KO",
  "agv_type":               "KO",
  "lifting_height_mm":      "KO",
  "min_aisle_width_mm":     "KO",
  "stacking_capability":    "KO",
  "towing_capacity_kg":     "KO",
  "route_type":             "KO",
  "fleet_management_system":"KO",
  "load_type":              "KO",
  "infrastructure_required":"COND_KO",
  "outdoor_capable":        "COND_KO",
  "vda5050_compatible":     "COND_KO",
  "forks_free_floating":    "COND_KO",
  "barcode_readers":        "COND_KO",
  "vna_capable":            "COND_KO",
  "ingress_protection_rating": "COND_KO",
  "operating_temp_min_c":   "COND_KO",
  "trailer_loading":        "COND_KO",
  "auto_hitch":             "COND_KO",
  "workflow_capability":    "COND_KO",
  "grid_required":          "COND_KO",
  "picking_mechanism":      "COND_KO",
  "storage_system_type":    "COND_KO",
  "service_coverage":       "COND_KO",
  "languages_spoken":       "COND_KO",
  "reference_count":        "SCORING",
  "lead_time_weeks":        "SCORING",
  "battery_runtime_h":      "SCORING",
  "autonomous_charging":    "SCORING",
  "safety_standard":        "SCORING",
  "stop_accuracy_mm":       "SCORING",
  "drop_accuracy_lat_mm":   "SCORING",
  "throughput_picks_per_hour": "SCORING",
  "max_fleet_size":         "SCORING",
  "hq_city":                "CONTEXT",
  "founding_year":          "CONTEXT",
  "distribution_model":     "CONTEXT",
  "mast_type":              "CONTEXT",
  "trailer_compatibility":  "CONTEXT"
}
```

### Deliverable
- `src/data_loader.py`
- `src/models.py`
- `config/field_levels.json`
- `tests/unit/test_data_loader.py`

---

## AP-I2 -- Industrie-Kontext einbetten

### Ollama-Konfiguration (Pflicht)

Jeder Ollama-API-Call muss num_ctx explizit setzen (Lesson LL-01):

```python
response = requests.post(
    "http://localhost:11434/api/generate",
    json={
        "model": "qwen2.5:7b",
        "prompt": system_prompt + user_input,
        "stream": False,
        "options": {
            "num_ctx": 32768,
            "temperature": 0.1
        }
    }
)
```

Temperature 0.1 fuer strukturierte Ausgaben (minimale Varianz).

### LLM-Pipeline-Struktur (Lesson LL-03 und LL-04)

```
Call 1: Ausschreibungs-Extraktion
  Input:  Freitext-Ausschreibung vom Buyer
  Output: Strukturiertes JSON mit Pflichtfeldern
  Retry:  3 Versuche

Call 2: AGV-Typ-Klassifizierung
  Input:  Extrahierte Felder + Freitext
  Output: agv_type (Forklift AGV | Tugger AGV | Mobile AMR)
  Fallback: Keyword-Pruefung unabhaengig vom LLM (Lesson LL-05)

--- K.O.-Pruefung: regelbasiert in Python, KEIN LLM ---

Call 3: Ranking-Erklaerungen
  Input:  Ranking-Ergebnis (Top N Supplier mit Scores)
  Output: Deutsche Erklaerungstexte pro Supplier
  Retry:  2 Versuche
```

### JSON-Parser (Lesson LL-03 -- Pflicht)

```python
def repair_and_parse(raw: str) -> dict:
    """Mehrstufiger LLM-JSON-Reparatur-Parser. Nie direkt json.loads() verwenden."""
    import json, re

    # Stufe 1: direkt
    try:
        return json.loads(raw)
    except Exception:
        pass

    # Stufe 2: Markdown-Fences entfernen
    cleaned = re.sub(r'```(?:json)?\s*|\s*```', '', raw).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # Stufe 3: Text vor erstem { und nach letztem } entfernen
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass

    # Stufe 4: String-"null" normalisieren
    normalized = re.sub(r':\s*"null"', ': null', cleaned)
    normalized = re.sub(r':\s*"true"', ': true', normalized)
    normalized = re.sub(r':\s*"false"', ': false', normalized)
    try:
        return json.loads(normalized)
    except Exception:
        pass

    # Stufe 5: unescapte Newlines in Strings fixen
    fixed = re.sub(r'(?<!\\)\n(?=[^"]*")', '\\n', normalized)
    try:
        return json.loads(fixed)
    except Exception:
        pass

    # Stufe 6: abgeschnittenes JSON -- letztes vollstaendiges Feld-Paar nehmen
    partial = re.sub(r',\s*"[^"]*"\s*:\s*[^,}\]]*$', '', fixed)
    if not partial.endswith('}'):
        partial += '}'
    try:
        return json.loads(partial)
    except Exception:
        pass

    # Stufe 7: Felder einzeln per Regex extrahieren
    result = {}
    for key, val in re.findall(r'"(\w+)"\s*:\s*"([^"]*)"', raw):
        result[key] = val
    return result
```

### Keyword-Fallback AGV-Typ (Lesson LL-05)

```python
AGV_KEYWORDS = {
    "Forklift AGV": [
        "stapler", "forklift", "vna", "hubgeraet", "gabelstapler",
        "reach truck", "schmalgangstapler", "hubhoehe", "palette", "gabeln"
    ],
    "Tugger AGV": [
        "tugger", "schlepper", "routenzug", "milk run",
        "towing", "anhaenger", "zuege"
    ],
    "Mobile AMR": [
        "amr", "mobile robot", "unterfahrfahrzeug", "goods-to-person",
        "picking robot", "lagerroboter", "autonomer", "fahrroboter"
    ]
}

def agv_type_keyword_fallback(text: str) -> str | None:
    """Unabhaengig vom LLM. Prueft ersten 5.000 Zeichen."""
    excerpt = text[:5000].lower()
    scores = {t: sum(1 for kw in kws if kw in excerpt)
              for t, kws in AGV_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else None
```

### Prompt-Kontext-Builder `src/context_builder.py`

Maximale Laenge: 32.768 Token gesamt (Kontext + Prompt + Antwort).
Kontext-Budget: ~20.000 Token (Readme + Feldkommentare).

```
SYSTEM CONTEXT -- haystacked Matching Engine

## Industry domain knowledge
[Vollstaendiger Inhalt des Industry Readme]

## Field-level descriptions
[Alle K.O. und Cond. K.O. Felder mit Beschreibung aus AP0]

## Critical matching rules
1. K.O. fields: a supplier failing even one K.O. criterion is fully excluded.
2. Cond. K.O. fields: score by default; hard filter only when buyer marks required.
3. Blank != zero: NULL means unknown, never absent. Do not infer a capability
   is absent because a field is empty. NULL reference_count is NOT 0 references.
4. OEM rebadging: same physical machine under multiple brand names shares tech specs.
5. AGV type classification: derive from properties, never from vendor label alone.
   Use navigation_type, lift capability, towing, workflow -- not product name.
```

### Deliverable
- `scripts/extract_ap0_descriptions.py`
- `config/field_descriptions.json`
- `src/context_builder.py`
- `src/llm_client.py` (Ollama-Wrapper mit num_ctx, Retry)
- `src/json_repair.py` (kanonische repair_and_parse — genutzt von app.py, llm_client, Tests)
- `tests/unit/test_context_builder.py`

---

## AP-E1 -- Backend-Evaluation

### Testfall-Format `tests/tenders/tender_001.json`

```json
{
  "tender_id": "tender_001",
  "description": "Greenfield F&B -- Schmalgangstapler, 12m Hochregale, Naturnavigation",
  "requirements": {
    "agv_type": "Forklift AGV",
    "lifting_height_mm": 12000,
    "min_aisle_width_mm": 1800,
    "navigation_type": ["Natural Feature"],
    "outdoor_capable": "not_required",
    "vda5050_compatible": "preferred",
    "max_payload_kg": 1500,
    "service_coverage_required": ["DACH"],
    "forks_free_floating": "required"
  },
  "expected_ko_exclusions": [],
  "expected_top_3": []
}
```

### Evaluations-Skript `scripts/evaluate_backend.py`

Ausgabe:
```
Testfall: tender_001
==========================================
K.O.-Ausschluesse (3):
  FAIL Supplier X: lifting_height_mm = 8000, required >= 12000
  FAIL Supplier Y: navigation_type = [Laser Reflector], required [Natural Feature]
  FAIL Supplier Z: service_coverage = [EU], required [DACH]

Cond. K.O. aktiviert:
  forks_free_floating = required -- Filter aktiv

Ranking (5 Supplier):
  1. Supplier A: Score 87/100
     navigation_type: match (+15)
     reference_count: 12 (+10)
     vda5050_compatible: preferred (+5)
  2. Supplier B: Score 74/100
  ...

Ergebnis: Top-3 korrekt [JA/NEIN]
```

### Acceptance Criteria
- Mindestens 2 Testfaelle produzieren Ranking mit >= 3 Suppliern
- Alle K.O.-Ausschluesse: Feld + Wert + Anforderung begruendet
- NULL-Felder loesen KEINEN K.O.-Ausschluss aus
- Cond. K.O.: korrekt bei not_required (Score) und required (Filter)
- AGV-Typ-Klassifizierung: Keyword-Fallback greift wenn LLM versagt

### Deliverable
- `tests/tenders/tender_001.json` bis `tender_003.json`
- `scripts/evaluate_backend.py`
- `tests/integration/test_full_pipeline.py`
- `docs/evaluation_report_YYYYMMDD.md`

---

## AP-C1 -- Human-in-the-Loop Clarification Step

### Motivation

Nach der LLM-Extraktion koennen kritische K.O.-relevante Felder fehlen -- nicht weil die
Ausschreibung schlecht ist, sondern weil Werte wie Hubhoehe oder Nutzlast oft nur in
Anlagentechnik-Zeichnungen oder separaten Anhaengen stehen (z.B. Dragonfly: Hubhoehe nicht
im Freitext, nur in der Rackingzeichnung).

Einen Wert in diesem Fall zu erfinden oder einen generischen Fallback-Wert still anzuwenden
ist gefaehrlich: ein Supplier koennte faelschlicherweise ausgeschlossen oder eingeschlossen
werden. Stattdessen wird der User nach dem Extraction-Schritt um Bestaetigung gebeten --
explizit und nachvollziehbar.

### Prinzip

```
PDF Upload → Extraction (LLM) → [CLARIFICATION STEP] → Matching → Ergebnis
```

Nach dem LLM-Extraction-Schritt prueft das System, welche K.O.-relevanten Felder fuer den
erkannten AGV-Typ leer (None) sind. Nur fehlende Pflichtfelder werden abgefragt -- keine
Ueberforderung mit vollstaendigen Formularen.

### Welche Felder werden abgefragt (je AGV-Typ)?

| AGV-Typ | Felder | Fallback-Hint |
|---|---|---|
| Forklift AGV | `lifting_height_mm`, `min_aisle_width_mm`, `max_payload_kg` | VNA: typ. 10.000–17.000 mm |
| Forklift AGV (VNA-Subtyp) | zusaetzlich `vna_capable` (als Cond. K.O. aktivieren?) | Standard: Ja fuer VNA |
| Tugger AGV | `towing_capacity_kg`, `max_payload_kg` | je nach Traingroesse |
| Mobile AMR | `max_payload_kg`, `navigation_type` (als Cond. K.O. aktivieren?) | site-abhaengig |

Felder die bereits vom LLM extrahiert wurden werden NICHT erneut abgefragt.

### VNA-Bidirektionale Exklusionsregel (LL-10)

VNA-Geraete sind auf schmale Gangbreiten und spezialisierte Regalinfrastruktur ausgelegt
und sind gegenueber Standard-Staplern deutlich teurer. Deshalb gilt eine **bidirektionale
Exklusionslogik**:

| Ausschreibung | Supplier `vna_capable` | Ergebnis |
|---|---|---|
| VNA gefordert (`vna_capable = "required"`) | `True` | Pass |
| VNA gefordert | `False` oder `NULL` | **K.O.** |
| Kein VNA (`vna_not_required = True`) | `True` | **K.O.** -- ueberqualifiziert, falsche Infrastruktur |
| Kein VNA | `False` oder `NULL` | Pass |

**Implementierung (AP-D1):** `vna_capable` traegt den Operator `KO_BOOL_EXCLUSIVE` in
`field_levels.json`. `app.py` setzt:
- `vna_capable = "required"` wenn VNA erkannt
- `vna_capable = "not_required"` in allen anderen Faellen (Safe Default)

VNA ist immer ausgeschlossen, ausser wenn die Ausschreibung es explizit fordert.
Das gilt auch wenn der AGV-Typ nicht erkannt wurde (unbekannter Typ = kein VNA).

`matching.py` wertet den Operator generisch aus -- kein Python-Domaenwissen noetig.

> **Lesson Learned LL-10:** VNA-Geraete duerfen nie in einer Standard-Ausschreibung
> aufgefuehrt werden -- die Infrastruktur-Anforderungen sind inkompatibel, und der
> Buyer wuerde ein massiv ueberteuertes, schlechtperformendes Angebot erhalten.

### VNA-Sonderregel (LL-09)

Wenn der LLM-erkannte Fahrzeugtyp "VNA" ist (nicht bloss "Forklift AGV"):

1. `vna_capable = "required"` wird automatisch gesetzt (als Cond. K.O. aktiviert).
   Begruendung: VNA-Subtyp impliziert immer vna_capable=true beim Supplier.
2. Wenn `lifting_height_mm` fehlt: Clarification Step fragt den User.
   Fallback-Hint im UI: "VNA-Hochregallager: typisch 10.000-17.000 mm".
   Nur wenn der User explizit bestaetigt oder ueberspringt, wird ein Default angewendet.
3. Wenn der User das Feld leer laesst (Skip): kein lifting_height_mm K.O. -- NULL schliesst
   nie aus (LL-06).

> **Lesson Learned LL-09 (neu):** Werte die nicht aus der Ausschreibung extrahiert werden
> koennen, duerfen NICHT still durch Fallbacks ersetzt werden. Der User muss explizit
> entscheiden: Wert angeben, oder Feld weglassen (dann kein K.O.).

### Datenstruktur: Clarification im Tender-JSON

Das Tender-JSON (fuer Backend-Tests und fuer /match-Aufrufe) wird um ein optionales
`clarifications`-Feld erweitert. Damit ist der Clarification-Schritt vollstaendig backend-
testbar ohne das Frontend zu benoetigen.

```json
{
  "tender_id": "tender_001",
  "description": "Dragonfly -- VNA Forklift AGV, high-bay",
  "requirements": {
    "agv_type": "Forklift AGV",
    "min_aisle_width_mm": 1800,
    "max_payload_kg": 1500,
    "vna_capable": "required"
  },
  "clarifications": {
    "source": "user_confirmed",
    "fields_confirmed": ["lifting_height_mm"],
    "lifting_height_mm": 10000
  },
  "expected_ko_exclusions": [],
  "expected_top_3": []
}
```

Felder in `clarifications` werden mit `requirements` gemerged (clarifications haben Vorrang
bei Konflikten). `source` kann `"user_confirmed"`, `"user_skipped"`, oder `"auto_fallback"`
sein -- nur `"user_confirmed"` aktiviert den K.O. fuer das jeweilige Feld.

### Frontend-Flow

1. Extraction SSE laeuft durch (wie bisher).
2. Nach dem Extraction-Step: System berechnet fehlende Pflichtfelder fuer den AGV-Typ.
3. Wenn fehlende Felder vorhanden: Clarification-Panel erscheint (kein Modal, kein Blocker).
   - Pro Feld: Label, Eingabebox, Einheit-Hint, "Ueberspringen"-Link.
   - VNA: Hint "VNA-Hochregal: typisch 10.000-17.000 mm".
4. User bestaetigt Werte oder klickt "Ueberspringen".
5. "Matching starten"-Button wird aktiv --> ruft /match mit angereicherten Daten.

### Backend-Testpfad (ohne Frontend)

```python
# tests/integration/test_clarification.py

# Fall 1: User bestaetigt lifting_height
req = load_tender("tender_001_with_clarification.json")
assert req["requirements"]["lifting_height_mm"] == 10000
assert req["clarifications"]["source"] == "user_confirmed"
top, all_results = match_suppliers_new(req["requirements"], suppliers)
assert all(r["product"] != "AMADEUS Classic" for r in top)  # 2800mm < 10000mm KO

# Fall 2: User skippt lifting_height (kein K.O.)
req_skipped = load_tender("tender_001_no_clarification.json")
assert req_skipped["requirements"].get("lifting_height_mm") is None
top2, _ = match_suppliers_new(req_skipped["requirements"], suppliers)
# AMADEUS Classic darf jetzt im Pool sein (NULL schliesst nie aus)

# Fall 3: Backend-Skript mit clarifications-Feld
# evaluate_backend.py liest clarifications und mergt in requirements
```

### Test-Tender-Dateien

| Datei | Inhalt |
|---|---|
| `tests/tenders/tender_001.json` | Dragonfly mit user_confirmed lifting_height=10000 |
| `tests/tenders/tender_001_no_clarification.json` | Dragonfly ohne lifting_height (user_skipped) |
| `tests/tenders/tender_002.json` | Mama AMR -- keine Clarification noetig |
| `tests/tenders/tender_003.json` | Out of scope |

### Acceptance Criteria

- [ ] Clarification-Panel erscheint nur fuer fehlende K.O.-Felder, nicht fuer alle Felder
- [ ] User kann jedes Feld ueberspringen -- kein Zwang
- [ ] Uebersprungene Felder loesen keinen K.O. aus (LL-06)
- [ ] `evaluate_backend.py` liest `clarifications` aus Tender-JSON und mergt korrekt
- [ ] `source = "user_skipped"` --> Feld wird aus requirements entfernt (kein K.O.)
- [ ] `source = "user_confirmed"` --> Wert wird in requirements gemergt (K.O. aktiv)
- [ ] VNA-Subtyp: `vna_capable = "required"` wird automatisch gesetzt (kein User-Input noetig)
- [ ] Kein stiller Fallback ohne User-Bestaetigung (LL-09)

### Deliverable
- `templates/index.html` (Clarification-Panel, nach Extraction-Step)
- `static/style.css` (Clarification-Panel-Styles)
- `tests/tenders/tender_001_no_clarification.json`
- `tests/integration/test_clarification.py`
- Aktualisiertes `scripts/evaluate_backend.py` (clarifcations-Merge)

---

## AP-E2 -- Frontend-Evaluation

### Checkliste

Eingabe-Flow:
- [ ] Ausschreibungsform zeigt alle K.O.-Felder
- [ ] Cond. K.O.-Felder haben drei Optionen: required / preferred / not relevant
- [ ] Pflichtfelder verhindern Submit wenn leer
- [ ] agv_type-Dropdown filtert sichtbare Felder (Lesson LL-05: Typ steuert Features)

Ergebnis-Flow:
- [ ] Ranking wird angezeigt (mindestens Top 5)
- [ ] K.O.-Ausschluesse sichtbar und begruendet (Feld + Wert + Anforderung)
- [ ] Score pro Supplier sichtbar
- [ ] Mindestens eine Score-Begruendung pro Supplier (LLM-generiert)

Robustheit:
- [ ] Ausschreibung ohne Treffer: sinnvolle Meldung
- [ ] LLM-Timeout (> 30s): Fallback auf regelbasiertes Ergebnis ohne Erklaerungstext
- [ ] Ladezeit < 3 Sekunden fuer Matching (ohne LLM-Erklaerung)
- [ ] Kein JS-Fehler in Browser-Konsole
- [ ] Kein Netzwerkaufruf ausser localhost:11434 (Ollama)

### Deliverable
- `docs/frontend_evaluation_YYYYMMDD.md`

---

## AP-O1 -- Frontend-Anpassung

### Neue UI-Komponenten

**1. Score-Breakdown pro Supplier**
```
Supplier A                    87/100
--------------------------------------
navigation_type     match      +15
reference_count     12         +10
vda5050             preferred  +5
battery_runtime     (unknown)  --
```

**2. K.O.-Ausschluss-Panel**
```
Ausgeschlossen (3 Supplier):
  FAIL Supplier X -- lifting_height_mm: 8m < gefordert 12m
  FAIL Supplier Y -- navigation_type: Laser != Natural Feature
```

**3. Cond. K.O.-Toggle im Formular**
```
outdoor_capable:  ( ) required   (*) preferred   ( ) not relevant
```

**4. Debug-Panel (URL-Parameter ?debug=true)**
- Rohwerte aus DB
- Field-Level-Mapping
- Scoring-Gewichtungen live editierbar --> sofortiges Re-Ranking
- LLM-Prompt-Anzeige (welcher Prompt wurde gesendet?)
- LLM-Rohausgabe (was kam zurueck vor dem Repair-Parser?)

### Deliverable
- Aktualisiertes Frontend mit allen vier Komponenten
- `docs/ui_component_spec.md`

---

## AP-O2 -- Scoring-Debug

### Gewichtungsstruktur `config/scoring_weights.json`

```json
{
  "default": {
    "reference_count": 15,
    "lead_time_weeks": 10,
    "vda5050_compatible": 8,
    "battery_runtime_h": 7,
    "autonomous_charging": 6,
    "safety_standard": 5,
    "stop_accuracy_mm": 5
  },
  "forklift_specific": {
    "drop_accuracy_lat_mm": 8,
    "pick_req_accuracy_lat_mm": 6,
    "stacking_capability": 5
  },
  "tugger_specific": {
    "auto_hitch": 8,
    "trailer_steering_technology": 6
  },
  "amr_specific": {
    "rotation_capable": 7,
    "throughput_picks_per_hour": 8
  }
}
```

### Acceptance Criteria Demo-Ready
- [ ] Tender 001: Top-1 ist ein bekannter Marktfuehrer in der Kategorie
- [ ] Tender 002: K.O.-Ausschluesse intuitiv erklaerbar (kein Experte noetig)
- [ ] Tender 003: Score-Differenz Rang 1 vs. Rang 2 nachvollziehbar
- [ ] Cond. K.O. forks_free_floating=required schliesst alle Straddle-Designs aus
- [ ] AGV-Typ-Erkennung korrekt auch wenn Freitext nur "VNA" oder "Schmalgang" enthaelt

### Deliverable
- Finalisierte `config/scoring_weights.json`
- Finaler `docs/evaluation_report_YYYYMMDD.md`

---

## Vollstaendige Testliste

### Teststruktur

```
tests/
  unit/
    test_data_loader.py
    test_matching_logic.py
    test_context_builder.py
    test_json_repair_parser.py
    test_agv_keyword_fallback.py
  integration/
    test_full_pipeline.py
    test_offline_mode.py
    test_sync_script.py
  tenders/
    tender_001.json
    tender_002.json
    tender_003.json
```

### Unit-Tests: Datenschicht

| Test-ID | Beschreibung | Erwartetes Ergebnis |
|---------|--------------|---------------------|
| U-D-01 | Multi-Select 'Laser\|Natural Feature' | ['Laser', 'Natural Feature'] |
| U-D-02 | Multi-Select leer | [] (nicht None) |
| U-D-03 | Multi-Select NULL | [] (nicht None) |
| U-D-04 | Boolean 1 --> True | True |
| U-D-05 | Boolean 0 --> False | False |
| U-D-06 | Boolean NULL --> None | None |
| U-D-07 | reference_count leer --> None | None (nicht 0) |
| U-D-08 | max_payload_kg leer --> None | None (nicht 0.0) |
| U-D-09 | UUID-Format korrekt | UUID-Regex-Match |
| U-D-10 | FK-Integritaet company_id | Kein Orphan |
| U-D-11 | FK-Integritaet base_model_id | Kein Orphan |
| U-D-12 | 3-Wege-JOIN: Pflichtfelder vorhanden | product_name, company_name, agv_type OK |
| U-D-13 | Nur active=1 geladen | Inaktive ausgeschlossen |
| U-D-14 | Sync idempotent: 2x ausfuehren | Kein Duplicate-Error |
| U-D-15 | Sync ohne Netz: lesbare Fehlermeldung | Kein Python-Traceback |
| U-D-16 | CSV-Parsing: Felder mit eingebettetem Komma | Korrekt geparst (csv-Modul) |

### Unit-Tests: JSON-Repair-Parser

| Test-ID | Beschreibung | Erwartetes Ergebnis |
|---------|--------------|---------------------|
| U-J-01 | Sauberes JSON | Direkt geparst |
| U-J-02 | JSON mit Markdown-Fence ```json | Fence entfernt, geparst |
| U-J-03 | JSON mit prosaischem Text davor | Text entfernt, geparst |
| U-J-04 | String "null" statt null | Normalisiert, geparst |
| U-J-05 | String "true" / "false" statt bool | Normalisiert, geparst |
| U-J-06 | Abgeschnittenes JSON | Letztes vollstaendiges Feld behalten |
| U-J-07 | Unescapte Newlines in String-Werten | Repariert, geparst |
| U-J-08 | Komplett unparsbares JSON | Leeres dict, kein Absturz |

### Unit-Tests: AGV-Keyword-Fallback

| Test-ID | Beschreibung | Erwartetes Ergebnis |
|---------|--------------|---------------------|
| U-K-01 | Text enthaelt "VNA" | Forklift AGV |
| U-K-02 | Text enthaelt "Schmalgangstapler" | Forklift AGV |
| U-K-03 | Text enthaelt "Routenzug" | Tugger AGV |
| U-K-04 | Text enthaelt "Milk Run" | Tugger AGV |
| U-K-05 | Text enthaelt "AMR" | Mobile AMR |
| U-K-06 | Text enthaelt "Goods-to-Person" | Mobile AMR |
| U-K-07 | Text ohne erkennbare Keywords | None (kein Absturz) |
| U-K-08 | Nur erste 5.000 Zeichen werden geprueft | Timeout-sicher |

### Unit-Tests: Matching-Logik

| Test-ID | Beschreibung | Erwartetes Ergebnis |
|---------|--------------|---------------------|
| U-M-01 | K.O. max_payload_kg: Supplier unter Anforderung | Ausgeschlossen |
| U-M-02 | K.O. max_payload_kg: Supplier NULL | NICHT ausgeschlossen |
| U-M-03 | K.O. agv_type: falsche Kategorie | Ausgeschlossen |
| U-M-04 | Cond. K.O. navigation_type=required, kein Match | Ausgeschlossen |
| U-M-04b | Cond. K.O. navigation_type=not_required, kein Match | NICHT ausgeschlossen |
| U-M-05 | Cond. K.O. outdoor_capable=not_required | Kein Filter |
| U-M-06 | Cond. K.O. outdoor_capable=required, Wert=False | Ausgeschlossen |
| U-M-07 | Cond. K.O. outdoor_capable=required, Wert=NULL | NICHT ausgeschlossen |
| U-M-08 | Cond. K.O. forks_free_floating=required, Straddle | Ausgeschlossen |
| U-M-09 | Cond. K.O. forks_free_floating=required, Counterbalanced | Im Pool |
| U-M-10 | Scoring: hoehere reference_count --> hoeher | Rang 1 hat mehr Referenzen |
| U-M-11 | Scoring: reference_count=NULL --> neutral | Kein Bonus, kein Abzug |
| U-M-12 | Cond. K.O. vda5050=preferred --> Score, kein Filter | Nicht ausgeschlossen |
| U-M-13 | Leere Ausschreibung (nur agv_type) | Alle aktiven Supplier des Typs |
| U-M-14 | K.O. service_coverage: DACH required, Supplier EU only | Ausgeschlossen |
| U-M-15 | Ranking >= 3 Supplier bei grossem Pool | 3+ Eintraege |
| U-M-16 | Score-Erklaerung: Feld + Wert + Punkte | Vollstaendig |
| U-M-17 | Deterministisch: gleiche Eingabe = gleiche Reihenfolge | Identisch |

### Unit-Tests: Kontext-Builder

| Test-ID | Beschreibung | Erwartetes Ergebnis |
|---------|--------------|---------------------|
| U-C-01 | Industry Readme vollstaendig im Kontext | Alle 14 Abschnitte vorhanden |
| U-C-02 | Feldkommentar fuer alle K.O.-Felder vorhanden | Kein K.O. ohne Beschreibung |
| U-C-03 | Kontext-String < 20.000 Token | Passt in num_ctx=32768 |
| U-C-04 | 'blank != zero'-Regel explizit im Kontext | Text vorhanden |
| U-C-05 | OEM-Rebadging-Erklaerung vorhanden | Abschnitt 7 aus Readme |
| U-C-06 | AGV-Typ-Klassifizierungs-Regel vorhanden | Properties not label |

### Integration-Tests

| Test-ID | Beschreibung | Erwartetes Ergebnis |
|---------|--------------|---------------------|
| I-01 | Voller Pipeline: Sync --> DB --> Load --> Match --> Report | Kein Fehler |
| I-02 | Offline: Matching ohne Netzwerkverbindung (kein Airtable-Call) | Ergebnis OK |
| I-03 | Sync-Skript: Mac ohne Aenderungen | Keine OS-Fehler |
| I-04 | Sync-Skript: Windows ohne Aenderungen | Keine Pfad-/Encoding-Fehler |
| I-05 | LLM-Timeout-Fallback: Ollama antwortet nicht | Regelbasiertes Ergebnis, kein Absturz |
| I-06 | Tender 001: K.O.-Ausschluesse vorhanden | Ausschlussliste stimmt |
| I-07 | Tender 002: Top-3 plausibel | Bekannte Marktfuehrer vorne |
| I-08 | Tender 003: Cond. K.O. auto_hitch=required | Nur Auto-Hitch-Supplier |
| I-09 | Leistungstest: Matching (ohne LLM) < 1 Sekunde | Timing-Assertion |
| I-10 | Leistungstest: Matching + LLM-Erklaerung < 30 Sekunden | Timing-Assertion |

### Frontend-Tests

| Test-ID | Beschreibung | Erwartetes Ergebnis |
|---------|--------------|---------------------|
| F-01 | Pflichtfeld leer --> kein Submit | Validation-Fehler |
| F-02 | agv_type Forklift --> Forklift-Felder, AMR-Felder nicht | Korrekt |
| F-03 | Score-Breakdown aufklappbar | Karte oeffnet sich |
| F-04 | K.O.-Panel: Feld + Wert + Anforderung | Vollstaendig |
| F-05 | ?debug=true aktiviert Debug-Panel | Panel sichtbar |
| F-06 | Gewichtung aendern --> sofortiges Re-Ranking | Kein Reload |
| F-07 | Debug-Panel zeigt LLM-Prompt und Rohausgabe | Sichtbar |
| F-08 | Kein externer Netzwerkaufruf (nur localhost:11434) | Network-Tab leer |
| F-09 | LLM-Timeout: Ergebnis ohne Erklaerungstext angezeigt | Kein Absturz |
| F-10 | Ladezeit Matching (ohne LLM) < 1 Sekunde | Timing-Check |
| F-11 | Kein JS-Fehler in Browser-Konsole | Konsole leer |

---

## Offene Punkte vor der Claude Code Session

| #  | Punkt | Wer | Wann |
|----|-------|-----|------|
| 1  | PoC-Ordner: Pfad und Dateistruktur mitteilen | Christian | Vor S0 |
| 2  | Airtable Token und Base-ID: Claude Code liest aus bestehendem PoC-Code | Claude Code | In S0 |
| 3  | Drei Demo-Ausschreibungen als Testfaelle definieren (anonymisiert OK) | Christian | Vor E1 |
| 4  | Sprache der Frontend-Demo: Englisch (festgelegt) | -- | -- |

---

## Technischer Stack

| Komponente | Entscheidung | Begruendung |
|------------|--------------|-------------|
| Lokale DB | SQLite 3 | Keine Installation, eine Datei, Python-nativ, Cross-Platform |
| DB-Bibliothek | sqlite3 (stdlib) | Keine kompilierte Abhaengigkeit -- kein pandas (Lesson LL-08) |
| CSV-Parsing | csv (stdlib) | Kein str.split() (Lesson LL-06) |
| Sync-Skript | Python + requests + python-dotenv | Einzige externe Abhaengigkeiten |
| Pfad-Handling | pathlib.Path | Kein hartcodierter Slash, Mac + Windows identisch |
| LLM | qwen2.5:7b via Ollama | Bewaehrt aus PoC v1 (Lesson LL-01) |
| LLM-Kontext | num_ctx: 32768 (explizit) | Ollama-Default nie vertrauen (Lesson LL-02) |
| JSON-Parsing | repair_and_parse() | Direkt json.loads() ist verboten (Lesson LL-03) |
| K.O.-Logik | Regelbasiert in Python | LLM nie fuer K.O.-Entscheidungen (Lesson LL-04) |
| AGV-Typ | LLM + Keyword-Fallback | Kritische Felder immer doppelt absichern (Lesson LL-05) |
| Shell-Wrapper | Nur 7-bit ASCII | Unicode in .bat crasht Windows (Lesson LL-07) |
| Tests | pytest | Standard, gut dokumentiert |
| Frontend | Bestehendes PoC-Frontend erweitern | Nicht ersetzen |
| Git | Spaeter | Kein Git installiert -- nach Demo-Phase separat aufsetzen |

---

---

## AP-D1 -- Data-Driven Matching Engine (implementiert Mai 2026)

### Ziel und Motivation

Die Matching-Logik (K.O.-Regeln, Vergleichsoperatoren) soll vollstaendig ausserhalb
von Python liegen. Das ermoeglicht:
- **Neue Industrien ohne Code-Aenderungen**: Neue Felder und Operatoren kommen
  ausschliesslich aus der AP0 xlsx -- kein Python-Entwickler noetig.
- **Transparenz im Pitch**: Die gesamte Matching-Semantik ist in einer Excel-Datei
  lesbar und erklaerbar. Kein verstecktes Domaenwissen im Code.
- **Konsistenz**: Single Source of Truth bleibt die AP0 xlsx -- jetzt auch fuer
  Operatoren, nicht nur fuer Feldklassifikationen.

### Architektur

```
AP0 xlsx (v0.8+)
  Spalte "Level":            KO / COND_KO / SCORING / CONTEXT
  Spalte "Matching Operator": KO_IF_LT / KO_IF_GT / KO_IF_NEQ /
                               KO_BOOL_REQUIRED / KO_BOOL_EXCLUSIVE / KO_SUBSET
      ↓
scripts/generate_field_levels.py
      ↓
config/field_levels.json
  { "max_payload_kg": { "level": "KO", "operator": "KO_IF_LT" }, ... }
      ↓
src/matching.py  ←  generische Rule Engine, kein Domaenwissen
```

### Matching-Operatoren

| Operator | Semantik | Typische Felder |
|---|---|---|
| `KO_IF_LT` | K.O. wenn Supplier-Wert < Tender-Wert | max_payload_kg, lifting_height_mm, towing_capacity_kg |
| `KO_IF_GT` | K.O. wenn Supplier-Wert > Tender-Wert | min_aisle_width_mm, turning_radius_mm, operating_temp_min_c |
| `KO_IF_NEQ` | K.O. wenn Supplier-Wert ≠ Tender-Wert | agv_type, route_type |
| `KO_BOOL_REQUIRED` | K.O. wenn Tender=required und Supplier=False (NULL bleibt) | stacking_capability, outdoor_capable, vda5050_compatible |
| `KO_BOOL_EXCLUSIVE` | Bidirektional: required→Supplier muss True; not_required→Supplier darf nicht True | vna_capable |
| `KO_SUBSET` | K.O. wenn kein Overlap zwischen Tender-Liste und Supplier-Liste | navigation_type, load_type, workflow_capability |

### Null-Regelwerk

| Operator | Tender=None | Supplier=None |
|---|---|---|
| KO_IF_LT / KO_IF_GT | Kein K.O. (kein Constraint) | Kein K.O. (LL-06), aber -15 Scoring-Penalty |
| KO_IF_NEQ | Kein K.O. | Kein K.O. |
| KO_BOOL_REQUIRED | Kein K.O. | Kein K.O. (nur False loest aus) |
| KO_BOOL_EXCLUSIVE | Kein Constraint | K.O. wenn Tender=required (LL-10) |
| KO_SUBSET | Kein K.O. | Kein K.O. |

### Neue Industrie hinzufuegen

1. Neue Spalten in AP0 xlsx anlegen (Felder, Level, Operator)
2. `python3 scripts/generate_field_levels.py --xlsx neue_industrie_AP0.xlsx`
3. Neues `scoring_weights.json` fuer Branche anlegen
4. Airtable-Schema erweitern, Supplier-Daten importieren
5. App neustarten -- matching.py unveraendert

**Kein Python-Code wird benoetigt.**

### Implementierte Dateien

| Datei | Aenderung |
|---|---|
| `Specs/haystacked_AP0_field_spec_v0_8.xlsx` | Neue Spalte "Matching Operator" (52 Felder mit Operator) |
| `scripts/generate_field_levels.py` | Liest + validiert Operator-Spalte |
| `config/field_levels.json` | Format: `{ level, operator }` pro Feld |
| `src/matching.py` | Vollstaendige Rewrite als generische Rule Engine |
| `app.py` | vna_not_required-Flag entfernt; vna_capable=not_required fuer Std.-Forklift |

---

*haystacked - PoC Offline-Integration Spec v1.2 - Vertraulich*

---

## Nachtrag v1.2 -- Letzte offene Punkte geschlossen

**Frontend-Sprache:** Englisch. Alle UI-Texte, Labels, Fehlermeldungen und
LLM-generierten Erklaerungstexte im Frontend sind auf Englisch.

**Demo-Ausschreibungen:** Die drei Ausschreibungen "Dragonfly", "CompanyX" und
"Mama" liegen als Dateien im PoC-Ordner. Claude Code liest sie zu Beginn von
AP-E1 und leitet daraus die Felder expected_ko_exclusions und expected_top_3
der Tender-JSONs ab. Der Originaldateiname wird im description-Feld vermerkt:

  tender_001.json -- Dragonfly
  tender_002.json -- CompanyX
  tender_003.json -- Mama

Alle offenen Punkte sind damit geschlossen. Die Spec ist bereit fuer die
Claude Code Session.
