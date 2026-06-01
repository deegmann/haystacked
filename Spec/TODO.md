# haystacked — Offene Punkte

> Zuletzt aktualisiert: 2026-06-01
> Kontext: AP0 v0.10, Matching Engine AP-D1, 52 aktive Supplier-Records

---

## 🔴 Kritisch — Airtable Datenvervollständigung

Fehlende Felder blockieren das Matching direkt (KO feuert nicht oder trifft falsch).

### Forklift AGV (21 Supplier)

| Feld | Gefüllt | Lücke | Warum kritisch |
|---|---|---|---|
| `route_type` | 0/21 | **100%** | KO-Feld — alle Forklift-Supplier ohne Routen-Info |
| `vna_capable` | 4/21 | **81%** | VNA-Tender disqualifiziert alle unbekannten Supplier |
| `min_aisle_width_mm` | 6/21 | **71%** | Häufigster Tender-Parameter, KO leer |
| `vda5050_compatible` | 5/21 | **76%** | Scoring + Cond. KO — sehr häufig gefragt |
| `forks_free_floating` | 5/21 | **76%** | Entscheidend für geschlossene Paletten/Förderer-Tender |
| `lifting_height_mm` | 13/21 | **38%** | Direktes KO — VNA/Dragonfly scheitert hier |
| `max_payload_kg` | 16/21 | **24%** | Null-Penalty -15 Pkt pro fehlendem Wert |
| `outdoor_capable` | 0/21 | **100%** | Cond. KO — komplett leer |
| `infrastructure_required` | 8/21 | **62%** | Navigation-KO |
| `station_applications` | 4/21 | **81%** | Floor/Conveyor-Matching |

### Tugger AGV (10 Supplier) — großteils leer

| Feld | Gefüllt | Lücke |
|---|---|---|
| `max_trailers` | 0/10 | **100%** |
| `turning_radius_mm` | 0/10 | **100%** |
| `tugger_min_aisle_width_mm` | 0/10 | **100%** |
| `coupling_type` | 0/10 | **100%** |
| `max_payload_kg` | 1/10 | **90%** |

### Mobile AMR (21 Supplier)

| Feld | Gefüllt | Lücke |
|---|---|---|
| `workflow_capability` | 0/21 | **100%** — Basis für AMR-Matching, komplett leer |
| `grid_required` | 3/21 | **86%** |
| `vda5050_compatible` | 8/21 | **62%** |
| `lift_height_mm` | 1/21 | **95%** |
| `min_turning_radius_mm` | 6/21 | **71%** |

---

## 🟡 Offen — Matching & Extraction

- [ ] **`required_fork_type` LLM-Halluzination**: LLM setzt "Standard Fork" als Default auch wenn nicht im Dokument — AP0 Description-Regel hilft teilweise, aber VNA-Fälle brauchen noch Post-Processing-Logik (z.B. `required_fork_type → null` wenn `required_vna = required` und kein expliziter Fork-Typ im Dokument)
- [ ] **`required_load_types` Mama.pdf**: Dokument enthält keinen expliziten Trägertyp — LLM halluziniert Prozessbeschreibungen. AP0-Filter fängt es ab, aber `required_load_types` bleibt null → kein Load-Type-KO → Mama matcht zu viele Supplier
- [ ] **Dragonfly 100% disqualifiziert**: Kein VNA-Supplier in DB mit ≥2900 kg Payload — Data-Problem, kein Code-Problem. Wird gelöst wenn Airtable-Daten vollständiger

---

## 🟢 Erledigt (diese Session)

- [x] AP0 v0.10: alle 41 fehlenden `Tender JSON Key` Werte eingetragen
- [x] `generate_all.py`: liest `tender_key`, `data_type`, `allowed_values` aus AP0
- [x] `generate_field_levels.py`: in sync mit `generate_all.py`
- [x] `matching.py` `TenderRequirements`: vollständig data-driven via AP0 tender_key
- [x] `matching.py` `validate_tender_values()`: AP0 allowed_values als Post-Processing-Filter
- [x] `extraction_template.txt`: generiert aus AP0 Descriptions (nie mehr manuell editieren)
- [x] AP0 Descriptions aktualisiert: Unit-Regeln, Null-Regeln, VNA-Regeln, Allowed Values
- [x] Null-String-Normalisierung (`"None"`, `"null"`, `""` → Python None)
- [x] `_ms()`: splittet auf `,` und `|`
- [x] `_op_lt` / `_op_gt`: type-safe mit float-Konversion
- [x] MES zu `required_integration` Allowed Values in AP0 hinzugefügt

---

## 📋 Architektur-Prinzipien (nicht vergessen)

- **AP0 xlsx** = einzige Quelle für Felder, Operatoren, Allowed Values, LLM-Hints
- **Airtable** = einzige Quelle für Supplier-Daten
- Kein industrie-spezifischer Hardcode in Python
- `extraction_template.txt` wird generiert — nie manuell editieren
- Nach AP0-Änderung: `python3 scripts/generate_all.py --xlsx <path>` ausführen
