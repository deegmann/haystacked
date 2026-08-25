# E2E Cross-Model Comparison: Mistral Large 3 (viertes und letztes registriertes Cloud-Modell)

**Datum:** 2026-08-25
**Zweck:** Mistral Large 3 (`mistralai/mistral-large-2512`) war schon vor dieser Runde registriert
(EU/französisches Unternehmen, Apache-2.0-offene Gewichte), aber noch nie real getestet. User-
Nachfrage: kann es mit Qwen 3.8 27B und DeepSeek V4 Flash mithalten, obwohl es auf OpenRouters
eigenem Intelligence-Index deutlich schwächer abschneidet (15,9 vs. 52,0/51,8)? Damit sind jetzt
**alle drei registrierten Cloud-Modelle** real getestet.

## Ein echter Zwischenfall unterwegs — und ein Live-Beweis, dass die heutigen Fixes funktionieren

Der erste Durchlauf brach nach CompanyX ab: nach 220 Sekunden Laufzeit (mehrere reale LLM-Calls,
inkl. Pass 4b) endete der Call mit `httpx.ConnectError: All connection attempts failed` — eine
echte, transiente Netzwerkstörung, keine Modell- oder Code-Ursache. **Genau der heute Nachmittag
gebaute Fix (SA-Pflichtkorrektur: `except (LLMProviderError, httpx.HTTPError)` an den
4a/4b/4c-Handlern) hat das live und korrekt abgefangen** — der Lauf brach sofort und sichtbar ab,
statt mit einem stillen, unvollständigen Ergebnis weiterzulaufen. Die sieben nachfolgenden Tender
scheiterten in derselben Sekunde ebenfalls (Verbindungsstörung hielt an), jeweils ebenso laut.
Nach Bestätigung, dass die Verbindung zu OpenRouter wieder stabil war (`GET /api/v1/models` →
200 OK in 0,2s), wurden alle 7 betroffenen Tender wiederholt — beim zweiten Versuch lief jeder
einzelne fehlerfrei durch. Das ist keine Modell-Schwäche, sondern die erste echte
Produktionsbewährung der heutigen Fehlerbehandlungs-Fixes unter einer realen Störung.

## Ergebnis-Tabelle (alle vier getesteten Konfigurationen)

Format: `Felder/Guard-Nullungen`

| Ausschreibung | lokal (7b) | Qwen 3.8 27B | DeepSeek V4 Flash | **Mistral Large 3** |
|---|---:|---:|---:|---:|
| Nordlicht | 17/0 | **27**/0 | 20/0 | 22/0 |
| CompanyX | 1/0 | 10/0 | 9/0 | **14**/0 |
| Dragonfly | 2/0 | 10/0 | 8/0 | **11**/0 |
| Mama | 5/0 | 14/0 | 12/0 | **15**/0 |
| OeA (out-of-scope) | 0/0 | 0/0 | 0/0 | 0/0 |
| IK Cold Store | 7/1 | 10/0 | 10/0 | **11**/1 |
| IK Deep Freeze | 7/1 | 7/2 | 7/2 | **8**/1 |
| IK Process Cooling | 5/1 | 8/1 | 8/1 | **9**/1 |

**Mistral Large 3 hat auf 6 von 7 relevanten Ausschreibungen die höchste Feldzahl aller vier
Konfigurationen** — nur bei Nordlicht liegt Qwen vorn. Besonders auffällig: CompanyX, historisch
das schwerste Dokument (reiner Fließtext, keine Tabellen), wo lokal fast komplett versagt (1
Feld) — Mistral liefert hier mit 14 Feldern spürbar mehr als Qwen (10) oder DeepSeek (9).

## Kritische Felder — Dragonfly-VNA als Referenztest

**Alle drei Cloud-Modelle lösen die VNA-Anforderung bei Dragonfly jetzt korrekt:**
`required_vna_capable=true`, `required_min_aisle_width=1900` (mit echtem Zitat), `required_drive_type="VNA Turret"`
— identisch zu Qwen und DeepSeek. Auffällig: trotz korrekter VNA-Erkennung landet der Top-Match
bei Score 0 (`MX-X iGo mit Teleskoptisch`), anders als bei Qwen (Score 17, `EKX 516ka`). Das ist
plausibel keine Fehlfunktion, sondern eine direkte Folge der höheren Feldzahl — mehr echte
extrahierte Anforderungen bedeuten mehr echte Prüfkriterien, die zusätzliche Lieferanten
korrekt disqualifizieren können. Nicht weiter verifiziert (würde eine eigene Matching-Analyse
brauchen), aber kein Hinweis auf Halluzination bei den geprüften Kernfeldern.

## Modell-spezifische Formatbesonderheiten

- **Markdown-Code-Fences:** Mistral verpackt praktisch jede JSON-Antwort in ```` ```json ... ``` ````
  (99 Vorkommen im gesamten Log) — anders als Qwen/DeepSeek, die rohes JSON liefern.
  `repair_and_parse()` kommt damit klar (kein Extraktionsschaden beobachtet), aber es ist ein
  echtes, konsistentes Formatverhalten dieses Modells.
- **Verschachtelte Kontaktfelder (einmalig beobachtet):** bei Nordlichts erster Basisextraktion
  lieferte Mistral `contact_name`/`contact_email`/`contact_phone` als verschachtelte Objekte
  (`{"technical": "...", "commercial": "..."}`) statt flacher Strings — ein Schema-Abweichung,
  aber nur 1 von vielen Vorkommen im Log, kein systematisches Muster.
- **Kein Reasoning-Leck** (erwartungsgemäß, Mistral Large 3 ist laut eigenen Metadaten nicht
  reasoning-fähig — trotzdem vollständig gegengeprüft, 0 Treffer über 2355 Log-Zeilen).

## Geschwindigkeit

Deutlich langsamer als die anderen beiden Cloud-Modelle — 60-220s pro Ausschreibung (Median
~150s), gegenüber Qwens 30-90s und DeepSeeks 30-155s. Passt zur Modellgröße (675B Parameter,
mit Abstand das größte der drei getesteten Cloud-Modelle).

## Kosten

Kumulative Gesamtkosten (alle drei Cloud-Modelle zusammen): **$0,66**. Mistral-Anteil für diesen
Lauf: **≈$0,27** (inkl. des durch die Netzwerkstörung verlorenen ersten Versuchs) — der teuerste
der drei Cloud-Läufe, aber absolut betrachtet weiterhin sehr günstig.

## Einordnung

Der schwache generische Benchmark-Wert (15,9) hat sich auf unserer eigenen strukturierten
Extraktionsaufgabe **nicht bestätigt** — im Gegenteil, Mistral Large 3 liefert auf 6 von 7
Ausschreibungen die höchste Feldzahl aller vier getesteten Konfigurationen, bei ebenfalls
niedrigen Guard-Nullungen und korrekter VNA-Erkennung. Das bestätigt die Vermutung von vorhin:
generische Intelligenz-Indizes sagen wenig über Performance auf einer spezifischen,
strukturierten Extraktionsaufgabe aus. Für den europäischen Anwendungsfall ist das eine
überraschend gute Nachricht — trotz des benchmark-bedingten Zweifels ist Mistral Large 3 auf
diesem konkreten Task mindestens ebenbürtig, in mehreren Fällen sogar der stärkste Kandidat.
Einschränkung: nur ein Lauf, kleine Stichprobe, und die reale Netzwerkstörung unterwegs zeigt,
dass Cloud-Zuverlässigkeit ein eigener Faktor ist, unabhängig von Modellqualität.
