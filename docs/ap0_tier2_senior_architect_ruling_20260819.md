# Tier 2 AP0-Lücken — Senior-Architect Pre-Plan-Review (2026-08-19)

Vollständige Antwort archiviert; hier die kondensierte Fassung mit den konkreten Entscheidungen. Alle load-bearing Zahlen vom Tech Lead gegen `data/haystacked.db`/`config/` verifiziert (siehe Chat 2026-08-19).

## Strukturfakt, der die halbe Liste umdreht
`base_model_extensions` ist EINE breite Tabelle (121 Spalten), Scope ist nur ein logischer Filter in AP0. Ein Feld einer weiteren Scope-Tab hinzuzufügen kostet **eine xlsx-Zeile, keine DB-Migration, kein Airtable-Change** — Präzedenzfall existiert schon (`min_aisle_width` ist bereits in Forklift UND Tugger). Die eigentliche Risikofrage ist nicht "geht das", sondern **auf welchem Level** (CONTEXT vs. KO) das neue Feld landet.

## Urteile je Punkt

| # | Thema | Urteil |
|---|---|---|
| 3 | `forks_free_floating` Hint widerspricht README | **Höchste Priorität** — Hint ist nachweislich falsch, invertiert einen scharfen COND_KO für Reach Trucks. Braucht dein bewusstes Go, da es echte Tender-Ergebnisse verschiebt. 16 bereits befüllte Zeilen müssen nach Fix neu geprüft werden. |
| 9 | `rotation_capable` Mis-Mapping | Schlimmer als gedacht: 89 true/0 false/177 null — ein reiner Hint-Fix reicht NICHT, braucht zusätzlich einen Daten-Backfill mit echten `false`-Werten (wie beim `grid_required`/`vna_capable`-Sweep 2026-07-22). |
| 5 | Plausibility-Floors zu strikt | Betrifft 4 Felder, nicht 2 — 21 Zeilen unter `lifting_height`-Floor, 18 von 21 `turning_radius`-Zeilen sind `0`. **Blocker:** mm→m-Konvertierungsschwelle ist geteilt über 9 Felder, muss pro Feld durchgerechnet werden bevor ein Floor sinkt, sonst drohen stille ×1000-Fehler. |
| 1, 2 | Kein Wenderadius (Forklift) / keine Gangbreite (AMR) | xlsx-Zeile ist billig, aber: **Level = CONTEXT, nicht KO** (Empfehlung) — sonst kollabiert die KO-Null-Penalty auf 96%+ der Flotte, die das Feld noch nicht hat. KO-Promotion erst nach Coverage-Gate (Vorschlag: ≥60%). |
| 4 | `charge_time` 4 Formate | **Kein neues Datenmodell bauen** — das Feld hat aktuell gar kein Scoring-Gewicht (inert). Nur Hint schärfen + Floor + Datenreparatur (AGILOX ONE `3`, plus ein verdächtiger `8`×7-Cluster bei Dynamo/Veloce). |
| 6 | Nicht-konforme `allowed_values` ("CE" etc.) | Ist **kein AP0-Problem** — `sync_airtable.py`s Validierung ist Show (jeder Branch `continue`). Braucht einen `fields.json`-getriebenen Report-Only-Validator, niemals Auto-Null. |
| 7 | `floor_flatness_req` kategorial statt mm | Real, aber **zurückstellen** — Feld ist CONTEXT/inert, nur 1 von 266 Zeilen befüllt, Airtable-Feldtyp-Änderung nötig (manuell, wegen bekanntem 422-Limit). |
| 8 | Scope-Asymmetrie | Teilweise falsch gelesen (`drop_accuracy_*` ist schon in beiden Scopes) — echtes Problem ist fehlendes Scoring-Gewicht, nicht Scope. `barcode_readers`→AMR ist der einzige Punkt mit echter Matching-Wirkung. Neue Felder (Healthcare, Mehretagen, Wireless, Leergewicht) sind die einzig wirklich teuren Punkte — als EIN gebündelter Airtable-Change, nicht vier einzelne. |

## Explizit abgelehnt: "jedes Scope kriegt jedes Feld"
Bewusster Gegenvorschlag verworfen — würde die Pass-4b-Prompts mit irrelevanten Feldern fluten (bekanntes Muster für Batch-Collapse) und den `max_score`-Nenner verwässern. Stattdessen: `generate_all.py` soll bei Feldern warnen, die in ≥1 aber nicht allen AGV-Scopes vorkommen — macht Lücken zu bewussten Entscheidungen statt stillen Zufällen.

## 4 neue Defekte, die nicht auf der ursprünglichen Liste standen
- **N1**: `tugger_min_aisle_width` — 0 befüllte Zeilen, fast identischer Hint wie `min_aisle_width`, gleicher Scope — toter Zwilling, der zwei konkurrierende K.O.s auf denselben physischen Sachverhalt auslösen kann.
- **N2**: `safety_standard`/`functional_safety_level` nutzen `score_function=nonempty`, aber `'None'` ist ein gültiger Wert — **7 Supplier bekommen volle Punktzahl fürs Fehlen eines Sicherheitsstandards.**
- **N3**: 37 SCORING-Felder ohne Gewicht, komplett wirkungslos im Matching (u.a. mehrere der Tier-2-Punkte betroffen).
- **N4**: ~500 Out-of-Scope-Zellen bereits in der DB befüllt (z.B. `stacking_capability` auf 107 AMRs) — Ingestion schreibt ohne Scope-Check. Ohne Sync-seitigen Report reproduziert der nächste Datenblatt-Batch das Problem schneller, als dieser Batch es fixt.

## Empfohlene Reihenfolge (4 Batches, bewusst nicht verschachtelt)
1. **Korrektheit, nur AP0-Zellen** (kein neues Feld, kein Level-Wechsel): forks_free_floating-Hint, rotation_capable-Hint, charge_time-Hint+Floor, safety_standard/functional_safety_level Score-Function, Plausibility-Floors (nach Konvertierungs-Mathematik).
2. **Datenreparatur, kein AP0-Change**: rotation_capable-Backfill, forks_free_floating-Re-Audit (16 Zeilen), charge_time-Cluster-Fix.
3. **Scope-Erweiterungen auf CONTEXT-Level**: turning_radius→Forklift, min_aisle_width→AMR.
4. **Zurückgestellt, je eigene Spec nötig**: KO-Promotion für #1/#2, die 4 neuen Airtable-Spalten als ein Change, tugger_min_aisle_width-Konsolidierung, floor_flatness_req numerisch.

**Wichtig laut Senior Architect:** Batch 1 ist der einzige, der Matching-Ergebnisse verändert (und zwar in die richtige Richtung). Batches 2+3 dürfen NICHT mit Batch 1 verschachtelt werden, sonst wird ein E2E-Delta nicht mehr einer Ursache zuordenbar — genau das Muster, das im Projekt schon zweimal eine volle Untersuchung gekostet hat (CompanyX 11→9→4, OI-114).

## 4 Blocker — brauchen dein bewusstes Go, bevor der Plan geschrieben wird
1. **Level-Entscheidung #1/#2**: CONTEXT (Empfehlung) oder KO mit Coverage-Gate?
2. **Konvertierungs-Kollisions-Mathematik** für #5, pro Feld, vor jeder Floor-Änderung.
3. **Explizites Go für die Reach-Truck-Neudefinition** (#3) — invertiert einen scharfen COND_KO, ist eine Semantik-Änderung, keine reine Fehlerkorrektur.
4. **Keine Feldnamen-Umbenennungen in diesem Batch** (N1 und die turning_radius/min_turning_radius-Dopplung verleiten dazu — beide auf Batch 4 verschieben).
