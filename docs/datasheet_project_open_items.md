# Datasheet Project — Consolidated Open Items

Stand: 2026-08-21 — Tier 0, 1, 3, 4 komplett abgeschlossen. Tier 2 Entscheidungen komplett + Batch-1-Plan guardian-reviewed, Umsetzung durch `haystacked-developer` offen. Tier 5 (Import-Skript) kann jetzt beginnen. Konsolidiert aus `docs/datasheet_coverage_report.md`, `docs/datasheet_coverage_report_opus.md`, `docs/datasheet_conflict_resolution_20260806.md` und allen `docs/research_findings_{datasheet,opus}_*.json`. Nichts davon ist in Airtable oder `data/haystacked.db` gelandet — alles ist Stand jetzt nur gestagte JSON.

---

## Tier 0 — ✅ VOLLSTÄNDIG ABGESCHLOSSEN (2026-08-21)

- [x] **Sonnet- vs. Opus-Werte-Widersprüche auflösen** — 106 Widersprüche, Challenge-Runde (60/27/19), verifiziert. `docs/sonnet_opus_challenge_results.json`.
- [x] **Company-wide-Context-Blöcke abgeglichen** — 22 Widersprüche, Challenge-Runde (18/2/2), verifiziert. `docs/sonnet_opus_cwc_challenge_results.json`.
- [x] **Merge gebaut** — `docs/sonnet_opus_merged_dataset.json` (276 Produkte), Opus als Basis + Sonnet-exklusive Felder + alle Challenge-Urteile + Radius=0-Regel angewendet.
- [x] **Rest-Matching geklärt** — OSCAR Spin180/360/Omni und ek robotics COMPACT/VNA-MOVE sind bei Opus als Serien-Einträge erfasst (auf die einzelnen DB-Zeilen verteilt, nicht als ein Produkt behandelt); K10P One-Way bleibt reiner Sonnet-Stand (kein Opus-Gegencheck verfügbar).
- [x] **`db_status` final gegen die echte DB neu abgeleitet** — 276 Produkte: **130 neu / 61 enrich / 85 Konflikt**. `docs/datasheet_db_status_final.json`, unabhängig verifiziert (Zahlen stimmen exakt).
- [x] **Alle Konflikte triagiert** — 193 Produktzeilen×Feld-Kombinationen (178 eindeutige), Verdicts: **157 RESOLVED / 18 VARIANT-SPLIT-NEEDED / 13 UNRESOLVED / 5 DB-CLEANUP**. `docs/datasheet_final_conflicts_20260821.md`.

**Wichtigster Einzelfund:** AGILOX-Gangbreite — beide Durchläufe (Sonnet UND Opus) haben unabhängig voneinander dieselbe falsche Kennzahl gegriffen: die vorgeschlagene Korrektur (2100mm) steht im Original unter dem Label "Drehkreis" (Wenderadius), nicht Gangbreite. Der bestehende DB-Wert (1300mm) ist zusätzlich verdächtig (identisch bei zwei AGILOX-Produkten, vermutlich kopiert). **Empfehlung: weder Wert übernehmen**, echte Gangbreite fehlt für AGILOX komplett.

**Weitere Funde, die vor Import angeschaut werden sollten:**
- 331 Out-of-Scope-Zellen in der DB (AMR-Felder auf Forklift-Zeilen etc.) — separat von echten Wert-Konflikten geloggt, reine DB-Hygiene.
- 66 Tokens außerhalb der AP0 `allowed_values` (u.a. `service_coverage='EU'` auf ALLEN 266 Zeilen, neun Varianten von `Proprietary (<Produktname>)`).
- 12 Variant-Split-Kandidaten, wo eine DB-Zeile mehrere dokumentierte Produkte gleichzeitig abbildet (z.B. SAFELOG M4 core/lift/tow = 300/1000/1500kg gegen eine gespeicherte 200kg-Zeile).
- ek robotics VNA MOVE 1350/1500: DB hat dafür noch gar keine Zeilen (nicht wie ursprünglich angenommen bereits vorhanden) — beide als `new` gestaged.

## Tier 1 — Reine Tech-Lead-Entscheidungen — Runde 1 abgeschlossen (2026-08-20)

- [x] **ek robotics ↔ NEURA Mobile Robots GmbH** — **Entscheidung: nur Firmenname/Metadaten anpassen.** Kein separater NEURA-Produkteintrag. (Weiterhin offen, separat: ek robotics fehlen 6 von 9 Produktlinien inkl. VNA — das ist ein Coverage-Punkt, keine Namensfrage, siehe Import-Vorbereitung.)
- [x] **STILL iGo == Linde MATIC?** — **Entscheidung: erstmal getrennt lassen**, als offener Punkt hinterlegt (nicht PoC-relevant, zusätzlich verkompliziert durch die Linde/Balyo-Beziehung).
- [x] **Stäubli PF3 vs. PF3 OMNI** — **Entscheidung: als zwei getrennte Produkte anlegen** (User-bestätigt anhand Stäubli-Produktseite, Abmessungen massiv unterschiedlich).
- [x] **KNAPP "Open Shuttle" == "Open Shuttle 50"?** — **Entscheidung: Annahme bestätigt.**
- [x] **Radius/Diameter-Konvention — final gelöst (2026-08-21), kein ÷2-Trick nötig.** Der AP0-Hint für `min_turning_radius` sagt explizit "0 if omnidirectional... combine with footprint" — die eigentliche Auflösung: wenn der Datenblatt-Text eine Drehung auf der Stelle beschreibt (echter Omnidirektionalantrieb ODER Differentialantrieb mit "turn on the spot"-Fähigkeit), ist der korrekte Wert **0**, nicht die separat gedruckte "Turning radius (Xm)"-Zahl — die beschreibt ein anderes Manöver (Kurvenfahrt in Bewegung), nicht das, was dieses Feld will. Bestätigt für: SAFELOG S3, SAFELOG X1, SAFELOG L2, Magazino SOTO (User-bestätigt: "SOTO ist auch omnidirektional") → alle `min_turning_radius = 0`. Für alle anderen Fälle (SAFELOG M4/GT1 spin/XS1, alle Nicht-AMR wie VisionNav/STILL-Gabelstapler) bleibt die alte konservative Regel (nur explizite Radius-Angabe übernehmen), bis dort ebenfalls eine "Drehen auf der Stelle"-Fähigkeit im Text bestätigt ist. Kein Notiz-/Confidence-Feld nötig, da es sich um eine klare Ja/Nein-Textevidenz handelt, keine unsichere Ableitung.
- [x] **Konvention für Konfigurationsmatrizen** (z.B. Toyota-Aisle-Width) — **Entscheidung: Best Case (schmalste Zeile) für jetzt.** Langfristig: generische, industrieübergreifende Matrix-Implementierung nötig — als eigenes künftiges Architektur-Thema vormerken, nicht Teil des PoC.

## Tier 2 — AP0-Schema-Lücken — Entscheidungen komplett (2026-08-21), final priorisiert (2026-08-22)

**Finale Priorisierung nach Nutzer-Review aller 6 Punkte (2026-08-22):**
1. Wenderadius→Forklift: unwichtig, **fallengelassen** — Gangbreite (Ast) ist die entscheidende Zahl, die schon existiert.
2. Gangbreite→AMR: akzeptiert, wie geplant.
3. forks_free_floating-Hint: bestätigt, wie geplant.
4. safety_standard/functional_safety_level-Fix: "an den Haaren herbeigezogen, aber ok" — bestätigt, bleibt in Batch 2.
5. charge_time-Standardisierung: **komplett geparkt als OI-124** (Memory-Backlog) — Standardisierung ohne Marktmacht gegenüber Lieferanten aussichtslos, laut User erst relevant "wenn wir den Firmen die KPI diktieren können".
6. Plausibility-Floors: bestätigt, wie geplant.

Punkte 1 und 5 vereinfachen Batch 3 und 4 (siehe dort).

Vollständiges Ruling: `docs/ap0_tier2_senior_architect_ruling_20260819.md`. Alle 4 Blocker entschieden:
- [x] **Wenderadius→Forklift / Gangbreite→AMR: Level = K.O.** (User-Entscheidung, abweichend von SA-Empfehlung CONTEXT — akzeptiertes Risiko: Null-Penalty auf >95% der noch leeren Flotte bis zum nächsten Datenblatt-Batch).
- [x] **`forks_free_floating`-Hint umdrehen: freigegeben.** README-Lesart übernehmen, 16 betroffene Zeilen nach Fix neu prüfen.
- [x] **Plausibility-Floors senken**: nach Konvertierungs-Kollisions-Mathematik pro Feld (Entwickler-Aufgabe, keine offene Entscheidung mehr).
- [x] **Keine Feldnamen-Umbenennungen in diesem Batch** — bestätigt.

**Noch zu tun: Implementierungsplan schreiben + durch `ap0-architecture-guardian` und `reference-integrity-guardian` laufen lassen, dann `haystacked-developer`.** Batches laut SA-Empfehlung (nicht verschachteln, siehe Ruling-Datei):
- [x] **Batch 1 Plan geschrieben + BEIDE Guardian-Reviews abgeschlossen (2026-08-21)** — `docs/ap0_tier2_batch1_plan_20260821.md`, bereit für `haystacked-developer`. Zwei echte Fehler gefunden und korrigiert: (1) `ap0-architecture-guardian` — safety_standard/functional_safety_level Score-Fix funktioniert so nicht gegen echte DB-Werte (nie reiner String `'None'`, sondern Varianten wie `'None (CE/TÜV marks only)'`) und riskierte einen Domain-Logik-in-Python-Verstoß → nach Batch 2 verschoben. (2) `reference-integrity-guardian` — Plausibility-Floors stehen in der HAUPT-AP0-xlsx, nicht in `haystacked_platform_config.xlsx` wie ursprünglich im Plan geschrieben — hätte einen Entwickler zur falschen Datei geschickt, ohne dass ein Test das gefangen hätte. Auch: E2E-Replay-Schritt hat keine CI-Absicherung, jetzt explizit als manueller Schritt dokumentiert.
- [ ] **Batch 2 (Datenreparatur, kein AP0-Change)**: rotation_capable-Backfill mit echten `false`-Werten, forks_free_floating-Re-Audit (16 Zeilen), charge_time-Cluster-Fix (AGILOX ONE + der 8×7-Cluster bei Dynamo/Veloce), **safety_standard/functional_safety_level Score-Fix + `'None (...)'`-Varianten-Bereinigung (neu hierher verschoben)**.
- [ ] **Batch 3 (Scope-Erweiterung) — vereinfacht (User-Entscheidung 2026-08-22): nur `min_aisle_width`→AMR, als K.O.** `turning_radius`→Forklift **fallengelassen** — User: "Das spielt keine Rolle, die wichtige Zahl ist die Gangbreite (Ast)." Die 3 bekannten Fälle (Toyota RAE250, Grenzebach FF1200S, Linde R-MATIC k), wo ein korrekter Forklift-Wenderadius im falschen Tugger-Feld sitzt, bleiben unkorrigiert — kein aktiver Auftrag, kein Datenverlust (Wert steht ja schon irgendwo), nur kein eigenes Zuhause.
- [ ] **Batch 4 (zurückgestellt, je eigene Spec)**: 4 neue Airtable-Spalten als ein Change (Healthcare, Mehretagen, Wireless, Leergewicht), `tugger_min_aisle_width`-Konsolidierung (toter Zwilling, N1), `floor_flatness_req` numerisch. `charge_to_run_ratio` **entfällt** — siehe OI-124, charge_time-Standardisierung komplett geparkt.

## Tier 3 — Braucht externe/manuelle Recherche — ✅ ALLE 4 GEKLÄRT (2026-08-19, Web-Recherche)

- [x] **Toyota RAE250 `min_aisle_width`** — 3071mm ist real, bestätigt über 2 unabhängige neuere Toyota-Revisionen (Triplex Hi-Lo C, 419mm Batteriefach, rotate-on-point, EUR-Palette). **Flag:** das ist die EUR-Paletten-Zelle, nicht die Minimum-Zelle (2879mm wäre niedriger) — bei `KO_IF_GT` eine bewusste konservative Wahl, keine Korrektur nötig. **Bonus:** DB's `lifting_height=12000` ist korrekt und nur durch die neueste Revision (v3.2) gedeckt — nicht "zurückkorrigieren".
- [x] **DS Automotion AMADEUS Grip `max_payload`/`lifting_height`** — bestätigt die bestehenden DB-Werte über eine echte generische Quelle. **`lifting_height` final: 2800mm** (2 von 3 Quellen, User-Entscheidung 2026-08-21, betrifft alle AMADEUS-Varianten, nicht nur Grip). `max_payload=2000` unverändert.
- [x] **Balyo REACHY `battery_type`** — aktuelle REACHY bietet jetzt auch Li-Ion (NMC-Chemie). Da Li-Ion schon in der DB steht, ist die eigentliche Korrektur: **Lead-Acid ergänzen** (beide Chemien jetzt offiziell angeboten).
- [x] **VisionNav R-series `-07`-Varianten** — dreifach bestätigt: nicht mehr im Programm (aktueller Katalog, Sitemap, verwaiste Seite). **Keine neuen Zeilen anlegen** — bestehende VNR16/VNR20-Zeilen stimmen bereits mit den aktuellen Live-Werten überein.

## Tier 4 — ✅ ABGESCHLOSSEN (2026-08-20)

- [x] `1728979799.pdf` — VisionNav-Katalog Spanisch: "nur bestätigend"-Annahme war FALSCH, 13 Produkte extrahiert (1 neu/1 enrich/11 Konflikte).
- [x] Hikrobot 69-Seiten-Vollkatalog — 73 Produkte extrahiert (69 neu/1 enrich/3 Konflikte). **Entscheidung: alle 73 erstmal übernehmen**, TP6-STU-Serie und CT7L-1000-Klassifizierung nicht vorab aussortiert.
- [x] **VisionNav Reach-Truck Gangbreite-Konvention: Mast-eingefahren bestätigt** (passt zur bestehenden DB).

## Tier 5 — Infrastruktur

- [ ] **Import-Skript** — kann jetzt gebaut werden, Basis ist `docs/datasheet_db_status_final.json` (276 Produkte, finaler db_status, alle Konflikte trianiert). Insert-only-Konvention wie bei den bisherigen Batches (`scripts/import_research_20260801.py` als Vorbild), 178 unentschiedene Konflikte + 13 UNRESOLVED + 18 VARIANT-SPLIT-NEEDED sollten vor dem eigentlichen Import noch einmal von dir überflogen werden.

---

**Referenzdateien:**
- `docs/datasheet_coverage_report.md` / `docs/datasheet_coverage_report_opus.md` — die zwei Coverage-Reports (Sonnet/Opus getrennt)
- `docs/datasheet_conflict_resolution_20260806.md` — Klärungsrunde zu den ursprünglichen 20 Sonnet-Konflikten (17 gelöst/2 Variant-Split/3 unresolved)
- `docs/datasheet_source_index.json` / `docs/datasheet_source_index_opus.json` — PDF↔Produkt-Zuordnung je Durchlauf
- `docs/research_findings_datasheet_20260806_*.json` (Sonnet) / `docs/research_findings_opus_20260808_*.json` (Opus)
