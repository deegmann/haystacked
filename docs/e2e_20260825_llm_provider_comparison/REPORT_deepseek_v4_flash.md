# E2E Cross-Model Comparison: DeepSeek V4 Flash (drittes Cloud-Modell)

**Datum:** 2026-08-25
**Zweck:** DeepSeek V4 Flash (`deepseek/deepseek-v4-flash-0731`) wurde auf User-Wunsch als
viertes Registry-Modell hinzugefügt und eigenständig (ohne weitere Rückfragen, User-Vorgabe)
durch denselben 8-Tender-Vergleich geschickt wie zuvor Qwen 3.8 27B. Ergänzt
`REPORT.md` (lokal vs. Qwen) und `GROUND_TRUTH_ANALYSIS.md` (manuelle Referenzwerte, dort
weiterhin die Quelle für "was steht wirklich im Dokument").

**Warum dieses Modell:** höchster Intelligence-Index aller praktisch lokal betreibbaren offenen
Modelle in der eigenen Recherche (51,8, nahezu gleichauf mit Qwen 3.8 27Bs 52,0), sparse MoE
(284B total / 13B aktiv — günstig und schnell im Betrieb), andere Modell-Familie als die
bisherigen drei Einträge.

## Ergebnis-Tabelle

| Ausschreibung | Dauer | Felder | Guard-Nullungen | in_scope |
|---|---:|---:|---:|---|
| Nordlicht | 153.7s | 20 | 0 | True |
| CompanyX | 150.6s | 9 | 0 | True |
| Dragonfly | 72.6s | 8 | 0 | True |
| Mama | 106.5s | 12 | 0 | True |
| OeA (out-of-scope) | 33.7s | 0 | 0 | False |
| IK Cold Store | 29.7s | 10 | 0 | **True** (lokal+Qwen: False) |
| IK Deep Freeze | 120.6s (2. Versuch) | 7 | 2 (L0+plausibility) | False |
| IK Process Cooling | 126.7s | 8 | 1 (L0) | True |
| **Summe** | **~13min** | — | **3** | |

## Kernbefunde

1. **Ein echter Zwischenfall — IK Deep Freeze schlug beim ersten Versuch fehl.** DeepSeek
   lieferte für den ersten LLM-Call (Pass "basic") eine Antwort, die nur aus einem einzelnen
   Leerzeichen bestand. Der bestehende R3-Check (`if not content`) fängt das nicht ab — ein
   String mit einem Leerzeichen ist in Python nicht "falsy". Die Pass-"basic"-Handler-Logik hat
   den Lauf trotzdem laut abgebrochen (kein stiller Fehler, aber über den *falschen* Mechanismus
   — einen generischen JSON-Parse-Fehler statt der eigens dafür gebauten R3-Absicherung). **Fix
   angewendet:** `_call_openrouter()` prüft jetzt `not content.strip()` zusätzlich zu `not
   content` (`src/llm_client.py`, Commit siehe unten). Neuer Regressionstest mit 4
   Leer/Whitespace-Varianten. Zweiter Versuch nach Fix: sofort erfolgreich — das Leerzeichen war
   ein transientes Ereignis, kein reproduzierbares Muster.
   **Warum das wichtig ist:** wäre derselbe Leerzeichen-Response bei Pass 4b statt "basic"
   aufgetreten, hätte der (jetzt gefixte) alte Code NICHT abgebrochen — Pass 4b's
   Fehlerbehandlung fängt nur `LLMProviderError`/`httpx.HTTPError` explizit ab, alles andere
   landet im alten, nicht-abbrechenden `except Exception`-Pfad. Das hätte einen leeren,
   plausibel aussehenden Match-Result erzeugt, ohne dass irgendjemand es bemerkt hätte — exakt
   das Szenario, für das R3 gebaut wurde. Live-Evidenz, kein hypothetisches Risiko.

2. **Kein Reasoning-Leck** — vollständig verifiziert über alle 961 Zeilen Raw-Output (kein
   `<think>`, keine Denk-Präambel-Phrasen gefunden). Der `"reasoning": {"enabled": false}`-Fix
   greift providerübergreifend, nicht nur bei Qwen. Damit ist die zuvor als "unverifiziert"
   geflaggte DeepSeek-V4-Reasoning-Eigenheit (siehe Registry-Kommentar in `src/llm_client.py`)
   jetzt live bestätigt.

3. **Beide Mehrdeutigkeits-Fallen bei IK Deep Freeze korrekt gelöst** — genau wie Qwen: 340 kW
   (Gesamtanlage, nicht die 280-kW-Schockfroster-Teilzahl) und -22°C (der als "verbindlich"
   markierte Wert, nicht die -18°C-Kerntemperatur). Auch R717 korrekt ausgeschlossen
   (`"R744, R290"`), wo das Dokument es explizit als "nicht genehmigungsfähig" markiert.

4. **Zusätzlicher, bisher unbeobachteter Erfolg: OI-122 (ausgeschriebene deutsche Zahlwörter)
   korrekt gelöst.** `required_blast_freeze_capacity` wurde als `650` extrahiert aus "0,65 t/h
   (**sechshundertfünfzig** Kilogramm pro Stunde)" — die einzige Stelle im gesamten heutigen
   Test, an der ein Modell dieses spezifische, im Backlog dokumentierte Problem (LLM extrahiert
   die t/h-Ziffer statt der ausgeschriebenen kg-Zahl) tatsächlich richtig löst. Weder lokal noch
   Qwen wurden auf dieses Feld hin geprüft (außerhalb der ursprünglichen 36-Felder-Stichprobe) —
   kein direkter Vergleich möglich, aber ein positiver Einzelbefund.

5. **`required_temperature_min` bei IK Process Cooling: DeepSeek widerspricht Qwen UND lokal.**
   Beide anderen Modelle wählen +4°C ("Vorlauftemperatur... muss bis auf +4°C abgesenkt werden
   können" — die Zielfähigkeit). DeepSeek wählt +2°C ("Eine Unterschreitung von +2°C ist nicht
   zulässig" — die harte Untergrenze). Beides sind im Dokument wörtlich stehende, plausible
   Lesarten derselben Ambiguität (Zielwert vs. absolute Untergrenze) — kein Halluzinieren, aber
   ein echtes Uneinigkeits-Signal zwischen den Modellen, das die Feldbedeutung von
   `temperature_min` selbst als nicht eindeutig genug definiert entlarvt. Nicht weiter verfolgt,
   aber wert, bei einer künftigen AP0-Hint-Präzisierung berücksichtigt zu werden.

6. **IK Cold Store: DeepSeek klassifiziert `in_scope=True`, lokal UND Qwen beide `False`.** Ein
   drittes Domain-Klassifikations-Delta (nach den bereits bei Qwen beobachteten
   IK-Deep-Freeze/Process-Cooling-Fällen) — diesmal in die andere Richtung. Bestätigt das
   Muster "Domain-Erkennung bei Kälte-Tendern ist modellabhängig uneinheitlich", ohne dass klar
   ist, welche Einordnung eigentlich richtig ist (nicht Teil dieser Analyse).

7. **Kleinere Formatinkonsistenz beobachtet:** `required_refrigerant_types` kam bei IK Process
   Cooling als echtes JSON-Array (`["R717"]`) an, bei IK Deep Freeze dagegen als sauberer
   Komma-String (`"R744, R290"`) — vom selben Modell, in derselben Session. Nicht weiter
   untersucht, ob das die finale Extraktion beeinträchtigt hat (non_null-Zahl für Process
   Cooling blieb im normalen Bereich); als Beobachtung festgehalten, verwandt mit dem bereits
   bekannten OI-112 (Python-Listen-Repr-Format bei `refrigerant_types`), aber eine andere
   Erscheinungsform (echtes JSON-Array statt Python-repr-String).

## Kosten

Kumulative Gesamtkosten (Qwen 3.8 27B + DeepSeek V4 Flash zusammen): **$0,39**. DeepSeek-Anteil
für diesen Lauf: **≈$0,11** (inkl. des fehlgeschlagenen ersten Versuchs auf IK Deep Freeze).

## Einordnung

DeepSeek V4 Flash schneidet auf allen geprüften kritischen Feldern mindestens gleichauf mit
Qwen 3.8 27B ab, in einem Fall (OI-122-Zahlwort-Konvertierung) sogar sichtbar besser. Der
Zwischenfall (leere Antwort) war ein reales, aber transientes Infrastruktur-Problem — durch den
heutigen Fix strukturell abgesichert für alle zukünftigen Cloud-Aufrufe, nicht nur DeepSeek. Kein
Hinweis auf die befürchtete Guard-Layer-0-Falle. Ein echtes Uneinigkeits-Signal zwischen den
Modellen (`temperature_min` bei Process Cooling) zeigt, dass nicht jede Mehrdeutigkeit im
Dokument selbst eindeutig auflösbar ist — das ist ein AP0-Hint-Thema, kein Modell-Qualitätsproblem.
