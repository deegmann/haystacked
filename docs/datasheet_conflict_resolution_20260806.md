# Datasheet Conflict Resolution — 2026-08-06 (dedicated re-examination pass)

**Scope:** every `db_status: conflict` item, the two "Pending clarification" items, the VisionNav R-series
reconciliation flag, and the DS Automotion OSCAR `min_ground_clearance` data-quality flag, as recorded in
`docs/datasheet_coverage_report.md` across all five 2026-08-06 ingestion runs.

**Method:** each cited source PDF was re-opened from `Datasheets/AGV_AMR/Analysed/` at the cited page(s) and
re-read — text extraction *plus* page-image rendering wherever table structure, footnote-marker placement or
column grouping was load-bearing. Adjacent pages, companion documents in the same pair, and OEM-sibling
datasheets already in `Analysed/` were used as cross-references. A read-only `sqlite3` query against
`data/haystacked.db` was used to re-confirm current DB values (no sync, no writes).

**Explicitly out of scope** (Tech-Lead policy/structure decisions, untouched here): ek robotics↔NEURA naming,
Stäubli PF3/PF3-OMNI product identity, KNAPP "Open Shuttle"=="Open Shuttle 50" mapping, and the general
radius/diameter AP0 semantics ruling.

**Nothing was written to Airtable. No DB value was changed.** All of the below are staged recommendations.

## Verdict summary

| Verdict | Count |
|---|---|
| RESOLVED | 17 |
| VARIANT-SPLIT-NEEDED | 2 |
| UNRESOLVED — needs manual/external research | 3 |
| **Total items** | **22** |

**Correction by Tech Lead (2026-08-06):** the agent's own tally here originally read 18/2/2 — off by one against
the actual per-item verdicts below (items 2, 14, and 16 are each explicitly headed UNRESOLVED, not 2). Fixed to
17/2/3; the per-item sections themselves were not affected, only this summary table.

Of the 17 RESOLVED, **4 turned out to be false positives** where the DB was already correct and the earlier
pass's flag was the error (items 6, 9, 12, 13). This is worth noting for calibration: a flagged conflict is
not automatically a DB defect.

---

## 1. Toyota RAE160 — `lifting_height` — **RESOLVED**

- **Original conflict:** DB = 11000 mm vs datasheet footnote "Max lift height 9500mm". Source: `747505-040.pdf` p.3.
- **Tech Lead working hypothesis:** correct value is 10000 mm; 11176 mm is total vehicle height with mast
  extended, not lift height; DB's 11000 may be a slightly-off copy of that total height.
- **Verdict: hypothesis CONFIRMED on both counts.** Recommended value: **10000 mm**.

**Reasoning.** Page 3 carries two separate tables and the earlier pass conflated them.

1. The **9500 mm footnote does not apply to RAE160 at all.** The "Battery dependent dimensions" table groups
   its 13 columns by model — RAE160 owns the first 4 (battery compartments 275¹⁾, 347, 419, 491; confirmed by
   the `4.35 Turning radius` row which reads 1715 ×4, then 1845 ×5 for RAE200, then 1903 ×4 for RAE250).
   Footnote marker ²⁾ ("Max lift height 9500mm") appears only on RAE200's `347²⁾ 419²⁾ 491²⁾` and RAE250's
   `419²⁾ 491²⁾` cells. The only footnote touching a RAE160 cell is ¹⁾ ("Max lift height 7500mm") on the
   275 mm battery compartment. Verified by page-image rendering of the marker positions, not text order.
2. The separate **"Mast dimensions" table** has its own RAE160 / Triplex Hi-Lo-B block whose `Lift height h₂₃`
   row runs 4850 / 5400 / 5700 / 6300 / 7000 / 7500 / 8000 / 8500 / 9000 / 9500 / **10000** mm. 10000 mm is the
   documented maximum lift height for RAE160.
3. In the same RAE160 block, row `4.5 Height, mast extended h₄` ends at **11176 mm** — this is the
   Tech Lead's suspected total-height figure, confirmed. It is a *vehicle* height, not a lift height, and the
   drawing on the same page labels h₄ at the top of the extended mast, distinct from h₂₃.
4. 11000 mm appears nowhere on the page in any row. It is neither a documented mast option nor an exact copy of
   11176 — but it sits within rounding distance of the h₄ total height and far from any h₂₃ value, which is
   consistent with the Tech Lead's "rounded copy of the total-height figure" reading.

**Secondary note (no action required, flagged for transparency):** the table also prints row `4.4 Lift h₃`
ending at 9945 mm. Per VDI 2198, h₃ is the mast stroke and h₂₃ the lift height including fork height; the
round 10000 mm h₂₃ figure is the one manufacturers publish as "Hubhöhe" and is the correct match for AP0's
`lifting_height` ("the height the forks travel"). Recommending 10000, not 9945.

---

## 2. Toyota Reflex RAE250 — `min_aisle_width` — **UNRESOLVED (needs manual/external research)**

- **Original conflict:** DB = 3071 mm vs no exact match in the aisle-width matrix (range 2876–3336 mm).
  Source: `747505-040.pdf` p.4 ("Aisle width Auto mode").
- **Verdict: UNRESOLVED.** The document cannot settle this.

**Reasoning.** I read every cell of the RAE250 block of the p.4 matrix from the rendered page image. RAE250 has
16 documented values across a 4-axis configuration space (mast type C/D × battery compartment 419/491 ×
rotation mode "Rotate on point"/"Rotate with radius 400 mm" × load size 800×1200 / 1000×1200 / 1200×800 /
1200×1000):

```
Triplex hilo-C, 419:  2886 3023 3081 3127  |  2876 3053 3195 3212
Triplex hilo-C, 491:  2932 3078 3147 3190  |  2938 3119 3266 3282
Triplex hilo-D, 419:  2921 3065 3132 3175  |  2924 3104 3249 3265
Triplex hilo-D, 491:  2970 3121 3198 3239  |  2987 3171 3321 3336
```

**3071 does not appear** in the RAE250 block, nor anywhere else in the table (I checked all 104 cells; the
nearest values anywhere on the page are 3069, 3072 and 3067, all belonging to RAE160/RAE200 rows).

This is not a "wrong number" problem — `min_aisle_width` genuinely has no single authoritative value for this
product in this document; it is a 4-axis matrix with no corresponding AP0 axis. Two independently plausible
readings exist and the document gives no basis to choose:

- **Best case** (what a vendor usually publishes as "min aisle width"): 2876 mm.
- **Conservative / worst case** (what a `KO_IF_GT` field arguably wants, so the supplier is never wrongly admitted): 3336 mm.

**Strongest lead for the manual pass:** the standard EUR-pallet configuration (load 1200 × 800, rotate on point,
smallest mast C, smallest battery 419) gives **3081 mm** — within 10 mm of the DB's 3071. That is close enough
to suggest the DB value came from *this exact configuration cell* in a different revision of this datasheet,
rather than being a random error. If that is confirmed, the DB value is substantively fine and only 10 mm stale.

**Needed:** confirm against a different/newer Toyota RAE250 datasheet or Toyota's published Aₛₜ figure which
configuration the 3071 mm was taken from, then decide the project-wide convention for collapsing an
aisle-width configuration matrix into one `min_aisle_width` value. That convention decision is a Tech Lead call,
not a document question.

---

## 3. VisionNav VNR16 — `lifting_height` + `min_aisle_width` — **RESOLVED**

- **Original conflict:** `lifting_height` DB = 5500 mm vs datasheet max 9455 mm; `min_aisle_width` DB = 3250 mm
  vs datasheet 3150 mm. Source: `1688618048.pdf` p.3 (headline) / p.4 (table).
- **Pending-clarification hypothesis:** a possible extra non-SLAM 11455 mm VNR16 variant; and a request to
  re-check which model 9455 / 11455 actually belong to.
- **Verdict:** model attribution **CONFIRMED CORRECT**; the extra-variant hypothesis is **REFUTED**.
  Recommended values: **`lifting_height` = 9455 mm**, **`min_aisle_width` = 3150 mm**.

**Reasoning.**

*Attribution.* `1688618048.pdf` is a 6-page, 3-model document: pp.1–2 = VNR14(V)-01 (1.4 T, 8555 mm),
pp.3–4 = VNR16(V)-01 (1.6 T, 9455 mm), pp.5–6 = VNR20(V)-01 (2.0 T, 11455 mm). Each model gets a cover page
with a headline stat block and a spec page with a full table. **9455 mm belongs to VNR16 and 11455 mm to
VNR20** — the earlier pass had it right.

*The extra-variant hypothesis is refuted.* 11455 mm does not appear anywhere on VNR16's two pages. The
confusion is explained by the footnotes: VNR16's and VNR20's footnotes are byte-identical strings
("...triplex mast option with lifting height 5755mm, 7255mm, 8555mm, 9455mm..."), so a text-only pass that
lost page boundaries would see a 9455-capped option list next to an 11455 headline and infer a mismatch.
There is no non-SLAM 11455 mm VNR16 configuration documented.

*Why 9455 and not 5500.* 9455 mm is stated **twice, independently**: as the cover-page headline "9455mm Max.
Lifting Height" (p.3) and as the spec-table row "Max. Lifting Height 9455mm(372.24in)" (p.4). It is also the
top entry of that page's own triplex-mast option ladder (5755 / 7255 / 8555 / 9455). **5500 mm matches no
documented VNR16 figure in any VisionNav document on file** — see item 5 for where it most likely came from.

*Why 3150 and not 3250.* Also stated twice: headline "3150mm Min. Stacking Aisle Width" (p.3) and table
"Min. Stacking Aisle Width (Pallet Size L*W: 1200*1000mm, Across Forks On Width) 3150mm (124.02in)" (p.4).

> **Caveat the Tech Lead should weigh before applying the aisle-width correction.** The DB's VNR16 (3250) and
> VNR20 (3300) values are *each exactly 100 mm above* the datasheet's figure. A consistent offset across two
> independent products is more likely a deliberate convention (e.g. a 100 mm safety margin added at entry time)
> than two coincidental errors. If that margin was intentional project policy, "correcting" to 3150/3200 removes
> it. The `lifting_height` corrections carry no such ambiguity and are safe to apply independently.

---

## 4. VisionNav VNR20 — `lifting_height` + `min_aisle_width` — **RESOLVED**

- **Original conflict:** `lifting_height` DB = 7000 mm vs datasheet 11455 mm (which itself contradicts the
  shared triplex-mast footnote); `min_aisle_width` DB = 3300 mm vs 3200 mm. Source: `1688618048.pdf` p.5 / p.6.
- **Verdict: RESOLVED.** Recommended values: **`lifting_height` = 11455 mm**, **`min_aisle_width` = 3200 mm**.
  The source-document inconsistency flagged by the earlier pass is real but is a demonstrable copy-paste
  artifact in the footnote, not doubt about the headline figure.

**Reasoning.** Four independent lines of evidence, three of them new to this pass:

1. **Stated twice.** 11455 mm appears as the cover headline (p.5) and as the spec-table row "Max. Lifting
   Height 11455mm (450.98in)" (p.6). The imperial conversion is internally consistent (11455 mm = 450.98 in),
   which rules out a digit typo — a typo'd figure would not carry a correctly-converted inch value.
2. **The footnote is provably the stale element, not the headline.** Comparing all three models' footnotes in
   the same document: VNR14's option list ends at 8555 mm and VNR14's max is 8555 mm ✓; VNR16's ends at
   9455 mm and VNR16's max is 9455 mm ✓; VNR20's ends at 9455 mm but VNR20's max is 11455 mm ✗. VisionNav
   demonstrably maintains this list per model and simply failed to extend VNR20's when the taller mast was added.
   The two correct instances establish the pattern that convicts the third.
3. **Physical corroboration from the vehicle dimensions** (read from the p.4/p.6 page images, since the text
   layer interleaves the mm and inch strings unreadably). VNR16's mast-lowered height h₁ = **3920 mm**;
   VNR20's h₁ = **4967 mm**. VNR20 carries a 1047 mm taller lowered mast, which on a triplex is fully
   consistent with the ~2000 mm higher documented lift. A 7000 mm lift height on a 4967 mm lowered triplex mast
   would be physically implausible (it would be lower than VNR16's lift on a much shorter mast).
4. **Cross-manufacturer sanity check.** Balyo's REACHY datasheet (`Reach Truck Gen 2-Black Truck-Datasheet-EN.pdf`
   p.1, also in `Analysed/`) independently publishes **11 455 mm** as a reach-truck max stacking height. The
   figure is a standard mast configuration height in this vehicle class, not an outlier.

Neither 7000 mm nor 3300 mm appears anywhere in the document. VNR20 does not appear in VisionNav's 2022
full-line catalog at all, so the DB values cannot have come from a VNR20-specific figure — see item 5.

---

## 5. VisionNav R-series reconciliation (`1657089341.pdf` pp.12–16) — **VARIANT-SPLIT-NEEDED**

- **Original flag:** the catalog documents four operation-type sub-variants per R-series model code, and prints
  two different spec sets both labelled "VNR16(V)-07" — an internal naming collision. Cited as pp.12–15.
- **Verdict: VARIANT-SPLIT-NEEDED**, plus two corrections to the original flag and one significant new finding
  that also explains items 3 and 4.

### 5a. Correction: the two documents are 13 months apart, and the newer one wins

The filename of each VisionNav PDF is its **publication Unix timestamp** — confirmed three independent ways:

| File | Filename-as-epoch | PDF metadata | Title |
|---|---|---|---|
| `1657089341.pdf` | 2022-07-06 | CreationDate 2022-06-01 | `产品目录-05601` ("product catalog") |
| `1688618048.pdf` | 2023-07-06 | ModDate **2023-07-06** | `VNR14(V)-01-CE` |
| `1685356775.pdf` | 2023-05-29 | CreationDate **2023-05-29** | (VNST20 deck) |

The individual R-series datasheet (`1688618048.pdf`) is **13 months newer** than the full-line catalog and is
the CE-certified revision. Where the two disagree, the 2023 datasheet supersedes the 2022 catalog.

They disagree substantially for the same model codes:

| VNR16(V)-01 | 2022 catalog p.13 | 2023 datasheet p.4 |
|---|---|---|
| Body weight | 3190 kg | 3190 kg (unchanged) |
| Fork lift height h₃ | 8255 mm | 9455 mm |
| Mast options | 7255 / 7955 / 8955 | 5755 / 7255 / 8555 / 9455 |
| Mast lowered h₁ | 3448 mm | 3920 mm |
| Min. stacking aisle | 3192 mm (retracted) | 3150 mm |
| Min. turning radius Wa | 1768 mm | 1800 mm |

This is a genuine product upgrade, not a documentation error: the 472 mm taller lowered mast (3448 → 3920)
maps almost exactly onto the 1200 mm greater lift height (8255 → 9455) at the ~3:1 ratio a triplex mast gives.
**This independently confirms item 3's recommendation of 9455 mm.**

### 5b. New finding: the DB's 5500 / 7000 values are traceable to this catalog, under the wrong model codes

The catalog's p.16 ("R Series — Seated Tiller") table gives:

- **VNR16(V)-07**: weight 3910 kg, Fork Lift Height h₃ = **7000 mm**, Wa 1786 mm
- **VNR25(V)-07**: weight 5238 kg, Fork Lift Height h₃ = **5500 mm**, Wa 2055 mm

The DB holds VNR16 = 5500 mm and VNR20 = 7000 mm. Both figures exist verbatim in this two-column table, but
attached to *different model codes* and in swapped order — the signature of a column-shift error during a
prior data-entry pass. (A secondary candidate: p.15's VNR25(V)-07 mast-option list reads
"Triplex (5500mm、6000mm、7000mm)", which contains both values in one line.) Either way, **neither 5500 nor
7000 is a documented VNR16 or VNR20 lift height in any VisionNav document on file**, which closes items 3 and 4.

### 5c. Correction: the collision is on pp.14/16, and there are *two* collisions, not one

Grepping every model code per page:

| Page | Section header | Model(s) | Weight | h₃ | Wa | Stacking aisle (retracted) |
|---|---|---|---|---|---|---|
| p.13 | R Series (Manual Seated) | VNR14(V)-01 | 3140 kg | 7255 mm | 1665 mm | 3200 mm |
| p.13 | R Series (Manual Seated) | VNR16(V)-01 | 3190 kg | 8255 mm | 1768 mm | 3192 mm |
| p.14 | R Series (Manual Handheld) | **VNR16(V)-07** | 4500 kg | 6300 mm | 1661 mm | 2942 mm |
| p.15 | R Series (Standing Tiller) | **VNR25(V)-07** | 4162 kg | 6500 mm | 2109 mm | 3158 mm |
| p.16 | R Series (Seated Tiller) | **VNR16(V)-07** | 3910 kg | 7000 mm | 1786 mm | 3042 mm |
| p.16 | R Series (Seated Tiller) | **VNR25(V)-07** | 5238 kg | 5500 mm | 2055 mm | 3271 mm |

The collision is between **p.14 and p.16** (the original flag said pp.13/15 — off by one, though the substance
was right: a Manual-Handheld page and a Manual-Seated page both label their vehicle VNR16(V)-07). And
**VNR25(V)-07 collides identically between p.15 and p.16** — a second collision not previously noted.

### 5d. Recommended structure

The `-01` / `-07` suffix is **not** a unique product identifier at VisionNav — it appears to be a
generation/series marker, with *operation type* as an orthogonal axis that the model code does not encode. Two
vehicles with different chassis weights (4500 kg vs 3910 kg) and different lift heights legitimately share the
code VNR16(V)-07. Recommendation:

1. **Do not** create any R-series rows from `1657089341.pdf` on the model code alone.
2. Treat **operation type as part of product identity** and name rows accordingly, e.g.
   `VisionNav VNR16-07 (Manual Handheld)` vs `VisionNav VNR16-07 (Seated Tiller)`, following the project's
   existing disambiguating-name convention (`EKX 516a` / `EKX 516ka`).
3. Keep the existing `VisionNav VNR16` / `VisionNav VNR20` rows bound to the **2023 CE datasheet**
   (`1688618048.pdf`), i.e. the `(V)-01` Manual Seated variants, and apply items 3 and 4's corrections to them.
4. The 2022-catalog `-07` variants are 4 years old and may be discontinued. Recommend confirming they are still
   offered *before* creating rows for them — otherwise this adds four stale products.
5. **Also note:** VNR14(V)-01 is documented in *both* VisionNav files but has **no DB row at all** (confirmed by
   query). It is a straightforward new-product candidate, unrelated to the collision problem.

---

## 6. Magazino SOTO — `min_turning_radius` — **RESOLVED (false positive — DB is correct, no change)**

- **Original conflict:** DB = 1550 mm vs datasheet "Min. Wendekreis 3.100 mm" — flagged as suspiciously exactly 2×.
  Source: `download-technical-data-amr-soto-data.pdf` p.2.
- **Verdict: RESOLVED. The DB value 1550 mm is correct. No change.** The flag is an artifact of comparing a
  radius against a diameter.

**Reasoning — this one is decidable by geometry alone, independently of the open AP0 semantics ruling.**

The same p.2 table gives SOTO's footprint as **2230 × 1060 × 2160 mm (L × B × H)** and its drive as
"omnidirektionaler Antrieb". The circumscribed circle of a 2230 × 1060 mm rectangle has diameter
√(2230² + 1060²) ≈ **2469 mm**, i.e. radius ≈ 1235 mm.

- If 3100 mm were a **radius**, the vehicle would sweep a 6200 mm circle — 2.5× its own circumscribed diameter.
  Physically impossible for a vehicle that turns about its own centre.
- If 3100 mm is a **diameter**, the implied radius is 1550 mm, which sits just above the 1235 mm geometric
  minimum — exactly the small clearance margin you expect for a real vehicle that does not rotate about its
  precise geometric centroid.

So "Wendekreis" here is unambiguously the turning **circle diameter**, the DB's 1550 mm is its correct radius,
and whoever entered it did the conversion right. This resolves the Magazino item specifically; it does **not**
resolve the general radius/diameter AP0 ruling (out of scope), though it is a clean worked example for it.

**Secondary observation for the Tech Lead (not a recommendation to change anything):** AP0's `min_turning_radius`
hint says "0 if omnidirectional", and this datasheet explicitly calls SOTO omnidirectional. Storing 0 would
nonetheless be misleading here — SOTO can rotate in place but its 2.23 m body still sweeps a 3.1 m circle. This
is a genuine edge case in the AP0 hint wording, worth folding into the radius/diameter ruling when it is made.

---

## 7. Hikrobot F3-1500 — `max_speed` + `vehicle_width` — **RESOLVED**

- **Original conflict:** `max_speed` DB = 2.1 m/s vs datasheet 1.5/1.2 m/s; `vehicle_width` DB = 870 mm vs 863 mm.
  Source: `F3-1500_flyer_eng_cemat_v2.pdf` p.1 (headline) / p.2 (table).
- **Verdict: RESOLVED.** Recommended: **`max_speed` = 1.5 m/s**, **`vehicle_width` = 863 mm**.

**Reasoning.** I re-extracted the complete text of both pages and regex-searched for `2.1`, `870` and `2100`:
**none of them occurs anywhere in the document.** The flyer's spec table is short (9 rows) and unambiguous:

```
Dimension (Length*Width*Height)   1632*863*1986mm
Rated Load                        1500kg
Running Speed                     1.5/1.2m/s
```

1.5 m/s is stated twice independently — the p.1 key-feature line "Efficient Transferring: max. running speed
1.5m/s" and the p.2 table row — which rules out a typo. The 1.5/1.2 pair is the standard
unloaded/loaded convention; AP0's `max_speed` hint ("capture rated/unloaded if only one given") selects 1.5.

`vehicle_width` = 863 mm is stated once, inside the combined dimension string. This is a CONTEXT-level field
with no matching operator, so the 7 mm delta carries **zero matching risk** — low priority.

**Punch-list note (no action now):** the Hikrobot 69-page full-line catalog
(`AGV_Brochure_(Full_Version)_ENG_2026Q2-V1...pdf`) is still unprocessed in `New/` and very likely contains an
F3-1500 spec page. Both figures should be re-checked against it when that catalog is finally worked, in case
2.1 m/s / 870 mm belong to a newer F3-1500 revision. That file was deliberately not opened in this pass
(`New/` is out of scope here).

---

## 8. Stäubli PF3 — `max_payload` + `max_speed` — **RESOLVED**

- **Original conflict:** `max_payload` DB = 2721 kg vs datasheet "Payload (tons) Up to 3"; `max_speed`
  DB = 1.1 m/s vs "Max. speed (m/s) Up to 1.5". Source: `PF3-data-sheet-EN.pdf` p.2.
- **Verdict: RESOLVED.** Recommended: **`max_payload` = 3000 kg**, **`max_speed` = 1.5 m/s**.

**Reasoning.** The p.2 "Performance" block is unambiguous and is the manufacturer's own primary EU spec sheet:
`Payload (tons) Up to 3`, `Max. speed (m/s) Up to 1.5`, alongside `Drive type Tricycle`,
`Turning radius (m) 1.7`, `Ground clearance min. (mm) 30`, `Dead weight (kg) 615`.

**The DB's oddly precise 2721 kg is explained: it is exactly 6 000 lb** (6000 × 0.45359237 = 2721.55 kg → 2721).
That is a unit conversion of an imperial-market figure, not an independently-measured European rating. Since
6000 lb (2721 kg) is a marketing round-down of 3 t (which is 6614 lb), the two figures are not in genuine
engineering conflict — one is the metric rating, the other the US-market rounded equivalent. The AP0 record
should hold the manufacturer's own metric maximum: 3000 kg.

`max_speed` = 1.1 m/s has no comparable clean imperial explanation (1.1 m/s ≈ 2.46 mph, 216 ft/min) and appears
nowhere in the datasheet. It is a SCORING field (no KO operator), so the correction is low-risk.

**Caveat:** both datasheet figures are "Up to" values. If the project's convention is to store a guaranteed
rather than best-case rating, the Tech Lead may prefer to leave `max_payload` at the more conservative 2721 —
note that `max_payload` is `KO_IF_LT`, so raising it to 3000 makes the supplier pass *more* tenders.

**Not addressed here (out of scope):** the separate PF3 / PF3-OMNI product-identity question. Note only that
this datasheet's `Drive type: Tricycle` is the same evidence that raised it.

---

## 9. Jungheinrich ERC 213a — `battery_type` — **RESOLVED (false positive — DB is correct)**

- **Original conflict:** DB = Li-Ion vs specsheet VDI row 6.3 "B 3 PzS" (flooded lead-acid).
  Source: `erc-2a-2019-specsheet-de-2026-05-pdf-data.pdf` p.4.
- **Verdict: RESOLVED — not a conflict.** **Keep Li-Ion.** Recommend *additionally* filling `Lead-Acid`
  (`battery_type` is a Multi-Select field, so this is a fill, not an overwrite).

**Reasoning.** Two decisive pieces of evidence, both inside the source document pair itself:

1. **The specsheet explicitly disclaims its own exhaustiveness.** Page 5 prints:
   *"Dieses Typenblatt nach VDI-Richtlinie 2198 nennt nur die technischen Werte des **Standard-Gerätes**.
   Abweichende Bereifungen, andere Hubgerüste, ..."* — a VDI 2198 Typenblatt states the values of the
   **standard unit only**, with deviating configurations treated as options. Row 6.3's "B 3 PzS" is therefore
   the standard-configuration battery, not an assertion that no other battery is available. A VDI row is not
   an exclusivity claim, and this was the structural mistake in the original flag.
2. **The companion factsheet from the same document pair markets Li-Ion heavily.** `erc-2a-2019-factsheet-...pdf`
   p.2: *"Mit der Jungheinrich Li-ion Guarantee Plus geben wir Ihnen ein langfristiges Leistungsversprechen von
   bis zu 8 Jahren auf unsere hochwertigen Lithium-Ionen-Batterien"*, and p.3 lists
   *"Lithium-Ionen-Technologie · Kein Batteriewechsel notwendig"* explicitly contrasted with
   *"gegenüber Blei-Säure-Batterien"*. The same product family, the same 2019/2026 document set.

So both chemistries are genuinely offered. The DB's Li-Ion is right; Lead-Acid is the missing value.

---

## 10. Jungheinrich ERC 217a — `battery_type` + `lifting_height` — **RESOLVED**

- **Original conflict:** `battery_type` same as ERC 213a; `lifting_height` DB = 4400 mm vs the datasheet's own
  ERC 217a mast table capping at 3540 mm. Source: `erc-2a-2019-specsheet-de-2026-05-pdf-data.pdf` p.3.
- **Verdict: RESOLVED.** `battery_type`: identical to item 9 — **keep Li-Ion, add Lead-Acid**.
  `lifting_height`: **3540 mm**. The earlier pass's "copy-paste from the sibling row" hypothesis is confirmed.

**Reasoning.** Page 3 prints **two separate mast tables stacked vertically**, each headed with its own model
name and both titled "Zweifach-Hubgerüst ZT":

```
ERC 213a   Hub (h3)   h1      Freihub (h2)   h4
           3100 mm    2150    200            3625
           3800 mm    2500    200            4325
           4400 mm    2750    200            4925

ERC 217a   Hub (h3)   h1      Freihub (h2)   h4
           2840 mm    2150    200            3495
           3540 mm    2500    200            4195
```

The evidence is unusually clean:

- ERC 213a has **three** mast options (max 4400 mm); ERC 217a has only **two** (max 3540 mm). The 4400 mm row
  belongs to the 213a table and is physically absent from the 217a table.
- The `h1` (mast lowered) columns confirm this is a real mast-availability difference, not a truncation:
  213a offers 2150/2500/**2750**, 217a offers 2150/2500 only. ERC 217a simply cannot be ordered with the
  tallest mast.
- It is physically coherent: per p.4's VDI row `1.5 Tragfähigkeit/Last Q`, ERC 213a carries 1300 kg and
  ERC 217a carries 1700 kg. Higher payload on the same chassis → lower maximum lift. Exactly the expected
  trade-off.
- The DB currently stores 4400 for **both** 213a and 217a (confirmed by query). 4400 is correct for 213a.
- The p.1 headline "Hubhöhe: 3100-4400 mm / Tragfähigkeit: 1300-1700 kg" is a **family** range spanning both
  models — 4400 is the family maximum (from 213a), not a 217a figure. This is the most likely origin of the error.

---

## 11. Jungheinrich arculee M — `max_payload` — **RESOLVED**

- **Original conflict:** DB = 1200 kg vs datasheet's twice-repeated 1300 kg.
  Source: `download-factsheet-amr-arculee-m-data.pdf` p.1 / p.2.
- **Verdict: RESOLVED.** Recommended value: **1300 kg**.

**Reasoning.** 1300 kg is stated **three** times across the four-page factsheet, in three different registers:
p.1 cover spec line *"Tragfähigkeit: 1.300 kg / Fahrgeschwindigkeit: 1,6 m/s (beladen)"*; p.2 prose
*"Tragfähigkeit von 1.300 kg bei hervorragender Kippstabilität"*; p.2 bullet *"Flexible
Unterfahrtransportlösung für Lasten bis 1.300 kg bei 2,1 m Lasthöhe"*. Three consistent statements exclude a
source-side typo. 1200 kg appears nowhere in the document.

I also checked the sibling-confusion hypothesis that produced item 10: the DB holds arculee S = 1000 kg and
arculee XS = 250 kg, so 1200 is **not** a copied sibling value — it appears to be a stale or third-party figure.
Straightforward correction.

---

## 12. DS Automotion OSCAR Omni — `lift_height` — **RESOLVED (false positive — DB is correct, no change)**

- **Original conflict:** DB = 200 mm vs datasheet 160 mm (positionally inferred from column order).
  Source: `OSCAR-OnePager-2025-DE.pdf` p.2.
- **Verdict: RESOLVED — there is no conflict. The DB already holds 160 mm.** No change.

**Reasoning.** A read-only query of the current DB returns:

| Product | `lift_height` | `min_ground_clearance` |
|---|---|---|
| OSCAR Spin 180 | 80 | 260 |
| OSCAR Spin 360 | 130 | 295 |
| OSCAR Omni | **160** | 320 |
| OSCAR Omni XL | **200** | 380 |

The datasheet's `Hub: 80 mm / 130 mm / 160 mm` maps positionally onto Spin 180 / Spin 360 / Omni — and **all
three already match the DB exactly.** The 200 mm the earlier pass reported as "DB value" belongs to
**OSCAR Omni XL**, a *fourth* variant that the earlier pass did not account for: the one-pager's variant table
has only three columns (OSCAR spin 180 / spin 360 / omni), so Omni XL is not covered by this document at all.
The flag was a row-misidentification, not a data defect.

**Genuine gap surfaced instead:** `OSCAR Omni XL` has **no datasheet coverage** in `Analysed/`. Its 200 mm /
380 mm values are unverified by any document on file. Worth adding to the coverage-gap list rather than the
conflict list.

---

## 13. DS Automotion OSCAR line — `min_ground_clearance` — **RESOLVED (false positive — DB is correct, no change)**

- **Original flag:** `min_ground_clearance` = 260 / 295 / 320 mm for spin180 / spin360 / omni "strongly appears
  to have been populated from vehicle HEIGHT, not actual ground clearance — this document states the real
  ground clearance as 25 mm for the whole line, a huge discrepancy".
  Source: `OSCAR-OnePager-2025-DE.pdf` p.2.
- **Verdict: RESOLVED — the DB values are correct and 25 mm would be wrong.** No change. The earlier pass's
  observation about provenance was factually right, but its conclusion was inverted.

**Reasoning.** This turns entirely on AP0's own definition of the field, which the earlier pass did not consult.
`config/fields.json` gives, for `min_ground_clearance` (entity Base Model, scope `Logistics:AGV:AMR`, `KO_IF_LT`, unit mm):

> "Robot height / clearance needed to drive UNDER the carrier (undercarriage workflows). **Source: vehicle
> height spec.** Must be less than the carrier's underside gap — classic undercarriage K.O."

The field is *defined* as the robot's height — it is the clearance the **carrier** must provide, not the gap
under the robot. The name is misleading; the hint is not.

The one-pager's variant table gives exactly this:

```
OSCAR spin 180        OSCAR spin 360        OSCAR omni
1.620 x 560 x 260 mm  1.620 x 712 x 295 mm  1.520 x 720 x 320 mm     (L x W x H)
```

**260 / 295 / 320 mm are the three vehicles' heights, and they match the DB exactly.** The DB is right.

The 25 mm figure is a different quantity entirely — p.2 prose: *"Zudem bietet die OSCAR-Baureihe eine mit 25 mm
ausreichend große **Bodenfreiheit**, um auch Bodenunebenheiten überwinden zu können"* — the robot's own
under-body clearance for driving over floor irregularities. Writing 25 mm into a `KO_IF_LT` undercarriage field
would have been a serious error, wrongly qualifying OSCAR for carriers it physically cannot fit under. **Good
outcome of the "never overwrite, only flag" rule.**

**Optional refinement for the Tech Lead.** The same table also prints a per-variant
*"Unterfahrmaß mind. 610 × 280 mm / 760 × 315 mm / 770 × 340 mm (B × H)"* — the minimum under-drive opening
DS Automotion themselves require, i.e. 280 / 315 / 340 mm, each ~20 mm above the bare vehicle height. That is
arguably an even better fit for "clearance needed to drive UNDER the carrier" and is the manufacturer's own
stated requirement rather than a derived one. AP0's hint says "Source: vehicle height spec", so the current
values are hint-compliant; switching to Unterfahrmaß would be an AP0-hint change, not a data fix. Flagged, not
recommended either way.

---

## 14. DS Automotion AMADEUS Grip — `max_payload` + `lifting_height` — **UNRESOLVED (needs manual/external research)**

- **Original conflict:** DB = 2000 kg / 2880 mm vs the one-pager's 800 kg / 600 mm.
  Source: `AMADEUS_Grip_Onepager_2022_DE.pdf` p.2.
- **Verdict: UNRESOLVED.** Neither figure can be established as AMADEUS Grip's rated maximum from the documents
  on file. **Recommend no change** until a Grip-specific product datasheet exists.

**Reasoning.** I read both the Grip one-pager and the general series one-pager (`AMADEUS-OnePager-2025-DE.pdf`,
p.2 read as a rendered image to get the two-column layout right).

**Why the 800 kg / 600 mm figures cannot be taken as the variant's rating.** The 2022 document is titled
*"FTS LÖSUNGEN FÜR DIE Dämmstoffproduktion"* — an **application/industry solution sheet** for insulation-material
production, not a product datasheet. Its body refers to *"der AMADEUS"* generically, describes one customer's
load geometry (*"2 Blöcke von einer Größe bis zu 1.050×1.600×6.000 mm"* — bulky but light insulation blocks),
and explicitly states *"Die exakten Maße können dabei gezielt an Ihre individuellen Anforderungen angepasst
werden"* (the exact dimensions can be adapted to your individual requirements). Its `Hubhöhe: 85-600 mm` and
`Navigation: Magnet` are likewise project-configured. An 800 kg figure driven by a light bulky load says
nothing about the mechanism's rated capacity.

**Why the DB's 2000 kg / 2880 mm cannot be confirmed either.** The 2025 series one-pager confirms
**AMADEUS grip is a genuine named series variant** (alongside classic, counter, wide, low) and shows a photo of
a clamp/grip attachment in place of forks. But its central "Technische Details" table
(`Nutzlast: max. 1,5 t / 2,0 t`, `Duplex-Mast: 85 mm – 2.800 mm`) is laid out as belonging to the two
unannotated variants (classic, wide); counter and low each carry a "Technische Details abweichend" caption.
**The document gives no Grip-specific numeric figures at all.** The DB's 2000 kg / 2880 mm is simply the
family/classic spec — the identical triple (2000 / 2880 / 1.8) is stored for AMADEUS Classic, AMADEUS Wide *and*
AMADEUS Grip — inherited, not verified for Grip. A gripper attachment plausibly reduces both usable payload and
lift height relative to forks, so inheriting the fork variant's numbers is exactly the assumption in question.

**Needed:** a DS Automotion AMADEUS grip product datasheet, or vendor confirmation of the grip variant's rated
payload and maximum lift height. Until then both DB values should be treated as unverified.

> **New, previously unflagged observation from this pass.** The 2025 series one-pager states the Duplex-Mast
> range as `85 mm – 2.800 mm`, but the DB stores `lifting_height = 2880` for AMADEUS Classic, AMADEUS Wide *and*
> AMADEUS Grip — an 80 mm discrepancy on a `KO_IF_LT` field affecting three products. Not part of the original
> conflict list; surfaced here because it is the same document and the same question. Worth a separate check.

---

## 15. AGILOX OCF — `min_aisle_width` — **RESOLVED**

- **Original conflict:** DB = 1300 mm vs the product page's "MIN. GANGBREITE 2.100 MM".
  Source: `AGILOX  OCF.html` ("TECHNISCHE DETAILS OCF" block).
- **Verdict: RESOLVED.** Recommended value: **2100 mm**.

**Reasoning.** The saved page's spec block prints three distinct and separately-labelled geometry figures:

```
ABMASSE (L x B x H)        2.784 x 1.200 x 2.566 MM
WENDEKREIS                 3.500 MM   (turning circle)
MIN. GANGBREITE            2.100 MM   (min aisle width)
MIN. DURCHFAHRTSBREITE     1.700 MM   (min transit width)
```

AP0's `min_aisle_width` hint names its source term explicitly: *"Source terms: 'Gangbreite', 'aisle width',
'working aisle'"* and defines the field as the **minimum working aisle width**. The page prints
"MIN. GANGBREITE" verbatim. That is a direct, literal match — 2100 mm. The 1700 mm
"Durchfahrtsbreite" is the narrower drive-through corridor (a different quantity, correctly not used) and
3500 mm is a turning circle (correctly excluded under the established Drehkreis/Wendekreis discipline).

**1300 mm appears nowhere on the page.** This is a large error on a `KO_IF_GT` field: at 1300 mm the OCF would
pass VNA-class tenders it cannot physically serve (its own body is 1200 mm wide). Recommend prioritising this
correction.

> **New, previously unflagged observation.** The DB stores `min_aisle_width = 1300` for **both** AGILOX OCF and
> **AGILOX ONE** — the same undocumented value on two different vehicles, suggesting a shared bulk-entered
> default. I checked `Agilox One.pdf`: it prints only `DREHKREIS 2.100 MM` and no Gangbreite at all, which is
> why ONE never produced a detectable conflict. ONE's 1300 mm is equally unsupported and should get the same
> scrutiny. (AGILOX ONE was not on the conflict list, so no verdict is issued for it here.)

---

## 16. Balyo REACHY — `battery_type` — **UNRESOLVED (needs manual/external research)**

- **Original conflict:** DB = Li-Ion vs the 2020-dated datasheet's "lead-acid or TPPL".
  Source: `Reach Truck Gen 2-Black Truck-Datasheet-EN.pdf` p.1 / p.2.
- **Verdict: UNRESOLVED** for the Li-Ion claim. **Partial action available now:** `battery_type` is Multi-Select,
  so **`Lead-Acid` can be filled** (a pure fill, no overwrite) on well-documented evidence. Whether `Li-Ion`
  should be *removed* cannot be settled from the documents on file.

**Reasoning.** The REACHY datasheet is dated 01/2020 in its own footer and states lead-acid/TPPL twice
(p.1 "Energy : lead-acid or TPPL auto charging (2020)"; p.2 "Energy options : standard lead-acid or TPPL
opportunity fast charging technology"). TPPL (Thin Plate Pure Lead) is a lead-acid sub-chemistry, so both
statements map to AP0's `Lead-Acid`. No Li-Ion anywhere.

I then used the OEM-sibling cross-reference already established in earlier runs (Balyo REACHY = Linde R-MATIC),
since both Linde sheets are in `Analysed/`:

| Document | Date | Battery |
|---|---|---|
| `Reach Truck Gen 2-Black Truck-Datasheet-EN.pdf` (Balyo REACHY) | 01/2020 | lead-acid / TPPL |
| `EN_ds_r_matic_1120_en_b_0623_view.pdf` (Linde R-MATIC) | 06/2023 | 4PzS-560 Ah TPPL, 5PzS-700 Ah TPPL — **options list, no Li-Ion** |
| `DE_tb_r_matic_k_5190_dt_a_0425_view.pdf` (Linde R-MATIC **k**) | 04/2025 | *"Wahl zwischen Blei-Säure- oder **Li-ION**-Batterien"*, Li-Ion 13–35 kWh |

This is stronger than the original flag suggested but still not conclusive. The 2023 R-MATIC sheet's p.7 is an
explicit **options/accessories list** (not just a VDI standard-config row, so the item-9 disclaimer logic does
*not* rescue it) and it contains no Li-Ion — so as of mid-2023 this vehicle genuinely did not offer Li-Ion.
However, the 2025 R-MATIC **k** sheet proves Li-Ion arrived in the product line since. R-MATIC k is a different
model (its own DB row), so this does not transfer automatically, but it makes "the DB reflects a post-2023
REACHY generation" entirely plausible rather than merely a hedge.

**Needed:** a current (2024+) Balyo REACHY or Linde R-MATIC (non-k) datasheet, or vendor confirmation of whether
Li-Ion is now offered on the standard reach truck. Low urgency: `battery_type` is CONTEXT-level with
`operator: None`, so it has **no effect on matching** either way.

---

## 17. STILL FM-X iGo — `max_payload` — **RESOLVED**

- **Original conflict:** DB = 2500 kg vs the VDI table's FM-X 25 iGo column at 2400 kg.
  Source: `iGo_systems_DE_TD.pdf` p.10.
- **Verdict: RESOLVED.** Recommended value: **2400 kg**.

**Reasoning.** Page 10 is a genuine VDI 2198 multi-model table listing all five family variants side by side:

```
1.2 Typzeichen des Herstellers   FM-X 12 iGo  FM-X 14 iGo  FM-X 17 iGo  FM-X 20 iGo  FM-X 25 iGo
1.5 Tragfähigkeit/Last Q  kg           1100         1300         1600         1900         2400
4.4 Hub h3                mm           5532         5532         5532         5362         5362
```

The rated capacity is per-variant and unambiguous: **FM-X 25 iGo = 2400 kg**. The DB's 2500 kg is explained by
the type designation itself: STILL's "25" denotes the 2.5 t nominal class inherited from the manual FM-X 25.
The automated iGo version is de-rated to 2400 kg — the standard pattern where automation hardware consumes
payload. The DB value is the model-name-implied class figure, not the automated variant's VDI rating.

**Recommended alongside the value fix:** rename the generic `FM-X iGo` row to **`STILL FM-X 25 iGo`**, for
consistency with the four sibling rows (FM-X 12/14/17/20 iGo) created in the earlier run and to make the
2400 kg figure self-evidently correct rather than looking like an unexplained downgrade.

> **New, previously unflagged observation.** The DB stores `lifting_height = 9800` for FM-X iGo. I searched the
> entire 18-page document for "9800" — **it does not occur**. The three FM-X mast tables on p.11 all top out at
> `Hub h3 = 9582 mm` (mast extended h4 = 10693 mm). Unlike the MX-X iGo case (where the earlier run correctly
> established 14000 mm as a documented automatic-mode cap), there is no such statement for FM-X. This was not on
> the conflict list; surfacing it here since it is the same document and the same product row.

---

## 18. Kivnon K05 (Underride) — `max_payload` + `max_speed` — **RESOLVED**

- **Original conflict:** `max_payload` DB = 500 kg vs 450 kg onboard; `max_speed` DB = 1.0 m/s vs 0.7 m/s.
  Source: `Kivnon-Catalogo-2026-—-Editable-ENG.pdf` p.7 as cited (= PDF page 8; the catalog's printed page
  numbering runs one behind the PDF index — both are given below).
- **Verdict: RESOLVED.** Recommended: **`max_payload` = 450 kg**, **`max_speed` = 0.7 m/s`**.

**Reasoning.** The K05 page (PDF p.8, printed "08 / 23", header "04 · K05 TWISTER") states both figures **twice
each** — once in the three-stat headline row and once in the `— SPECIFICATION · K05-M1000` block:

```
MAX. PAYLOAD   MAX. SPEED.   NAV.
450 kg         0,7 m/s       Magnetic
...
DIMENSIONS     800 × 800 × 280 mm
LIFT           Integrated lifting table, 60 mm stroke
MAX. PAYLOAD   450 kg onboard / 1.000 kg tow
MAX. SPEED     0,7 m/s
```

Two independent statements each rule out a typo, and this is the current (2026) catalog edition — the newest
Kivnon document on file.

Note the payload is explicitly split: **450 kg onboard** vs **1000 kg tow**. The DB row is named
"K05 (Underride)", i.e. the carrying mode, so `max_payload` = 450 kg is the correct mapping. The 1000 kg tow
figure belongs in a towing field, which is Tugger-scope and therefore not available on this Mobile AMR record —
worth noting so the 1000 kg is not later mistaken for the payload.

**Confidence caveat:** 500 → 450 kg is exactly the kind of figure that changes between product generations, and
the catalog documents only one sub-model (`K05-M1000`). The DB's 500 kg may be a genuine earlier K05 rating
rather than an error. The recommendation stands on the 2026 catalog being the newest available source.

---

## 19. Kivnon K32 Tractor — `max_speed` — **RESOLVED**

- **Original conflict:** DB = 1.0 m/s vs catalog 0.7 m/s.
  Source: `Kivnon-Catalogo-2026-—-Editable-ENG.pdf` p.11 as cited (= PDF page 12, printed "12 / 23",
  header "08 · K32 TUGGER").
- **Verdict: RESOLVED.** Recommended value: **0.7 m/s**.

**Reasoning.** Stated twice on the page — headline stat row (`2.000 kg | 0,7 m/s | Magn. / SLAM`) and
`— SPECIFICATION · K32` block (`MAX. SPEED 0,7 m/s`), alongside `DIMENSIONS 1.492 × 460 × 332 mm`,
`MAX. PAYLOAD 2.000 kg`, `TRAIN Up to 4–5 trolleys`.

**Important refinement to the earlier pass's hypothesis.** The original flag suggested several Kivnon
`max_speed` values might have been bulk-entered from a marketing headline, since K05, K32, K10P, K10HP and K41
all sit at exactly 1.0 in the DB. I tested this by extracting the `MAX. SPEED` line from every model page in the
catalog:

| Catalog page | Model | Catalog speed | DB speed |
|---|---|---|---|
| PDF p.8 | K05 Twister | 0,7 m/s | 1.0 ✗ |
| PDF p.9 | K07 Twister | 2,1 – 2,5 m/s | — |
| PDF p.10 | K10 series (5.000 kg) | **1 m/s** | 1.0 ✓ |
| PDF p.11 | K10 series (5.000 kg) | **1 m/s** | 1.0 ✓ |
| PDF p.12 | K32 Tugger | 0,7 m/s | 1.0 ✗ |
| PDF p.13 | K50 Pallet Mover | 1,0 – 1,2 m/s | — |
| PDF p.14 | K55 (1.200 kg) | 1 m/s | — |
| PDF p.15 | K60 Stacker | 1,2 m/s | — |

Kivnon's speeds genuinely vary per model, and **1.0 m/s is confirmed correct for the K10 family** (K10P One-Way,
K10HP One-Way). So the "systematic placeholder" hypothesis is **refuted** — only K05 and K32 are actually wrong,
and they are two independent per-model errors rather than one bulk defect. `K41 Platform` (also 1.0 in the DB)
has no page in this catalog and remains unverified either way.

---

## 20. Kivnon K50 Pallet Truck — `max_payload` + `lifting_height` — **VARIANT-SPLIT-NEEDED**

- **Original conflict:** DB = 1000 kg / 150 mm vs the catalog's two sub-models (2000 kg / 3000 kg) and
  ≈205 mm family lift height — neither matches.
  Source: `Kivnon-Catalogo-2026-—-Editable-ENG.pdf` p.12 as cited (= PDF page 13, printed "13 / 23",
  header "09 · K50 PALLET MOVER SERIES").
- **Verdict: VARIANT-SPLIT-NEEDED.** This is not one wrong number — the DB has one row where the current
  product line has two, and the existing row matches neither.

**Reasoning.** The catalog page is explicitly labelled **"— SERIES · 2 CONFIGURATIONS"** and names both:

```
MODELS       K50-S2002 · K50-S3002
DIMENSIONS   K50-S2002: 1.730 × 942 × 1.920 mm
             K50-S3002: 1.740 × 950 × 2.118 mm
LIFT HEIGHT  ≈ 205 mm
MAX. PAYLOAD 2.000 kg · 3.000 kg
MAX. SPEED   1,0 – 1,2 m/s
```

The two sub-models have **distinct model codes and distinct physical dimensions** (different length, width and
notably a 198 mm height difference) — these are two different vehicles, not two configuration options of one.
That is the AP0 Entity Model's threshold for separate Product rows.

**Recommended structure:**

1. Create **`KIVNON K50-S2002`** — `max_payload` 2000 kg, dimensions 1730 × 942 × 1920 mm, `lifting_height` ≈205 mm.
2. Create **`KIVNON K50-S3002`** — `max_payload` 3000 kg, dimensions 1740 × 950 × 2118 mm, `lifting_height` ≈205 mm.
3. Note in the base-model grouping that the two share the K50 Pallet Mover series and its 1,0–1,2 m/s speed band
   and SLAM navigation.
4. **Decide what to do with the existing `KIVNON K50 Pallet Truck` row (1000 kg / 150 mm).** It matches neither
   current sub-model and is most likely a discontinued earlier K50 configuration absent from the 2026 edition.
   Per project convention this makes it a removal/deactivation candidate — **but this agent only flags; it does
   not deactivate or delete.** Confirm against Kivnon's current site before retiring it.
5. `lifting_height` ≈205 mm is printed as an approximate family-level figure. If a `KO_IF_LT` field needs a hard
   number, 205 is the only documented value; flag the "≈" in the record notes.

---

## 21. Omron MD-650 — `battery_type` — **RESOLVED**

- **Original conflict:** DB = Li-Ion (generic) vs datasheet's explicit "Lithium-Ion (LiFePO4)".
  Source: `i885_md_series_amr_(autonomous_mobile_robot)_datasheet_en.pdf` p.6.
- **Verdict: RESOLVED.** Recommended value: **LiFePO4**.

**Reasoning.** Page 6's Battery block prints `Type  Lithium-Ion (LiFePO4)` verbatim. `config/fields.json` lists
both `Li-Ion` and `LiFePO4` as allowed values for `battery_type`, so the more specific one is available and
should be used where the manufacturer states it.

**This is a precision refinement, not a factual contradiction** — LiFePO₄ *is* a lithium-ion chemistry, so the
existing "Li-Ion" is not false, merely less specific. Since `battery_type` is CONTEXT-level with
`operator: None`, there is **no matching impact** and therefore no urgency or risk either way.

Two supporting points: (a) the same chemistry is already correctly recorded for the LD-series and HD-1500
siblings, so this aligns the MD-series with its own family; (b) `battery_type` is Multi-Select — recommend
setting `["LiFePO4"]` rather than `["Li-Ion", "LiFePO4"]`, since carrying both would double-count one chemistry.

---

## 22. Omron MD-900 — `battery_type` — **RESOLVED**

- **Original conflict:** identical to MD-650. Same source document and page (the MD-series datasheet covers both
  models with a shared Battery block).
- **Verdict: RESOLVED.** Recommended value: **LiFePO4**. See item 21 — same evidence, same reasoning, same
  (nil) matching impact.

---

## Punch list for the manual / external research phase

Four items cannot be settled from the documents on file. In priority order:

| # | Model | Field(s) | What is needed | Why the document can't settle it | Priority |
|---|---|---|---|---|---|
| 2 | Toyota Reflex RAE250 | `min_aisle_width` | Check a different/newer Toyota RAE250 datasheet or Toyota's published Aₛₜ figure to identify which configuration 3071 mm came from; then a **Tech Lead convention decision** on collapsing an aisle-width matrix to one value | The value is a 4-axis configuration matrix (mast × battery × rotation mode × load size) with no corresponding AP0 axis; 3071 appears in none of the 104 cells. Best case 2876, worst case 3336, EUR-pallet cell 3081 | Medium — KO field, but the DB value is within 10 mm of the most plausible cell |
| 14 | DS Automotion AMADEUS Grip | `max_payload`, `lifting_height` | **Request a Grip-specific product datasheet from DS Automotion**, or vendor confirmation of the grip variant's rated payload and max lift | The only Grip-specific numeric document is an insulation-industry *application* sheet that states its own dimensions are customer-configurable; the 2025 series sheet names the Grip variant but gives it no figures at all | Medium — two KO fields, both currently unverified inherited values |
| 16 | Balyo REACHY | `battery_type` | A current (2024+) Balyo REACHY or Linde R-MATIC datasheet, or vendor confirmation that Li-Ion is now offered | The 2020 REACHY sheet and the 2023 R-MATIC options list both exclude Li-Ion; the 2025 R-MATIC **k** sheet includes it. Whether the change reached the non-k reach truck is not documented anywhere on file | Low — CONTEXT field, `operator: None`, zero matching impact. `Lead-Acid` can be filled now regardless |
| 5 | VisionNav R-series (`-07` variants) | product structure | Confirm with VisionNav whether the 2022 catalog's four operation-type `-07` variants are still offered, before creating rows for them | The vendor's own catalog assigns one model code (VNR16(V)-07, and separately VNR25(V)-07) to two physically different vehicles; the code alone cannot identify a product. This part is a *structure* question, not a value question — see item 5d for the recommended split | Medium — creating rows from a 4-year-old catalog risks adding stale products |

### Additional findings surfaced during this pass (not on the original conflict list — no verdict issued)

These were found while re-reading the cited documents and are the same class of discrepancy. Recommend folding
them into the next review cycle:

1. **DS Automotion AMADEUS Classic / Wide / Grip — `lifting_height` 2880 mm** vs the 2025 series one-pager's
   `Duplex-Mast: 85 mm – 2.800 mm` (`AMADEUS-OnePager-2025-DE.pdf` p.2). 80 mm on a KO field, three products.
2. **STILL FM-X iGo — `lifting_height` 9800 mm** does not occur anywhere in `iGo_systems_DE_TD.pdf`; the mast
   tables (p.11) cap at `Hub h3 = 9582 mm`.
3. **AGILOX ONE — `min_aisle_width` 1300 mm** is the same undocumented value as OCF's (item 15). ONE's own sheet
   (`Agilox One.pdf`) prints only `DREHKREIS 2.100 MM` and no Gangbreite, which is why it never produced a
   detectable conflict.
4. **DS Automotion OSCAR Omni XL** has **no datasheet coverage** at all in `Analysed/` — the OSCAR one-pager's
   variant table has only three columns. Its 200 mm / 380 mm values are unverified. (Coverage gap, not a conflict.)
5. **DS Automotion OSCAR Spin 180 / Spin 360** have NULL `max_payload`, but the one-pager states
   `Transportgewicht: max. 1,0 t` for the whole line — a straightforward fill opportunity.
6. **VisionNav VNR14(V)-01** is documented in *both* VisionNav files but has no DB row — a clean new-product
   candidate, independent of the R-series collision problem.
7. **Kivnon K41 Platform — `max_speed` 1.0 m/s** remains unverified: K41 has no page in the 2026 catalog. Given
   that K05 and K32 both turned out wrong at the same value, this one deserves a check.

---

*Produced by the `agv-datasheet-ingestor` agent, 2026-08-06. `Datasheets/AGV_AMR/New/` was not touched.
No Airtable writes, no DB writes.*
