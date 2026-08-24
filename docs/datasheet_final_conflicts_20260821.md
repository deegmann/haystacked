# Final DB reconciliation — fresh conflicts and triage verdicts

**Run date:** 2026-08-21  
**Scope:** all 276 products in `docs/sonnet_opus_merged_dataset.json`, re-derived field by field against the live DB after `python3 sync_airtable.py` (38 Companies / 266 Products / 266 Extensions).  
**Companion file:** `docs/datasheet_db_status_final.json` (per-product db_status + the machine-readable conflict list).  
**Nothing was written to Airtable, `data/haystacked.db` was not modified, and no file in `Datasheets/AGV_AMR/` was moved.**

## How `db_status` was re-derived

The pre-merge `db_status_sonnet` / `db_status_opus` fields were ignored as stale. For every merged product, each field was compared against the live DB value:

| Situation | Classified as |
|---|---|
| DB value is NULL | **fill** → product is `enrich` |
| Values equal | match |
| Multi-select, datasheet set ⊃ DB set | **extend** → `enrich`, not a conflict (additive) |
| Multi-select, datasheet set ⊂ DB set | **subset** → not a conflict (the sheet is merely silent) |
| Anything else with a non-null DB value | **conflict** |
| No plausible DB row under that company | `new` |

Twenty datasheet values in the merged file are literally `null`/`[]`; they were skipped rather than compared (they had previously surfaced as seven phantom conflicts, e.g. STILL `LTX 50 iGo.route_type` and Omron `LD-60.battery_type`).

## Headline numbers

- **178 fresh conflicts** (distinct product × field), materialising as **193 product-row × field pairs** once series-level reads are fanned onto their several DB rows.
- Triage verdicts (per distinct conflict): **144 RESOLVED**, **16 VARIANT-SPLIT-NEEDED**, **13 UNRESOLVED**, **5 DB-CLEANUP**.
- `db_status` across all 276: **130 new / 61 enrich / 85 conflict**.
- Separately logged, not conflicts: **28 multi-select extends**, **30 multi-select subsets**, **331 wrong-scope DB values**, **66 distinct DB tokens outside AP0 `allowed_values`**.

### Recurring causes, ranked

1. **Take-the-first-column on a multi-configuration VDI sheet** (Linde ×6, Toyota ×2, Geek+, ek robotics). A sheet listing 3–4 masts or payload classes side by side was read as if column 1 were the product. Every one of these went *against* the datasheet — the DB was right and the proposed value would have understated a K.O. field.
2. **Cross-model contamination inside one supplier** (Grenzebach ×4, Geek+ ×2, Balyo). A value that belongs to a sibling model sits in the wrong DB row — Grenzebach L1200S carries FF1200S's 2.0 m/s, OL1200S carries L1200S's 60 mm lift, and Geek+ F12ML/F20MT have their lift heights effectively swapped.
3. **Mast-reference convention (`lifting_height`)**, 15 conflicts. The DB stores a *reference* mast, the catalog states the *maximum* mast. Proven for VisionNav; the same 3000-vs-4500 pair reappears on Hikrobot F5-1600. Not an error on either side — it needs the open AP0 ruling (tracked as the Hub-vs-Einlagerungshöhe question in `docs/datasheet_project_open_items.md`).
4. **`Contour` vs `Natural Feature (SLAM)`**, 14 conflicts. Several vendors print both terms for the same capability *in the same document* (DS Automotion: "konturbasiert (SLAM)"; Grenzebach OL1200S: "SLAM navigation" on p.2 and "Contour navigation" on p.4). Treated as additive everywhere, never as a replacement.
5. **Series-level figures fanned onto per-variant rows** (DS Automotion AMY/AMADEUS, ek robotics COMPACT MOVE, SAFELOG M4). A single spec block that the manufacturer never split by variant was applied to every variant row.
6. **Imperial-conversion artefacts in DB values** (Linde P-MATIC 1778 mm = 70.0 in and 914 mm = 36.0 in; VisionNav VNQ50 19958 kg = 44,000 lb exactly). A suspiciously precise or suspiciously round DB number that resolves to a clean imperial figure did not come from the European datasheet.
7. **Payload read off the model name** (VisionNav VNP20 2000 vs 1900; Hikrobot F5-1600 1600 vs 1350). `max_payload` is `KO_IF_LT`, so an overstatement wins tenders the vehicle cannot serve.

---

## Conflicts by company

### VisionNav Robotics — 29 conflicts

- **`min_aisle_width`** (KO, mm) — *VisionNav VNE20* → DB row(s) `VisionNav VNE20`  
  DB **3760** vs datasheet **3800** (merge provenance: `sonnet_only`)  
  **Source:** 1657089341.pdf ('AUTOMATE YOUR INTRALOGISTICS', metric-first, -01/-07 suffixes) vs 1728979799.pdf / the newer 'FULL SPECTRUM LOGISTICS AUTOMATION' sheets  
  **Verdict: RESOLVED — Keep DB 3760 mm; the 3800 mm figure is from the other document generation**  
  Two VisionNav document generations publish different aisle figures for the same model code, and each forklift page prints TWO aisle rows ('Min. Stacking Aisle Width' vs 'Min. Turning Aisle Width'). All deltas here are under 2%. Keep the DB value, which matches the older sheets, and record the alternative.

- **`lifting_height`** (KO, mm) — *VisionNav VNE20(VL)-07* → DB row(s) `VisionNav VNE20`  
  DB **3000** vs datasheet **4500** (merge provenance: `opus_only`)  
  **Source:** 1728979799.pdf (Catalog-Spainish-2024V1.2) footnote *1 on the spec pages, e.g. VNSL14 'un mástil dúplex de 1600 mm (63 pulg.)' and the P/E-series footnote 'mástil dúplex de 118 pulgadas (3000 mm)'  
  **Verdict: RESOLVED — Reference-mast (DB) vs max-mast (catalog) artefact — do NOT overwrite; escalate the convention**  
  Established across eight products at once in the 2026-08-19 closeout: the DB stores the footnote *1 REFERENCE mast while the catalog headline states the MAXIMUM mast. Proof is exact — every P/E-series footnote reads 3000 mm and the DB holds exactly 3000 on all seven. Not a data error on either side; it needs an AP0 convention ruling (same family as the Hub-vs-Einlagerungshöhe question) before either value is changed.

- **`lifting_height`** (KO, mm) — *VisionNav VNE30(VL)-07* → DB row(s) `VisionNav VNE30`  
  DB **3000** vs datasheet **4500** (merge provenance: `opus_only`)  
  **Source:** 1728979799.pdf (Catalog-Spainish-2024V1.2) footnote *1 on the spec pages, e.g. VNSL14 'un mástil dúplex de 1600 mm (63 pulg.)' and the P/E-series footnote 'mástil dúplex de 118 pulgadas (3000 mm)'  
  **Verdict: RESOLVED — Reference-mast (DB) vs max-mast (catalog) artefact — do NOT overwrite; escalate the convention**  
  Established across eight products at once in the 2026-08-19 closeout: the DB stores the footnote *1 REFERENCE mast while the catalog headline states the MAXIMUM mast. Proof is exact — every P/E-series footnote reads 3000 mm and the DB holds exactly 3000 on all seven. Not a data error on either side; it needs an AP0 convention ruling (same family as the Hub-vs-Einlagerungshöhe question) before either value is changed.

- **`lifting_height`** (KO, mm) — *VisionNav VNE35(VL)-07* → DB row(s) `VisionNav VNE35`  
  DB **3000** vs datasheet **4500** (merge provenance: `opus_only`)  
  **Source:** 1728979799.pdf (Catalog-Spainish-2024V1.2) footnote *1 on the spec pages, e.g. VNSL14 'un mástil dúplex de 1600 mm (63 pulg.)' and the P/E-series footnote 'mástil dúplex de 118 pulgadas (3000 mm)'  
  **Verdict: RESOLVED — Reference-mast (DB) vs max-mast (catalog) artefact — do NOT overwrite; escalate the convention**  
  Established across eight products at once in the 2026-08-19 closeout: the DB stores the footnote *1 REFERENCE mast while the catalog headline states the MAXIMUM mast. Proof is exact — every P/E-series footnote reads 3000 mm and the DB holds exactly 3000 on all seven. Not a data error on either side; it needs an AP0 convention ruling (same family as the Hub-vs-Einlagerungshöhe question) before either value is changed.

- **`lifting_height`** (KO, mm) — *VisionNav VNE40* → DB row(s) `VisionNav VNE40`  
  DB **3000** vs datasheet **7000** (merge provenance: `sonnet_only`)  
  **Source:** 1728979799.pdf (Catalog-Spainish-2024V1.2) footnote *1 on the spec pages, e.g. VNSL14 'un mástil dúplex de 1600 mm (63 pulg.)' and the P/E-series footnote 'mástil dúplex de 118 pulgadas (3000 mm)'  
  **Verdict: RESOLVED — Reference-mast (DB) vs max-mast (catalog) artefact — do NOT overwrite; escalate the convention**  
  Established across eight products at once in the 2026-08-19 closeout: the DB stores the footnote *1 REFERENCE mast while the catalog headline states the MAXIMUM mast. Proof is exact — every P/E-series footnote reads 3000 mm and the DB holds exactly 3000 on all seven. Not a data error on either side; it needs an AP0 convention ruling (same family as the Hub-vs-Einlagerungshöhe question) before either value is changed.

- **`max_payload`** (KO, kg) — *VisionNav VNE40* → DB row(s) `VisionNav VNE40`  
  DB **4000.0** vs datasheet **2800** (merge provenance: `sonnet_only`)  
  **Source:** VisionNav VNE-series spec page (model code VNE40 implies 4.0 t)  
  **Verdict: UNRESOLVED — DB 4000 vs extracted 2800**  
  Two competing explanations: either the DB echoes the model number (the VNP20 error class) or 2800 is a load-centre-derated figure. Only one pass produced 2800 and it was not challenged. Needs a targeted re-read of the VNE40 rated-load row before either value moves.

- **`max_speed`** (SCORING, m/s) — *VisionNav VNE40* → DB row(s) `VisionNav VNE40`  
  DB **2.2** vs datasheet **2.0** (merge provenance: `opus`)  
  **Source:** 1657089341.pdf vs the newer generation spec pages  
  **Verdict: RESOLVED — Keep DB 2.2 m/s (the higher, per the AP0 top-speed rule)**  
  Same two-generation split as the aisle widths. The AP0 max_speed hint takes the top figure and the field is SCORING, so there is no K.O. risk in keeping the higher value.

- **`min_aisle_width`** (KO, mm) — *VisionNav VNE40* → DB row(s) `VisionNav VNE40`  
  DB **4430** vs datasheet **4400** (merge provenance: `sonnet_only`)  
  **Source:** 1657089341.pdf ('AUTOMATE YOUR INTRALOGISTICS', metric-first, -01/-07 suffixes) vs 1728979799.pdf / the newer 'FULL SPECTRUM LOGISTICS AUTOMATION' sheets  
  **Verdict: RESOLVED — Keep DB 4430 mm; the 4400 mm figure is from the other document generation**  
  Two VisionNav document generations publish different aisle figures for the same model code, and each forklift page prints TWO aisle rows ('Min. Stacking Aisle Width' vs 'Min. Turning Aisle Width'). All deltas here are under 2%. Keep the DB value, which matches the older sheets, and record the alternative.

- **`lifting_height`** (KO, mm) — *VisionNav VNE40(VL)-07* → DB row(s) `VisionNav VNE40`  
  DB **3000** vs datasheet **4500** (merge provenance: `opus_only`)  
  **Source:** 1728979799.pdf (Catalog-Spainish-2024V1.2) footnote *1 on the spec pages, e.g. VNSL14 'un mástil dúplex de 1600 mm (63 pulg.)' and the P/E-series footnote 'mástil dúplex de 118 pulgadas (3000 mm)'  
  **Verdict: RESOLVED — Reference-mast (DB) vs max-mast (catalog) artefact — do NOT overwrite; escalate the convention**  
  Established across eight products at once in the 2026-08-19 closeout: the DB stores the footnote *1 REFERENCE mast while the catalog headline states the MAXIMUM mast. Proof is exact — every P/E-series footnote reads 3000 mm and the DB holds exactly 3000 on all seven. Not a data error on either side; it needs an AP0 convention ruling (same family as the Hub-vs-Einlagerungshöhe question) before either value is changed.

- **`max_speed`** (SCORING, m/s) — *VisionNav VNK15* → DB row(s) `VisionNav VNK15`  
  DB **1.8** vs datasheet **1.5** (merge provenance: `sonnet_only`)  
  **Source:** 1657089341.pdf vs the newer generation spec pages  
  **Verdict: RESOLVED — Keep DB 1.8 m/s (the higher, per the AP0 top-speed rule)**  
  Same two-generation split as the aisle widths. The AP0 max_speed hint takes the top figure and the field is SCORING, so there is no K.O. risk in keeping the higher value.

- **`lifting_height`** (KO, mm) — *VisionNav VNP15* → DB row(s) `VisionNav VNP15`  
  DB **3000** vs datasheet **4500** (merge provenance: `sonnet_only`)  
  **Source:** 1728979799.pdf (Catalog-Spainish-2024V1.2) footnote *1 on the spec pages, e.g. VNSL14 'un mástil dúplex de 1600 mm (63 pulg.)' and the P/E-series footnote 'mástil dúplex de 118 pulgadas (3000 mm)'  
  **Verdict: RESOLVED — Reference-mast (DB) vs max-mast (catalog) artefact — do NOT overwrite; escalate the convention**  
  Established across eight products at once in the 2026-08-19 closeout: the DB stores the footnote *1 REFERENCE mast while the catalog headline states the MAXIMUM mast. Proof is exact — every P/E-series footnote reads 3000 mm and the DB holds exactly 3000 on all seven. Not a data error on either side; it needs an AP0 convention ruling (same family as the Hub-vs-Einlagerungshöhe question) before either value is changed.

- **`lifting_height`** (KO, mm) — *VisionNav VNP15(VL)-07* → DB row(s) `VisionNav VNP15`  
  DB **3000** vs datasheet **4500** (merge provenance: `opus_only`)  
  **Source:** 1728979799.pdf (Catalog-Spainish-2024V1.2) footnote *1 on the spec pages, e.g. VNSL14 'un mástil dúplex de 1600 mm (63 pulg.)' and the P/E-series footnote 'mástil dúplex de 118 pulgadas (3000 mm)'  
  **Verdict: RESOLVED — Reference-mast (DB) vs max-mast (catalog) artefact — do NOT overwrite; escalate the convention**  
  Established across eight products at once in the 2026-08-19 closeout: the DB stores the footnote *1 REFERENCE mast while the catalog headline states the MAXIMUM mast. Proof is exact — every P/E-series footnote reads 3000 mm and the DB holds exactly 3000 on all seven. Not a data error on either side; it needs an AP0 convention ruling (same family as the Hub-vs-Einlagerungshöhe question) before either value is changed.

- **`lifting_height`** (KO, mm) — *VisionNav VNP20(VL)-07* → DB row(s) `VisionNav VNP20`  
  DB **3000** vs datasheet **4500** (merge provenance: `opus_only`)  
  **Source:** 1728979799.pdf (Catalog-Spainish-2024V1.2) footnote *1 on the spec pages, e.g. VNSL14 'un mástil dúplex de 1600 mm (63 pulg.)' and the P/E-series footnote 'mástil dúplex de 118 pulgadas (3000 mm)'  
  **Verdict: RESOLVED — Reference-mast (DB) vs max-mast (catalog) artefact — do NOT overwrite; escalate the convention**  
  Established across eight products at once in the 2026-08-19 closeout: the DB stores the footnote *1 REFERENCE mast while the catalog headline states the MAXIMUM mast. Proof is exact — every P/E-series footnote reads 3000 mm and the DB holds exactly 3000 on all seven. Not a data error on either side; it needs an AP0 convention ruling (same family as the Hub-vs-Einlagerungshöhe question) before either value is changed.

- **`max_payload`** (KO, kg) — *VisionNav VNP20(VL)-07* → DB row(s) `VisionNav VNP20`  
  DB **2000.0** vs datasheet **1900** (merge provenance: `opus_only`)  
  **Source:** 1728979799.pdf VNP20 spec page, rated-load row  
  **Verdict: RESOLVED — 1900 kg — DB 2000 echoes the model number**  
  Confirmed error class: a stored payload that merely repeats the digits in the model name. max_payload is KO_IF_LT, so a 100 kg overstatement wins unfulfillable tenders. Same class as Hikrobot F5-1600.

- **`lifting_height`** (KO, mm) — *VisionNav VNP30(VL)-07* → DB row(s) `VisionNav VNP30`  
  DB **3000** vs datasheet **4500** (merge provenance: `opus_only`)  
  **Source:** 1728979799.pdf (Catalog-Spainish-2024V1.2) footnote *1 on the spec pages, e.g. VNSL14 'un mástil dúplex de 1600 mm (63 pulg.)' and the P/E-series footnote 'mástil dúplex de 118 pulgadas (3000 mm)'  
  **Verdict: RESOLVED — Reference-mast (DB) vs max-mast (catalog) artefact — do NOT overwrite; escalate the convention**  
  Established across eight products at once in the 2026-08-19 closeout: the DB stores the footnote *1 REFERENCE mast while the catalog headline states the MAXIMUM mast. Proof is exact — every P/E-series footnote reads 3000 mm and the DB holds exactly 3000 on all seven. Not a data error on either side; it needs an AP0 convention ruling (same family as the Hub-vs-Einlagerungshöhe question) before either value is changed.

- **`min_aisle_width`** (KO, mm) — *VisionNav VNP30(VL)-07* → DB row(s) `VisionNav VNP30`  
  DB **3992** vs datasheet **4050** (merge provenance: `opus_only`)  
  **Source:** 1657089341.pdf ('AUTOMATE YOUR INTRALOGISTICS', metric-first, -01/-07 suffixes) vs 1728979799.pdf / the newer 'FULL SPECTRUM LOGISTICS AUTOMATION' sheets  
  **Verdict: RESOLVED — Keep DB 3992 mm; the 4050 mm figure is from the other document generation**  
  Two VisionNav document generations publish different aisle figures for the same model code, and each forklift page prints TWO aisle rows ('Min. Stacking Aisle Width' vs 'Min. Turning Aisle Width'). All deltas here are under 2%. Keep the DB value, which matches the older sheets, and record the alternative.

- **`towing_capacity`** (KO, kg) — *VisionNav VNQ50* → DB row(s) `VisionNav VNQ50`  
  DB **19958.0** vs datasheet **5000** (merge provenance: `sonnet_only`)  
  **Source:** 1657089341.pdf p.17 VNQ40/VNQ60 tow-tractor page ('Rated Load Capacity (Q)' is a traction rating; 'Center Height of Traction Pin 324mm'); VNQ50 spec page  
  **Verdict: RESOLVED — 5000 kg — DB 19958 is an imperial artefact**  
  19958 kg is exactly 44,000 lb (19958 / 0.45359237 = 44000.0) — a converted US figure, not an independent measurement. It also breaches the plausible tugger band (2000-15000 kg). 5000 kg is consistent with the model code VNQ50 (5.0 t).

- **`towing_capacity`** (KO, kg) — *VisionNav VNQ50(VL)-01* → DB row(s) `VisionNav VNQ50`  
  DB **19958.0** vs datasheet **5000** (merge provenance: `opus_only`)  
  **Source:** 1657089341.pdf p.17 VNQ40/VNQ60 tow-tractor page ('Rated Load Capacity (Q)' is a traction rating; 'Center Height of Traction Pin 324mm'); VNQ50 spec page  
  **Verdict: RESOLVED — 5000 kg — DB 19958 is an imperial artefact**  
  19958 kg is exactly 44,000 lb (19958 / 0.45359237 = 44000.0) — a converted US figure, not an independent measurement. It also breaches the plausible tugger band (2000-15000 kg). 5000 kg is consistent with the model code VNQ50 (5.0 t).

- **`navigation_type`** (CONTEXT) — *VisionNav VNR16(V)-07 (Manual Handheld)* → DB row(s) `VisionNav VNR16`  
  DB **Natural Feature (SLAM)** vs datasheet **Vision** (merge provenance: `opus_only`)  
  **Source:** 1657089341.pdf / 1728979799.pdf spec pages, 'Positioning Method' row; the (V)/(VL)/(VM) model-code suffix decodes it: (V)='Vision-based Navigation', (VL)='Vision-based Navigation+3D Laser Navigation'  
  **Verdict: RESOLVED — Vision**  
  VisionNav's whole product identity is vision-based navigation and the suffix is printed in the model code itself. DB's Natural Feature (SLAM) is the generic fallback, not what the document says.

- **`navigation_type`** (CONTEXT) — *VisionNav VNR16(V)-07 (Manual Seated)* → DB row(s) `VisionNav VNR16`  
  DB **Natural Feature (SLAM)** vs datasheet **Vision** (merge provenance: `opus_only`)  
  **Source:** 1657089341.pdf / 1728979799.pdf spec pages, 'Positioning Method' row; the (V)/(VL)/(VM) model-code suffix decodes it: (V)='Vision-based Navigation', (VL)='Vision-based Navigation+3D Laser Navigation'  
  **Verdict: RESOLVED — Vision**  
  VisionNav's whole product identity is vision-based navigation and the suffix is printed in the model code itself. DB's Natural Feature (SLAM) is the generic fallback, not what the document says.

- **`lifting_height`** (KO, mm) — *VisionNav VNR16(VL)-01* → DB row(s) `VisionNav VNR16`  
  DB **5500** vs datasheet **11400** (merge provenance: `opus_only`)  
  **Source:** 1728979799.pdf (Catalog-Spainish-2024V1.2) footnote *1 on the spec pages, e.g. VNSL14 'un mástil dúplex de 1600 mm (63 pulg.)' and the P/E-series footnote 'mástil dúplex de 118 pulgadas (3000 mm)'  
  **Verdict: RESOLVED — Reference-mast (DB) vs max-mast (catalog) artefact — do NOT overwrite; escalate the convention**  
  Established across eight products at once in the 2026-08-19 closeout: the DB stores the footnote *1 REFERENCE mast while the catalog headline states the MAXIMUM mast. Proof is exact — every P/E-series footnote reads 3000 mm and the DB holds exactly 3000 on all seven. Not a data error on either side; it needs an AP0 convention ruling (same family as the Hub-vs-Einlagerungshöhe question) before either value is changed.

- **`navigation_type`** (CONTEXT) — *VisionNav VNR16(VL)-01* → DB row(s) `VisionNav VNR16`  
  DB **Natural Feature (SLAM)** vs datasheet **Vision** (merge provenance: `opus_only`)  
  **Source:** 1657089341.pdf / 1728979799.pdf spec pages, 'Positioning Method' row; the (V)/(VL)/(VM) model-code suffix decodes it: (V)='Vision-based Navigation', (VL)='Vision-based Navigation+3D Laser Navigation'  
  **Verdict: RESOLVED — Vision**  
  VisionNav's whole product identity is vision-based navigation and the suffix is printed in the model code itself. DB's Natural Feature (SLAM) is the generic fallback, not what the document says.

- **`lifting_height`** (KO, mm) — *VisionNav VNR20(VL)-01* → DB row(s) `VisionNav VNR20`  
  DB **7000** vs datasheet **11400** (merge provenance: `opus_only`)  
  **Source:** 1728979799.pdf (Catalog-Spainish-2024V1.2) footnote *1 on the spec pages, e.g. VNSL14 'un mástil dúplex de 1600 mm (63 pulg.)' and the P/E-series footnote 'mástil dúplex de 118 pulgadas (3000 mm)'  
  **Verdict: RESOLVED — Reference-mast (DB) vs max-mast (catalog) artefact — do NOT overwrite; escalate the convention**  
  Established across eight products at once in the 2026-08-19 closeout: the DB stores the footnote *1 REFERENCE mast while the catalog headline states the MAXIMUM mast. Proof is exact — every P/E-series footnote reads 3000 mm and the DB holds exactly 3000 on all seven. Not a data error on either side; it needs an AP0 convention ruling (same family as the Hub-vs-Einlagerungshöhe question) before either value is changed.

- **`navigation_type`** (CONTEXT) — *VisionNav VNR20(VL)-01* → DB row(s) `VisionNav VNR20`  
  DB **Natural Feature (SLAM)** vs datasheet **Vision** (merge provenance: `opus_only`)  
  **Source:** 1657089341.pdf / 1728979799.pdf spec pages, 'Positioning Method' row; the (V)/(VL)/(VM) model-code suffix decodes it: (V)='Vision-based Navigation', (VL)='Vision-based Navigation+3D Laser Navigation'  
  **Verdict: RESOLVED — Vision**  
  VisionNav's whole product identity is vision-based navigation and the suffix is printed in the model code itself. DB's Natural Feature (SLAM) is the generic fallback, not what the document says.

- **`lifting_height`** (KO, mm) — *VisionNav VNSL14* → DB row(s) `VisionNav VNSL14`  
  DB **1600** vs datasheet **3000** (merge provenance: `sonnet_only`)  
  **Source:** 1728979799.pdf (Catalog-Spainish-2024V1.2) footnote *1 on the spec pages, e.g. VNSL14 'un mástil dúplex de 1600 mm (63 pulg.)' and the P/E-series footnote 'mástil dúplex de 118 pulgadas (3000 mm)'  
  **Verdict: RESOLVED — Reference-mast (DB) vs max-mast (catalog) artefact — do NOT overwrite; escalate the convention**  
  Established across eight products at once in the 2026-08-19 closeout: the DB stores the footnote *1 REFERENCE mast while the catalog headline states the MAXIMUM mast. Proof is exact — every P/E-series footnote reads 3000 mm and the DB holds exactly 3000 on all seven. Not a data error on either side; it needs an AP0 convention ruling (same family as the Hub-vs-Einlagerungshöhe question) before either value is changed.

- **`max_speed`** (SCORING, m/s) — *VisionNav VNSL14* → DB row(s) `VisionNav VNSL14`  
  DB **1.3** vs datasheet **1.0** (merge provenance: `sonnet_only`)  
  **Source:** 1657089341.pdf vs the newer generation spec pages  
  **Verdict: RESOLVED — Keep DB 1.3 m/s (the higher, per the AP0 top-speed rule)**  
  Same two-generation split as the aisle widths. The AP0 max_speed hint takes the top figure and the field is SCORING, so there is no K.O. risk in keeping the higher value.

- **`min_aisle_width`** (KO, mm) — *VisionNav VNSL14* → DB row(s) `VisionNav VNSL14`  
  DB **2250** vs datasheet **2100** (merge provenance: `sonnet_only`)  
  **Source:** 1657089341.pdf ('AUTOMATE YOUR INTRALOGISTICS', metric-first, -01/-07 suffixes) vs 1728979799.pdf / the newer 'FULL SPECTRUM LOGISTICS AUTOMATION' sheets  
  **Verdict: RESOLVED — Keep DB 2250 mm; the 2100 mm figure is from the other document generation**  
  Two VisionNav document generations publish different aisle figures for the same model code, and each forklift page prints TWO aisle rows ('Min. Stacking Aisle Width' vs 'Min. Turning Aisle Width'). All deltas here are under 2%. Keep the DB value, which matches the older sheets, and record the alternative.

- **`lifting_height`** (KO, mm) — *VisionNav VNSL14(VL)-07* → DB row(s) `VisionNav VNSL14`  
  DB **1600** vs datasheet **3000** (merge provenance: `opus_only`)  
  **Source:** 1728979799.pdf (Catalog-Spainish-2024V1.2) footnote *1 on the spec pages, e.g. VNSL14 'un mástil dúplex de 1600 mm (63 pulg.)' and the P/E-series footnote 'mástil dúplex de 118 pulgadas (3000 mm)'  
  **Verdict: RESOLVED — Reference-mast (DB) vs max-mast (catalog) artefact — do NOT overwrite; escalate the convention**  
  Established across eight products at once in the 2026-08-19 closeout: the DB stores the footnote *1 REFERENCE mast while the catalog headline states the MAXIMUM mast. Proof is exact — every P/E-series footnote reads 3000 mm and the DB holds exactly 3000 on all seven. Not a data error on either side; it needs an AP0 convention ruling (same family as the Hub-vs-Einlagerungshöhe question) before either value is changed.

- **`min_aisle_width`** (KO, mm) — *VisionNav VNSL14(VL)-07* → DB row(s) `VisionNav VNSL14`  
  DB **2250** vs datasheet **2200** (merge provenance: `opus_only`)  
  **Source:** 1657089341.pdf ('AUTOMATE YOUR INTRALOGISTICS', metric-first, -01/-07 suffixes) vs 1728979799.pdf / the newer 'FULL SPECTRUM LOGISTICS AUTOMATION' sheets  
  **Verdict: RESOLVED — Keep DB 2250 mm; the 2200 mm figure is from the other document generation**  
  Two VisionNav document generations publish different aisle figures for the same model code, and each forklift page prints TWO aisle rows ('Min. Stacking Aisle Width' vs 'Min. Turning Aisle Width'). All deltas here are under 2%. Keep the DB value, which matches the older sheets, and record the alternative.


### Linde Material Handling — 28 conflicts

- **`max_payload`** (KO, kg) — *Linde C-MATIC* → DB row(s) `Linde C-MATIC`  
  DB **1500.0** vs datasheet **1000** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_c_matic_8925_dt_e_1025_view.pdf p.2 rows 1.2/1.5 'C-MATIC 10 | C-MATIC 15' / 'Q (t) 1,0 1,5'; p.1 'Tragfähigkeit 1,0 t – 1,5 t'; p.4 'Tragfähigkeit (kg) 1000 1500'  
  **Verdict: VARIANT-SPLIT-NEEDED — 1500 kg for the DB row (= C-MATIC 15); a separate C-MATIC 10 row should hold 1000 kg**  
  The sheet documents two models sharing one chassis (identical 1180/832 mm footprint). The merged dataset holds BOTH a 'Linde C-MATIC' and a 'Linde C-MATIC 10' entry that resolve to the same single DB row. Split the DB row rather than choosing a number.

- **`max_speed`** (SCORING, m/s) — *Linde C-MATIC* → DB row(s) `Linde C-MATIC`  
  DB **1.2** vs datasheet **1.19** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_c_matic_8925_dt_e_1025_view.pdf p.2 row 5.1 'Fahrgeschwindigkeit mit/ohne Last km/h 4,3/5,4'  
  **Verdict: RESOLVED — 1.5 m/s (both DB 1.2 and the extracted 1.19 are wrong)**  
  4,3 km/h = 1.19 m/s is the LADEN figure; 5,4 km/h = 1.5 m/s is the unladen/top figure the AP0 hint asks for. Neither pass took it.

- **`max_payload`** (KO, kg) — *Linde C-MATIC 10* → DB row(s) `Linde C-MATIC`  
  DB **1500.0** vs datasheet **1000.0** (merge provenance: `opus_only`)  
  **Source:** DE_tb_c_matic_8925_dt_e_1025_view.pdf p.2 row 1.2/1.5; p.4 'Tragfähigkeit (kg) 1000 1500'  
  **Verdict: VARIANT-SPLIT-NEEDED — 1000 kg belongs to a new 'C-MATIC 10' product row, not to the existing 'Linde C-MATIC' row**  
  Same finding as above, seen from the other side. Importing 1000 onto the existing row would silently downgrade a K.O. field by 500 kg.

- **`max_speed`** (SCORING, m/s) — *Linde C-MATIC HP* → DB row(s) `Linde C-MATIC HP`  
  DB **2.22** vs datasheet **2.2** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_c_matic_hp_10_8928_dt_a_0523_view.pdf p.2 row 5.1 'Fahrgeschwindigkeit mit / ohne Last (m / s) 2.2'; p.1 'maximale Geschwindigkeit von 8 km/h'  
  **Verdict: RESOLVED — 2.2 m/s (immaterial; datasheet row wins)**  
  The VDI row prints 2.2 m/s directly; DB 2.22 is the km/h->m/s conversion of the p.1 marketing figure. <1% apart, SCORING field — prefer the printed row for cleanliness.

- **`lifting_height`** (KO, mm) — *Linde K-MATIC* → DB row(s) `Linde K-MATIC`  
  DB **14000** vs datasheet **7200** (merge provenance: `sonnet_only`)  
  **Source:** EN_ds_k_matic_5231_en_a_0224_view.pdf p.2 row 4.4 'Lift h3 (mm) 7200 11550 14350'; p.1 '… up to 14 m lifting height'  
  **Verdict: RESOLVED — 14350 mm (DB 14000 materially correct)**  
  7200 is the first of three mast columns — the classic take-the-first-column error. Maximum is 14350.

- **`min_aisle_width`** (KO, mm) — *Linde K-MATIC* → DB row(s) `Linde K-MATIC`  
  DB **1800** vs datasheet **1850** (merge provenance: `sonnet_only`)  
  **Source:** EN_ds_k_matic_5231_en_a_0224_view.pdf p.2 row 4.34 'Ast (mm) 1850/-- 1850/1900 2000/2000'  
  **Verdict: RESOLVED — 1850 mm (datasheet correct; DB 1800 unsupported)**  
  Smallest printed Ast is 1850. 1800 appears nowhere. Material for VNA screening (K-MATIC is the VNA turret truck).

- **`navigation_type`** (CONTEXT) — *Linde K-MATIC* → DB row(s) `Linde K-MATIC`  
  DB **Natural Feature (SLAM)** vs datasheet **Contour** (merge provenance: `sonnet_only`)  
  **Source:** EN_ds_k_matic_5231_en_a_0224_view.pdf p.1 '→ Control via intelligent contour navigation'; p.5 'Contour navigation'  
  **Verdict: RESOLVED — Contour**  
  Printed twice, in English, unambiguously. Store AP0 'Contour'.

- **`lifting_height`** (KO, mm) — *Linde L-MATIC* → DB row(s) `Linde L-MATIC`  
  DB **2900** vs datasheet **1924** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_l_matic_br133_de_a_0516.pdf p.2 row 4.4 'Hub h3 (mm) 1924'; p.3 Serienausstattung 'Standard Hubmast 1924mm'  
  **Verdict: UNRESOLVED — 1924 mm per this sheet; DB 2900 unsupported**  
  Stated twice independently in the document (VDI row + equipment list) = strong. DB 2900 appears nowhere. Same generation caveat as max_payload.

- **`max_payload`** (KO, kg) — *Linde L-MATIC* → DB row(s) `Linde L-MATIC`  
  DB **1600.0** vs datasheet **1200** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_l_matic_br133_de_a_0516.pdf p.2 row 1.5 'Tragfähigkeit/Last Q (t) 1,2 / 2,0 1)'  
  **Verdict: UNRESOLVED — DB 1600 is not supported by the only L-MATIC sheet on file**  
  The 2016 Balyo-based L-MATIC sheet gives 1,2 t / 2,0 t (footnote-qualified). Neither DB 1600 nor the extracted 1200 is the whole story, and the DB row may describe a newer L-MATIC generation with no datasheet in the corpus. Needs vendor/manual confirmation.

- **`max_speed`** (SCORING, m/s) — *Linde L-MATIC* → DB row(s) `Linde L-MATIC`  
  DB **2.0** vs datasheet **1.67** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_l_matic_br133_de_a_0516.pdf p.2 row 5.1 'Fahrgeschwindigkeit mit/ohne Last (km/h) 6/6 (max. 7,2/2,9)'  
  **Verdict: RESOLVED — 2.0 m/s (DB already correct)**  
  Top figure 7,2 km/h = 2.0 m/s. The extracted 1.67 is 6 km/h (the rated, not top, figure). AP0 max_speed hint says capture the top/rated figure.

- **`navigation_type`** (CONTEXT) — *Linde L-MATIC* → DB row(s) `Linde L-MATIC`  
  DB **Natural Feature (SLAM)** vs datasheet **Contour** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_l_matic_br133_de_a_0516.pdf p.1 'Geo-Navigation'; p.4 '3 Navigationslaser … Strukturen (Wände, Säulen, Regale,…)'  
  **Verdict: RESOLVED — Natural Feature (SLAM) — DB already correct**  
  The word 'Kontur' never appears; the vendor's term is 'Geo-Navigation' localising off building structures. The Contour rule only fires when the vendor actually prints a contour claim. Reject the proposed Contour.

- **`lifting_height`** (KO, mm) — *Linde L-MATIC AC* → DB row(s) `Linde L-MATIC AC`  
  DB **4200** vs datasheet **1844** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_l_matic_ac_1170_dt_c_1024_view.pdf p.2 row 4.4 'Hub h3 (mm) 1924 1844 4224 4144'; p.1 '→ Hubhöhe bis zu 4,2 m'; mast table p.4  
  **Verdict: RESOLVED — 4224 mm (DB 4200 is the rounded marketing figure)**  
  1844 is the 1.6 t short-mast column. Max stroke across the four printed masts is 4224 mm. DB 4200 = the p.1 marketing rounding, materially correct.

- **`max_payload`** (KO, kg) — *Linde L-MATIC AC* → DB row(s) `Linde L-MATIC AC`  
  DB **1600.0** vs datasheet **1200** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_l_matic_ac_1170_dt_c_1024_view.pdf p.2 row 1.5 'Nenntragfähigkeit/Last Q (t) 1.2 1.6 1.2 1.6'; p.1 'Tragfähigkeit 1,2 t – 1,6 t'  
  **Verdict: RESOLVED — 1600 kg (DB already correct)**  
  Sheet covers 4 configurations; the datasheet value 1200 is only the first column. AP0 max_payload hint says report the heaviest stated number. DB is right; do not import 1200.

- **`max_speed`** (SCORING, m/s) — *Linde L-MATIC AC* → DB row(s) `Linde L-MATIC AC`  
  DB **2.0** vs datasheet **1.7** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_l_matic_ac_1170_dt_c_1024_view.pdf p.2 row 5.1 'Max. Fahrgeschwindigkeit mit/ohne Last vorwärts m/s 1.7/1.7'  
  **Verdict: RESOLVED — 1.7 m/s (datasheet correct; DB 2.0 unsupported)**  
  Row 5.1 prints 1.7 m/s laden AND unladen on all four columns. No 2.0 figure appears anywhere in the document.

- **`min_aisle_width`** (KO, mm) — *Linde L-MATIC AC* → DB row(s) `Linde L-MATIC AC`  
  DB **3400** vs datasheet **3340** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_l_matic_ac_1170_dt_c_1024_view.pdf p.2 rows 4.34.1/4.34.2 Ast 3370/3730/3430/3800 and 3340/3710/3340/3710  
  **Verdict: RESOLVED — 3340 mm (datasheet correct; DB 3400 unsupported)**  
  Per the reconciliation rule 'min_aisle_width = narrowest aisle the vehicle can work in', take the smallest Ast across pallet-size/orientation rows = 3340 (850x1250 längs).

- **`navigation_type`** (CONTEXT) — *Linde L-MATIC AC* → DB row(s) `Linde L-MATIC AC`  
  DB **Natural Feature (SLAM)** vs datasheet **Contour** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_l_matic_ac_1170_dt_c_1024_view.pdf p.1 '→ Intelligente Konturnavigation'; p.5 'Konturnavigation' (Serienausstattung); p.6 'Konturnavigation ermöglicht…'  
  **Verdict: RESOLVED — Contour**  
  Vendor prints 'Konturnavigation' three times and never 'SLAM' / 'natürliche Merkmale'. Per the settled rule, a printed contour claim stores AP0 'Contour'.

- **`lifting_height`** (KO, mm) — *Linde L-MATIC AC k* → DB row(s) `Linde L-MATIC AC k`  
  DB **3800** vs datasheet **2844** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_l_matic_ac_k_1171_dt_b_1225_view.pdf p.2 row 4.4 'Hub h3 (mm) 2844 2844'; p.4 Masttabelle 'h3: 2844 / 3244 / 3744 / 4144'; p.1 'Einlagerungshöhe bis 3,8 Meter'  
  **Verdict: UNRESOLVED — 2844 / 3800 / 4144 — depends on the unruled Hub-vs-Einlagerungshöhe convention**  
  Three defensible readings coexist in one document: VDI standard mast 2844, marketed Einlagerungshöhe 3800 (= DB), mast-table maximum 4144. Needs the open AP0 ruling on which one lifting_height means before any value is changed.

- **`max_payload`** (KO, kg) — *Linde L-MATIC AC k* → DB row(s) `Linde L-MATIC AC k`  
  DB **1400.0** vs datasheet **1000** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_l_matic_ac_k_1171_dt_b_1225_view.pdf p.2 row 1.5 '1,0 1,4'; p.1 'Tragfähigkeit bis 1.400 kg'  
  **Verdict: RESOLVED — 1400 kg (DB already correct)**  
  1000 is the L-MATIC 12 AC k column. Heaviest stated = 1400. DB right.

- **`lifting_height`** (KO, mm) — *Linde L-MATIC HD k* → DB row(s) `Linde L-MATIC HD k`  
  DB **3000** vs datasheet **2844** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_l_matic_hd_hdk_1173_01_dt_d_0524_view.pdf p.2 row 4.4 'Hub h3 (mm) 2344 2844'; p.1 '→ Hubkraft bis zu 1,6 t und Hubhöhe bis zu 3,5 m'; p.4 Masttabelle is a non-extractable image  
  **Verdict: UNRESOLVED — 2844 (VDI) vs ~3500 (marketing) vs DB 3000**  
  Same Hub-vs-Einlagerungshöhe family as L-MATIC AC k, and the mast table on p.4 carries no extractable text, so the mast maximum could not be confirmed. Needs a visual read of p.4 plus the AP0 ruling.

- **`max_speed`** (SCORING, m/s) — *Linde L-MATIC core* → DB row(s) `Linde L-MATIC core`  
  DB **2.0** vs datasheet **1.67** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_l_matic_core_1195_01_dt_b_0425_view.pdf p.2 row 5.1 'km/h 4/41) 6,0/7,22)'  
  **Verdict: RESOLVED — 2.0 m/s (DB already correct)**  
  Automatic-mode top speed 7,2 km/h = 2.0 m/s. 1.67 = the 6,0 km/h laden figure.

- **`navigation_type`** (CONTEXT) — *Linde P-MATIC* → DB row(s) `Linde P-MATIC`  
  DB **Natural Feature (SLAM)** vs datasheet **Contour** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_p_matic_br1190_dt_a_0416.pdf p.1 'Geo-Navigation'; p.4 '3 Navigationslaser … Strukturen (Wände, Säulen, Regale,…)'  
  **Verdict: RESOLVED — Natural Feature (SLAM) — DB already correct**  
  Identical reasoning to L-MATIC: 'Geo-Navigation', never 'Kontur'. Reject the proposed Contour.

- **`vehicle_length`** (CONTEXT, mm) — *Linde P-MATIC* → DB row(s) `Linde P-MATIC`  
  DB **1778** vs datasheet **1750** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_p_matic_br1190_dt_a_0416.pdf p.2 row 4.19 'Gesamtlänge l1 (mm) 1750'  
  **Verdict: RESOLVED — 1750 mm (datasheet correct)**  
  DB 1778 mm is exactly 70.0 inches — an imperial-market rounding, not an independent measurement (same forensic pattern as Staeubli PF3's 2721 kg = 6000 lb).

- **`vehicle_width`** (CONTEXT, mm) — *Linde P-MATIC* → DB row(s) `Linde P-MATIC`  
  DB **914** vs datasheet **798** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_p_matic_br1190_dt_a_0416.pdf p.2 row 4.21 'Gesamtbreite b1/b2 (mm) 798 / 790'  
  **Verdict: RESOLVED — 798 mm (datasheet correct)**  
  DB 914 mm is exactly 36.0 inches. Same imperial artefact as the length; both DB dimensions came from a US spec sheet, not this VDI sheet.

- **`lifting_height`** (KO, mm) — *Linde R-MATIC* → DB row(s) `Linde R-MATIC`  
  DB **11000** vs datasheet **6844** (merge provenance: `sonnet_only`)  
  **Source:** EN_ds_r_matic_1120_en_b_0623_view.pdf p.2 row 4.4 'Lift h3 (mm) 6844 8444 9644 11344'  
  **Verdict: RESOLVED — 11344 mm (DB 11000 materially correct)**  
  6844 is the first of four mast columns. Maximum is 11344; DB 11000 is the marketing rounding.

- **`min_aisle_width`** (KO, mm) — *Linde R-MATIC* → DB row(s) `Linde R-MATIC`  
  DB **2900** vs datasheet **2990** (merge provenance: `sonnet_only`)  
  **Source:** EN_ds_r_matic_1120_en_b_0623_view.pdf p.2 row 4.34.2 'Ast (mm) 2990 2990 2990 3160'  
  **Verdict: RESOLVED — 2990 mm (datasheet correct; DB 2900 unsupported)**  
  Smallest printed automatic-mode Ast is 2990.

- **`vna_capable`** (COND_KO) — *Linde R-MATIC* → DB row(s) `Linde R-MATIC`  
  DB **False** vs datasheet **True** (merge provenance: `sonnet_only`)  
  **Source:** EN_ds_r_matic_1120_en_b_0623_view.pdf p.1 'Automated reach truck'; p.2 row 4.34.2 Ast 2990 mm  
  **Verdict: RESOLVED — False — DB already correct**  
  A reach truck needing a ~3 m aisle is not a VNA machine (VNA band is 1600-2000 mm). Setting vna_capable=True would wrongly admit it to VNA tenders via KO_BOOL_EXCLUSIVE. Reject the extraction.

- **`lifting_height`** (KO, mm) — *Linde R-MATIC k (R-MATIC 17 k)* → DB row(s) `Linde R-MATIC k (R-MATIC 17 k)`  
  DB **10274** vs datasheet **10000** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_r_matic_k_5190_dt_a_0425_view.pdf p.1 '→ … in Höhen bis zu 10 m'; p.5 row 4.4 'Hub h3 (mm) 6774 6874 6704'  
  **Verdict: RESOLVED — DB 10274 stands**  
  10000 is the p.1 marketing rounding; the standard-mast VDI row is 6874. DB 10274 is a precise mast-table figure consistent with 'bis zu 10 m'. Do not replace a precise value with a rounded one.

- **`max_payload`** (KO, kg) — *Linde R-MATIC k (R-MATIC 17 k)* → DB row(s) `Linde R-MATIC k (R-MATIC 17 k)`  
  DB **1550.0** vs datasheet **1100** (merge provenance: `sonnet_only`)  
  **Source:** DE_tb_r_matic_k_5190_dt_a_0425_view.pdf p.5 row 1.5 'Nenntragfähigkeit/Last Q (t) 1,07 1,55 2,33'  
  **Verdict: RESOLVED — 1550 kg (DB already correct)**  
  The DB row is explicitly the 17 k, i.e. the 1,55 t column. 1100 is the 12 k column. Also flags a variant gap: R-MATIC 12 k and 25 k are undocumented in the DB.


### DS Automotion GmbH — 20 conflicts

- **`lifting_height`** (KO, mm) — *AMADEUS Classic / Wide / Low / Counter (series-level values)* → DB row(s) `AMADEUS Classic + AMADEUS Wide + AMADEUS Low`  
  DB **2880** vs datasheet **2800** (merge provenance: `opus_only`)  
  **Source:** AMADEUS-OnePager-2025-DE.pdf p.2 'Hubhöhe / Monomast: Gabeloberkante 85 mm – 1.200 mm; Duplex-Mast: 85 mm – 2.800 mm'; p.2 badge 'Hubhöhe bis max. 2.800 mm'  
  **Verdict: RESOLVED — 2800 mm for Classic/Wide — already settled by the Tech Lead; do NOT fan out to Low**  
  Prior Tech Lead decision fixes 2800 for the series. But AMADEUS Low is explicitly marked 'Technische Details abweichend' on the same page and the DB holds 100 mm for it — a low-lifter. Fanning the series value onto Low would be a 28x error on a K.O. field.

- **`load_type`** (KO) — *AMADEUS Classic / Wide / Low / Counter (series-level values)* → DB row(s) `AMADEUS Counter`  
  DB **Pallet EUR, Pallet ISO, Plastic Bin** vs datasheet **Custom Carrier, Pallet EUR, Pallet ISO** (merge provenance: `opus_only`)  
  **Source:** AMADEUS-OnePager-2025-DE.pdf p.1 'Er kann nicht nur Europaletten und Industriepaletten aufnehmen, sondern auch Boxen, Container oder auf Sie abgestimmte Sondergüter.'  
  **Verdict: RESOLVED — Union — additive only**  
  Adds Custom Carrier to the DB's Pallet EUR/ISO. The DB's existing values are all supported; nothing is contradicted.

- **`max_payload`** (KO, kg) — *AMADEUS Classic / Wide / Low / Counter (series-level values)* → DB row(s) `AMADEUS Counter`  
  DB **1200.0** vs datasheet **2000** (merge provenance: `opus_only`)  
  **Source:** AMADEUS-OnePager-2025-DE.pdf p.1 'Nutzlast bis max. 2.000 kg'; p.2 'Nutzlast: max. 1,5 t / 2,0 t'; p.2 'AMADEUS counter — Technische Details abweichend'  
  **Verdict: VARIANT-SPLIT-NEEDED — Do not apply 2000 kg to AMADEUS Counter**  
  The sheet gives a series-level 1,5 t / 2,0 t range and explicitly says the counter variant deviates. The 2000 cannot be attributed to Counter; DB's 1200 is not contradicted by this document.

- **`navigation_type`** (CONTEXT) — *AMADEUS Classic / Wide / Low / Counter (series-level values)* → DB row(s) `AMADEUS Low`  
  DB **Contour, Laser Reflector** vs datasheet **Laser Reflector, Natural Feature (SLAM)** (merge provenance: `opus_only`)  
  **Source:** AMADEUS-OnePager-2025-DE.pdf p.2 'Die Fahrzeuge beherrschen die Lasernavigation ebenso wie die konturbasierte Navigation (SLAM)'; spec block 'Navigation: Laser, SLAM. AMADEUS counter: zzgl. Magnet'  
  **Verdict: RESOLVED — Union [Contour, Laser Reflector, Natural Feature (SLAM)]**  
  Same 'konturbasierte Navigation (SLAM)' equation as OSCAR. Additive; remove nothing.

- **`stacking_capability`** (COND_KO) — *AMADEUS Classic / Wide / Low / Counter (series-level values)* → DB row(s) `AMADEUS Low`  
  DB **False** vs datasheet **True** (merge provenance: `opus_only`)  
  **Source:** AMADEUS-OnePager-2025-DE.pdf p.2 'AMADEUS low — Technische Details abweichend'  
  **Verdict: VARIANT-SPLIT-NEEDED — Do not apply the series value to AMADEUS Low**  
  The series read cannot speak for the 'low' variant. DB's stacking_capability=False on a 100 mm-lift low-lifter is consistent with its own geometry; the series True belongs to Classic/Wide.

- **`fleet_management_system`** (CONTEXT) — *AMADEUS Grip* → DB row(s) `AMADEUS Grip`  
  DB **VDA 5050 compatible|Open API** vs datasheet **Proprietary** (merge provenance: `opus`)  
  **Source:** AMADEUS_Grip_Onepager_2022_DE.pdf p.2 'Unser inhouse produzierter Flottenmanager NAVIOS bietet Leitsteuerung, Lagerverwaltung und Prozessabwicklung in einem einzigen Produkt.'  
  **Verdict: RESOLVED — Proprietary — but low materiality (CONTEXT field)**  
  The document supports a proprietary in-house controller. It does not deny VDA 5050/Open API, but neither does it evidence them. Note DB currently stores two piped values in a single-select field.

- **`lifting_height`** (KO, mm) — *AMADEUS Grip* → DB row(s) `AMADEUS Grip`  
  DB **2880** vs datasheet **600** (merge provenance: `opus`)  
  **Source:** AMADEUS_Grip_Onepager_2022_DE.pdf p.2 'Hubhöhe: 85-600 mm'  
  **Verdict: RESOLVED — 600 mm — DB 2880 is wrong**  
  AMADEUS Grip is a clamp vehicle for insulation blocks, not a high-lift stacker. DB 2880 looks copied from the AMADEUS series' 2880/2800 mm duplex figure.

- **`max_payload`** (KO, kg) — *AMADEUS Grip* → DB row(s) `AMADEUS Grip`  
  DB **2000.0** vs datasheet **800** (merge provenance: `opus`)  
  **Source:** AMADEUS_Grip_Onepager_2022_DE.pdf p.2 'Technische Daten | Nutzlast: bis 800 kg'; same page prose 'Mit einer Nutzlast von max. 800 kg'  
  **Verdict: RESOLVED — 800 kg — DB 2000 is wrong**  
  Stated twice independently on the same page (spec block + prose). DB overstates a K.O. field by 2.5x, which would win tenders the vehicle cannot serve.

- **`navigation_type`** (CONTEXT) — *AMADEUS Grip* → DB row(s) `AMADEUS Grip`  
  DB **Laser Reflector, Natural Feature (SLAM)** vs datasheet **Magnetic Tape** (merge provenance: `opus`)  
  **Source:** AMADEUS_Grip_Onepager_2022_DE.pdf p.2 'Navigation: Magnet'; prose 'Der AMADEUS navigiert mit Hilfe von Referenzmagneten durch die Produktions- und Lagerhallen'  
  **Verdict: RESOLVED — Magnetic Tape (magnet-point) — DB [Laser Reflector, SLAM] unsupported**  
  Stated twice. AP0 has no 'Magnetic Spot' value, so Magnetic Tape is the nearest allowed value — worth noting as an AP0 gap (magnet-POINT vs magnet-TAPE navigation are different technologies).

- **`battery_type`** (CONTEXT) — *AMY Deck / AMY Lift* → DB row(s) `AMY Deck + AMY Lift`  
  DB **LiFePO4** vs datasheet **Li-Ion** (merge provenance: `opus_only`)  
  **Source:** Amy-FourPager-2025-DE.pdf p.3 'Batterie: Lithium'  
  **Verdict: RESOLVED — Keep DB [LiFePO4]**  
  Same granularity argument as ARNY/OSCAR.

- **`min_ground_clearance`** (KO, mm) — *AMY Deck / AMY Lift* → DB row(s) `AMY Lift`  
  DB **580** vs datasheet **349** (merge provenance: `opus_only`)  
  **Source:** Amy-FourPager-2025-DE.pdf p.3 'Abmessungen in mm: 638 (l) x 428 (b) x 349 (h)'  
  **Verdict: VARIANT-SPLIT-NEEDED — Do not overwrite AMY Lift's 580 mm with 349 mm**  
  min_ground_clearance holds ROBOT HEIGHT (AP0 hint). 349 mm is the bare AMY body height; 580 mm is plausibly AMY Lift with its lift top module fitted. This is a K.O. field for undercarriage workflows — do not lower it on a series-level read.

- **`vehicle_length`** (CONTEXT, mm) — *AMY Deck / AMY Lift* → DB row(s) `AMY Deck + AMY Lift`  
  DB **690** vs datasheet **638** (merge provenance: `opus_only`)  
  **Source:** Amy-FourPager-2025-DE.pdf p.3 'Abmessungen in mm: 638 (l) x 428 (b) x 349 (h)'  
  **Verdict: VARIANT-SPLIT-NEEDED — Do not fan 638 mm onto both AMY rows**  
  The FourPager prints ONE dimension block for the AMY family and never splits Deck vs Lift. The DB holds distinct per-variant footprints (690x453 / 640x520) that are more specific and not contradicted by a series-level figure.

- **`vehicle_width`** (CONTEXT, mm) — *AMY Deck / AMY Lift* → DB row(s) `AMY Deck + AMY Lift`  
  DB **453** vs datasheet **428** (merge provenance: `opus_only`)  
  **Source:** Amy-FourPager-2025-DE.pdf p.3 'Abmessungen in mm: 638 (l) x 428 (b) x 349 (h)'  
  **Verdict: VARIANT-SPLIT-NEEDED — Do not fan 428 mm onto both AMY rows**  
  Same series-level-figure problem as the length.

- **`battery_type`** (CONTEXT) — *ARNY Mono / ARNY Duplex / ARNY Triplex / ARNY HD Triplex* → DB row(s) `ARNY Mono + ARNY Duplex + ARNY Triplex + ARNY HD Triplex`  
  DB **Lead-Acid, LiFePO4** vs datasheet **Lead-Acid, Li-Ion** (merge provenance: `opus`)  
  **Source:** Arny-OnePager-2026-DE.pdf p.2 table row 'Batterie: Blei-Säure, Reinblei, Lithium'  
  **Verdict: RESOLVED — Keep DB [Lead-Acid, LiFePO4]; do not import [Lead-Acid, Li-Ion]**  
  The sheet says only 'Lithium' and cannot discriminate Li-Ion from LiFePO4. Replacing the DB's more specific LiFePO4 with a coarser Li-Ion loses information for no evidential gain. Affects all four ARNY rows identically.

- **`safety_coverage`** (SCORING) — *ARNY Mono / ARNY Duplex / ARNY Triplex / ARNY HD Triplex* → DB row(s) `ARNY Mono + ARNY Duplex + ARNY Triplex + ARNY HD Triplex`  
  DB **Full 3D (360° + 3D sensors)** vs datasheet **Single plane (2D)** (merge provenance: `opus`)  
  **Source:** Arny-OnePager-2026-DE.pdf p.2 'Ein umfassendes Sicherheitskonzept mit drei integrierten Sicherheitsscannern … 360° Personenschutz. Ein 3D-Objektschutz ist optional erhältlich.'; table row 'Personensicherheit: 3 Sicherheitslaserscanner für 360° Rundumschutz'  
  **Verdict: RESOLVED — Single plane (2D) — the datasheet is right for the standard build**  
  Three 2D laser scanners arranged for 360° coverage is still single-plane sensing; 3D is explicitly OPTIONAL. DB's 'Full 3D (360° + 3D sensors)' overstates the standard configuration — and is not even a valid AP0 token (see DB-cleanup). Affects all four ARNY rows.

- **`battery_type`** (CONTEXT) — *OSCAR spin 180 / OSCAR spin 360 / OSCAR omni* → DB row(s) `OSCAR Omni`  
  DB **LiFePO4** vs datasheet **Li-Ion** (merge provenance: `opus`)  
  **Source:** OSCAR-OnePager-2025-DE.pdf p.2 spec block 'Batterie: Lithium'  
  **Verdict: RESOLVED — Keep DB [LiFePO4]**  
  Same granularity argument as ARNY: 'Lithium' cannot displace a stored LiFePO4.

- **`navigation_type`** (CONTEXT) — *OSCAR spin 180 / OSCAR spin 360 / OSCAR omni* → DB row(s) `OSCAR Spin 180 + OSCAR Spin 360 + OSCAR Omni`  
  DB **Contour, Magnetic Tape** vs datasheet **Magnetic Tape, Natural Feature (SLAM)** (merge provenance: `opus`)  
  **Source:** OSCAR-OnePager-2025-DE.pdf p.2 'Die OSCAR-Baureihe navigiert konturbasiert (SLAM) per KBL-Technologie und beherrscht zusätzlich die Magnetpunktnavigation'; spec block 'Navigation: SLAM, Magnetpunktfolge'  
  **Verdict: RESOLVED — Union: [Contour, Magnetic Tape, Natural Feature (SLAM)]**  
  The document literally equates the two terms ('konturbasiert (SLAM)'), so DB=Contour and datasheet=SLAM are the same physical capability under two AP0 labels. Not a data conflict — it is the unresolved Contour/SLAM modelling overlap. Safest import is the union; no value should be removed.

- **`vehicle_length`** (CONTEXT, mm) — *OSCAR spin 180 / OSCAR spin 360 / OSCAR omni* → DB row(s) `OSCAR Spin 360`  
  DB **1670** vs datasheet **1620** (merge provenance: `opus`)  
  **Source:** OSCAR-OnePager-2025-DE.pdf p.2 variant table 'OSCAR spin 360 — 1.620 x 712 x 295 mm'  
  **Verdict: RESOLVED — OSCAR Spin 360 = 1620 mm (datasheet correct)**  
  Explicit per-variant LxWxH row. DB 1670 appears nowhere in the document.

- **`vehicle_width`** (CONTEXT, mm) — *OSCAR spin 180 / OSCAR spin 360 / OSCAR omni* → DB row(s) `OSCAR Spin 360`  
  DB **700** vs datasheet **712** (merge provenance: `opus`)  
  **Source:** OSCAR-OnePager-2025-DE.pdf p.2 variant table 'OSCAR spin 360 — 1.620 x 712 x 295 mm'  
  **Verdict: RESOLVED — OSCAR Spin 360 = 712 mm (datasheet correct)**  
  Same row. DB 700 is a rounding; 712 is printed. Cross-check: spin 180 = 1620x560x260, omni = 1520x720x320 — the table is internally consistent and per-variant.

- **`load_type`** (KO) — *SALLY / SALLY Rollgang* → DB row(s) `SALLY + SALLY Rollgang`  
  DB **Custom Carrier, Tote** vs datasheet **Custom Carrier, Plastic Bin** (merge provenance: `opus`)  
  **Source:** SALLY-OnePager-2024-DE.pdf p.1 'Zulieferer für Arbeitsmaterial in KLT-Boxen'; p.2 'Kundenspezifische Lastaufnahmemittel'  
  **Verdict: RESOLVED — Union [Custom Carrier, Tote, Plastic Bin]**  
  'KLT-Box' maps to Plastic Bin; the DB's Tote is a defensible synonym for the same carrier and must not be removed (load_type is a K.O. field, so dropping a value can disqualify). Additive, not contradictory. Applies to both SALLY and SALLY Rollgang.


### Geek+ (Geekplus Technology Co.) — 16 conflicts

- **`lifting_height`** (KO, mm) — *Geek+ F12ML* → DB row(s) `Geek+ F12ML`  
  DB **120** vs datasheet **2300** (merge provenance: `opus`)  
  **Source:** F12ML.pdf p.1 'Lifting Height 2300mm'  
  **Verdict: RESOLVED — 2300 mm — DB 120 is wrong (it is the F20MT's figure)**  
  Confirmed cross-model contamination: the DB's F12ML lift (120 mm) and F20MT lift (3244 mm) are both wrong, and 120 mm is exactly what F20MT.pdf prints. K.O. field.

- **`max_payload`** (KO, kg) — *Geek+ F12ML* → DB row(s) `Geek+ F12ML`  
  DB **1400.0** vs datasheet **1500** (merge provenance: `challenge:CONFIRM`)  
  **Source:** F12ML.pdf p.1 'Payload Capacity: 0–2 m: 1500 kg / 2–2.5 m: 1200 kg / 2.5–3 m: 1000 kg'  
  **Verdict: RESOLVED — 1500 kg**  
  Height-dependent payload matrix. AP0 max_payload hint says report the heaviest stated number = 1500 (valid to 2 m). Worth recording the derating in a note at import time.

- **`max_speed`** (SCORING, m/s) — *Geek+ F12ML* → DB row(s) `Geek+ F12ML`  
  DB **1.2** vs datasheet **1.5** (merge provenance: `opus`)  
  **Source:** F12ML.pdf p.1 'BaseTravel Speed: Maximum speed of 1.5m/s'  
  **Verdict: RESOLVED — 1.5 m/s**  
  Printed maximum; DB 1.2 appears nowhere.

- **`stacking_capability`** (COND_KO) — *Geek+ F12ML* → DB row(s) `Geek+ F12ML`  
  DB **False** vs datasheet **True** (merge provenance: `opus`)  
  **Source:** F12ML.pdf p.1 'Lifting Height 2300mm'; 'Position Accuracy ±10mm for precise handling and stacking'  
  **Verdict: RESOLVED — True**  
  A 2300 mm mast plus an explicit stacking claim. DB False is a direct consequence of the wrong 120 mm lift height.

- **`drive_type`** (CONTEXT) — *Geek+ F20MT* → DB row(s) `Geek+ F-Series (F20MT Smart Forklift)`  
  DB **Counterbalanced** vs datasheet **Pallet Mover** (merge provenance: `opus`)  
  **Source:** F20MT.pdf p.1 'Lifting Height 120mm'; 'Payload Capacity Up to 2000kg'; 'Fork Dimensions 55x180x1200mm; Spread 560x620x680 mm'  
  **Verdict: RESOLVED — Pallet Mover**  
  Fork geometry + 120 mm stroke = pallet mover. DB 'Counterbalanced' is inconsistent with every dimension on the sheet.

- **`lifting_height`** (KO, mm) — *Geek+ F20MT* → DB row(s) `Geek+ F-Series (F20MT Smart Forklift)`  
  DB **3244** vs datasheet **120** (merge provenance: `opus`)  
  **Source:** F20MT.pdf p.1 'Lifting Height 120mm'; 'Lift Speed With load: 35mm/s, Without load: 40mm/s'  
  **Verdict: RESOLVED — 120 mm — DB 3244 is wrong**  
  The 35/40 mm/s lift speed corroborates a short-stroke pallet mover, not a 3.2 m mast.

- **`stacking_capability`** (COND_KO) — *Geek+ F20MT* → DB row(s) `Geek+ F-Series (F20MT Smart Forklift)`  
  DB **True** vs datasheet **False** (merge provenance: `opus`)  
  **Source:** F20MT.pdf p.1 'Lifting Height 120mm'  
  **Verdict: RESOLVED — False**  
  A 120 mm stroke cannot stack. Follows directly from the lift height correction.

- **`max_speed`** (SCORING, m/s) — *Geek+ P1200R* → DB row(s) `Geek+ P1200R`  
  DB **2.0** vs datasheet **2.6** (merge provenance: `challenge:CONFIRM`)  
  **Source:** P-series.pdf spec table; adjudicated challenge:CONFIRM 2026-08-19  
  **Verdict: RESOLVED — 2.6 m/s**  
  Same rule as P800R.

- **`navigation_type`** (CONTEXT) — *Geek+ P1200R* → DB row(s) `Geek+ P1200R`  
  DB **Natural Feature (SLAM)** vs datasheet **QR/DM Code** (merge provenance: `challenge:CONCEDE`)  
  **Source:** P-series.pdf / RS-series-1.pdf; same challenge:CONCEDE ruling as P500R  
  **Verdict: RESOLVED — QR/DM Code**  
  Identical class to Geek+ P500R — one shared vendor term across the whole shelf-to-person and RoboShuttle range.

- **`navigation_type`** (CONTEXT) — *Geek+ P500R* → DB row(s) `Geek+ P500R`  
  DB **Natural Feature (SLAM)** vs datasheet **QR/DM Code** (merge provenance: `challenge:CONCEDE`)  
  **Source:** P-series.pdf (Geek+ P-series shelf-to-person); already adjudicated as challenge:CONCEDE in the 2026-08-19 round  
  **Verdict: RESOLVED — QR/DM Code**  
  Settled rule: 'QR code visual navigation' is ONE vendor compound term mapping to the single AP0 value QR/DM Code — not QR + Vision, and not SLAM. Shelf-to-person P-series robots run on floor QR codes; DB's SLAM is wrong and also implies infrastructure-free operation they do not have.

- **`max_payload`** (KO, kg) — *Geek+ P800R* → DB row(s) `Geek+ P800R`  
  DB **600.0** vs datasheet **1000** (merge provenance: `opus`)  
  **Source:** P-series.pdf spec table (P800R row); merged value carries opus provenance  
  **Verdict: RESOLVED — 1000 kg**  
  The P-series model number encodes the shelf-rated load, not the robot's rated payload; 600 kg in the DB is below every figure printed for this model. K.O. field — verify against p.1 of P-series.pdf before import.

- **`max_speed`** (SCORING, m/s) — *Geek+ P800R* → DB row(s) `Geek+ P800R`  
  DB **2.0** vs datasheet **2.3** (merge provenance: `challenge:CONFIRM`)  
  **Source:** P-series.pdf spec table; adjudicated challenge:CONFIRM 2026-08-19  
  **Verdict: RESOLVED — 2.3 m/s**  
  AP0 max_speed hint takes the top/unloaded figure and the field is SCORING, so there is no K.O. downside to the higher number.

- **`navigation_type`** (CONTEXT) — *Geek+ P800R* → DB row(s) `Geek+ P800R`  
  DB **Natural Feature (SLAM)** vs datasheet **QR/DM Code** (merge provenance: `challenge:CONCEDE`)  
  **Source:** P-series.pdf / RS-series-1.pdf; same challenge:CONCEDE ruling as P500R  
  **Verdict: RESOLVED — QR/DM Code**  
  Identical class to Geek+ P500R — one shared vendor term across the whole shelf-to-person and RoboShuttle range.

- **`navigation_type`** (CONTEXT) — *Geek+ RoboShuttle P40* → DB row(s) `Geek+ RoboShuttle P40`  
  DB **Natural Feature (SLAM)** vs datasheet **QR/DM Code** (merge provenance: `challenge:CONCEDE`)  
  **Source:** P-series.pdf / RS-series-1.pdf; same challenge:CONCEDE ruling as P500R  
  **Verdict: RESOLVED — QR/DM Code**  
  Identical class to Geek+ P500R — one shared vendor term across the whole shelf-to-person and RoboShuttle range.

- **`navigation_type`** (CONTEXT) — *Geek+ RoboShuttle RS11-DA* → DB row(s) `Geek+ RoboShuttle RS11-DA`  
  DB **Natural Feature (SLAM)** vs datasheet **QR/DM Code** (merge provenance: `challenge:CONCEDE`)  
  **Source:** P-series.pdf / RS-series-1.pdf; same challenge:CONCEDE ruling as P500R  
  **Verdict: RESOLVED — QR/DM Code**  
  Identical class to Geek+ P500R — one shared vendor term across the whole shelf-to-person and RoboShuttle range.

- **`navigation_type`** (CONTEXT) — *Geek+ RoboShuttle RS8-DA* → DB row(s) `Geek+ RoboShuttle RS8-DA`  
  DB **Natural Feature (SLAM)** vs datasheet **QR/DM Code** (merge provenance: `challenge:CONCEDE`)  
  **Source:** P-series.pdf / RS-series-1.pdf; same challenge:CONCEDE ruling as P500R  
  **Verdict: RESOLVED — QR/DM Code**  
  Identical class to Geek+ P500R — one shared vendor term across the whole shelf-to-person and RoboShuttle range.


### Grenzebach Maschinenbau GmbH — 14 conflicts

- **`infrastructure_free`** (COND_KO) — *Grenzebach FF1200S* → DB row(s) `Grenzebach FF1200S`  
  DB **False** vs datasheet **True** (merge provenance: `opus`)  
  **Source:** Grenzebach_Intralogistics_Data_Sheet_FF1200S_en.pdf p.2 'The free contour navigation' + spec table 'Contour navigation (Safety scanner detects surrounding and compares with internal map)'  
  **Verdict: RESOLVED — True**  
  Map-based contour navigation with no floor-side installation is infrastructure-free by the industry-README definition. COND_KO field — False wrongly disqualifies this vehicle from infrastructure-free tenders.

- **`navigation_type`** (CONTEXT) — *Grenzebach FF1200S* → DB row(s) `Grenzebach FF1200S`  
  DB **Inductive Loop** vs datasheet **Contour** (merge provenance: `challenge:CONCEDE`)  
  **Source:** Grenzebach_Intralogistics_Data_Sheet_FF1200S_en.pdf p.2 'The free contour navigation …'; spec table 'Navigation | Contour navigation (Safety scanner …)'  
  **Verdict: RESOLVED — Contour — DB 'Inductive Loop' is wrong**  
  Printed twice. Inductive Loop appears nowhere in the document and is the root cause of the infrastructure_free=False error below.

- **`operating_humidity_max`** (COND_KO, %) — *Grenzebach FF1200S* → DB row(s) `Grenzebach FF1200S`  
  DB **70** vs datasheet **80** (merge provenance: `opus`)  
  **Source:** Grenzebach_Intralogistics_Data_Sheet_FF1200S_en.pdf p.2 spec table 'Air humidity | Max. 80 %, non-condensing'  
  **Verdict: RESOLVED — 80 %**  
  Printed explicitly; DB 70 appears nowhere.

- **`operating_temp_min`** (COND_KO, °C) — *Grenzebach FF1200S* → DB row(s) `Grenzebach FF1200S`  
  DB **5** vs datasheet **10** (merge provenance: `opus`)  
  **Source:** Grenzebach_Intralogistics_Data_Sheet_FF1200S_en.pdf p.2 spec table 'Temperature range | +10 to +40 °C (0 °C to 40 °C, [on request])'  
  **Verdict: RESOLVED — 10 °C standard (0 °C available on request)**  
  DB's 5 °C matches neither figure. Recommend 10 with the on-request 0 recorded in notes; taking 0 would claim an option as standard.

- **`max_speed`** (SCORING, m/s) — *Grenzebach L1200S* → DB row(s) `Grenzebach L1200S`  
  DB **2.0** vs datasheet **1.0** (merge provenance: `sonnet_only`)  
  **Source:** Grenzebach_Data_Sheet_L1200S-Li_en.pdf p.2 'Speed (unloaded) | Up to 1 m/s'; 'Speed (loaded) | Up to 1 m/s'  
  **Verdict: RESOLVED — 1.0 m/s — DB 2.0 is wrong (it is the FF1200S figure)**  
  Both speed rows print 1 m/s. The FF1200S sheet prints 2.0 m/s — cross-model contamination again.

- **`navigation_type`** (CONTEXT) — *Grenzebach L1200S* → DB row(s) `Grenzebach L1200S`  
  DB **Natural Feature (SLAM)** vs datasheet **Contour** (merge provenance: `sonnet_only`)  
  **Source:** Grenzebach_Data_Sheet_L1200S-Li_en.pdf p.2 'Due to the free contour navigation…'; spec table 'Navigation | Contour navigation (safety scanner …)'  
  **Verdict: RESOLVED — Contour**  
  Printed twice. Note the OL1200S brochure uses BOTH 'SLAM navigation' (p.2) and 'Contour navigation' (p.4) for its sibling machine — direct in-corpus evidence that this vendor treats the two as the same thing.

- **`vehicle_length`** (CONTEXT, mm) — *Grenzebach L1200S* → DB row(s) `Grenzebach L1200S`  
  DB **1263** vs datasheet **1238** (merge provenance: `sonnet_only`)  
  **Source:** Grenzebach_Data_Sheet_L1200S-Li_en.pdf p.2 spec table 'Length | 1,238 mm'  
  **Verdict: RESOLVED — 1238 mm**  
  Printed explicitly; DB 1263 appears nowhere in the document.

- **`vehicle_width`** (CONTEXT, mm) — *Grenzebach L1200S* → DB row(s) `Grenzebach L1200S`  
  DB **695** vs datasheet **693** (merge provenance: `sonnet_only`)  
  **Source:** Grenzebach_Data_Sheet_L1200S-Li_en.pdf p.2 spec table 'Width | 693 mm'  
  **Verdict: RESOLVED — 693 mm**  
  Printed explicitly; DB 695 is a rounding.

- **`max_speed`** (SCORING, m/s) — *Grenzebach L1200S-Li* → DB row(s) `Grenzebach L1200S`  
  DB **2.0** vs datasheet **1.0** (merge provenance: `opus_only`)  
  **Source:** Grenzebach_Data_Sheet_L1200S-Li_en.pdf p.2 'Speed (unloaded) | Up to 1 m/s'  
  **Verdict: RESOLVED — 1.0 m/s — duplicate of the L1200S finding**  
  The 'L1200S-Li' merged entry and the 'L1200S' merged entry hold byte-identical field values and both derive from this one sheet; they are the same product read twice, not two products.

- **`vehicle_length`** (CONTEXT, mm) — *Grenzebach L1200S-Li* → DB row(s) `Grenzebach L1200S`  
  DB **1263** vs datasheet **1238** (merge provenance: `opus_only`)  
  **Source:** Grenzebach_Data_Sheet_L1200S-Li_en.pdf p.2 'Length | 1,238 mm'  
  **Verdict: RESOLVED — 1238 mm — duplicate of the L1200S finding**  
  See above.

- **`vehicle_width`** (CONTEXT, mm) — *Grenzebach L1200S-Li* → DB row(s) `Grenzebach L1200S`  
  DB **695** vs datasheet **693** (merge provenance: `opus_only`)  
  **Source:** Grenzebach_Data_Sheet_L1200S-Li_en.pdf p.2 'Width | 693 mm'  
  **Verdict: RESOLVED — 693 mm — duplicate of the L1200S finding**  
  See above.

- **`fleet_management_system`** (CONTEXT) — *Grenzebach OL1200S* → DB row(s) `Grenzebach OL1200S`  
  DB **Proprietary (Fleet Manager)** vs datasheet **VDA 5050 compatible** (merge provenance: `sonnet_only`)  
  **Source:** Grenzebach_Intralogistics_OL1200S_Brochure_EN.pdf p.2 'integration … is possible at all times via the VDA 5050 interface'; p.3 'via the VDA 5050 interface'; p.4 'Fleet Manager Software (FMS)'  
  **Verdict: RESOLVED — VDA 5050 compatible**  
  The vendor's own interoperability claim is the VDA 5050 interface, stated twice. Note the DB's current token 'Proprietary (Fleet Manager)' is not a valid AP0 value at all (see DB-cleanup).

- **`integration_capability`** (COND_KO) — *Grenzebach OL1200S* → DB row(s) `Grenzebach OL1200S`  
  DB **WMS** vs datasheet **ERP** (merge provenance: `sonnet_only`)  
  **Source:** Grenzebach_Intralogistics_OL1200S_Brochure_EN.pdf p.4 'Administration level | Enterprise Resource Planning (ERP)'  
  **Verdict: RESOLVED — Union [WMS, ERP]**  
  The sheet adds ERP; it does not deny WMS. COND_KO field — additive only, never subtract.

- **`lift_height`** (KO, mm) — *Grenzebach OL1200S* → DB row(s) `Grenzebach OL1200S`  
  DB **60** vs datasheet **140** (merge provenance: `opus`)  
  **Source:** Grenzebach_Intralogistics_OL1200S_Brochure_EN.pdf p.4 spec table 'Lifting height | Approx. 140 mm (5.51 in), electrical'  
  **Verdict: RESOLVED — 140 mm — DB 60 is wrong (it is the L1200S figure)**  
  The imperial conversion 5.51 in = 140 mm is internally consistent, which rules out a source typo. 60 mm is exactly what the L1200S sheet prints — third cross-model contamination in this one supplier.


### Mobile Industrial Robots A/S (MiR) — 14 conflicts

- **`fleet_management_system`** (CONTEXT) — *MiR1200 Pallet Jack* → DB row(s) `MiR1200 Pallet Jack`  
  DB **Open API** vs datasheet **Proprietary** (merge provenance: `sonnet_only`)  
  **Source:** MiR1200 Pallet Jack specifications.pdf p.1 general information block  
  **Verdict: RESOLVED — Proprietary (MiR Fleet) — low materiality**  
  MiR Fleet is a proprietary controller that exposes a REST API; AP0's single-select cannot express both. CONTEXT field, no matching impact. Flagged as an AP0 modelling limitation rather than a data error.

- **`lift_height`** (KO, mm) — *MiR1200 Pallet Jack* → DB row(s) `MiR1200 Pallet Jack`  
  DB **200** vs datasheet **1140** (merge provenance: `opus`)  
  **Source:** MiR1200 Pallet Jack specifications.pdf p.1 spec table 'Maximum fork lifting height | 1 140 mm | 44.9 in'  
  **Verdict: RESOLVED — 1140 mm — DB 200 is wrong**  
  The imperial pair 1140 mm / 44.9 in is internally consistent, ruling out a typo. K.O. field understated by ~940 mm — this vehicle would be wrongly excluded from most pallet-rack tenders.

- **`integration_capability`** (COND_KO) — *MiR1350* → DB row(s) `MiR1350`  
  DB **REST API, WMS** vs datasheet **Modbus, REST API** (merge provenance: `opus`)  
  **Source:** MiR1350 Specifications 2.99.pdf p.11 'Communication protocols | REST, Modbus'; p.11 'Ethernet interface | 10/100Mbit Ethernet with Modbus protocol'  
  **Verdict: RESOLVED — Union [REST API, WMS, Modbus]**  
  The sheet adds Modbus; it says nothing about WMS integration either way. COND_KO field — additive only.

- **`load_type`** (KO) — *MiR1350* → DB row(s) `MiR1350`  
  DB **Custom Carrier, Pallet EUR** vs datasheet **Pallet EUR, Pallet ISO** (merge provenance: `opus`)  
  **Source:** MiR1350 Specifications 2.99.pdf p.2 'Maximum lifting capacity with a MiR EU-/US-lift'  
  **Verdict: RESOLVED — Union [Custom Carrier, Pallet EUR, Pallet ISO]**  
  'EU-/US-lift' evidences both EUR and ISO pallets. Custom Carrier stays — MiR top modules are explicitly customisable. K.O. field, so never subtract.

- **`max_speed`** (SCORING, m/s) — *MiR1350* → DB row(s) `MiR1350`  
  DB **2.7** vs datasheet **1.2** (merge provenance: `opus`)  
  **Source:** MiR1350 Specifications 2.99.pdf p.2 'Maximum speed (with maximum payload on a flat surface)'  
  **Verdict: RESOLVED — 1.2 m/s — DB 2.7 is unsupported and implausible**  
  2.7 m/s exceeds the plausibility band for a 1350 kg human-shared AMR (<=1.5 m/s) and is not a MiR figure anywhere in the corpus. The spec-table cell did not extract cleanly, so confirm the printed digit before import — but 2.7 must not stand.

- **`operating_temp_max`** (COND_KO, °C) — *MiR1350* → DB row(s) `MiR1350`  
  DB **40** vs datasheet **25** (merge provenance: `challenge:CONFIRM`)  
  **Source:** MiR1350 Specifications 2.99.pdf p.9 'Ambient temperature range, operation | 5–25 °C for continuous use, maximum 40 °C for 1 hour'  
  **Verdict: RESOLVED — 25 °C**  
  Same MiR house convention as MiR250.

- **`charge_time`** (SCORING, min) — *MiR250* → DB row(s) `MiR250`  
  DB **10** vs datasheet **52** (merge provenance: `opus`)  
  **Source:** MiR250 Specifications 2.99.pdf p.9 'Charging time from 10%–90% with MiR Charge 48V (at an ambient temperature of 22°C) | 52 min'  
  **Verdict: RESOLVED — 52 min — DB 10 is a misread**  
  The DB's '10' is the '10%' from the state-of-charge range '10%–90%', not a duration. Classic label-vs-value misalignment.

- **`cleanroom_class`** (COND_KO) — *MiR250* → DB row(s) `MiR250`  
  DB **ISO 4 (optional)** vs datasheet **ISO 1–9** (merge provenance: `opus`)  
  **Source:** MiR250 Specifications 2.99.pdf p.11 'Cleanroom | Optional Class 4 (ISO 14644-1) — see the cleanroom certificate'  
  **Verdict: RESOLVED — ISO Class 4, optional — DB is substantively right, the extracted 'ISO 1–9' is wrong**  
  'ISO 1–9' is the Omron datasheet convention and does not belong to MiR. Note the DB's stored token 'ISO 4 (optional)' is outside AP0 allowed values and needs normalising (DB-cleanup).

- **`operating_temp_max`** (COND_KO, °C) — *MiR250* → DB row(s) `MiR250`  
  DB **40** vs datasheet **25** (merge provenance: `challenge:CONFIRM`)  
  **Source:** MiR250 Specifications 2.99.pdf p.11 'Ambient temperature range, operation | 5–25 °C for continuous use, maximum 40 °C for 1 hour'  
  **Verdict: RESOLVED — 25 °C**  
  MiR house convention (settled 2026-08-19): the 40 °C is a one-hour excursion, not a range bound. COND_KO field — storing 40 claims continuous hot-environment capability the vendor does not offer.

- **`battery_runtime`** (SCORING, hours) — *MiR600* → DB row(s) `MiR600`  
  DB **8.0** vs datasheet **8.33** (merge provenance: `opus`)  
  **Source:** MiR600 Specifications 2.99.pdf p.8 'Active operation time with no payload (100–0%) | 10h45min' and the adjacent max-payload row  
  **Verdict: RESOLVED — 8.33 h (8h20min) at maximum payload — immaterial**  
  DB's 8.0 is a rounding of the same figure. SCORING field, ~4% apart.

- **`integration_capability`** (COND_KO) — *MiR600* → DB row(s) `MiR600`  
  DB **MQTT, REST API, WMS** vs datasheet **Modbus, REST API** (merge provenance: `opus`)  
  **Source:** MiR600 Specifications 2.99.pdf p.11 'Communication protocols | REST, Modbus'  
  **Verdict: RESOLVED — Union [MQTT, REST API, WMS, Modbus]**  
  Additive only, same as MiR1350.

- **`min_ground_clearance`** (KO, mm) — *MiR600* → DB row(s) `MiR600`  
  DB **320** vs datasheet **322** (merge provenance: `challenge:CONFIRM`)  
  **Source:** MiR600 Specifications 2.99.pdf p.1 'Dimensions | Height 322mm'  
  **Verdict: RESOLVED — 322 mm**  
  min_ground_clearance holds ROBOT HEIGHT per the AP0 hint (the field name is a trap — the actual floor gap on this machine is 25–27 mm). 322 is the printed height; DB 320 is a rounding. Adjudicated challenge:CONFIRM.

- **`operating_temp_max`** (COND_KO, °C) — *MiR600* → DB row(s) `MiR600`  
  DB **40** vs datasheet **25** (merge provenance: `challenge:CONFIRM`)  
  **Source:** MiR600 Specifications 2.99.pdf p.9 'Ambient temperature range, operation | 5–25 °C for continuous use, maximum 40 °C for 1 hour'  
  **Verdict: RESOLVED — 25 °C**  
  Same MiR house convention.

- **`vehicle_width`** (CONTEXT, mm) — *MiR600* → DB row(s) `MiR600`  
  DB **920** vs datasheet **910** (merge provenance: `opus`)  
  **Source:** MiR600 Specifications 2.99.pdf p.1 'Dimensions | Width 910mm'  
  **Verdict: RESOLVED — 910 mm**  
  Printed explicitly; DB 920 is a rounding.


### Toyota Material Handling Europe — 14 conflicts

- **`load_type`** (KO) — *Toyota Autopilot SAI125CB* → DB row(s) `Toyota Autopilot SAI125CB`  
  DB **Pallet EUR, Pallet ISO, Roll Container** vs datasheet **Half-Euro, Pallet EUR, Pallet ISO** (merge provenance: `opus`)  
  **Source:** tmha_sai125cb_brochure.pdf p.2 row 4.22 'Fork dimensions s/e mm 40/100'  
  **Verdict: UNRESOLVED — DB [Pallet EUR, Pallet ISO, Roll Container] vs extracted [Half-Euro, Pallet EUR, Pallet ISO]**  
  The sheet gives fork geometry but no explicit pallet-compatibility list. Roll Container on a forked counterbalance stacker is doubtful and Half-Euro is plausible, but neither is evidenced. K.O. field — leave both and escalate.

- **`max_speed`** (SCORING, m/s) — *Toyota Autopilot SAI125CB* → DB row(s) `Toyota Autopilot SAI125CB`  
  DB **2.22** vs datasheet **2.19** (merge provenance: `opus`)  
  **Source:** tmha_sai125cb_brochure.pdf p.2 row 5.1.1 'Travel speed, with/without load, automatic mode, drive wheel direction km/h 7.9/7.9'  
  **Verdict: RESOLVED — 2.19 m/s**  
  7.9 km/h = 2.194 m/s. DB's 2.22 corresponds to 8.0 km/h, which is not printed anywhere.

- **`min_aisle_width`** (KO, mm) — *Toyota Autopilot SAI125CB* → DB row(s) `Toyota Autopilot SAI125CB`  
  DB **3000** vs datasheet **2963** (merge provenance: `opus`)  
  **Source:** tmha_sai125cb_brochure.pdf p.3 'Aisle width Auto mode | Ast' table  
  **Verdict: RESOLVED — 2963 mm (datasheet figure); DB 3000 is a rounding**  
  Prefer the printed precise figure over a round number that appears nowhere. Low materiality (1.2%) but min_aisle_width is a K.O. field where precision is cheap.

- **`lifting_height`** (KO, mm) — *Toyota RAE160 Autopilot* → DB row(s) `Toyota RAE160 Autopilot`  
  DB **11000** vs datasheet **10000** (merge provenance: `opus`)  
  **Source:** 747505-040.pdf p.3 mast dimensions table 'Lift height h23 mm 4850 5400 5700 6300 7000 7500 8000 8500 9000 9500 10000'  
  **Verdict: RESOLVED — 10000 mm — DB 11000 is unsupported**  
  The mast table tops out at 10000 mm (VDI 4.4 Lift h3 = 9945). 11000 appears nowhere in the document.

- **`lifting_height`** (KO, mm) — *Toyota Reflex RAE250 Autopilot* → DB row(s) `Toyota Reflex RAE250 Autopilot`  
  DB **12000** vs datasheet **10000** (merge provenance: `opus`)  
  **Source:** 747505-040.pdf p.3 mast dimensions table (shared across RAE160/200/250) 'Lift height h23 … 10000'  
  **Verdict: RESOLVED — 10000 mm — DB 12000 is unsupported**  
  One mast table serves all three models. 12000 appears nowhere.

- **`load_detection`** (CONTEXT) — *Toyota Reflex RAE250 Autopilot* → DB row(s) `Toyota Reflex RAE250 Autopilot`  
  DB **Mechanical/Tactile** vs datasheet **Barcode/DataMatrix, Camera/Vision** (merge provenance: `opus`)  
  **Source:** 747505-040.pdf p.5 '• Multi load detection (optional)'  
  **Verdict: UNRESOLVED — DB [Mechanical/Tactile] vs extracted [Barcode/DataMatrix, Camera/Vision]**  
  The only load-detection statement in the document is a single optional-equipment bullet that names no sensing technology. Neither value can be confirmed or refuted from this sheet.

- **`max_speed`** (SCORING, m/s) — *Toyota Reflex RAE250 Autopilot* → DB row(s) `Toyota Reflex RAE250 Autopilot`  
  DB **2.5** vs datasheet **2.0** (merge provenance: `opus`)  
  **Source:** 747505-040.pdf p.2 rows 5.1a/5.1b 'Travel speed, with/without load Auto mode km/h 7,2/7,2'  
  **Verdict: RESOLVED — 2.0 m/s — DB 2.5 is unsupported**  
  7,2 km/h = 2.0 m/s, identical in auto and manual mode across all three models.

- **`min_aisle_width`** (KO, mm) — *Toyota Reflex RAE250 Autopilot* → DB row(s) `Toyota Reflex RAE250 Autopilot`  
  DB **3071** vs datasheet **3198** (merge provenance: `opus`)  
  **Source:** 747505-040.pdf p.4 'Aisle width Auto mode' table  
  **Verdict: RESOLVED — 3071 mm — already settled by Tech Lead decision; keep DB**  
  Pre-settled; not re-opened in this pass. The extracted 3198 comes from a different cell of the same configuration-dependent table.

- **`vehicle_length`** (CONTEXT, mm) — *Toyota Reflex RAE250 Autopilot* → DB row(s) `Toyota Reflex RAE250 Autopilot`  
  DB **2755** vs datasheet **2091** (merge provenance: `opus`)  
  **Source:** 747505-040.pdf p.2 row 4.19 'Overall length … See battery and options dependent table'; length table on p.3/p.4  
  **Verdict: UNRESOLVED — DB 2755 vs extracted 2091 — neither confirmable from the text layer**  
  Overall length is published only in the battery/mast-option-dependent table, whose cells did not extract as text. Needs a visual read of the p.3/p.4 tables.

- **`vehicle_width`** (CONTEXT, mm) — *Toyota Reflex RAE250 Autopilot* → DB row(s) `Toyota Reflex RAE250 Autopilot`  
  DB **1270** vs datasheet **1570** (merge provenance: `opus`)  
  **Source:** 747505-040.pdf p.2 row 4.21 'Overall width b1 mm 1270/1470'; row 4.22 'Overall width over support arms (including scanners) b mm 1570/1770'  
  **Verdict: RESOLVED — Keep DB 1270 mm (VDI 4.21); 1570 mm is row 4.22**  
  Both figures are printed with different definitions. AP0 vehicle_width has no support-arm qualifier, so the VDI 4.21 value is the conventional read. Not an error — an AP0 definitional gap for reach trucks. Both cited so a reviewer can choose.

- **`lifting_height`** (KO, mm) — *Toyota Staxio SAE160 Autopilot (Duplex Tele)* → DB row(s) `Toyota Staxio SAE160 Autopilot`  
  DB **4700** vs datasheet **2350** (merge provenance: `opus_only`)  
  **Source:** sae160-technicky-list.pdf p.2 'Lift height h23 mm | 2350 3) | 4700 3)' (DX Tele | TX Hi-Lo); VDI 4.4 'Lift movement h3 mm 2310 | 4658'  
  **Verdict: VARIANT-SPLIT-NEEDED — 2350 mm belongs to a DX-Tele-mast product row, not to the existing (TX Hi-Lo, 4700 mm) row**  
  The DB's 4700 is exactly the TX Hi-Lo column, so the DB is correct for the configuration it documents. Overwriting it with 2350 would halve a K.O. field.

- **`mast_type`** (CONTEXT) — *Toyota Staxio SAE160 Autopilot (Duplex Tele)* → DB row(s) `Toyota Staxio SAE160 Autopilot`  
  DB **Duplex|Triplex** vs datasheet **Duplex** (merge provenance: `opus_only`)  
  **Source:** sae160-technicky-list.pdf p.3 'Dimensions | DX Tele mast | TX Hi-Lo mast'  
  **Verdict: VARIANT-SPLIT-NEEDED — See the Triplex Hi-Lo entry**  
  Same split.

- **`mast_type`** (CONTEXT) — *Toyota Staxio SAE160 Autopilot (Triplex Hi-Lo)* → DB row(s) `Toyota Staxio SAE160 Autopilot`  
  DB **Duplex|Triplex** vs datasheet **Triplex** (merge provenance: `opus`)  
  **Source:** sae160-technicky-list.pdf p.2/p.3 'Dimensions | DX Tele mast | TX Hi-Lo mast'; p.2 'Lift height h23 mm 2350 3) | 4700 3)'  
  **Verdict: VARIANT-SPLIT-NEEDED — Keep DB 'Duplex|Triplex' on the combined row; split into two products**  
  One datasheet, two mast configurations with materially different lift heights. The DB has a single blended row holding both mast types. Not a value conflict.

- **`vehicle_length`** (CONTEXT, mm) — *Toyota Staxio SAE160 Autopilot (Triplex Hi-Lo)* → DB row(s) `Toyota Staxio SAE160 Autopilot`  
  DB **2261** vs datasheet **2258** (merge provenance: `opus`)  
  **Source:** sae160-technicky-list.pdf p.2 row 4.19 'Overall length … See battery and options dependent table'  
  **Verdict: RESOLVED — Immaterial (2258 vs 2261 mm, 3 mm apart)**  
  Both figures come from the same options-dependent length table under slightly different option assumptions. No action needed.


### Balyo — 13 conflicts

- **`lifting_height`** (KO, mm) — *LOWY* → DB row(s) `LOWY / LOWY HD`  
  DB **3000** vs datasheet **2900** (merge provenance: `opus`)  
  **Source:** LOWY, Robotic Stacker, AGV:AMR | BALYO.pdf p.1 'With a lift height of up to 10 ft (2.93 m), LOWY can also handle pallets from gravity …'  
  **Verdict: RESOLVED — 2930 mm (both DB 3000 and the extracted 2900 are roundings)**  
  The metric/imperial pair 10 ft / 2.93 m is internally consistent. Use the precise 2930.

- **`min_aisle_width`** (KO, mm) — *LOWY* → DB row(s) `LOWY / LOWY HD`  
  DB **2700** vs datasheet **2900** (merge provenance: `challenge:CONFIRM`)  
  **Source:** LOWY, Robotic Stacker, AGV:AMR | BALYO.pdf p.1 stat block 'Aisle width'; LOWY HD, Robotic Heavy Duty Stacker, AGV:AMR | BALYO.pdf p.1 stat block 'Aisle width'  
  **Verdict: VARIANT-SPLIT-NEEDED — LOWY 2900 vs LOWY HD 2950 come from two separate documents; the DB merges both into one row 'LOWY / LOWY HD'**  
  The stat-block digits sit in a graphic and did not extract as text, so the exact values could not be re-verified — but the structural point stands: two documented machines, one DB row, and a DB value (2700) that matches neither extraction.

- **`safety_coverage`** (SCORING) — *LOWY* → DB row(s) `LOWY / LOWY HD`  
  DB **Single plane (2D)** vs datasheet **Full 3D** (merge provenance: `opus`)  
  **Source:** LOWY, Robotic Stacker, AGV:AMR | BALYO.pdf p.1 'a 3D lidar positioned on top of the robot uses 64 planes of data to guarantee unrivaled safety by dynamically detecting obstacles across all three planes'; 'Equipped with advanced 3D pallet detection and a comprehensive smart safety field'  
  **Verdict: RESOLVED — Full 3D**  
  64-plane 3D lidar plus 3D pallet detection is unambiguously more than single-plane. DB's 'Single plane (2D)' understates a SCORING field.

- **`min_aisle_width`** (KO, mm) — *LOWY CB* → DB row(s) `LOWY CB`  
  DB **3800** vs datasheet **3400** (merge provenance: `opus`)  
  **Source:** LOWY CB, Robotic Counterbalanced Stacker, AGV:AMR | BALYO.pdf p.1 stat block 'Aisle width' (value rendered in a graphic, not in the text layer)  
  **Verdict: UNRESOLVED — DB 3800 vs extracted 3400**  
  Could not be re-verified from the text layer. Needs a visual read of the p.1 stat block.

- **`min_aisle_width`** (KO, mm) — *LOWY HD* → DB row(s) `LOWY / LOWY HD`  
  DB **2700** vs datasheet **2950** (merge provenance: `opus_only`)  
  **Source:** LOWY HD, Robotic Heavy Duty Stacker, AGV:AMR | BALYO.pdf p.1 stat block 'Aisle width'  
  **Verdict: VARIANT-SPLIT-NEEDED — See the LOWY entry**  
  Same merged-row problem.

- **`safety_coverage`** (SCORING) — *LOWY HD* → DB row(s) `LOWY / LOWY HD`  
  DB **Single plane (2D)** vs datasheet **Full 3D** (merge provenance: `opus_only`)  
  **Source:** LOWY HD, Robotic Heavy Duty Stacker, AGV:AMR | BALYO.pdf p.1 'a 3D lidar positioned atop utilizes 64 planes of data … across all three planes'  
  **Verdict: RESOLVED — Full 3D**  
  Same as LOWY.

- **`battery_type`** (CONTEXT) — *REACHY* → DB row(s) `REACHY`  
  DB **Li-Ion** vs datasheet **Lead-Acid** (merge provenance: `opus`)  
  **Source:** Balyo REACHY product page PDF; Tech Lead ruling  
  **Verdict: RESOLVED — Union [Li-Ion, Lead-Acid] — already settled by Tech Lead decision**  
  Pre-settled; recorded here only for completeness.

- **`lifting_height`** (KO, mm) — *REACHY* → DB row(s) `REACHY`  
  DB **11000** vs datasheet **11455** (merge provenance: `opus`)  
  **Source:** Balyo REACHY product page PDF  
  **Verdict: RESOLVED — 11455 mm (DB 11000 is a rounding)**  
  11455 mm is the precise printed figure with a consistent imperial companion; prefer it over the round 11000.

- **`coupling_type`** (KO) — *TUGGY* → DB row(s) `TUGGY`  
  DB **Automatic (verify)** vs datasheet **Automatic** (merge provenance: `opus`)  
  **Source:** Balyo TUGGY product page PDF  
  **Verdict: DB-CLEANUP — 'Automatic' — the DB's stored token 'Automatic (verify)' is not a valid AP0 value**  
  Not a value conflict: the DB and the datasheet agree on 'Automatic'. The '(verify)' suffix is a leftover research annotation that breaks AP0 allowed-values validation.

- **`battery_type`** (CONTEXT) — *VEENY* → DB row(s) `VEENY`  
  DB **Li-Ion** vs datasheet **Lead-Acid** (merge provenance: `opus`)  
  **Source:** LOWY HD, Robotic Heavy Duty Stacker, AGV:AMR | BALYO.pdf p.1 'Battery options | Lead Acid / LTO batteries'  
  **Verdict: RESOLVED — Union [Li-Ion, Lead-Acid]**  
  Balyo builds on OEM trucks offered with both chemistries. Same ruling the Tech Lead already made for REACHY. Additive — never remove Li-Ion.

- **`lifting_height`** (KO, mm) — *VEENY* → DB row(s) `VEENY`  
  DB **17200** vs datasheet **14710** (merge provenance: `challenge:CONCEDE`)  
  **Source:** Balyo VEENY product page PDF; adjudicated challenge:CONCEDE in the 2026-08-19 round  
  **Verdict: RESOLVED — 14710 mm — DB 17200 is unsupported**  
  Already litigated once and conceded. K.O. field overstated by 2.5 m in the DB.

- **`load_detection`** (CONTEXT) — *VEENY* → DB row(s) `VEENY`  
  DB **Camera/Vision** vs datasheet **Barcode/DataMatrix** (merge provenance: `opus`)  
  **Source:** Balyo VEENY product page PDF  
  **Verdict: RESOLVED — Union [Camera/Vision, Barcode/DataMatrix]**  
  Additive; the sheet names an extra sensing method without denying the stored one.

- **`max_speed`** (SCORING, m/s) — *VEENY* → DB row(s) `VEENY`  
  DB **2.2** vs datasheet **2.0** (merge provenance: `opus`)  
  **Source:** Balyo VEENY product page PDF; cf. LOWY HD p.1 'Travel Speed | Up to 2m/s / 4.4 mph'  
  **Verdict: UNRESOLVED — DB 2.2 vs extracted 2.0 m/s**  
  Balyo's sibling pages print 2 m/s, which supports 2.0, but the VEENY page's own stat block was not re-read in this pass. SCORING field, low materiality.


### AGILOX Services GmbH — 8 conflicts

- **`fork_spread`** (COND_KO) — *AGILOX OCF* → DB row(s) `AGILOX OCF`  
  DB **Auto (optional)** vs datasheet **Auto** (merge provenance: `opus`)  
  **Source:** agilox-corporate-folder-o-de_02_2026_web.pdf  
  **Verdict: DB-CLEANUP — 'Auto' — the DB's 'Auto (optional)' is not a valid AP0 value**  
  Not a value conflict: both sides say Auto. The '(optional)' suffix breaks allowed-values validation on a COND_KO field.

- **`min_aisle_width`** (KO, mm) — *AGILOX OCF* → DB row(s) `AGILOX OCF`  
  DB **1300** vs datasheet **2100** (merge provenance: `opus`)  
  **Source:** agilox-corporate-folder-o-de_02_2026_web.pdf; cf. Agilox One.pdf p.1 stat strip where 2.100 mm is printed under the label 'Drehkreis'  
  **Verdict: RESOLVED — Do NOT import 2100; DB 1300 is also unsupported.**  
  The extracted 2100 mm for OCF is exactly the Drehkreis figure printed on the AGILOX ONE page, and the same 'Drehkreis' label heads the fourth stat on every AGILOX one-pager. Both passes appear to have mapped AGILOX's turning-circle headline onto min_aisle_width. The recurring DB value of 1300 mm on BOTH OCF and ONE is separately suspicious of one figure copied across the range.

- **`load_type`** (KO) — *AGILOX ODM 600* → DB row(s) `AGILOX ODM 600/800`  
  DB **Custom Carrier (dolly), Roll Container** vs datasheet **Custom Carrier** (merge provenance: `opus`)  
  **Source:** Agilox ODM.pdf p.1  
  **Verdict: DB-CLEANUP — Normalise 'Custom Carrier (dolly)' -> 'Custom Carrier'; Roll Container is not contradicted**  
  The datasheet's [Custom Carrier] is a subset of what the DB already holds, so this is not a contradiction at all — it only surfaced as a conflict because the DB token is non-canonical.

- **`load_type`** (KO) — *AGILOX ODM 800* → DB row(s) `AGILOX ODM 600/800`  
  DB **Custom Carrier (dolly), Roll Container** vs datasheet **Custom Carrier** (merge provenance: `opus_only`)  
  **Source:** Agilox ODM.pdf p.1  
  **Verdict: DB-CLEANUP — See AGILOX ODM 600**  
  Same row, same finding. Also note ODM 600 and ODM 800 are two merged entries resolving to one DB row 'AGILOX ODM 600/800' — a split candidate.

- **`load_type`** (KO) — *AGILOX OFL* → DB row(s) `AGILOX OFL`  
  DB **Custom Carrier, Medium Euro, Pallet EUR, Plastic** vs datasheet **Custom Carrier, Half-Euro, Pallet EUR, Pallet ISO** (merge provenance: `opus`)  
  **Source:** agilox-corporate-folder-o-de_02_2026_web.pdf / Agilox OFL.pdf  
  **Verdict: DB-CLEANUP — Normalise DB tokens; then the sets substantially agree**  
  The DB holds 'Plastic', which is not an AP0 allowed value (nearest: 'Plastic Bin'), and 'Medium Euro' where the extraction says 'Half-Euro'. Once normalised, the remaining delta is only Pallet ISO vs Medium Euro. Fix the tokens before adjudicating the values.

- **`min_aisle_width`** (KO, mm) — *AGILOX ONE* → DB row(s) `AGILOX ONE`  
  DB **1300** vs datasheet **1600** (merge provenance: `sonnet_only`)  
  **Source:** Agilox One.pdf p.1 headline stat strip, read as an image: '1.000 kg / 2.204 lbs — maximales Hubgewicht | 500 mm / 19,7 in — maximale Stationshoehe | 1,4 m/s / 4,6 ft/s — maximale Geschwindigkeit | 2.100 mm / 82,7 in — Drehkreis'  
  **Verdict: RESOLVED — Do NOT import 1600; and DB 1300 is also unsupported. The datasheet publishes a *Drehkreis* (turning circle), not an aisle width.**  
  The fourth headline figure is explicitly labelled 'Drehkreis' (turning CIRCLE, i.e. a diameter) on every AGILOX one-pager ('minimaler Drehkreis' on Agilox OFL.pdf). It is not an aisle width and must not be mapped to min_aisle_width; mapping it to min_turning_radius would additionally require halving and is blocked by the open radius/diameter question. Neither 1300 nor 1600 appears anywhere in the document.

- **`lift_height`** (KO, mm) — *AGILOX ONE (Doppelscherenhub)* → DB row(s) `AGILOX ONE`  
  DB **620** vs datasheet **1100** (merge provenance: `opus_only`)  
  **Source:** Agilox One.pdf p.1 stat strip '500 mm / 19,7 in — maximale Stationshoehe' (read as an image) and body text 'Einfachscherenhub 1.000 kg auf bis zu 500 mm und mit einem Doppelscherenhub 750 kg auf bis zu 1.000 [mm]'  
  **Verdict: VARIANT-SPLIT-NEEDED — Single-scissor = 500 mm (confirmed in the headline stat strip); double-scissor = ~1000 mm. DB's 620 mm matches neither.**  
  The headline 500 mm and the body text agree for the single-scissor build, which corroborates the two-configuration reading. The DB's 620 mm is not printed anywhere on the page.

- **`max_payload`** (KO, kg) — *AGILOX ONE (Doppelscherenhub)* → DB row(s) `AGILOX ONE`  
  DB **1000.0** vs datasheet **750** (merge provenance: `opus_only`)  
  **Source:** Agilox One.pdf p.1 'Einfachscherenhub 1.000 kg auf bis zu 500 mm und mit einem Doppelscherenhub 750 kg auf bis zu 1.000 [mm]'  
  **Verdict: VARIANT-SPLIT-NEEDED — Single-scissor = 1000 kg / 500 mm; double-scissor = 750 kg / ~1000 mm. The DB has one blended row.**  
  One sentence documents two lift configurations with inversely related payload and stroke. The DB's 1000 kg + 620 mm pairing matches neither configuration and would misrepresent both K.O. fields.


### SAFELOG GmbH — 8 conflicts

- **`max_speed`** (SCORING, m/s) — *SAFELOG GT1 spin* → DB row(s) `SAFELOG AGV GT1 spin`  
  DB **2.2** vs datasheet **3.0** (merge provenance: `challenge:CONFIRM`)  
  **Source:** SAFELOG_Datenblatt_GT1-spin_EN.pdf p.2 'Under full load, the robot can reach a top speed of up to 2.0 m/s, while speeds of up to 3 m/s are possible without a payload.'; p.3 'Speed ([non]safe) (m/s) 0.02 – 2.0 [3.0]'  
  **Verdict: RESOLVED — 3.0 m/s**  
  AP0 max_speed hint captures the rated/unloaded figure and the field is SCORING. Adjudicated challenge:CONFIRM. DB's 2.2 matches neither the laden 2.0 nor the unladen 3.0.

- **`max_payload`** (KO, kg) — *SAFELOG M4 core* → DB row(s) `SAFELOG AGV M4`  
  DB **200.0** vs datasheet **300** (merge provenance: `opus`)  
  **Source:** SAFELOG_Datasheet_M4-core_EN.pdf p.3 'Topload level (kg) 300'; SAFELOG_Datasheet_M4-lift_EN.pdf p.3 'Topload level (kg) 1,000'; SAFELOG_Datasheet_M4-tow_EN.pdf p.3 'Topload level (kg) 1,500'  
  **Verdict: VARIANT-SPLIT-NEEDED — M4 core = 300 kg; M4 lift = 1000 kg; M4 tow = 1500 kg. DB's single 200 kg row matches none of them.**  
  Three separate datasheets document three top-module configurations of one chassis. The DB collapses them into one row carrying 200 kg — a value none of the three sheets prints. If the row must stay single, the AP0 hint (heaviest stated) gives 1500; but the right fix is a split.

- **`max_payload`** (KO, kg) — *SAFELOG M4 lift* → DB row(s) `SAFELOG AGV M4`  
  DB **200.0** vs datasheet **1000** (merge provenance: `opus`)  
  **Source:** SAFELOG_Datasheet_M4-lift_EN.pdf p.2 'the mobile robot can lift standard market racks, elevated pallets and load carriers weighing up to 1,000 kg'; p.3 'Topload level (kg) 1,000'  
  **Verdict: VARIANT-SPLIT-NEEDED — 1000 kg for the lift configuration**  
  Stated twice (prose + spec row). Same split as M4 core.

- **`navigation_type`** (CONTEXT) — *SAFELOG M4 tow* → DB row(s) `SAFELOG AGV M4`  
  DB **Natural Feature (SLAM)** vs datasheet **Inductive Loop, Magnetic Tape, Vision** (merge provenance: `opus`)  
  **Source:** SAFELOG_Datasheet_M4-tow_EN.pdf p.3 navigation row; same cross-sheet comparison as S3 tow  
  **Verdict: RESOLVED — Union [Natural Feature (SLAM), Inductive Loop, Magnetic Tape, Vision]**  
  Identical to S3 tow.

- **`navigation_type`** (CONTEXT) — *SAFELOG S3 tow* → DB row(s) `SAFELOG AGV S3`  
  DB **Natural Feature (SLAM)** vs datasheet **Inductive Loop, Magnetic Tape, Vision** (merge provenance: `opus`)  
  **Source:** SAFELOG_Datasheet_S3-tow_EN.pdf p.3 navigation row; cf. the eight other SAFELOG sheets where SLAM was retained and the extra methods merely ADDED  
  **Verdict: RESOLVED — Union [Natural Feature (SLAM), Inductive Loop, Magnetic Tape, Vision]**  
  The two 'tow' extractions dropped SAFELOG's standard LiDAR (LLS) localisation while the ten other SAFELOG entries in the same batch kept it as an extend. That asymmetry is an extraction gap, not a product difference — removing SLAM would turn a LiDAR-localising AGV into a purely infrastructure-bound one.

- **`max_payload`** (KO, kg) — *SAFELOG X1 core* → DB row(s) `SAFELOG AGV X1`  
  DB **1200.0** vs datasheet **1500** (merge provenance: `opus`)  
  **Source:** SAFELOG_Datasheet_X1-core_EN.pdf p.3 'Topload level (kg) 1.500'  
  **Verdict: RESOLVED — 1500 kg — DB 1200 is unsupported**  
  European decimal point: '1.500' = 1500 kg. K.O. field understated by 300 kg.

- **`max_payload`** (KO, kg) — *SAFELOG XS1 IntelliCart* → DB row(s) `SAFELOG AGV XS1`  
  DB **85.0** vs datasheet **50** (merge provenance: `opus`)  
  **Source:** SAFELOG_Datasheet_XS1-IntelliCart_EN.pdf p.2 'With a load capacity of up to 50 kg'; p.3 'Topload (kg) 50'; p.3 footnote 4 'load of 50 kg, 80% driving share'  
  **Verdict: RESOLVED — 50 kg — DB 85 is unsupported**  
  Stated three times in one document. DB's 85 kg OVERSTATES a K.O. field — this picking cart would win tenders it cannot serve.

- **`max_speed`** (SCORING, m/s) — *SAFELOG XS1 IntelliCart* → DB row(s) `SAFELOG AGV XS1`  
  DB **4.0** vs datasheet **3.0** (merge provenance: `opus`)  
  **Source:** SAFELOG_Datasheet_XS1-IntelliCart_EN.pdf p.3 'Speed (m/s) 0.1 – 3.0'  
  **Verdict: RESOLVED — 3.0 m/s — DB 4.0 is unsupported**  
  Printed range tops at 3.0.


### ek robotics — 6 conflicts

- **`lifting_height`** (KO, mm) — *ek robotics COMPACT MOVE (series)* → DB row(s) `ek robotics COMPACT MOVE CB 25`  
  DB **5500** vs datasheet **8000** (merge provenance: `opus`)  
  **Source:** NMR_ek_robotics_COMPACT_MOVE_Broschuere_de.pdf spec table, Hub row  
  **Verdict: UNRESOLVED — DB 5500 (CB 25) vs series-level 8000 mm**  
  Same series-fan risk as the payload. Whether 8000 mm is a CB 25 mast option or another model's figure could not be settled from the extracted table. Needs a per-column re-read.

- **`max_payload`** (KO, kg) — *ek robotics COMPACT MOVE (series)* → DB row(s) `ek robotics COMPACT MOVE CB 10`  
  DB **1000.0** vs datasheet **2500** (merge provenance: `opus`)  
  **Source:** NMR_ek_robotics_COMPACT_MOVE_Broschuere_de.pdf spec table 'COMPACT MOVE CB 10 | CB 25'  
  **Verdict: RESOLVED — DB is correct — 2500 kg belongs to CB 25, not CB 10**  
  Mapping artefact, not a data conflict: a series-level read was fanned onto both DB rows, pushing the CB 25 payload onto the CB 10 row. The CB 10 is a 1000 kg machine as stored.

- **`navigation_type`** (CONTEXT) — *ek robotics COMPACT MOVE (series)* → DB row(s) `ek robotics COMPACT MOVE CB 10`  
  DB **Laser Reflector, Natural Feature (SLAM)** vs datasheet **Contour, Laser Reflector** (merge provenance: `opus`)  
  **Source:** NMR_ek_robotics_COMPACT_MOVE_Broschuere_de.pdf / NMR_ek_robotics_X_MOVE_Broschuere_de.pdf navigation row ('Kontur-' / 'Laser-' navigation)  
  **Verdict: RESOLVED — Union [Contour, Laser Reflector, Natural Feature (SLAM)]**  
  The recurring Contour/SLAM labelling overlap: the vendor prints 'Kontur', the DB stores SLAM, and both describe the same map-based localisation. Additive; remove nothing. Affects CB 10, X MOVE 600 and X MOVE 1200.

- **`lifting_height`** (KO, mm) — *ek robotics VARIO MOVE (series)* → DB row(s) `ek robotics VARIO MOVE CB`  
  DB **5000** vs datasheet **5250** (merge provenance: `opus`)  
  **Source:** NMR_ek_robotics_VARIO_MOVE_Broschuere_de.pdf spec table, Hub row  
  **Verdict: RESOLVED — 5250 mm (datasheet); DB 5000 is a rounding**  
  Low materiality (5%), but prefer the printed figure.

- **`navigation_type`** (CONTEXT) — *ek robotics X MOVE 600 / X MOVE 1200* → DB row(s) `ek robotics X MOVE 600 + ek robotics X MOVE 1200`  
  DB **Laser Reflector, Natural Feature (SLAM)** vs datasheet **Contour, Laser Reflector** (merge provenance: `None`)  
  **Source:** NMR_ek_robotics_COMPACT_MOVE_Broschuere_de.pdf / NMR_ek_robotics_X_MOVE_Broschuere_de.pdf navigation row ('Kontur-' / 'Laser-' navigation)  
  **Verdict: RESOLVED — Union [Contour, Laser Reflector, Natural Feature (SLAM)]**  
  The recurring Contour/SLAM labelling overlap: the vendor prints 'Kontur', the DB stores SLAM, and both describe the same map-based localisation. Additive; remove nothing. Affects CB 10, X MOVE 600 and X MOVE 1200.

- **`top_module_type`** (SCORING) — *ek robotics X MOVE 600 / X MOVE 1200* → DB row(s) `ek robotics X MOVE 1200`  
  DB **Custom** vs datasheet **Lift, Roller** (merge provenance: `None`)  
  **Source:** NMR_ek_robotics_X_MOVE_Broschuere_de.pdf X MOVE 1200 spec block, Lastaufnahme row  
  **Verdict: RESOLVED — Union [Custom, Lift, Roller]**  
  The brochure names two concrete top modules; the DB's generic 'Custom' is not wrong, just unspecific. SCORING field — additive.


### Hikrobot — 6 conflicts

- **`max_speed`** (SCORING, m/s) — *Hikrobot F3-1500* → DB row(s) `Hikrobot F3-1500`  
  DB **2.1** vs datasheet **1.5** (merge provenance: `opus`)  
  **Source:** F3-1500_flyer_eng_cemat_v2.pdf F3-1500 spec table, travel-speed row; cf. AGV_Brochure_(Full_Version)_ENG_2026Q2-V1_READ_updated_16_Jun_2026.pdf F3-series pages  
  **Verdict: UNRESOLVED — DB 2.1 vs flyer 1.5 m/s**  
  A 40% gap between two Hikrobot documents for the same model code. Hikrobot prints every speed in mm/s in the full catalog and in m/s in the CeMAT flyer, so a unit-handling difference is plausible — needs both rows read side by side.

- **`min_aisle_width`** (KO, mm) — *Hikrobot F3-1500* → DB row(s) `Hikrobot F3-1500`  
  DB **2100** vs datasheet **2213** (merge provenance: `opus`)  
  **Source:** F3-1500_flyer_eng_cemat_v2.pdf F3-1500 spec table, aisle row  
  **Verdict: UNRESOLVED — DB 2100 vs flyer 2213 mm**  
  Same two-document problem; 5% apart on a K.O. field.

- **`vehicle_width`** (CONTEXT, mm) — *Hikrobot F3-1500* → DB row(s) `Hikrobot F3-1500`  
  DB **870** vs datasheet **863** (merge provenance: `opus`)  
  **Source:** F3-1500_flyer_eng_cemat_v2.pdf F3-1500 spec table, width row  
  **Verdict: RESOLVED — 863 mm (flyer); DB 870 is a rounding**  
  Immaterial (0.8%), CONTEXT field.

- **`lifting_height`** (KO, mm) — *Hikrobot F5-1600* → DB row(s) `Hikrobot F5-1600`  
  DB **3000** vs datasheet **4500** (merge provenance: `opus_only`)  
  **Source:** AGV_Brochure_(Full_Version)_ENG_2026Q2-V1_READ_updated_16_Jun_2026.pdf F5-1600 spec table, lift-height row  
  **Verdict: RESOLVED — Same reference-mast vs max-mast pattern as VisionNav — do not overwrite**  
  DB 3000 / catalog 4500 reproduces the exact pair seen across seven VisionNav P/E-series products. Treat as the same unruled mast-reference convention rather than an error.

- **`max_payload`** (KO, kg) — *Hikrobot F5-1600* → DB row(s) `Hikrobot F5-1600`  
  DB **1600.0** vs datasheet **1350.0** (merge provenance: `opus_only`)  
  **Source:** AGV_Brochure_(Full_Version)_ENG_2026Q2-V1_READ_updated_16_Jun_2026.pdf F5-1600 spec table, rated-load row  
  **Verdict: RESOLVED — 1350 kg — DB 1600 echoes the model number**  
  Confirmed in the 2026-08-19 closeout alongside VisionNav VNP20. max_payload is KO_IF_LT, so a 250 kg overstatement admits the vehicle to tenders it cannot serve.

- **`max_speed`** (SCORING, m/s) — *Hikrobot Q7-1000D* → DB row(s) `Hikrobot Q7-1000D`  
  DB **1.8** vs datasheet **2.0** (merge provenance: `sonnet_only`)  
  **Source:** QF Pallet-handling Mobile Robot_Flyer_2024 Cemat_eng.pdf, Q7-1000D column, travel-speed row  
  **Verdict: RESOLVED — 2.0 m/s**  
  AP0 max_speed hint takes the top figure; SCORING field, no K.O. downside.


### Magazino — 1 conflicts

- **`min_turning_radius`** (KO, mm) — *SOTO* → DB row(s) `SOTO`  
  DB **1550** vs datasheet **0** (merge provenance: `omnidirectional_pivot_rule`)  
  **Source:** download-technical-data-amr-soto-data.pdf  
  **Verdict: RESOLVED — 0 mm — per the already-agreed omnidirectional_pivot_rule**  
  Pre-settled and explicitly out of scope for re-litigation. SOTO pivots on the spot, so the AP0 turning RADIUS is 0; the DB's 1550 mm is a footprint-derived turning CIRCLE. Recorded for completeness only.


### Stäubli — 1 conflicts

- **`omnidirectional_movement`** (SCORING) — *Stäubli PF3* → DB row(s) `Stäubli PF3`  
  DB **True** vs datasheet **False** (merge provenance: `opus`)  
  **Source:** Mobile-Robotics-portfolio-EN.pdf (portfolio page listing 'PF3' and 'PF3 OMNI' as distinct models); PF3-data-sheet-EN.pdf  
  **Verdict: RESOLVED — False for PF3; True belongs to the separate PF3 OMNI**  
  The existence of a separately-named 'PF3 OMNI' model is itself the evidence that the base PF3 is not omnidirectional. Also a variant gap: PF3 OMNI has no DB row (staged as new in this pass).


---

## DB-cleanup items (logged separately — not value conflicts)

### A. Wrong-scope values

**331 DB cells** hold a value for a field whose AP0 `scope` does not match that row's `product_type` (e.g. an AMR-only field populated on a Forklift AGV row). Confirmed as a known DB defect class, not an extraction error. Breakdown:

| Field scope | Row product_type | Cells |
|---|---|---|
| `Logistics:AGV:Forklift` | Mobile AMR | 116 |
| `Logistics:AGV:AMR` | Forklift AGV | 97 |
| `Logistics:AGV:Tugger` | Forklift AGV | 53 |
| `Logistics:AGV:Tugger` | Mobile AMR | 27 |
| `Logistics:AGV:Forklift` | Tugger AGV | 23 |
| `Logistics:AGV:AMR` | Tugger AGV | 15 |

Most-affected fields: `grid_required` (75), `vna_capable` (66), `stacking_capability` (60), `min_aisle_width` (37), `route_programming` (18), `route_type` (18), `workflow_capability` (11), `rack_pin_compatible` (10), `lifting_height` (8), `picking_mechanism` (5), `intersection_management` (4), `free_lift_open_closed_pallet` (3), `rotation_capable` (3), `drop_accuracy_lat` (3), `turning_radius` (3).

By company: Linde Material Handling (40), Toyota Material Handling Europe (28), VisionNav Robotics (28), DS Automotion GmbH (27), STILL GmbH (27), Omron Mobile Robotics (26), KIVNON Logística S.L. (21), ek robotics (19), AGILOX Services GmbH (16), Jungheinrich AG (15), Geek+ (Geekplus Technology Co.) (14), Grenzebach Maschinenbau GmbH (14), Balyo (12), Hikrobot (11), KNAPP AG (9), Mobile Industrial Robots A/S (MiR) (9), SAFELOG GmbH (9), Stäubli (5), Magazino (1).

The full per-cell list is in `docs/datasheet_db_status_final.json` → `db_cleanup_wrong_scope_values.cells`. It is deliberately NOT staged for import — these cells need deleting or the rows need re-typing, both of which are Airtable-side decisions.

### B. Values outside AP0 `allowed_values`

An allowed-values audit of the whole DB (not just the 146 matched rows) found **66 distinct invalid tokens**. Several of the 'conflicts' above are purely this: DB and datasheet agree on the substance but the DB token carries a research annotation. Highlights:

| Field | Invalid token | Rows | Note |
|---|---|---|---|
| `service_coverage` | EU | 266 | AP0 allows ISO country codes + `Global`/`None`; `EU` is not among them. Affects **every** product row — likely an Airtable option that predates the AP0 country list. |
| `safety_standard` | ISO 3691-4 (verify) | 17 | Annotation suffix; substance matches `ISO 3691-4`. |
| `load_type` | Pallet EUR/ISO | 12 | One cell holding two allowed values instead of two piped values. |
| `load_type` | None | 9 | `None` is not an allowed `load_type` value. |
| `safety_standard` | None (CE/TÜV marks only) | 7 | KIVNON rows. |
| `fleet_management_system` | Proprietary (X-SWARM) / (iGo TCS) / (T-ONE) / (RCS 2000) / … | 31 | Nine different `Proprietary (<product name>)` variants across 9 suppliers; all should be `Proprietary` with the product name in a note. |
| `safety_coverage` | Full 3D (360° + 3D sensors) | 5 | DS Automotion ARNY ×4 + AGILOX OFL — and see the ARNY conflict above, where the substance is also wrong. |
| `load_type` | Custom Carrier (dolly) / (paper reels) / (shelf/rack) | 3 | Annotation suffixes on `Custom Carrier`. |
| `navigation_type` | Wire | 1 | STILL MX-X iGo — `Wire` belongs to the `guidance` field, not `navigation_type`. |
| `cleanroom_class` | ISO 4 (optional) / ISO 1-9 | 2 | MiR250 and Magazino SOTO. |
| `top_module_type` | Pallet Lift | 2 | MiR1350, MiR600 — nearest allowed value is `Lift`. |
| `coupling_type` | Automatic (verify) | 1 | Balyo TUGGY — see the conflict entry above. |
| `fork_spread` | Auto (optional) | 1 | AGILOX OCF — see the conflict entry above. |

### C. Structural / variant-split items

Cases where one DB row is doing the work of two or more documented products. These are not conflicts to resolve but records to split before import:

- `Linde C-MATIC` — one row for C-MATIC 10 (1000 kg) and C-MATIC 15 (1500 kg), `DE_tb_c_matic_8925_dt_e_1025_view.pdf` p.2 rows 1.2/1.5.
- `Linde R-MATIC k (R-MATIC 17 k)` — the sheet documents 12 k / 17 k / 25 k (1.07 / 1.55 / 2.33 t), `DE_tb_r_matic_k_5190_dt_a_0425_view.pdf` p.5 row 1.5. Only the 17 k exists in the DB.
- `Toyota Staxio SAE160 Autopilot` — one row for both the DX Tele mast (2350 mm) and the TX Hi-Lo mast (4700 mm), `sae160-technicky-list.pdf` p.2/p.3.
- `SAFELOG AGV M4` — one row for three documented top-module configurations: core 300 kg, lift 1000 kg, tow 1500 kg (three separate SAFELOG datasheets, each p.3 'Topload level').
- `SAFELOG AGV L2` / `AGV S3` / `AGV X1` — likewise carry 2–3 documented configurations each (core/lift/tow/spin), all mapped onto one row.
- `AGILOX ONE` — single-scissor (1000 kg / 500 mm) and double-scissor (750 kg / ~1000 mm) configurations, `Agilox One.pdf` p.1.
- `AGILOX ODM 600/800` — one row named for two models; the merged dataset holds separate ODM 600 and ODM 800 entries.
- `LOWY / LOWY HD` — one row for two separately-documented Balyo machines with different aisle widths.
- `Geek+ F-Series (F20MT Smart Forklift)` — generic row that in practice documents F20MT; see the F12ML/F20MT contamination above.
- `Stäubli PF3 OMNI` — no DB row at all (staged `new`); its existence is the evidence that base PF3 is not omnidirectional.
- `AMADEUS Low` / `AMADEUS Counter` — the AMADEUS series read must NOT be fanned onto these two; the sheet marks both 'Technische Details abweichend' (`AMADEUS-OnePager-2025-DE.pdf` p.2).
- `AMY Deck` / `AMY Lift` — `Amy-FourPager-2025-DE.pdf` p.3 prints one dimension block for the family; the DB's per-variant footprints are more specific.

### D. Product-matching notes

- **ek robotics VNA MOVE 1350 / 1500** — the task brief expected these to map onto existing DB rows, but the live DB holds **no VNA MOVE rows at all** (ek robotics has 7 products: COMPACT MOVE CB 10/CB 25, FAST MOVE, VARIO MOVE CB, X MOVE 300/600/1200). Both VNA MOVE entries are therefore staged `new`, not `enrich`.
- **DS Automotion OSCAR** — handled as instructed: the combined `OSCAR spin 180 / OSCAR spin 360 / OSCAR omni` entry was applied to all three existing DB rows individually. Note the dataset *also* contains standalone `OSCAR Spin 360` and `OSCAR Omni` entries, which reconcile to the same rows with nothing left to add.
- **ek robotics COMPACT MOVE (series)** — applied to `COMPACT MOVE CB 10` and `CB 25` individually, as instructed.
- **VisionNav suffixed codes** — `VNSL14(V)-07`, `VNSL14(VL)-07` etc. were matched to the base DB row (`VisionNav VNSL14`) by stripping the `(V)`/`(VL)`/`(VM)` navigation-package marker and the trailing `-NN` epoch, consistent with how both earlier passes staged them. `VNR14`, `VNR25`, `VNT20`, `VNL14`, `VNL16`, `VNQ40`, `VNQ60`, `VNP15A` have no base row and are staged `new`.
- **Grenzebach L1200S-Li** — the `L1200S-Li` and `L1200S` merged entries hold byte-identical field values from the same PDF; treated as one product mapped to `Grenzebach L1200S`, which is why their three conflicts are duplicates of each other.
- **Enabled Robotics ApS** — the company does not exist in the DB at all; both products are `new` and would require a new Company record.
- **Magazino `Jungheinrich SOTO`** — staged `new`; per the 2026-08-06 rebadge resolution this should become a separate Jungheinrich Product row sharing the SOTO base model, and Jungheinrich currently has no SOTO row.
- **KNAPP `Open Shuttle 50`** — staged `new` (payload 120 kg, 762×752 mm; distinct from `Open Shuttle 50 ASG` at 50 kg). Separately, the DB's generic `Open Shuttle` row (120 kg, no dimensions) looks like a duplicate of `KNAPP Open Shuttle 100` (also 120 kg) — flagged for review, not touched.

---

## Additive multi-select changes (`extend`) — no adjudication needed

28 cases where the datasheet set strictly contains the DB set. These are counted as `enrich`, not conflict.

- `battery_type` — LOWY / LOWY HD: Li-Ion → Lead-Acid, Li-Ion
- `battery_type` — LOWY CB: Li-Ion → Lead-Acid, Li-Ion
- `load_detection` — REACHY: Camera/Vision, Laser/LiDAR profiling → Barcode/DataMatrix, Camera/Vision, Laser/LiDAR profiling
- `battery_type` — TUGGY: Li-Ion → Lead-Acid, Li-Ion
- `load_type` — AMADEUS Low: Pallet EUR, Pallet ISO → Custom Carrier, Pallet EUR, Pallet ISO
- `load_type` — ARNY Mono: Pallet EUR, Pallet ISO → Custom Carrier, Pallet EUR, Pallet ISO
- `load_type` — ARNY Duplex: Pallet EUR, Pallet ISO → Custom Carrier, Pallet EUR, Pallet ISO
- `load_type` — ARNY Triplex: Pallet EUR, Pallet ISO → Custom Carrier, Pallet EUR, Pallet ISO
- `load_type` — ARNY HD Triplex: Pallet EUR, Pallet ISO → Custom Carrier, Pallet EUR, Pallet ISO
- `battery_type` — LUCY: Li-Ion → Lead-Acid, Li-Ion
- `navigation_type` — SALLY Kurier: Contour → Contour, Natural Feature (SLAM)
- `load_detection` — Geek+ F-Series (F20MT Smart Forklift): Laser/LiDAR profiling → Camera/Vision, Laser/LiDAR profiling
- `navigation_type` — Grenzebach OL1200S: Natural Feature (SLAM) → Contour, Natural Feature (SLAM)
- `load_detection` — Hikrobot F3-1500: Camera/Vision → Camera/Vision, Laser/LiDAR profiling
- `navigation_type` — Hikrobot F3-1500: Natural Feature (SLAM) → Contour, Natural Feature (SLAM)
- `navigation_type` — Hikrobot Q7-1000D: Natural Feature (SLAM) → Natural Feature (SLAM), QR/DM Code, Vision
- `navigation_type` — Hikrobot Q7-1000E: Natural Feature (SLAM) → Natural Feature (SLAM), QR/DM Code, Vision
- `safety_standard` — MiR1350: ISO 3691-4 → ANSI/ITSDF B56.5, ISO 3691-4
- `safety_standard` — MiR600: ISO 3691-4 → ANSI/ITSDF B56.5, ISO 3691-4
- `navigation_type` — SAFELOG AGV L2: Natural Feature (SLAM) → Inductive Loop, Magnetic Tape, Natural Feature (SLAM), QR/DM Code
- `navigation_type` — SAFELOG AGV L2: Natural Feature (SLAM) → Inductive Loop, Magnetic Tape, Natural Feature (SLAM), QR/DM Code
- `navigation_type` — SAFELOG AGV M4: Natural Feature (SLAM) → Inductive Loop, Magnetic Tape, Natural Feature (SLAM), Vision
- `navigation_type` — SAFELOG AGV M4: Natural Feature (SLAM) → Inductive Loop, Magnetic Tape, Natural Feature (SLAM), Vision
- `navigation_type` — SAFELOG AGV S3: Natural Feature (SLAM) → Inductive Loop, Magnetic Tape, Natural Feature (SLAM), Vision
- `navigation_type` — SAFELOG AGV X1: Natural Feature (SLAM) → Inductive Loop, Magnetic Tape, Natural Feature (SLAM), QR/DM Code, Vision
- `navigation_type` — SAFELOG AGV X1: Natural Feature (SLAM) → Inductive Loop, Magnetic Tape, Natural Feature (SLAM), QR/DM Code, Vision
- `navigation_type` — SAFELOG AGV X1: Natural Feature (SLAM) → Inductive Loop, Magnetic Tape, Natural Feature (SLAM), QR/DM Code, Vision
- `navigation_type` — ek robotics COMPACT MOVE CB 25: Laser Reflector → Contour, Laser Reflector

## Datasheet-is-a-subset cases — deliberately NOT conflicts

30 cases where the datasheet names fewer values than the DB already holds. Under `Blank ≠ Zero` a silent datasheet is not a denial, so no action is proposed. Examples:

- `load_type` — AGILOX ONE: DB Custom Carrier, Half-Euro, Pallet EUR, Pallet ISO, Plastic, Tote ⊃ datasheet Custom Carrier, Half-Euro, Pallet EUR, Pallet ISO, Tote
- `workflow_capability` — AGILOX ONE: DB Goods-to-Person, Transport ⊃ datasheet Transport
- `workflow_capability` — AGILOX ONE: DB Goods-to-Person, Transport ⊃ datasheet Transport
- `load_detection` — LOWY / LOWY HD: DB Camera/Vision, Laser/LiDAR profiling ⊃ datasheet Camera/Vision
- `navigation_type` — LOWY / LOWY HD: DB Natural Feature (SLAM), Vision ⊃ datasheet Natural Feature (SLAM)
- `station_applications` — LOWY / LOWY HD: DB Conveyor, Dock, Floor, Machine cell, Standard rack, Workstation ⊃ datasheet Conveyor, Floor, Machine cell
- `navigation_type` — LOWY CB: DB Natural Feature (SLAM), Vision ⊃ datasheet Natural Feature (SLAM)
- `load_detection` — LOWY / LOWY HD: DB Camera/Vision, Laser/LiDAR profiling ⊃ datasheet Camera/Vision
- `navigation_type` — LOWY / LOWY HD: DB Natural Feature (SLAM), Vision ⊃ datasheet Natural Feature (SLAM)
- `station_applications` — LOWY / LOWY HD: DB Conveyor, Dock, Floor, Machine cell, Standard rack, Workstation ⊃ datasheet Conveyor, Floor, Machine cell
- `integration_capability` — REACHY: DB ERP, MES, MQTT, Modbus, OPC-UA, REST API, SAP, WMS ⊃ datasheet ERP, WMS
- `load_type` — REACHY: DB Pallet EUR, Pallet ISO ⊃ datasheet Pallet EUR

---

## Open questions this pass could not close

- **`lifting_height`: VDI 4.4 *Hub* vs marketed *Einlagerungshöhe* vs mast-table maximum.** Linde L-MATIC AC k prints all three in one document (2844 / 3800 / 4144 mm). 15 conflicts across Linde, VisionNav, Hikrobot and Toyota hinge on this. Still unruled.
- **`Contour` vs `Natural Feature (SLAM)`.** The AP0 hint normalises 'contour-based' → SLAM on the tender side, which makes the supplier-side `Contour` value unreachable. Vendors print both terms for the same thing. 14 conflicts; handled additively here, but a ruling would remove the whole class.
- **`min_aisle_width` when the sheet prints several Ast rows** (pallet size × orientation, or stacking vs turning aisle). The convention used here — smallest printed working aisle — is still informal.
- **`vehicle_width` on reach trucks**: VDI 4.21 (chassis) vs 4.22 (over support arms incl. scanners) differ by 300 mm on Toyota RAE250. AP0 has one field.
- **Magnet-POINT navigation** (DS Automotion AMADEUS Grip: 'Referenzmagneten') has no AP0 value; it is currently forced into `Magnetic Tape`, a different technology.
- **`fleet_management_system` is single-select** but vendors are routinely both proprietary and VDA 5050 / open-API capable (Grenzebach, MiR, DS Automotion). This drives three of the conflicts above and 31 of the invalid-token rows.

---

*Generated by the AGV datasheet reconciliation pass, 2026-08-21. Staged for Tech Lead review only — no Airtable writes, no DB writes, no file moves.*