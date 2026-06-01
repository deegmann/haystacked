# haystacked — Industry Read Me (AGV / Intralogistik)

**Purpose.** This document gives an AI model the *domain context* needed to populate and match the haystacked AGV (Automated Guided Vehicle) supplier database correctly. The field specification (AP0) defines *what* to capture; this document explains the *non-obvious relationships* behind those fields — the things a model cannot infer from a datasheet alone. Read this before interpreting product specs or buyer tenders.

**Core principle: trust properties, not labels.** Vendors name the same machine in many ways for marketing reasons. The category a product belongs to should be *derived from its properties*, never taken from the vendor's label. Every section below exists to help you do that derivation.

**Format convention.** Abbreviations are spelled out on first use.

---

## 1. The category labels are deliberately fuzzy

AGV (Automated Guided Vehicle), AMR (Autonomous Mobile Robot), "transport robot", "picking robot" — these terms overlap heavily and are applied inconsistently across vendors. The same physical chassis is often sold as several "types". **Do not classify by the product name.** Classify by the underlying properties (navigation, lift, rotation, grid dependency, payload). The type is an *output* of the properties, not an input.

---

## 2. AGV vs. AMR — navigation is the real tell

The marketing distinction ("AGV = old/guided, AMR = new/smart") is unreliable. The meaningful technical difference is **infrastructure dependence**, visible in `navigation_type`:

- **Infrastructure-bound (classic AGV):** magnetic tape, inductive wire, QR/DataMatrix floor codes, laser reflectors. Needs floor/wall modification. Deterministic, cheap to scale densely.
- **Free-navigating (classic AMR):** Natural-Feature / SLAM (Simultaneous Localization and Mapping), contour, vision. No floor changes. Flexible, easier to re-route.

Edge case: some vendors (e.g. Balyo) do reflector-free geo-guidance yet are not marketed as AMRs. **Resolve this via `navigation_type` + `infrastructure_required`, not the badge.**

---

## 3. Goods-to-Person (G2P) vs. transport AMR — same hardware, different workflow

This is the single most confusing distinction in the catalogue. A latent-lift / undercarriage robot that drives under a rack and lifts it can serve **either** role; the hardware is often identical. The difference is the *workflow it is embedded in*:

- **Transport AMR:** moves a load/rack point-to-point. Defined by the movement. (`rotation_capable` usually false, `grid_required` usually false.)
- **Goods-to-Person:** runs a continuous loop bringing racks/pods to a fixed picking station, where a human (or arm) picks, then returns them. Defined by the picking process. (`rotation_capable` true — it turns the pod to present the right face; `grid_required` true — it operates on a structured storage field.)

**Worked example:** Geek+ M-series (transport) and P-series (picking) are near-identical latent-lift robots. The datasheets look almost the same; the workflow and surrounding system (picking station, pick-by-light, WMS logic) differ. **Derive the role from `rotation_capable` + `grid_required`, not from the series name.**

---

## 4. Goods-to-Person vs. Person-to-Goods (picking AMRs) — opposite directions

Easy to conflate with §3 but the opposite flow:

- **Goods-to-Person (G2P):** the human stays still; robots bring goods to them.
- **Person-to-Goods (picking AMR / "cart follower", e.g. Locus Origin, 6 River Chuck):** the human walks the aisles; the robot accompanies/leads them, carries the totes, and guides the pick path. The goods stay on the shelf.

Both raise picking productivity but imply completely different warehouse layouts and labour models. A "picking robot" could be either — check `picking_mechanism` and whether goods move to a station (G2P) or the worker moves to the goods (person-to-goods).

---

## 5. When VNA (Very Narrow Aisle) capability is needed

VNA trucks operate in aisles roughly 1.5–1.8 m wide (vs. ~2.5–3.5 m for standard reach trucks) by not needing to turn the chassis to stack — only the fork/turret rotates. They are more expensive and often rail/wire-guided in-aisle. Signals in a tender that VNA is required:

- Stated aisle width below ~1.9 m, or the word "Schmalgang" / "narrow aisle".
- High storage density / land-cost pressure ("maximise pallet positions per m²").
- Retrofitting an **existing** high-bay narrow-aisle warehouse (the racking is fixed; the truck must fit it).
- High lift heights (often >8–10 m) combined with tight aisles.
- "Man-up" picking references (operator cab rises with the forks).

If none of these is present, VNA is usually *not* required and demanding it would over-spec the tender. Conversely, a wide-aisle site never needs VNA. (`vna_capable`, `min_aisle_width_mm`, `guidance`.)

---

## 6. Counterbalance vs. reach vs. straddle — the closed-pallet & closed-conveyor problem

Forklift drive types differ in how the load sits relative to the support legs (straddle arms), and that determines whether they can handle closed-bottom pallets and closed floor conveyors:

- **Counterbalanced:** rear counterweight, no front legs. Free front face. Picks a **closed-bottom pallet standing on the floor** and mates with **closed conveyors** — nothing protrudes underneath.
- **Reach truck:** has straddle legs, **but** the forks reach forward *beyond* the legs, so the load is picked/placed in front of the legs. A reach truck **can** therefore handle closed-bottom and wider pallets — that is exactly what the reach is for. The legs are not under the load during the transfer.
- **Straddle stacker / Pallet mover (arms under the load):** the support legs must sit *under* the pallet. Here the legs **collide** with closed-bottom pallets (some CHEP/plastic pallets, mesh boxes) and with closed floor conveyors.

So the knockout for closed-bottom pallets / closed floor conveyors applies to straddle-under-load designs, **not** to reach trucks or counterbalanced trucks. The field that captures the "free front, nothing under the load" property is `forks_free_floating`. (`drive_type`, `forks_free_floating`, `station_applications`.)

**Detail (not needed for the PoC, but worth knowing):** with a reach truck, if the pallet fits *between* the load arms there is nothing special to consider when picking from a rack. But if the load carrier is **wider than the load arms** (typically >800 mm), then picking from a rack at marginal aisle width requires lifting the load *over* the arms first, retracting the reach, then driving out — which means extra vertical clearance is needed between the top of the load and the underside of the next rack level. So very wide carriers can impose a hidden height/clearance constraint in narrow aisles.

---

## 7. OEM rebadging — one machine, many brands

A large share of products are the **same physical machine sold under different brands** through OEM / distribution deals. The "manufacturer" on a datasheet is often *not* the engineering owner.

Verified examples:
- **Quicktron** (Shanghai) AMRs are distributed by **KION** brands — sold as **Linde Material Handling "M60"/"M100"**, and via **STILL** and **Dematic**.
- **Balyo** technology underpins **Linde "K-MATIC"/"L-MATIC"** and **STILL** automated trucks.
- **Idealworks** "iw.hub" is distributed via **Linde Material Handling**.

Implications for the database:
- Intrinsic technical specs belong to the **OEM base model** and are shared by every rebadge (`oem_base_model_id`). Learn a spec for one brand → it holds for all siblings.
- The commercial counterpart (price, service, lead time) differs per brand and belongs to the product/company layer.
- A datasheet's claimed "manufacturer" may be a reseller; check `oem_technology` for the real capability owner.

---

## 8. Food & Beverage (F&B) and cold chain — environmental gates that are often implicit

F&B and beverage tenders frequently imply hard environmental requirements that are **not stated as explicit specs** but follow from the environment:

- **Washdown / wet areas:** require high ingress protection (IP54–IP65+). Standard warehouse AMRs are ~IP20 and will not survive. (`ingress_protection_rating`, `operating_humidity_max_pct`.)
- **Cold store / freezer:** standard units are rated only to ~0–5 °C; freezer operation (down to −25 °C) needs a special cold-store variant. (`operating_temp_min_c`.)
- **Hygiene / cleanroom (dairy, pharma-adjacent food):** may need a cleanroom class. (`cleanroom_class`.)

When a tender names an F&B sub-sector, infer the likely environmental gate even if the buyer did not spell it out, and flag it. These are typically Conditional K.O. fields that become hard filters precisely in this market.

---

## 9. Tugger trains — trailer steering drives the real aisle requirement

For tugger / tractor trains, the **trailer** technology, not just the tractor, determines how much aisle width is actually needed:

- **Passive caster carts** "off-track" (the trailers cut corners / snake), so the train sweeps a wider path and needs wider aisles.
- **Self-steering / tracking carts** (quad-steer, tracking drawbar / virtual coupling, forced axle steer) follow the tractor's exact path with little deviation, allowing tighter aisles and safer operation.

So a tugger's own `min_aisle_width_mm` can be optimistic if paired with passive carts. Read `trailer_steering_technology` and `trailer_compatibility` together with the aisle figure. (Also: `auto_hitch` lets a train drop and collect carts without an operator — a throughput multiplier, not just a convenience.)

---

## 10. VDA 5050 — interoperability, trending from optional to mandatory

VDA 5050 is an open interface standard between AGVs/AMRs and a master control / fleet manager. It lets a buyer run a **mixed-vendor fleet** under one controller instead of being locked to one brand. Today it is often a scoring plus, but large European buyers increasingly make it a hard requirement — treat it as a Conditional K.O. that is rising in weight. A vendor stating "not VDA 5050 compatible" is a genuine differentiator against such buyers. (`vda5050_compatible`, `fleet_management_system`, `multi_fleet_capable`.)

---

## 11. Battery technology has downstream consequences

`battery_type` implies more than runtime:

- **Lithium (Li-Ion / LiFePO4):** supports opportunity charging (top-ups during natural idle), no dedicated battery-swap room, enables 24/7 operation with less floor space.
- **Lead-Acid:** longer charge cycles, often needs a ventilated battery-change room and spare batteries — consumes floor space and labour.

So a Li-Ion + autonomous-charging combination implies near-continuous uptime; lead-acid implies shift planning and infrastructure. Read `battery_type`, `autonomous_charging`, `charge_time_min`, and `battery_swap_capable` together when judging true availability.

---

## 12. Read spec sheets critically

- **Per-station vs. per-robot:** throughput numbers (e.g. picks/hour) may be quoted per workstation *or* per robot. They are not comparable across vendors without checking which. (`picks_per_hour_per_station`, `picks_per_hour`.)
- **Vendor claims:** "2–3× productivity", "2.5× storage density", "99.99% accuracy" are marketing figures — record them as vendor claims, not verified facts. (`storage_density_factor`.)
- **Rated vs. peak:** payload and speed are sometimes peak/unloaded; prefer rated values and note when unsure.
- **Blank ≠ zero:** a missing value means *unknown*, never 0. Never infer a capability is absent just because a field is empty. (Especially `reference_count`.)

---

## 13. Who the buyer actually contracts — manufacturer vs. integrator vs. OEM

Three different roles can sit behind one offering:

- **OEM / technology owner:** built the machine (may be invisible to the buyer — see §7).
- **Manufacturer/brand:** the name on the product.
- **System integrator / dealer:** designs the installation, integrates with WMS, provides service — often the buyer's actual counterpart, especially for complex systems (ASRS is almost always sold via integrators).

For matching the *commercial* counterpart, `distribution_model` and the company layer matter; for matching *technical capability*, the OEM base model matters. Keep the two questions separate.

---

## 15. Reading tender context to derive the required AGV type

Tenders rarely state the AGV type explicitly. Derive it from the *operational environment and task description*, not from isolated keywords. This section maps the most common tender contexts to the correct required_vehicle_type.

### Production / manufacturing environments — use payload and lift height, not environment alone

**Critical rule:** The environment alone (filling line, production hall, assembly) does NOT determine the AGV type. A 2,000 kg pallet on a production floor needs a Counterbalanced Forklift AGV, not a Mobile AMR. Use these discriminators:

**Payload is the primary discriminator:**
- **≤ 1,500 kg + flexible routing + SLAM navigation** → Mobile AMR
- **≥ 1,500 kg OR heavy pallets OR multiple pallet sizes** → Forklift AGV (Counterbalanced or Reach Truck)
- **Towing train, milk-run loop, multiple stops in sequence** → Tugger AGV

**Lift height is the secondary discriminator:**
- **Floor-only (lift ~200–400 mm, all stations "floor delivery")** → Counterbalanced Forklift (low-lift transport)
- **Racking / height > 2 m** → Reach Truck or VNA (see high-bay section below)
- **No lift at all (roller tops, belt tops)** → Mobile AMR with top module

**The "filling line" trap:** A filling line supply tender transporting heavy pallets (> 1,500 kg) floor-to-floor between warehouse and production stations is a **Counterbalanced Forklift AGV** task. Do not classify as Mobile AMR just because the environment is production. Check: (1) payload, (2) all stations floor-level, (3) buyer names forklift suppliers as preferred.

**Worked example — Forklift in production:** "AGV system for supplying 10 filling lines, 2,000 kg max load, all floor delivery stations, preferred suppliers: Jungheinrich and Linde" → required_vehicle_type = "Counterbalanced" (heavy load, floor-to-floor, forklift suppliers named).

**Worked example — AMR in production:** "Autonomous mobile robots for transporting empty containers between assembly workstations, max 300 kg, SLAM navigation, MES dispatching" → required_vehicle_type = "Mobile AMR" (light load, flexible routing, no fixed stations).

---

### High-bay warehouse with racking → Forklift AGV (check for VNA)

**Signals:** high-bay racking (Hochregallager), pallet racking (Palettenregal), rack positions (Stellplätze), storage and retrieval (Ein-/Auslagerung), picking lanes (Kommissioniergassen), VNA, narrow aisle (Schmalgang), warehouse management system (WMS).

**VNA check:** if aisle width < 2 m OR the words "VNA", "Schmalgang", or "turret truck" appear → required_vehicle_type = "VNA", required_vna = true, required_drive_type = "VNA Turret".

**Reach truck:** if aisle 2–3 m, lift > 4 m, racking → "Reach Truck".

**Counterbalanced:** only if aisle ≥ 3 m AND no racking involved (floor-level pallet transport, goods-in/out staging areas, flat warehouses). Counterbalanced forklifts do NOT operate in racking aisles.

---

### Wide-aisle transport / cross-docking → Counterbalanced Forklift or Tugger

**Signals:** transfer stations, dock loading (Verladung), flat warehouse, pallet buffer, goods-in/goods-out (Warenein-/ausgang), no racking mentioned, aisle ≥ 3 m.

**Counterbalanced:** if individual pallet transport between fixed floor-level stations → "Counterbalanced".
**Tugger:** if multiple loads are moved in a train along a fixed route → "Tugger AGV".

---

### Summary table (use as a checklist before setting required_vehicle_type)

| Environment signal | First candidate | Check for |
|---|---|---|
| Filling line / production hall / assembly | Mobile AMR | Tugger if milk-run |
| High-bay racking + aisle < 2 m | VNA (Forklift AGV) | required_vna = true |
| High-bay racking + aisle 2–3 m | Reach Truck (Forklift AGV) | Lift height |
| Wide-aisle warehouse, no racking | Counterbalanced | Tugger if train route |
| Trailer/dock loading | Counterbalanced or Tugger | auto_hitch |
| Goods-to-Person picking | Mobile AMR | grid_required = true |

---

## 14. Out of scope for the PoC (context, so you don't misclassify)

- **ASRS (Automated Storage and Retrieval System)** — fixed storage automation (shuttles, cube-storage like AutoStore, vertical lift modules, crane/RBG systems). Different buyer journey, different tender logic, usually sold as a whole system via integrators. Tracked as its own future main category, **not** mixed into the AGV PoC.
- **Sorter / sortation robots** — borderline with conveyor technology; excluded from the AGV PoC because buyers usually tender these as material-handling/conveyor systems, not AGVs.

If a product is clearly one of these, flag it as out-of-scope rather than forcing it into an AGV subtype.

---

*haystacked · Industry Read Me · companion to the AP0 field specification · confidential*
