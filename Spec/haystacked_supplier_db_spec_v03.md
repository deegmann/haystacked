# haystacked — Supplier Database Development Specification

**Focus:** AGV (Automated Guided Vehicle) / Intralogistics · PoC (Proof of Concept) phase
**Version:** 0.4 · May 2026
**Changes vs. 0.3:** navigation_type reclassified KO → Cond. K.O.; infrastructure_required
  reclassified KO → Cond. K.O.; Mobile AMR type-specific key fields updated accordingly.
**Confidential**

---

## 1. Purpose & Context

This document specifies the development work packages for the haystacked supplier database. It serves as complete context for a Claude Code session in which the implementation is worked through step by step.

**Starting situation:**
- haystacked is a B2B (Business-to-Business) matching platform for complex engineering tenders and specialised suppliers.
- Starting market: AGV / Intralogistics.
- The PoC is already running; supplier data currently sits in a CSV (Comma-Separated Values) file.
- Goal of this specification: structure the database cleanly, set it up in Airtable, and connect it to the PoC.

**Abbreviations:**
- AGV = Automated Guided Vehicle
- AMR = Autonomous Mobile Robot
- VNA = Very Narrow Aisle
- ASRS = Automated Storage and Retrieval System
- OEM = Original Equipment Manufacturer
- UUID = Universally Unique Identifier
- CSV = Comma-Separated Values
- JSON = JavaScript Object Notation
- K.O. = Knockout
- PoC = Proof of Concept
- F&B = Food & Beverage
- WMS = Warehouse Management System

---

## 2. Design Principles

### 2.1 Four matching levels

Every database field belongs to exactly one matching level:

| Level | Name | Meaning |
|---|---|---|
| 1 | K.O. criteria | Binary must-conditions. A supplier failing even one K.O. criterion is fully excluded from matching — regardless of all other values. |
| 2 | Conditional K.O. | Scores by default, but flips to a hard filter when the buyer explicitly requires the capability, or the environment demands it. Example: outdoor capability, IP rating, VNA, closed-pallet handling, barcode verification, VDA 5050, service region. |
| 3 | Scoring criteria | Continuous or graded values that determine the ranking of the surviving suppliers. Example: number of references, lead time, certifications, accuracy, throughput. |
| 4 | Context | Qualitative information with no direct matching weight, giving the buyer trust and orientation. Example: typical project size, known customer structure, dimensions. |

> **Implementation note:** a Conditional K.O. field carries BOTH a scoring weight and a flag "promote to K.O. if buyer requirement = required". In the tender model the buyer marks each such field as *required* / *preferred* / *not relevant* — only "required" activates the knockout.

### 2.2 Three entity layers

Matching happens at the product level, not the company level. The technical properties, however, sit one layer deeper — on the base model — because the same physical machine is frequently sold under several brands (OEM rebadging).

- **Company (Level 1):** master data of the commercial provider (manufacturer, brand, or distributor). Maintained once, valid for all its products.
- **Product (Level 2):** the branded commercial offering — the actual matching object from the buyer's perspective. Carries the *commercial* fields (brand, price band, lead time, service coverage, references for this offering). One company can have several products.
- **OEM Base Model (Level 3):** the actual physical machine / engineering platform. Carries all *intrinsic* technical properties (the entire AP0 extension schema: payload, navigation, accuracy, dimensions, …). Maintained **once** and inherited by every rebadged product.

**Relationships:**
- 1 Company → N Products
- 1 OEM Base Model → N Products (all rebadges of the same machine)
- 1 Product → exactly 1 OEM Base Model

**Rationale.** Verified example: Quicktron builds the machine; KION distributes it as Linde Material Handling "M60"/"M100" and via STILL and Dematic. Four products, one base model. Maintaining the technical data once on the base model avoids (a) threefold, diverging data entry for the same machine and (b) inconsistent scoring of identical devices. Learn one technical detail about one brand and it automatically holds for all siblings.

**Non-rebadged products (always-L3 model).** The technical data lives on the Base Model (L3) **in every case, never on the Product** — there is no technical field on L2. Every product points to exactly one base model via `base_model_id`. A device sold under only one brand (e.g. MiR250) simply forms a 1:1 relationship Product ↔ Base Model. This keeps the model uniform: the technology exists exactly **once per machine**, never duplicated, and a database query is always the same uniform join (`product → base_model → extension`) — no branching on "is the tech on L2 or L3?".

**Consequence — there is nothing to keep consistent.** Because there is exactly one L3 per physical machine, all rebadged products point to that single row. Maintaining the Quicktron M-series specs once automatically applies them to Linde "M60", STILL, and Dematic. The real challenge is therefore not *consistency* but *deduplication*: correctly recognising that "Linde M60" and "Quicktron M" are the same machine and linking both to the same L3 — rather than accidentally creating two L3 records for one machine. This is a data-entry task, addressed by the merge process (see §9, open point #5).

**The `is_oem_product` flag is derived, not structural.** It does not decide *whether* an L3 exists (one always does). It merely records whether the selling company is the manufacturer: `is_oem_product = (company_id == base_model.oem_company_id)`. true = the brand is the original maker; false = the product is a rebadge of someone else's machine.

**Visibility of the OEM link (a strategic decision, not a technical detail).** Whether the build-identity is disclosed to the buyer is a business decision, controlled by a flag `oem_link_public` (Boolean) per base model. Internally the link is *always* maintained (efficiency, data quality, single source of truth); disclosure is optional and potentially a differentiator for haystacked.

### 2.3 Polymorphism approach (AGV types)

Because the subtypes (Forklift AGV, Tugger AGV, Mobile AMR) have very different technical properties, the following structure is used. The type-specific fields now attach to the **OEM Base Model**, no longer to the Product (because the technology is a property of the machine, not of the branded offering):

- A `base_models` table with generic technical fields plus a mandatory `agv_type` field (dropdown).
- A linked `base_model_extensions` table with type-specific fields, populated sparsely (empty fields for non-relevant types).
- A `products` table (commercial branded offerings), linked to `companies` and to `base_models`.
- In Airtable, a filtered view per AGV type on `base_model_extensions` shows only the relevant fields — this solves the data-entry problem without true polymorphism.
- The CSV export produces three files: `companies.csv` + `products.csv` + `base_model_extensions.csv`, linked via UUID.

> **Note:** True polymorphism (separate tables per type) was deliberately not chosen, as it would needlessly complicate the Airtable export and the PoC connection. After the PoC, the design can migrate to PostgreSQL (Post-Gres Structured Query Language) with JSONB (JSON Binary) columns.

> **Note on migrating the schema from v0.1:** in v0.1 the extension fields attached to `product_id`. From v0.2 they attach to `base_model_id`. For data already captured, a 1:1 base model is created per product and the extension is re-pointed there; rebadges are subsequently merged manually.

### 2.4 Migration safety

- `company_id`, `product_id`, and `base_model_id` are UUIDs from the start — no auto-increment integers.
- UUIDs stay stable when moving from Airtable → PostgreSQL → another system.
- The extension schema is documented so it can be transferred into any target architecture.

---

## 3. Database Schema (generic fields)

**Entity overview (three layers):**

```
Company (1) ───< Product (N) >─── (1) OEM Base Model (1) ───< Base Model Extension (1:1, type-specific)
  Level 1            Level 2                Level 3
 sells           branded offering      physical machine
 (commercial)    (commercial)          (intrinsic technology)
```

- Matching technology (K.O. / Cond. K.O. / Scoring) lives mostly in **Base Model Extension** (Level 3).
- Commercial matching criteria (service coverage, project size, lead time) live in **Product** (Level 2).
- Provider trust (size, certifications, languages) lives in **Company** (Level 1).
- `oem_company_id` on Level 3 may point to a *different* company than the selling one — this represents rebadging correctly.

### 3.1 Company table (Level 1 — the provider)

| Field | Type | Matching Level | Mandatory | Description |
|---|---|---|---|---|
| `company_id` | UUID | — | ✓ | Primary key, system-generated |
| `company_name` | Text | — | ✓ | Official company name |
| `country` | ISO 3166 (2-letter) | Cond. K.O. | ✓ | Delivery country; K.O. filter possible |
| `hq_city` | Text | Context | — | Headquarters city |
| `employee_count_range` | Dropdown | Scoring | ✓ | <50 / 50–250 / 250–1000 / >1000 |
| `founding_year` | Integer | Context | — | Year founded |
| `website` | URL | — | — | Company website |
| `certifications_generic` | Multi-Select | Scoring | — | ISO 9001, etc. |
| `languages_spoken` | Multi-Select | Cond. K.O. | ✓ | Communication languages |
| `export_capable` | Boolean | Cond. K.O. | ✓ | International delivery capability |
| `last_updated` | Date | — | ✓ | Last data refresh |

### 3.2 Products table (Level 2 — the branded commercial offering)

The product is the brand-side offering. It carries **only commercial** fields; the technology lives in the linked base model (3.3).

| Field | Type | Matching Level | Mandatory | Description |
|---|---|---|---|---|
| `product_id` | UUID | — | ✓ | Primary key, system-generated |
| `company_id` | UUID (Linked) | — | ✓ | Foreign key → Company (who sells it) |
| `base_model_id` | UUID (Linked) | — | ✓ | Foreign key → OEM Base Model (what it technically is) |
| `product_name` | Text | — | ✓ | Brand name of the offering (e.g. "Linde M60") |
| `agv_type` | Dropdown | K.O. | ✓ | Must match the base model (denormalised for filtering) |
| `product_description` | Long Text | Context | ✓ | Max 500 characters |
| `reference_count` | Integer | Scoring | — | References of this branded offering (blank = unknown) |
| `min_project_value_eur` | Integer | Cond. K.O./Scoring | — | Minimum project size in EUR |
| `max_project_value_eur` | Integer | Cond. K.O./Scoring | — | Maximum project size in EUR |
| `lead_time_weeks` | Integer | Scoring | — | Lead time in weeks |
| `distribution_model` | Dropdown | Context | — | Direct / Dealer Network / Integrator only / License Platform |
| `is_oem_product` | Boolean (derived) | Context | — | Derived: company_id == base_model.oem_company_id. true = seller is the maker; false = rebadge |
| `service_coverage` | Multi-Select | Cond. K.O. | ✓ | None / DACH / EU / Global |
| `active` | Boolean | — | ✓ | Product currently available |

### 3.3 OEM Base Model table (Level 3 — the physical machine)

The base model carries the intrinsic technology. It is maintained once and inherited by all rebadged products. Linked via linked record to `base_model_extensions` (type-specific, AP0).

| Field | Type | Matching Level | Mandatory | Description |
|---|---|---|---|---|
| `base_model_id` | UUID | — | ✓ | Primary key, system-generated |
| `base_model_name` | Text | — | ✓ | Internal machine name (e.g. "Quicktron M-series rev1") |
| `oem_company_id` | UUID (Linked) | Context | — | Actual manufacturer / technology owner (may differ from the selling company) |
| `agv_type` | Dropdown | K.O. | ✓ | VNA / Tugger / AMR / Stacker / Other |
| `oem_link_public` | Boolean | — | ✓ | May the build-identity be disclosed to the buyer? (default: false) |
| `last_updated` | Date | — | ✓ | Last data refresh |

### 3.4 Base Model Extensions table (AGV-type-specific, Level 3)

Linked via linked record to the base models table (previously attached to Product — from v0.2 attached to the base model). The fields are fully worked out in AP0. Representative excerpt:

| Field | Type | Matching Level | Mandatory | Description |
|---|---|---|---|---|
| `extension_id` | UUID | — | ✓ | Primary key |
| `base_model_id` | UUID (Linked) | — | ✓ | Foreign key → OEM Base Model |
| `agv_type` | Dropdown | — | ✓ | Must match the linked base model |
| `max_payload_kg` | Float | K.O. | — | Maximum load capacity in kg |
| `navigation_type` | Multi-Select | Cond. K.O. | — | Laser / Natural Feature / Magnetic / Contour. Scores by default; hard filter only when buyer explicitly marks infrastructure-free navigation as required. |
| `safety_standard` | Multi-Select | Scoring | — | e.g. ISO 3691-4 (see AP0: no conformity marks such as CE) |
| `outdoor_capable` | Boolean | Cond. K.O. | — | Outdoor operation possible |
| `fleet_management_system` | Dropdown | K.O. | — | Proprietary / Open API / VDA 5050 / WMS-native |
| `integration_capability` | Multi-Select | Scoring | — | SAP / WMS / REST API / etc. |
| `min_aisle_width_mm` | Integer | K.O. | — | Relevant especially for VNA |

> **Note:** AP0 (the domain field specification) completes this list before AP1. Fields still missing or mis-typed here are corrected in AP0. From v0.2 all AP0 extension fields attach to the **base model** (Level 3), no longer to the Product.

---

## 4. AGV Type Overview

The PoC uses **three** subtypes. AGV/AMR is not split by hard marketing labels; the type is derived from properties (navigation, lift, rotation, grid dependency, picking mechanism). The former Undercarriage / Goods-to-Person / Picking distinctions are the *same free-navigating hardware in different workflows* and are therefore unified into one **Mobile AMR** subtype, with the workflow captured as a property (`workflow_capability`). Key fields are preliminary — AP0 specifies them fully.

| Subtype | Example manufacturers | Core use case | Type-specific key fields (selection) |
|---|---|---|---|
| Forklift AGV | Jungheinrich, DS Automotion, AGILOX, Toyota | Pallet storage & retrieval, incl. VNA (Very Narrow Aisle) and reach/counterbalance | `lifting_height_mm` (K.O.), `min_aisle_width_mm` (K.O.), `drive_type`, `forks_free_floating` (Cond. K.O.) |
| Tugger AGV | KIVNON, DS Automotion, STILL, Vecna | Material supply trains in production | `towing_capacity_kg` (K.O.), `coupling_type`, `trailer_steering_technology`, `route_type` |
| Mobile AMR | MiR, AGILOX, Geek+, Locus Robotics | Free-navigating transport, Goods-to-Person, and picking support | `workflow_capability` (Cond. K.O.), `navigation_type` (Cond. K.O. — scores by default, hard filter only when buyer requires infrastructure-free), `grid_required`, `rotation_capable`, `picking_mechanism` |

> **Note:** The workflow of a Mobile AMR (transport vs. goods-to-person vs. picking support) is a property, not a separate subtype — the same machine can offer several. ASRS (Automated Storage and Retrieval System) and sorter robots are out of scope for the PoC and tracked as future main categories. See the AP0 field specification and the Industry Read Me for the non-obvious domain relationships behind this.

---

## 5. Work Packages — Overview

The work packages are strictly sequential — each WP presupposes the previous one.

| WP | Title | Input | Output | Effort |
|---|---|---|---|---|
| AP0 | Domain field specification per AGV type | Domain knowledge (Christian) | Schema document: complete field lists per AGV type | ~3–4h (domain work) |
| AP1 | Schema definition | AP0 document | Formal database specification: all fields, types, levels | ~2–3h |
| AP2 | Airtable setup | AP1 | Airtable base with tables, views, forms | ~2–3h |
| AP3 | Initial population (10 suppliers) | AP2 | 10 complete, validated AGV supplier profiles | ~4–5h |
| AP4 | Export pipeline | AP2 + AP3 | `companies.csv` + `products.csv` + `base_model_extensions.csv`, UUID-stable | ~1h |
| AP5 | PoC connection & validation | AP4 | Running demo, matching result documented | ~3–4h |
| AP6 (opt.) | F&B parallel slice | AP1 + AP2 | 3–5 F&B profiles as a scalability demonstration | ~2h |

---

## 6. Detailed Specification per Work Package

### AP0 — Domain Field Specification

**Task:** For each of the 5–10 AGV types, work out a complete list of matching-relevant fields. Pure domain-knowledge work, no tool, no code.

**To clarify per type:**
- Which technical properties are absolute K.O. criteria for a tender?
- Which properties are conditional K.O. (only binding when the buyer requires them)?
- Which properties improve the ranking (Scoring)?
- Which information is useful to the buyer but not a matching criterion (Context)?
- Which data type fits (Boolean, number with unit, dropdown with defined values, multi-select)?

**Deliverable:** Structured document with field lists per AGV type — input for AP1. (Companion: the Industry Read Me, which gives the non-obvious domain relationships.)

**Validation:**
- Review the schema with Marcus: are all K.O. criteria from real AGV practice captured?
- Spot-check: can a real tender be fully described with the defined fields?

---

### AP1 — Schema Definition

**Task:** Convert the AP0 document into a formal database specification.

**Concrete steps:**
- Finalise the generic Company, Product, and OEM Base Model fields from section 3.
- Insert the extension fields from AP0 into the `base_model_extensions` table.
- For each field, set the Airtable-native type (Single Line Text, Number, Checkbox, Single Select, Multi Select, Linked Record, URL).
- List all dropdown values for `agv_type` and every select field completely.
- Tag each field with its entity layer (Company / Product / Base Model) per the AP0 "Entity" column.

**Deliverable:** Updated version of this document (section 3 fully completed).

**Validation:** Completeness check — every field has a type, matching level, entity layer, and mandatory flag.

---

### AP2 — Airtable Setup

**Task:** Set up the Airtable base per the AP1 specification. After AP2 the database is ready to populate.

**Concrete steps:**
- Create 4 tables: `Companies`, `Products`, `Base Models`, `Base Model Extensions`.
- Create all fields with the correct Airtable field type.
- Set up linked records: `Products → Companies`, `Products → Base Models`, `Base Model Extensions → Base Models`.
- Create one filtered view per AGV type in the `Base Model Extensions` table (filter: `agv_type = 'VNA'`, etc.).
- Configure input forms for Companies, Products, and Base Models (usable by non-programmers).

**Deliverable:** Working Airtable base; link accessible to Marcus.

**Validation:**
- Fill in a test form: does Airtable write the data correctly into all linked tables?
- Filtered views correctly show only type-relevant fields.

---

### AP3 — Initial Population (10 suppliers)

**Task:** Enter the first 10 AGV supplier profiles from public sources (websites, datasheets, VDMA directory) in a structured way.

**Quality criteria per profile:**
- All mandatory fields (✓) are filled.
- At least 3 scoring fields are filled.
- `agv_type` is set correctly.
- The source of the information is noted in the notes field.
- Where a machine is a known rebadge, the base model is linked / merged.

**Deliverable:** 10 complete profiles in Airtable, with at least 3 different AGV types represented.

**Validation:**
- Spot-check: cross-check 2–3 profiles manually against public sources (website, datasheet).
- Completeness check: all mandatory fields filled, no type inconsistencies.

---

### AP4 — Export Pipeline

**Task:** Configure the Airtable-native CSV export so the exported files can be read directly by the PoC.

**Concrete steps:**
- Run the Airtable export for the relevant tables (`Companies`, `Products`, `Base Model Extensions`).
- Reconcile the column names in the export with the PoC's expectations.
- Check UUID persistence: are `company_id`, `product_id`, and `base_model_id` present in the export and stable?
- Document the export routine (step-by-step instructions for non-programmers).

> **Note:** Since the PoC currently consumes a single CSV file, the import logic in the PoC must be adapted when moving to multiple files. That is part of AP5, not AP4.

**Deliverable:** `companies.csv` + `products.csv` + `base_model_extensions.csv`; documented export routine.

**Validation:**
- Are all 10 profiles present in the export?
- Are UUIDs correctly linked across the files (product → company, product → base model)?

---

### AP5 — PoC Connection & Validation

**Task:** Feed the exported CSV files into the PoC matching engine. The existing import logic must be rebuilt from one to multiple CSV files.

**Concrete steps:**
- PoC code: switch import logic to multiple CSV files.
- Implement join logic: `base_model_id` and `company_id` as keys between the files; the product row resolves both.
- Parse multi-select fields correctly (pipe-separated: `'Laser|Natural Feature'` → array).
- Run a demo tender through the system.
- Document the result: which suppliers match? Which don't? Why?

**Deliverable:** Running matching engine; documented matching result for at least one demo tender.

**Validation:**
- At least one tender produces a ranking with ≥ 3 suppliers.
- The scores are traceable (K.O. exclusions and scoring weights are explainable).
- The result is demo-ready for investor conversations.

---

### AP6 (optional) — F&B Parallel Slice

**Task:** Create 3–5 F&B supplier profiles with their own extension schema — as proof that the architecture scales industry-agnostically.

**Precondition:** AP5 runs stably and there is time. AP6 must not destabilise the AGV implementation.

**Approach:**
- Define a new extension schema for F&B (Unit Operations: pasteurisation, UHT, sterilisation, etc.).
- In Airtable: a new `agv_type`/`product_type` value `'F&B'` + a new filtered view.
- Enter 3–5 F&B supplier profiles from public sources.

**Deliverable:** At least 3 F&B profiles in the system; matching against a demo F&B tender works.

**Validation:**
- F&B profiles do not influence the AGV matching (clean separation via type).
- Communicable as a "proof of scalability" to investors.

---

## 7. CSV Export Format

### companies.csv

| Column | Type | Note |
|---|---|---|
| `company_id` | UUID | Primary key — stable across all exports |
| `company_name` | Text | |
| `country` | ISO 3166 | K.O. filter |
| `employee_count_range` | Enum | <50 / 50-250 / 250-1000 / >1000 |
| `service_coverage` | Text (Multi) | Pipe-separated |

### products.csv

| Column | Type | Note |
|---|---|---|
| `product_id` | UUID | Primary key — stable across all exports |
| `company_id` | UUID | Foreign key → `companies.csv` |
| `base_model_id` | UUID | Foreign key → `base_model_extensions.csv` (join key) |
| `company_name` | Text | Denormalised for simpler PoC import |
| `product_name` | Text | |
| `agv_type` | Enum | VNA / Tugger / AMR / Stacker |
| `reference_count` | Integer | Blank = unknown (not = 0) |
| `lead_time_weeks` | Integer | |
| `active` | Boolean | true / false |

### base_model_extensions.csv

| Column | Type | Note |
|---|---|---|
| `extension_id` | UUID | Primary key |
| `base_model_id` | UUID | Foreign key → `products.csv` (join key) |
| `agv_type` | Enum | Must match the linked base model |
| `max_payload_kg` | Float | Blank = unknown |
| `navigation_type` | Text (Multi) | Pipe-separated: `'Laser\|Natural Feature'` |
| `outdoor_capable` | Boolean | true / false / blank (unknown) |
| `fleet_management_system` | Enum | Proprietary / Open API / VDA 5050 / WMS-native |
| `integration_capability` | Text (Multi) | Pipe-separated: `'SAP\|WMS\|REST'` |
| `[further fields from AP0]` | — | Columns added after AP0 |

> **Note:** Multi-select values are exported pipe-separated. The PoC import must split these fields accordingly. This is implemented in AP5.

---

## 8. Technical Stack

| Component | Decision & rationale |
|---|---|
| Database (PoC) | Airtable — simple frontend, native CSV export, API available, free up to 1,000 records |
| Database (post-PoC) | PostgreSQL with a JSONB column for extension schemas — lossless migration via UUID keys |
| Export format | CSV — three files (`companies` + `products` + `base_model_extensions`), UUID-linked |
| IDs | UUID v4 — from the start, no auto-increment integers |
| Multi-select encoding | Pipe-separated in CSV: `'Laser\|Natural Feature'` |
| Frontend (PoC) | Airtable-native forms and views |
| Frontend (post-PoC) | Low-code tool (Retool / Budibase) or custom web app |

---

## 9. Open Points before the Claude Code Session

| # | Open point | Owner | When |
|---|---|---|---|
| 1 | AP0: work out complete field lists per AGV type (K.O., Cond. K.O., Scoring, Context, type) | Christian | Before AP1 |
| 2 | PoC code: exactly how is the CSV currently read? (column names, delimiter, encoding) | Christian | Before AP4/AP5 |
| 3 | Airtable account: who creates the base? | Both | Before AP2 |
| 4 | Demo tenders: are existing tenders usable as anonymised test cases? | Christian | Before AP5 |
| 5 | OEM base-model merging: define the manual process for identifying & linking rebadges | Both | Before AP3 |

---

*haystacked · Supplier Database Spec v0.3 · Confidential*
