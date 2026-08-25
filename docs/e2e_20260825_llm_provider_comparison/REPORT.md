# E2E Cross-Model Comparison: local qwen2.5:7b vs. OpenRouter qwen/qwen3.8-27b

**Datum:** 2026-08-25
**Zweck:** DoD #4 / R6 aus `docs/spec_llm_provider_abstraction_v0_1.md` — Vergleich des lokalen
7B-Baseline-Modells gegen das erste Cloud-Modell über den vollständigen Tender-Korpus (8
Ausschreibungen), mit Fokus auf Guard-Layer-Nullungen (nicht nur Füllquote — siehe Rev-2-Header
der Spec: ein stärkeres Modell kann durch Layer 0 des Halluzinations-Guards *schlechter*
abschneiden, weil die Guard-Annahme des wörtlichen Zitierens im Prompt verankert ist).

**Methode:** beide Läufe über den echten, laufenden `/analyze`-Endpoint (reale Pipeline, reale
11 LLM-Aufrufe, echter Halluzinations-Guard) — kein synthetischer Test. Pro Ausschreibung wurde
nach dem Lauf `data/haystacked.db` (`tender_extraction_values.nulled_by`) nach Layer abgefragt.
Orchestrierungs-Skript und Rohdaten liegen in diesem Ordner
(`local_7b.json`, `cloud_qwen3.8-27b.json`, `qwen3.8-27b_raw_output.txt`).

## Ergebnis-Tabelle

| Ausschreibung | 7B Dauer | 7B Felder | 7B Guard-Nullungen | 27B Dauer | 27B Felder | 27B Guard-Nullungen | in_scope (7b→27b) |
|---|---:|---:|---:|---:|---:|---:|---|
| Nordlicht | 400.1s | 17 | 0 | 83.4s | **27** | 0 | True → True |
| CompanyX | 320.9s | 1 | 0 | 66.9s | **10** | 0 | True → True |
| Dragonfly | 280.1s | 2 | 0 | 87.2s | **10** | 0 | True → True |
| Mama | 337.7s | 5 | 0 | 80.9s | **14** | 0 | True → True |
| OeA-199-25 (out-of-scope) | 13.3s | 0 | 0 | 34.8s | 0 | 0 | False → False |
| IK Cold Store | 108.3s | 7 | 1 (L1) | 31.4s | 10 | 0 | False → False |
| IK Deep Freeze | 132.2s | 7 | 1 (L0) | 45.1s | 7 | **2 (L0+plausibility)** | **False → True** |
| IK Process Cooling | 119.7s | 5 | 1 (L0) | 63.8s | 8 | 1 (L0) | **False → True** |
| **Summe** | **28m32s** | — | **3** | **8m13s** | — | **3** | |

## Kernbefunde

1. **Guard-Verhalten unauffällig — keine Bestätigung der befürchteten "stärkeres Modell = mehr
   Layer-0-Nullungen"-Falle.** Gesamt-Guard-Nullungen: 3 bei beiden Modellen, über 8
   Ausschreibungen. Kein systematischer Anstieg bei Qwen 3.8 27B. Stichprobe ist klein (nur 3
   Ereignisse insgesamt) — für eine belastbare statistische Aussage bräuchte es mehr Läufe, aber
   es gibt keinen Hinweis auf das befürchtete Muster.

2. **Deutlich mehr extrahierte Felder bei durchweg kürzerer Laufzeit.** Bei allen vier
   AGV-Ausschreibungen extrahiert Qwen 3.8 27B spürbar mehr Felder als das lokale 7B-Modell
   (CompanyX: 1→10, Dragonfly: 2→10, Mama: 5→14, Nordlicht: 17→27) — bei gleichzeitig ca.
   3,5× kürzerer Gesamtlaufzeit (28m32s → 8m13s). Das deckt sich mit der ursprünglichen
   Unzufriedenheit mit der 7B-Füllquote, die diesen Umbau motiviert hat.

3. **Kein Reasoning-Leak.** `_call_openrouter()`s `"reasoning": {"enabled": false}`-Absicherung
   hat funktioniert — der komplette Raw-Output (`qwen3.8-27b_raw_output.txt`, 1229 Zeilen über
   alle Aufrufe) enthält null `<think>`-Blöcke oder Denk-Präambeln (per Grep verifiziert). Jede
   Antwort ist direktes, valides JSON — `repair_and_parse()`s "erste `{`, kürzestes balanciertes
   Objekt"-Extraktion ist nicht gefährdet.

4. **Qualitativ überzeugender Raw-Output.** Stichprobe (Pass 4b, Nordlicht) zeigt saubere,
   korrekt formatierte JSON-Antworten mit echten, wörtlichen Quellenangaben in den `_source`-
   Feldern (z.B. `"required_max_payload_source": "Maximale Traglast ≥ 1.200 kg"`,
   `"required_lifting_height_source": "Hubhöhe ≥ 10 m (für Hochregaleinsatz)"`) — genau das
   verbatim-Zitierverhalten, auf das Layer 0 des Guards angewiesen ist. Keine erkennbaren
   Halluzinationen in der Stichprobe.

5. **Auffälligkeit: `in_scope`-Abweichung bei 2 von 3 IK-Ausschreibungen.** IK Deep Freeze und
   IK Process Cooling werden vom lokalen 7B-Modell als `in_scope=False` klassifiziert, vom
   Cloud-Modell dagegen als `in_scope=True`. Beide Modelle liefern in diesen Fällen trotzdem ein
   Matching-Ergebnis mit Score 0 (keine passenden Supplier gefunden) — die Abweichung wirkt sich
   also in diesem Sample nicht auf das Endergebnis aus, ist aber ein echtes Klassifikations-
   verhalten-Delta (NACE/Domain-Erkennung), nicht nur Rauschen. **Nicht weiter untersucht** —
   wert, im Blick zu behalten, falls IK-Ausschreibungen künftig systematisch mit Cloud-Modellen
   analysiert werden.

## Kosten

Gesamtkosten für den kompletten 8-Ausschreibungs-Vergleichslauf: **$0.28** (verifiziert über
OpenRouters `GET /api/v1/auth/key`, kostenloser Endpunkt).

## Einschränkungen dieser Messung

- Nur EIN Lauf pro Modell — kein Hinweis auf Cloud-seitige Nicht-Determinismus-Streuung (R7:
  Reproduzierbarkeit ist ab jetzt eine lokale Eigenschaft, nicht garantiert bei Cloud-Modellen).
- Nur 1 von 4 registrierten Modellen getestet (Qwen 3.8 27B). Llama 3.3 70B und Mistral Large 3
  noch nicht verglichen.
- Feldzahl-Vergleich ist ein grober Qualitätsindikator, kein vollständiger Korrektheits-Check
  gegen von Menschen verifizierte Ground-Truth-Werte — die zusätzlich extrahierten Felder bei
  27B wurden stichprobenartig, nicht vollständig gegen das Originaldokument verifiziert.
- `data/haystacked.db` wurde nach der Datenextraktion auf den committeten Stand zurückgesetzt
  (Testartefakte aus beiden Läufen wieder entfernt) — die `run_id`s aus dieser Messung existieren
  daher nicht mehr in der laufenden DB, nur in den JSON-Reports in diesem Ordner.

## Fazit

Kein Hinweis auf die befürchtete Guard-Layer-0-Falle. Deutlich bessere Füllquote und deutlich
kürzere Laufzeit bei Qwen 3.8 27B gegenüber dem lokalen 7B-Baseline, zu vernachlässigbaren
Kosten ($0.28 für 8 Ausschreibungen). DoD #4 / R6 damit erstmals erfüllt für ein Cloud-Modell —
Llama 3.3 70B und Mistral Large 3 stehen für einen analogen Vergleich noch aus.
