# Airtable-Sync — Schritt-für-Schritt-Anleitung

## Was macht das Skript?

`sync_airtable.py` verbindet sich einmalig mit Airtable, laedt alle Supplier-Daten herunter
und speichert sie in einer lokalen Datenbankdatei (`data/haystacked.db`).
Danach laeuft das System komplett offline — kein Netz erforderlich.

## Voraussetzungen

- Python 3.9 oder neuer
- Internetverbindung (nur beim Sync)
- Airtable-Token und Base-ID (von Christian)

## Einmalige Einrichtung

1. Erstelle eine Datei `.env` im Projektordner (gleicher Ordner wie `sync_airtable.py`):

```
AIRTABLE_TOKEN=pat...
AIRTABLE_BASE_ID=app...
```

2. Installiere die Abhaengigkeiten (einmalig):

```
pip3 install requests python-dotenv
```

## Sync ausfuehren

**Mac:** Doppelklick auf `sync_airtable.command`

**Windows:** Doppelklick auf `sync_airtable.bat`

**Terminal:**
```
python3 sync_airtable.py
```

## Ergebnis

Nach erfolgreichem Sync:
```
Sync complete: 10 Companies, 52 Products, 52 Extensions
Database: data/haystacked.db
```

Die Datei `data/raw/export_validation_report.txt` enthaelt die Validierungsergebnisse.

## Wann erneut ausfuehren?

Immer wenn neue Supplier-Daten in Airtable eingepflegt wurden. Der Sync ist idempotent —
mehrfaches Ausfuehren produziert dasselbe Ergebnis ohne Fehler.

## Kein Netz — was passiert?

Das Skript gibt eine verstaendliche Fehlermeldung aus und bricht sauber ab.
Die bestehende Datenbank bleibt unveraendert.

## Troubleshooting

| Problem | Loesung |
|---------|---------|
| "AIRTABLE_TOKEN missing" | `.env`-Datei anlegen oder Token als Umgebungsvariable setzen |
| "airtable_schema_ids.json not found" | `airtable/ap2_schema.py` ausfuehren (einmalig bei neuem Airtable-Base) |
| "Rate-limited" | Skript wartet automatisch 30 Sekunden, dann Retry |
| SQLite-Fehler | `data/haystacked.db` loeschen und Sync erneut ausfuehren |
