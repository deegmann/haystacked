# Spec: IK Completion + Multi-Industry Pipeline
**Version:** v0.5
**Datum:** 2026-07-19
**Status:** BEREIT ZUR FREIGABE (User Sign-off ausstehend)

SA-Reviews: CONDITIONAL PASS (Fable, 2026-07-18) → v0.3 → CONDITIONAL PASS (Fable, 2026-07-19) → v0.4 → Arch-Ruling Option D (Fable, 2026-07-19) → v0.5

---

## 1. Ziel und Constraints

### Ziel
Vollwertige zweite Industrie **FoodBev:Refrigeration (IK)** neben Logistics:AGV. Gleichwertige Experience: LLM-basierter Pass 4a klassifiziert IK-Tender-Subkategorie ("Process Cooling" / "Cold Store" / "Deep Freeze"), Matching läuft auf IK-spezifischen Feldern inkl. `served_categories` KO_SUBSET, PoC-Demo zeigt erkannte Kategorie. Abschluss: `agv_type` → `product_type` Rename.

### IK-Architekturentscheid (Option D — SA-Ruling 2026-07-19)
IK hat **einen Leaf** (`FoodBev:Refrigeration`), keine drei. Begründung: alle 3 Temperaturzonen (Process Cooling / Cold Store / Deep Freeze) teilen exakt dieselben 11 Felder — gleicher Feldset = Capability, kein Scope-Leaf. AGV-Leaves verdienen ihr Leafhood durch disjunkte Felder (Forklift ≠ AMR ≠ Tugger). Diese Bedingung ist für IK nicht erfüllt.

- Pass 4a läuft weiterhin via LLM und klassifiziert den Tender-Subtyp
- Klassifikationsergebnis (`"Cold Store"` etc.) → befüllt Tender-Feld `required_served_category`
- Intra-IK-Gate im Matching: `served_categories` (KO_SUBSET, Multi-Select auf Supplier-Seite)
- Dual-Capability-Supplier (CO2-Booster): 1 Record mit `served_categories = ["Cold Store", "Deep Freeze"]`
- `product_type` für IK-Supplier = `"Industrial Refrigeration"` (canonical_name des Domain-Nodes)

**Trigger für späteren Leaf-Split:** wenn ein KO-Level-Feld (nicht COND_KO) nur für eine `served_category` sinnvoll ist. Bis dahin bleibt 1 Leaf.

### Nicht-Ziele (diesen Sprint)
- EAV-Datenbankumbau (3rd-industry trigger)
- Neue Industrien jenseits IK

### Kernconstraints
- Keine Industry-Logik in Python: alles aus AP0 via `generate_all.py`
- Blank ≠ Zero: `None` = unbekannt, nie absent capability
- Neue Industrie wird ausschließlich über AP0 + Scope Registry hinzugefügt — kein Code-Change
- AGV-Behavior muss nach jeder Phase identisch bleiben (Tests grün, keine Golden-Regression bis Phase 2)

---

## 2. Was bereits implementiert ist (Stand 2026-07-18)

| Komponente | Status | Verifikation |
|---|---|---|
| IK drei Sub-Leaves in `scope_registry.json` | ⚠️ ZU ENTFERNEN | `FoodBev:Refrigeration:Process`, `:ColdStore`, `:DeepFreeze` — Option D: 1 Leaf, keine Sub-Leaves |
| `FoodBev:Refrigeration` mit `parent="*"` | ✅ | `config/scope_registry.json:92` — bleibt als einziger IK-Leaf |
| Pass 2b Domain-Detection (`domain_detection_template.txt`) | ✅ | `app.py:643` |
| Keyword-Fallback für Domain-Detection | ✅ | `app.py:660-666` |
| `_DOMAIN_CLASSIF_TEMPLATES` dispatch nach `detected_domain` | ✅ | `app.py:329-336` |
| `classification_template_foodbev_refrigeration.txt` | ✅ | `config/prompts/` |
| `is_agv_amr` aus `basic_template.txt` entfernt | ✅ | kein Hit |

**Einziger Pipeline-Blocker:** `app.py:673` — `is_agv = detected_domain == _SHARED_SCOPE`. IK erhält `is_agv=False` → gesamter 4a/4b/4c-Block wird übersprungen.

---

## 3. Weg einer Ausschreibung durch die Pipeline

```
PDF Upload
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  SCHRITT 0: Text-Extraktion (kein LLM)                          │
│  pdfplumber → raw_text (~80k Zeichen)                           │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  PASS 1: Grunddaten (basic_template.txt)  [domain-neutral]      │
│  Output: buyer, project_name, tender_category, summary,         │
│          contact_name/email/phone, deadline, tender_date        │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼ (wenn contact fehlt und doc > 6000 Zeichen)
┌─────────────────────────────────────────────────────────────────┐
│  PASS 1b: Contact-Fallback (letzte 4000 Zeichen)                │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  PASS 2: NACE-Klassifikation                                    │
│  Output: nace_tender, in_scope                                  │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  PASS 2b: Domain-Detection (domain_detection_template.txt)      │
│  Output: detected_domain ∈ {"Logistics:AGV",                   │
│          "FoodBev:Refrigeration", null}                         │
│  Fallback: Keyword-Scan auf ersten 5000 Zeichen                 │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  GATE: is_extractable = detected_domain in _EXTRACTABLE_DOMAINS │
│  _EXTRACTABLE_DOMAINS = alle Scopes mit parent="*"              │
│  → False: Extraktion endet hier (out-of-domain Tender)          │
│  → True:  Weiter mit Pass 4a                                    │
└─────────────────────────────────────────────────────────────────┘
    │ (nur wenn is_extractable = True)
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  PASS 4a: Sub-Typ-Klassifikation (LLM) [domain-spezifisch]     │
│  System:   _DOMAIN_SYSTEM[detected_domain]                      │
│            → lädt industry_readme_{domain_slug}.md              │
│  Template: _DOMAIN_CLASSIF_TEMPLATES[detected_domain]           │
│  AGV: canonical_type ∈ {"Forklift AGV","Tugger AGV","Mobile AMR"}│
│       → _LEGACY_MAP → leaf_scope_id (Routing)                  │
│  IK:  canonical_type ∈ {"Process Cooling","Cold Store",         │
│                          "Deep Freeze"}                          │
│       → stored as required_served_category (kein Scope-Routing) │
│       → _leaf_scope = detected_domain = "FoodBev:Refrigeration" │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  PASS 4b: Batch-Feld-Extraktion (LLM) [domain-spezifisch]      │
│  Template: extraction_template_{leaf_slug}.txt                  │
│  Felder:   alle Felder in resolution_order[leaf_scope]          │
│            → AGV: ~40 Felder | IK: ~12 Felder (inkl.           │
│              required_served_category bereits aus 4a)           │
│  System:   _DOMAIN_SYSTEM[detected_domain]                      │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼ (ein LLM-Call pro numerischem KO_IF_LT/GT-Feld)
┌─────────────────────────────────────────────────────────────────┐
│  PASS 4c: Per-Feld Präzisions-Extraktion                        │
│  AGV: ~8 Calls | IK: ~7 Calls (cooling_capacity_kw,            │
│  temperature_min_celsius, cop_efficiency,                       │
│  temperature_stability_k, room_volume_m3_max,                   │
│  blast_freeze_capacity_kg_h, pulldown_time_h)                   │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  SOURCE-SPAN HALLUCINATION GUARD (kein LLM)                     │
│  Layer 1: kein _source → null                                   │
│  Layer 0: source nicht im Dokument verankert → null             │
│  Layer 2: 4c abstained + source_confirms_value() False → null  │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  VALIDIERUNG (kein LLM)                                         │
│  validate_tender_values(): allowed_values-Filter                │
│  validate_agv_criteria(): Plausibility-Ranges                   │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  MATCHING (kein LLM)                                            │
│  AGV: Lädt Supplier via product_type → _LEGACY_MAP → leaf_scope │
│  IK:  Lädt Supplier via product_type="Industrial Refrigeration" │
│       → domain_scope="FoodBev:Refrigeration"                    │
│  Gates: product_type KO_IF_NEQ (Cross-Domain) →                 │
│         served_categories KO_SUBSET (Intra-IK) →               │
│         technische Felder (cooling_capacity_kw etc.)            │
│  Null-Regel (LL-06): null niemals KO; -15 Pt Penalty            │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
    Result (SSE-Stream → Frontend)
```

### LLM-Calls pro Tender-Typ

| Typ | Pässe | Calls | Dauer (est.) |
|---|---|---|---|
| Out-of-domain | 1+1b+2+2b | 3–4 | ~30 s |
| AGV | 1+1b+2+2b+4a+4b+4c×8 | 13–16 | ~330 s |
| IK | 1+1b+2+2b+4a+4b+4c×7 | 12–15 | ~280 s |

---

## 4. Phasen

---

### Phase 0 — Gate generisch machen
**Scope:** `app.py` (5 Stellen) + `generate_all.py` (Collision Guard)
**Dauer:** ~1 Tag
**AGV behavior-neutral:** Ja
**Golden Refresh:** Nein

#### Änderungen

**`app.py` — `_EXTRACTABLE_DOMAINS`** (nach Zeile 262):
```python
_EXTRACTABLE_DOMAINS = frozenset(_shared_candidates)
# {"Logistics:AGV", "FoodBev:Refrigeration"}
```

**`app.py:673`** — Gate generisch:
```python
# ALT: is_agv = result.get("detected_domain") == _SHARED_SCOPE
is_extractable = result.get("detected_domain") in _EXTRACTABLE_DOMAINS
```

**`app.py:691`, `app.py:954`** — `if is_agv` → `if is_extractable`

**`app.py:777`** — `_4c_scopes` über `_RESOLUTION_ORDER` (kein domain-Hardcode):
```python
_4c_scopes = frozenset(_RESOLUTION_ORDER.get(_leaf_scope, []))
```
Dazu Startup-Assertion: alle Leaves in `_LEGACY_MAP` müssen in `_RESOLUTION_ORDER` vorhanden sein.

**`app.py:509`** — Replay-Cache-Fallback:
```python
# ALT: or (_SHARED_SCOPE if cached.get("is_agv_amr") else None)
or cached.get("detected_domain")
```

**`generate_all.py`** — Collision Guard: wenn `field_name` in mehr als einem `fields.json`-Eintrag auftaucht, müssen `(data_type, unit)` identisch sein (Ausnahme: das eine Global-Feld `agv_type`/`product_type`). Sonst: `raise SystemExit`.

#### Definition of Done Phase 0
- [ ] `pytest tests/` — 239 Tests grün
- [ ] Alle 5 AGV-Golden-Tenders: Ergebnis byte-identisch
- [ ] **E2E LLM-Test:** `tender_ik_cold_store.pdf` hochladen → Log zeigt `detected_domain=FoodBev:Refrigeration` + `is_extractable=True` + "Pass 4a" Eintrag im Log (Pass 4a darf noch mit AGV-System-Context laufen — wird in Phase 1 gefixt)

---

### Phase 1 — Per-Domain System-Context + Domain-READMEs
**Scope:** `context_builder.py`, `app.py`, `generate_all.py`, Spec-Dateien umbenennen, IK-README schreiben
**Dauer:** ~1–2 Tage
**AGV behavior-neutral:** Ja — wenn AGV-README inhaltlich unverändert
**Golden Refresh:** Nein

#### Problem
`AGV_SYSTEM` ist ein einziger globaler System-Context — IK würde Pass 4a/4b mit AGV-Domänenwissen und AGV-KO-Feldliste laufen. Außerdem: `config/industry_readme.md` ist ein hardcodierter Name ohne Domain-Bezug.

#### README-Namenskonvention (Tech Lead Amendment)

Dateinamen werden aus dem Domain-Scope-ID abgeleitet — kein Hardcoding.

**Slug-Derivation** (in `generate_all.py`):
```python
def _domain_slug(scope_id: str) -> str:
    return scope_id.replace(":", "_").lower()
    # "Logistics:AGV" → "logistics_agv"
    # "FoodBev:Refrigeration" → "foodbev_refrigeration"
```

**Spec-Dateien (Quellen — manuell gepflegt):**
- `Spec/haystacked_industry_readme_logistics_agv.md` ← umbenennen von `Spec/haystacked_industry_readme.md`
- `Spec/haystacked_industry_readme_foodbev_refrigeration.md` ← neu schreiben

**`generate_all.py`** — synct alle Domain-READMEs automatisch:
```python
for domain_sid in extractable_domains:
    slug = _domain_slug(domain_sid)
    src = SPEC_DIR / f"haystacked_industry_readme_{slug}.md"
    dst = CONFIG_DIR / f"industry_readme_{slug}.md"
    if src.exists():
        dst.write_text(src.read_text())
    else:
        raise SystemExit(f"Missing README for domain {domain_sid}: {src}")
```
`config/industry_readme.md` (alter Name) wird nicht mehr generiert. Alle Consumers müssen auf `industry_readme_{slug}.md` umgestellt werden.

**`context_builder.py`** — `_load_readme(domain_sid)`:
```python
def _load_readme(domain_sid: str) -> str:
    slug = domain_sid.replace(":", "_").lower()
    path = CONFIG_DIR / f"industry_readme_{slug}.md"
    return path.read_text()  # kein Fallback — fehlende Datei = Build-Fehler
```
Außerdem: `_README_REMOTE` und `_README_LOCAL` (Synology-Fallback, `context_builder.py:11-12`) entfernen. Diese stehen im Widerspruch zur neuen One-README-per-Domain-Regel und würden bei fehlender Slug-Datei stumm eine falsche Quelle laden.

**`app.py`** — `_DOMAIN_SYSTEM` statt `AGV_SYSTEM`:
```python
_DOMAIN_SYSTEM: dict[str, str] = {
    sid: build_system_context(domain_prefix=sid)
    for sid in _EXTRACTABLE_DOMAINS
}
```
Bei allen Calls (Pass 4a/4b/4c): `_DOMAIN_SYSTEM[detected_domain]` statt `AGV_SYSTEM`.
`AGV_SYSTEM` als Name wird entfernt.

**IK-README Inhalt** (`Spec/haystacked_industry_readme_foodbev_refrigeration.md`):
Domänenwissen für das LLM: Kältemittel (R717/R744/R290/R134a), Kälteleistungsdefinition (kW Nettoleistung), COP-Berechnung, Temperaturbegriffe (Verdampfungstemperatur vs. Vorlauftemperatur vs. Raumtemperatur), Normen (EN 378, PED 2014/68/EU), Abgrenzung der 3 Sub-Typen. Länge: ~halbe AGV-README-Länge.

#### Definition of Done Phase 1
- [ ] `pytest tests/` — 239 Tests grün
- [ ] **Migration:** `git mv Spec/haystacked_industry_readme.md Spec/haystacked_industry_readme_logistics_agv.md`; `diff` gegen alte Datei = keine inhaltliche Änderung (AGV-behavior-neutral Nachweis)
- [ ] `generate_all.py:1916` Referenz auf alten Dateinamen aktualisiert
- [ ] `generate_all.py` generiert `config/industry_readme_logistics_agv.md` und `config/industry_readme_foodbev_refrigeration.md`; kein `config/industry_readme.md` mehr
- [ ] `context_builder.py`: kein `_README_REMOTE` / `_README_LOCAL` mehr (`context_builder.py:11-12` entfernt)
- [ ] Alle 5 AGV-Golden-Tenders: Ergebnis identisch
- [ ] **E2E LLM-Test (alle 3 IK-PDFs):**
  - `tender_ik_process_cooling.pdf` → `detected_domain=FoodBev:Refrigeration` + Pass 4a = `"Process Cooling"`
  - `tender_ik_cold_store.pdf` → Pass 4a = `"Cold Store"`
  - `tender_ik_deep_freeze.pdf` → Pass 4a = `"Deep Freeze"`
  - Log zeigt IK-README geladen (Länge sichtbar, nicht AGV-README-Länge)

---

### Phase 2 — Scope Registry bereinigen + `product_type` → Global
**Scope:** AP0 xlsx (③ Scope Registry Tab + 2 Felder-Zellen), `generate_all.py` (Sentinel-Expansion + `_DOMAIN_LEAVES`), `config/scope_registry.json` (wird regeneriert), `tests/unit/test_ap0_consistency.py`
**Dauer:** ~1 Tag
**AGV behavior-neutral:** Nein — allowed_values ändert sich (3 AGV → 4: 3 AGV + 1 IK-Domain)
**Golden Refresh:** Ja

#### Option D: Scope Registry Änderungen

**AP0 xlsx ③ Scope Registry Tab — IK Sub-Leaves entfernen:**
- Zeilen für `FoodBev:Refrigeration:Process`, `:ColdStore`, `:DeepFreeze` löschen
- `FoodBev:Refrigeration` erhält:
  - `canonical_name = "Industrial Refrigeration"` (für `product_type`-Routing)
  - `classification_guide` (bleibt — wird für `classification_template_foodbev_refrigeration.txt` genutzt)
  - `legacy_map` Einträge: `"Process Cooling" → "FoodBev:Refrigeration"`, `"Cold Store" → "FoodBev:Refrigeration"`, `"Deep Freeze" → "FoodBev:Refrigeration"` (alle 3 → 1 Leaf; `_LEGACY_MAP` in `app.py` bleibt uniform)
  - `resolution_order = ["FoodBev:Refrigeration"]` (nur der Domain-Node selbst)

**`_LEGACY_MAP` im Code bleibt uniform:** IK-canonical_type ("Cold Store") → `"FoodBev:Refrigeration"`. `_leaf_scope = "FoodBev:Refrigeration"` für alle IK-Tenders. Kein Code-Branch nötig.

#### `product_type` → Global Scope in AP0

**AP0 xlsx Felder-Tab:**
- `agv_type`-Zeile, Spalte Scope: `AGV_Shared` → `Global`
- `agv_type`-Zeile, Spalte Allowed Values: → Sentinel `@SCOPE_CANONICAL_NAMES`

**`generate_all.py`** — Sentinel-Expansion:
```python
if raw_allowed == "@SCOPE_CANONICAL_NAMES":
    allowed_values = sorted(
        d["canonical_name"]
        for d in scope_data["scopes"].values()
        if d.get("canonical_name")
    )
    # → ["Forklift AGV", "Industrial Refrigeration",
    #    "Mobile AMR", "Tugger AGV"]
    # (Process Cooling / Cold Store / Deep Freeze sind keine canonical_names
    #  von Scope-Nodes mehr — nur Werte in served_categories)
```

**`app.py`** — Domain-scoped 4a-Validation (Verteidigungslinie):
```python
_DOMAIN_CLASSIF_VALUES: dict[str, set[str]] = {
    # AGV: Leaves haben canonical_name
    "Logistics:AGV": {"Forklift AGV", "Tugger AGV", "Mobile AMR"},
    # IK: legacy_map-Keys für diesen Domain
    "FoodBev:Refrigeration": {"Process Cooling", "Cold Store", "Deep Freeze"},
}
# Nach Pass 4a: wenn canonical_type nicht in _DOMAIN_CLASSIF_VALUES[detected_domain] → warn + null
```

#### Definition of Done Phase 2
- [ ] `generate_all.py --dry-run`: `agv_type` scope=`*`, 4 allowed_values (`Forklift AGV`, `Industrial Refrigeration`, `Mobile AMR`, `Tugger AGV`)
- [ ] `config/scope_registry.json`: keine `FoodBev:Refrigeration:*` Einträge mehr
- [ ] `_LEGACY_MAP` enthält alle 3 IK-canonical_types → `"FoodBev:Refrigeration"`
- [ ] `pytest tests/` — alle Tests grün (`test_ap0_consistency.py` angepasst)
- [ ] AGV-Golden Refresh: alle 5 Goldens neu aufgezeichnet, Matching-Ergebnis identisch

---

### Phase 3 — IK-Inhalt in AP0 + Airtable + Goldens
**Scope:** AP0 xlsx (11 Felder), Airtable (manuell), `sync_airtable.py`, neue Golden-Dateien
**Dauer:** ~2–3 Tage
**AGV behavior-neutral:** Ja — additiv
**Golden Refresh:** Neue IK-Goldens

#### IK-Felder in AP0 (Scope: `FoodBev:Refrigeration`, Entity: Base Model)

> **Wichtig (SA-Ruling):** Entity = **Base Model** (`base_model_extensions`). `data_loader.py` wildcarded `bme.*` für Spec-Felder; Product-Columns kommen aus einer fixen `p.*`-Liste. IK-Felder auf `products` würden silently `None` laden.

> **Option D:** `served_categories` ist das Intra-IK-Gate (KO_SUBSET). `required_served_category` wird aus Pass 4a befüllt (kein separater 4b-Aufruf nötig — Wert bereits bekannt). Scope aller Felder: `FoodBev:Refrigeration` (kein Sub-Leaf).

| field_name | Operator | data_type | Quelle | Pass 4c | Level |
|---|---|---|---|---|---|
| `served_categories` | `KO_SUBSET` | MultiSelect | Supplier (Airtable) | — | KO |
| `cooling_capacity_kw` | `KO_IF_LT` | Float | Pass 4b | ✅ | KO |
| `temperature_min_celsius` | `KO_IF_GT` | Float | Pass 4b | ✅ | KO |
| `refrigerant_types` | `KO_SUBSET` | MultiSelect | Pass 4b | — | KO |
| `certifications_ik` | `KO_SUBSET` | MultiSelect | Pass 4b | — | KO |
| `cop_efficiency` | `KO_IF_LT` | Float | Pass 4b | ✅ | KO |
| `cooling_medium` | `KO_IF_NEQ` | SingleSelect | Pass 4b | — | COND_KO |
| `temperature_stability_k` | `KO_IF_GT` | Float | Pass 4b | ✅ | COND_KO |
| `room_volume_m3_max` | `KO_IF_LT` | Float | Pass 4b | ✅ | COND_KO |
| `humidity_control_capable` | `KO_BOOL_REQUIRED` | Boolean | Pass 4b | — | COND_KO |
| `blast_freeze_capacity_kg_h` | `KO_IF_LT` | Float | Pass 4b | ✅ | COND_KO |
| `pulldown_time_h` | `KO_IF_GT` | Float | Pass 4b | ✅ | COND_KO |

`required_served_category` (Tender-Seite des KO_SUBSET-Paares) = Ausgabe von Pass 4a; wird nicht in AP0 als separates Tender-Feld definiert, sondern als `tender_key` des `served_categories`-Feldes.

Jedes 4b-Feld benötigt: Extraction Hint (in AP0 Description-Spalte), Plausibility-Range (min/max), NULL RULE im Hint.

#### Airtable (manuell)
- `agv_type` (nach Phase 4: `product_type`) singleSelect: Wert `"Industrial Refrigeration"` für alle IK-Supplier (einheitlich — kein Cold Store / Deep Freeze als product_type, das sind `served_categories`-Werte)
- `served_categories` MultiSelect: Optionen `["Process Cooling", "Cold Store", "Deep Freeze"]` — neues Airtable-Feld in `base_model_extensions`
- IK Product-Records: GEA, Güntner, BITZER — prüfen ob vorhanden, sonst anlegen
- Dual-Capability-Produkte (CO2-Booster): **1 Record** mit `served_categories = ["Cold Store", "Deep Freeze"]` (kein Dual-Record mehr)

#### Definition of Done Phase 3
- [ ] `generate_all.py`: alle 11 IK-Felder in `config/fields.json` mit korrektem scope
- [ ] `sync_airtable.py --local`: IK-Supplier ohne Fehler geladen
- [ ] Alle 5 AGV-Goldens: unverändert
- [ ] **E2E LLM-Test (alle 3 IK-PDFs):**
  - Pass 4a klassifiziert korrekt
  - Pass 4b extrahiert IK-Felder (≥4 non-null Felder erwartet)
  - Pass 4c läuft für ≥1 numerisches Feld
  - Matching liefert ≥1 IK-Supplier-Match
- [ ] Golden-Files committed: `golden_run_tender_ik_process_cooling.json`, `_cold_store.json`, `_deep_freeze.json`

---

### Phase 4 — `agv_type` → `product_type` Rename + Cleanup
**Scope:** AP0 xlsx (field_name-Zelle), `generate_all.py`, alle Python-Dateien (~50 echte Code-Refs), Test-Fixtures, Airtable (3 Tabellen manuell), SQLite-Schema-Regen
**Dauer:** ~1–2 Tage
**AGV behavior-neutral:** Ja — rein mechanisch
**Golden Refresh:** Verify (Schema-Change, kein inhaltlicher Unterschied erwartet)

#### Warum jetzt (nicht deferred)
`agv_type = "Process Cooling"` ist für jeden Nutzer und Entwickler semantisch falsch. Der PoC kann nicht sauber demonstriert werden wenn das Feld-Label im UI und in der Datenbank einen falschen Namen trägt.

#### Änderungen

**AP0 xlsx:** `agv_type` → `product_type` in der field_name-Zelle. `generate_all.py` regeneriert alle config mit neuem Namen.

**Airtable (manuell):** Spalte `agv_type` in den 3 Tabellen (Base Models, Products, Base Model Extensions) auf `product_type` umbenennen.

**Was wird umbenannt / was bleibt:**
- `agv_type` (field_name im AP0, physische DB-Spalte, Python-Attribut) → `product_type`
- `required_agv_type` (AP0 Tender-Key) **bleibt** — Umbenennung würde LLM-Output-Vertrag brechen und alle Replays invalidieren. Kann eigenständig später erfolgen.
- Lokale Variablen wie `canonical_agv_type`, `agv_type_keyword_fallback` → ebenfalls umbenennen (keine semantische Auswirkung, nur Konsistenz)

**Code:** Sweep `\bagv_type\b` (whole-word) → `product_type` in:
- `app.py` (inkl. `_LEGACY_MAP`-Key `"agv_type"`, `canonical_agv_type` → `canonical_product_type`)
- `src/matching.py` (inkl. `matching.py:357` `MatchResult.to_dict()` Key, `matching.py:363-368` field-spread)
- `src/data_loader.py` (inkl. `:29` SELECT-Spalte, `:178` Dataclass-Konstruktor)
- `src/models.py` (`Product.agv_type: str` Attribut → `product_type`)
- `src/context_builder.py`
- `src/tender_store.py` (`is_agv_amr`-Cleanup-Kommentar bei :22)
- `scripts/sync_airtable.py`
- `templates/index.html`, `templates/debug.html`, `templates/db.html` (type-pill Rendering)
- `tests/unit/` (alle Fixtures und Assertions)
- `tests/tenders/golden_run_*.json` (Feld-Keys in golden files)

> **Hinweis:** `scripts/airtable_ik_migration.py` schreibt `"agv_type"` mit `typecast=True` — dieses Script NICHT nach dem Airtable-Rename neu ausführen. Phase 3 muss vollständig abgeschlossen sein bevor Phase 4 startet.

**`sync_airtable.py`:** Schema-Regen nach Airtable-Rename; `python3 sync_airtable.py --local` muss grün sein.

#### Definition of Done Phase 4
- [ ] `grep -rw "agv_type" src/ app.py scripts/ templates/` — kein Treffer (außer `required_agv_type`, das absichtlich bleibt)
- [ ] `src/models.py`: `Product.agv_type` → `Product.product_type` — greifbar in `data_loader.py` JOIN
- [ ] `pytest tests/` — alle Tests grün
- [ ] `sync_airtable.py --local` — kein Fehler
- [ ] Alle 5 AGV-Goldens + 3 IK-Goldens: verify (inhaltlich identisch, nur Feld-Key geändert)
- [ ] **Manueller UI-Check:** AGV-Tender hochladen → Typ-Pill zeigt "Forklift AGV" / "Tugger AGV" / "Mobile AMR" (nicht `–`); IK-Tender → Typ-Pill zeigt "Process Cooling" / "Cold Store" / "Deep Freeze"
- [ ] **E2E LLM-Test:** Ein AGV-Tender + Ein IK-Tender — `product_type` korrekt im Output

---

## 5. Invarianten (halten nach jeder Phase)

- **Blank ≠ Zero:** `None` = unbekannt; nie als "fehlt diese Eigenschaft"
- **Kein Industry-Hardcode in Python:** alles aus AP0/generate_all.py
- **README-Dateinamen** aus Domain-Slug abgeleitet — kein `industry_readme.md` ohne Slug
- **`source_confirms_value()` / `source_is_grounded()`** field-agnostic — kein IK-spezifischer Code
- **AP0 → generate_all → config → Runtime** — kein direktes Editieren von `config/`

---

## 6. SA-Review-Ergebnisse

### Review 1 (Fable, 2026-07-18) — CONDITIONAL PASS → v0.2/v0.3
Eingearbeitete Korrekturen:
1. `_4c_scopes`: `_RESOLUTION_ORDER.get(_leaf_scope, [])` statt domain-scan + Startup-Assertion
2. Pass 4c für IK: 7 Felder (alle KO_IF_LT/GT Float, unabhängig von KO vs COND_KO-Level)
3. IK-Felder: Entity = Base Model (nicht Product) — `data_loader.py` JOIN-Kompatibilität

### Review 2 (Fable, 2026-07-19) — CONDITIONAL PASS → v0.4
Eingearbeitete Korrekturen:
1. **Phase 4 Sweep-Liste vervollständigt:** `templates/index.html`, `templates/debug.html`, `templates/db.html` und `src/models.py` hinzugefügt; ohne diese Templates würden Typ-Pills stumm `–` rendern. DoD um manuellen UI-Check erweitert.
2. **Phase 4 DoD-Grep präzisiert:** `\bagv_type\b` (whole-word); `required_agv_type` (Tender-Key) bleibt absichtlich.
3. **Phase 1 Migration explizit im DoD:** `git mv` Spec-Datei + Diff-Nachweis + `generate_all.py:1916` + Synology-Fallback entfernen.

### Review 3 / Arch-Ruling (Fable, 2026-07-19) — Option D → v0.5
Frage: Gibt es IK-Subdomänen mit disjunkten Feldern, die Scope-Routing erfordern würden?

**Befund:** Nein. Alle IK-Temperaturzonen teilen dieselben 11 Felder. Kühlturm/Transportkühlung hätten disjunkte Felder, sind aber Adjacent Equipment (eigene Sibling-Leaves), keine IK-Subtypes. Option D schließt nichts.

**Option D ist die richtige Wahl.** Konsequenzen für Spec:
- IK: 1 Leaf (`FoodBev:Refrigeration`); Sub-Leaves aus scope_registry entfernen
- Pass 4a für IK: läuft weiterhin, klassifiziert → Output in `required_served_category`
- `_LEGACY_MAP` bleibt uniform: "Process Cooling"/"Cold Store"/"Deep Freeze" → alle `"FoodBev:Refrigeration"`
- `served_categories` KO_SUBSET (Multi-Select, Supplier-seitig) ist das Intra-IK-Gate
- `product_type` für IK-Supplier = `"Industrial Refrigeration"` (canonical_name des Domain-Nodes)
- Dual-Capability CO2-Booster: 1 Record statt 2

Upgrade-Pfad D→N-Leaves: niedrig (Pass 4a bleibt erhalten, nur Record-Partitionierung als Aufwand). Trigger: ein KO-Level-Feld, das nur für eine served_category gilt.
