#!/usr/bin/env python3
"""Apply the 2026-08-06 batch of ALREADY-DECIDED manual corrections to Airtable.

Follows scripts/import_research_20260801.py conventions:
  - Company -> Base Model -> Product -> Base Model Extension linked-record inserts
  - typecast=True so new select options are created automatically
  - live-schema quirks: AP0 Boolean fields are Airtable singleSelect "True"/"False";
    some AP0 Multi-Select fields are Airtable singleSelect with compound "A|B" choices

Scope (see docs/import_20260806_manual_notes_audit.jsonl for the full trail):
  Part 1  8 deletions (extension -> product -> base model). Companies table untouched.
  Part 2  Jungheinrich: ERC 217a + EKX 514a / 516ka / 516a (4 new products)
  Part 3  DS Automotion: 19 new products + FLEXIHAULER rename/enrich PATCH
          + AMADEUS Classic / Counter enrichment PATCHes

Usage:
    python3 scripts/import_manual_notes_20260806.py --dry-run
    python3 scripts/import_manual_notes_20260806.py --run
"""
import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT_PATH = ROOT / "docs" / "import_20260806_manual_notes_audit.jsonl"
RATE_LIMIT_SLEEP = 0.25
TODAY = "2026-08-06"


def load_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()
TOKEN = ENV["AIRTABLE_TOKEN"]
BASE_ID = ENV["AIRTABLE_BASE_ID"]

TBL = {
    "companies": "tblxZNhyTlfd1c5Po",
    "base_models": "tblsaCzUQUrC4m7lj",
    "products": "tblgizCLjKYcCAbwp",
    "extensions": "tblinb1Zn0Ihc977M",
}

CO_JUNGHEINRICH = "recoAvZXd1iBbz0KJ"
CO_DS = "recjVkDGpP36pQokQ"

DRY = True


# --------------------------------------------------------------------------- API
def _req(method, url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    })
    for _ in range(5):
        try:
            with urllib.request.urlopen(req) as resp:
                out = json.loads(resp.read())
            time.sleep(RATE_LIMIT_SLEEP)
            return out
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if e.code == 429:
                time.sleep(2)
                continue
            raise RuntimeError(f"{method} {url} -> {e.code} {body}") from e
    raise RuntimeError(f"retries exhausted: {method} {url}")


def get(tbl, rec_id):
    return _req("GET", f"https://api.airtable.com/v0/{BASE_ID}/{TBL[tbl]}/{rec_id}")


def create(tbl, fields):
    if DRY:
        print(f"    DRY create {tbl}: {json.dumps(fields, ensure_ascii=False)[:260]}")
        return {"id": f"rec_DRY_{tbl}"}
    return _req("POST", f"https://api.airtable.com/v0/{BASE_ID}/{TBL[tbl]}",
                {"records": [{"fields": fields}], "typecast": True})["records"][0]


def patch(tbl, rec_id, fields):
    if DRY:
        print(f"    DRY patch {tbl} {rec_id}: {json.dumps(fields, ensure_ascii=False)[:260]}")
        return {"id": rec_id}
    return _req("PATCH", f"https://api.airtable.com/v0/{BASE_ID}/{TBL[tbl]}",
                {"records": [{"id": rec_id, "fields": fields}], "typecast": True})["records"][0]


def delete(tbl, rec_id):
    if DRY:
        print(f"    DRY delete {tbl} {rec_id}")
        return {"deleted": True, "id": rec_id}
    return _req("DELETE", f"https://api.airtable.com/v0/{BASE_ID}/{TBL[tbl]}/{rec_id}")


def audit(entry):
    entry = {"ts": TODAY, **entry}
    print("  AUDIT " + json.dumps(entry, ensure_ascii=False)[:200])
    if not DRY:
        with AUDIT_PATH.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------- Part 1
DELETIONS = [
    # (label, extension, product, base_model, reason)
    ("SAFELOG AGV L1", "recw7fHNv5ux3J7Md", "rechKCQGnekjWCjaD", "recyXCBFIDlEVcuzN",
     "no longer listed on safelog.de; user confirmed removal"),
    ("Grenzebach FL1200S", "recZdeF5N3Csgr3tS", "recw9kWORrxGUwC3s", "rec9sALtMQMaP7nvn",
     "user confirmed deletion (no local datasheet PDF)"),
    ("Grenzebach L600", "recBQC4kxR8GOabGA", "recg9GzBjqutceerZ", "recpjifkAgzC4d8Gp",
     "user confirmed deletion (Grenzebach-branded only; Youibot L600 recEhGJiF1dNMKpKS untouched)"),
    ("DS ARNY (generic)", "reclw1DHLEJnWmTdG", "recgSv6KWiNjcGtVl", "recpnmj1CveM47l1L",
     "replaced by 4 ARNY variants"),
    ("DS OSCAR (generic)", "recoTbv9ChMsu0Etj", "recCYPqmsfvzh7Hcp", "rechGJ72f5kcuXJfi",
     "replaced by 4 OSCAR variants"),
    ("DS SALLY (generic)", "recTwmTU1Z44x32x4", "recckWiaNif9yMC9q", "rec7J4Z8BzlVFJuBw",
     "replaced by 3 SALLY variants"),
    ("DS Automotion AMY (generic)", "recxyZFtkob4xql4c", "recZaqpTPwWqsQepq", "recq54tw9Kza7mvU2",
     "replaced by 2 AMY variants (AMY Flap skipped: no specs given)"),
    ("Jungheinrich EKX 516a / 516ka", "recZj2rKeKlVrgysD", "recac2jti0Bm6exnP", "recHbKZxoL0rspfzs",
     "merged record split into EKX 514a / 516ka / 516a"),
]


def run_deletions():
    print("== PART 1: DELETIONS ==")
    for label, ext, prod, bm, reason in DELETIONS:
        print(f"  [{label}]")
        before = {}
        for tbl, rid in (("extensions", ext), ("products", prod), ("base_models", bm)):
            before[tbl] = {"airtable_id": rid, "fields": get(tbl, rid)["fields"]}
        audit({"op": "delete", "label": label, "reason": reason, "before": before})
        for tbl, rid in (("extensions", ext), ("products", prod), ("base_models", bm)):
            delete(tbl, rid)
            print(f"    deleted {tbl} {rid}")


# ------------------------------------------------------------ create helper
def create_product(company_rec, bm_name, product_name, product_type, ext_fields,
                   source_notes, product_description=None,
                   distribution_model=None, service_coverage=None, batch=""):
    bm_uuid = str(uuid.uuid4())
    bm = create("base_models", {
        "base_model_name": bm_name,
        "base_model_id": bm_uuid,
        "product_type": product_type,
        "oem_link_public": True,
        "last_updated": TODAY,
        "oem_company_id": [company_rec],
    })
    prod_uuid = str(uuid.uuid4())
    pf = {
        "product_name": product_name,
        "product_id": prod_uuid,
        "product_type": product_type,
        "is_oem_product": True,
        "active": True,
        "source_notes": source_notes[:9000],
        "company_id": [company_rec],
        "base_model_id": [bm["id"]],
    }
    if product_description:
        pf["product_description"] = product_description
    if distribution_model:
        pf["distribution_model"] = distribution_model
    if service_coverage:
        pf["service_coverage"] = service_coverage
    prod = create("products", pf)

    ext_uuid = str(uuid.uuid4())
    ef = dict(ext_fields)
    ef.update({
        "model_name": bm_name,
        "extension_id": ext_uuid,
        "product_type": product_type,
        "base_model_id": [bm["id"]],
        "source_notes": source_notes[:9000],
    })
    ef = {k: v for k, v in ef.items() if v is not None}
    ext = create("extensions", ef)

    audit({"op": "create", "batch": batch, "product_name": product_name,
           "base_model_name": bm_name, "product_type": product_type,
           "airtable": {"base_model": bm["id"], "product": prod["id"], "extension": ext["id"]},
           "uuids": {"base_model_id": bm_uuid, "product_id": prod_uuid, "extension_id": ext_uuid},
           "extension_fields": ef, "product_fields": pf})
    print(f"    -> bm={bm['id']} prod={prod['id']} ext={ext['id']}")
    return bm["id"], prod["id"], ext["id"]


# --------------------------------------------------------------------- Part 2
JH_SVC = ["EU", "Global"]
JH_DIST = "Direct|Dealer Network"

# cloned verbatim from the live "Jungheinrich ERC 213a" extension (reczlwgLcdzq3KVv1)
ERC_CLONE = {
    "vna_capable": "False",
    "grid_required": "False",
    "navigation_type": ["Laser Reflector", "Natural Feature (SLAM)"],
    "stacking_capability": "True",
    "battery_type": ["Li-Ion"],
    "autonomous_charging": True,
    "load_type": ["Pallet EUR"],
    "safety_standard": ["ISO 3691-4"],
    "fleet_management_system": "Proprietary",
    "integration_capability": ["SAP", "WMS"],
    "industries_served": ["General Manufacturing"],
    "manual_usage": True,
    "drive_type": "Reach Truck",
    "drop_accuracy_lat": 20,
    "pick_req_accuracy_lat": 20,
    "min_total_height": 2150,
    "lifting_height": 4400,
}

# cloned verbatim from the deleted "Jungheinrich EKX 516a / 516ka" extension (recZj2rKeKlVrgysD)
EKX_SHARED = {
    "vna_capable": "True",
    "grid_required": "False",
    "navigation_type": ["Laser Reflector", "QR/DM Code", "Inductive Loop"],
    "stacking_capability": "True",
    "battery_type": ["Li-Ion"],
    "infrastructure_free": "False",
    "autonomous_charging": True,
    "load_type": ["Pallet EUR", "Pallet ISO"],
    "safety_standard": ["ISO 3691-4"],
    "fleet_management_system": "Proprietary",
    "integration_capability": ["SAP", "WMS"],
    "industries_served": ["General Manufacturing", "3PL"],
    "min_aisle_width": 1727,
    "manual_usage": True,
    "mast_type": "Triplex",
    "drive_type": "VNA Turret",
    "special_fork_option": ["Telescopic"],
    "guidance": ["Wire"],
    "busbar_compatible": True,
}

EKX_VARIANTS = [
    # name, payload, lift, speed_kmh, l1_mm
    ("EKX 514a", 1400, 13000, 10.5, 3665),
    ("EKX 516ka", 1600, 12000, 12.0, 3775),
    ("EKX 516a", 1600, 13000, 12.0, 4045),
]

EKX_NOTE = (
    "Manual note from user research, 2026-08-06. Full table: payload/lift-height/speed/"
    "length-figure/voltage as given; split out from previously-merged EKX 516a/516ka record. "
    "{name}: {pay} kg / {lift} mm Hubhoehe / {kmh} km/h / {l1} mm / 80 V. "
    "UNIT CONVERSION: max_speed stored as {ms} m/s ({kmh} km/h / 3.6) -- the DB stores max_speed "
    "in m/s (AP0 unit), the user's note is in km/h. "
    "FIELD MAPPING of the 5th figure ({l1} mm): mapped to vehicle_length, NOT min_total_height. "
    "Confirmed against the local official Jungheinrich VDI-2198 spec sheet "
    "Datasheets/AGV_AMR/New/ekx-5a-20xx-specsheet-de-2026-08-pdf-data.pdf p.8 line 4.19 "
    "'Gesamtlaenge l1 mm 3665 / 3775 / 4045' for EKX 514a / 516ka / 516a. "
    "min_total_height (h1, Hubgeruest eingefahren) is ~5950 mm at 13000 mm lift per the same "
    "sheet and is deliberately left NULL here (config-dependent, outside this batch's scope). "
    "Battery voltage 80 V: no AP0 field exists -- recorded here only. "
    "battery_type Li-Ion cloned from the merged predecessor record; the VDI sheet's standard "
    "config is 80 V PzS lead-acid (3 PzS 465 / 4 PzS 620 / 6 PzS 930) -- FLAGGED for review."
)


def run_jungheinrich():
    print("== PART 2: JUNGHEINRICH ==")

    # A) ERC 217a
    ext = dict(ERC_CLONE)
    ext["max_payload"] = 1700
    ext["max_speed"] = 1.94  # 7 km/h / 3.6
    notes = (
        "Manual note from user research, 2026-08-06: like ERC 213a but 7 km/h and 1700 kg payload. "
        "All other field values cloned 1:1 from the sibling record 'Jungheinrich ERC 213a' "
        "(extension reczlwgLcdzq3KVv1). "
        "NAME CORRECTION: the user's note reads 'ECR217a'; corrected to 'ERC 217a' (letter swap). "
        "Confirmed by the local official Jungheinrich factsheet "
        "Datasheets/AGV_AMR/New/erc-2a-2019-factsheet-de-2026-05-pdf-data.pdf p.4: "
        "'ERC 217a | 1700 kg | 4400 mm | 7 km/h'. "
        "UNIT CONVERSION: max_speed stored as 1.94 m/s (7 km/h / 3.6); the DB stores max_speed in "
        "m/s per AP0, the user's note is in km/h. "
        "min_total_height 2150 cloned from ERC 213a = h1 at the lowest mast config; "
        "battery_type Li-Ion cloned from ERC 213a (VDI sheet standard config is 24 V / 375 Ah "
        "3 PzS lead-acid) -- FLAGGED for review."
    )
    print("  [ERC 217a]")
    create_product(CO_JUNGHEINRICH, "Jungheinrich ERC 217a", "ERC 217a", "Forklift AGV",
                   ext, notes,
                   product_description="Automated reach truck (Mobile Robot); 1700 kg; 4400 mm lift; 7 km/h",
                   distribution_model=JH_DIST, service_coverage=JH_SVC, batch="jungheinrich")

    # B) EKX split
    for name, pay, lift, kmh, l1 in EKX_VARIANTS:
        ext = dict(EKX_SHARED)
        ext["max_payload"] = pay
        ext["lifting_height"] = lift
        ext["max_speed"] = round(kmh / 3.6, 2)
        ext["vehicle_length"] = l1
        notes = EKX_NOTE.format(name=name, pay=pay, lift=lift, kmh=kmh, l1=l1,
                                ms=round(kmh / 3.6, 2))
        print(f"  [{name}]")
        create_product(CO_JUNGHEINRICH, f"Jungheinrich {name}", name, "Forklift AGV",
                       ext, notes,
                       product_description=f"Automated tri-lateral VNA turret truck; {pay} kg; "
                                           f"up to {lift} mm lift; wire guidance + RFID transponder",
                       distribution_model=JH_DIST, service_coverage=JH_SVC, batch="jungheinrich")


# --------------------------------------------------------------------- Part 3
DS_SVC = ["EU", "Global"]
DS_DIST = "Direct"

# Company-wide defaults, sourced from the 4 permitted ds-automotion.com technology pages
# plus the surviving/replaced sibling records.
DS_DEFAULTS = {
    "safety_standard": ["ISO 3691-4"],
    "functional_safety_level": "PLd",
    "fleet_control_architecture": "Centralized",
    "fleet_management_system": "VDA 5050 compatible|Open API",
    "vda5050_compatible": "True",
    "integration_capability": ["SAP", "WMS", "REST API", "OPC-UA", "MQTT"],
    "vna_capable": "False",
    "grid_required": "False",
    "industries_served": ["General Manufacturing"],
}

DS_SRC = (
    "Manual note from user research, 2026-08-06. "
    "Company-wide values from the 4 permitted ds-automotion.com technology pages: "
    "safety_standard ISO 3691-4 (DIN EN ISO 3691-4 + DIN EN 1525 named on /technologie/"
    "sicherheitstechnik/); functional_safety_level PLd ('nach EN Norm und Performance Level d "
    "produziert'); vda5050_compatible True ('Als einer von wenigen Herstellern bieten wir die "
    "VDA 5050 Schnittstelle...' on /technologie/sps-technologie/); integration_capability "
    "OPC-UA + MQTT from the same page (SAP|WMS|REST API carried over from the sibling DS records). "
    "industries_served 'General Manufacturing' = carried-over company default, not per-product "
    "evidence. "
)


def ds(**kw):
    f = dict(DS_DEFAULTS)
    f.update(kw)
    return f


def run_ds_automotion():
    print("== PART 3: DS AUTOMOTION ==")

    items = []  # (bare_name, product_type, ext_fields, extra_notes, description)

    # ---------------- AMADEUS variants (Forklift AGV) ----------------
    amadeus_energy_note = (
        "Energieversorgung: automatisches Laden + manueller Batteriewechsel. "
        "Batterie Li-NMC (24 V / 208 Ah / 312 Ah) oder Blei/Reinblei/Blei-Gel (24 V / 375 Ah) "
        "-> battery_type ['Li-Ion','Lead-Acid'] (Li-NMC ist eine Li-Ion-Chemie; AP0 kennt kein "
        "'NMC'). AC-Antriebe, 360 Grad Laserscanner. "
    )

    items.append((
        "AMADEUS Wide", "Forklift AGV",
        ds(max_payload=2000, max_speed=1.8, lifting_height=2880,
           navigation_type=["Laser Reflector", "Natural Feature (SLAM)"],
           autonomous_charging=True, battery_swap_capable=True,
           battery_type=["Li-Ion", "Lead-Acid"],
           load_type=["Pallet EUR", "Pallet ISO", "Custom Carrier"],
           drive_type="Straddle Stacker", stacking_capability="True"),
        "Nutzlast max 1,5 t / 2,0 t -> max_payload = 2000 (die 1,5-t-Konfiguration ist die "
        "kleinere Variante). Hubhoehe Monomast 85-1200 mm / Duplex-Mast 85-2880 mm -> "
        "lifting_height = 2880 (Maximum; Monomast-Variante 1200 mm). "
        + amadeus_energy_note +
        "Einsatz: Paletten/Gitterboxen quer, Gestelle mit Staplerlaschen, Bodenstellplaetze, "
        "Uebergabestationen. 'Gitterbox' und 'Gestelle mit Staplerlaschen' haben keinen eigenen "
        "AP0 load_type-Wert -> als 'Custom Carrier' abgebildet (identisch zum Schwester-Datensatz "
        "AMADEUS Classic). drive_type 'Straddle Stacker' uebernommen vom Schwester-Datensatz "
        "AMADEUS Classic (Radarm-Bauform) -- JUDGMENT CALL.",
        "Driverless high-lift stacker, wide track; up to 2 t; up to 2,880 mm lift; laser+SLAM",
    ))

    items.append((
        "AMADEUS Low", "Forklift AGV",
        ds(max_payload=2000, max_speed=1.8, lifting_height=100,
           vehicle_length=3400, vehicle_width=953, min_total_height=2379,
           navigation_type=["Contour", "Laser Reflector"],
           autonomous_charging=True, battery_swap_capable=True,
           battery_type=["Li-Ion", "Lead-Acid"],
           load_type=["Pallet EUR", "Pallet ISO"],
           drive_type="Pallet Mover", stacking_capability="False"),
        "Abmessungen L 3400 x B 953 x H 2379 mm. Hubhoehe max 100 mm. Nutzlast max 2,0 t. "
        "Lastaufnahme Paletten-Gabel 2350 mm (keine AP0-Entsprechung -> nur hier notiert). "
        "Geschwindigkeit max 1,8 m/s. Navigation: Kontur, Laser. "
        "Energieversorgung automatisches Laden + Batteriewechsel. "
        "Batterie Li-NMC (24 V / 208 Ah) / Blei-Gel (24 V / 375 Ah). "
        "drive_type 'Pallet Mover' und stacking_capability=False abgeleitet aus 100 mm Hubhoehe "
        "(Niederhub kann nicht stapeln) -- JUDGMENT CALL.",
        "Driverless low-lift pallet mover; 2 t; 100 mm lift; 2,350 mm forks; contour+laser nav",
    ))

    items.append((
        "AMADEUS Grip", "Forklift AGV",
        ds(max_payload=2000, max_speed=1.8, lifting_height=2880,
           navigation_type=["Laser Reflector", "Natural Feature (SLAM)"],
           autonomous_charging=True, battery_swap_capable=True,
           battery_type=["Li-Ion", "Lead-Acid"],
           stacking_capability="True"),
        "Nutzlast max 1,2 t / 2,0 t -> max_payload = 2000. Geschwindigkeit/Hubhoehe/Navigation/"
        "Energie/Batterie wie AMADEUS Wide. " + amadeus_energy_note +
        "Einsatz: Styroporblocke, Baustoffe. KEIN passender AP0-Wert in industries_served "
        "(weder 'Construction' noch 'Building Materials' existieren) -> Company-Default "
        "'General Manufacturing' gesetzt, echter Einsatzbereich nur hier notiert. "
        "special_fork_option BEWUSST NULL: Modellname 'grip' + Styroporblocke legen ein "
        "Klammer-/Greifanbaugerat ('Clamp') nahe, der Quelltext nennt es aber nicht explizit -- "
        "COND_KO-Feld, daher NULL statt Rateversuch. drive_type ebenfalls NULL (nicht belegt). "
        "load_type NULL (Styroporblocke/Baustoffe passen auf keinen AP0-Wert).",
        "Driverless AGV with gripping attachment for styrofoam blocks / building materials; 2 t",
    ))

    items.append((
        "AMADEUS Rack", "Forklift AGV",
        ds(max_payload=2200, max_speed=1.8, lifting_height=350,
           navigation_type=["Contour"],
           autonomous_charging=True,
           battery_type=["Li-Ion"],
           load_type=["Custom Carrier"],
           stacking_capability="False"),
        "Nutzlast max 2,2 t. Geschwindigkeit max 1,8 m/s. Hubhoehe 350 mm. "
        "Navigation: konturbasierte Lokalisierung -> 'Contour'. "
        "Energieversorgung: automatisches Laden (KEIN Batteriewechsel genannt -> "
        "battery_swap_capable bleibt NULL, nicht False -- Blank != Zero). "
        "Batterie 'Lithium' ohne Chemie-Angabe -> 'Li-Ion' (naechstliegender AP0-Wert). "
        "AC-Antriebe, 360 Grad Laserscanner. Einsatz: Transport von Serverschraenken -> "
        "load_type 'Custom Carrier'; kein AP0-Wert fuer 'IT/Data Center' in industries_served -> "
        "Company-Default gesetzt, echter Einsatzbereich nur hier notiert. "
        "stacking_capability=False abgeleitet aus 350 mm Hubhoehe -- JUDGMENT CALL. "
        "drive_type NULL (nicht belegt).",
        "Driverless server-rack transporter; 2.2 t; 350 mm lift; contour navigation",
    ))

    # ---------------- ARNY variants (Forklift AGV) ----------------
    arny_shared = dict(
        max_speed=1.5,
        navigation_type=["Contour", "Magnetic Tape", "Laser Reflector"],
        autonomous_charging=True, battery_swap_capable=True,
        battery_type=["Lead-Acid", "LiFePO4"],
        safety_coverage="Full 3D (360° + 3D sensors)",
        load_detection=["Camera/Vision"],
        drive_type="Counterbalanced",
        special_fork_option=["Side-Shift"],
        stacking_capability="True",
        forks_free_floating="True",
        manual_usage=True,
        load_type=["Pallet EUR", "Pallet ISO"],
        industries_served=["Automotive", "General Manufacturing"],
    )
    arny_note = (
        "Gemeinsam fuer alle ARNY-Varianten: Gabelausfuehrung ISO-Gabeltraeger, geschmiedete "
        "Zinken; optional Seitenschub / Neigungsverstellung / Zinkenverstellung -> "
        "special_fork_option ['Side-Shift'] (Seitenschub); Neigungs- und Zinkenverstellung haben "
        "keinen AP0-Wert. Navigation: Kontur-/Magnet-/Laser-/Hybridnavigation -> "
        "['Contour','Magnetic Tape','Laser Reflector'] ('Hybrid' = Kombination, kein eigener Wert). "
        "Energieversorgung: Batteriewechsel manuell oder automatisches Laden. "
        "Batterie Blei-Saeure / Reinblei / Lithium (LFP) -> ['Lead-Acid','LiFePO4']. "
        "3 Sicherheitslaserscanner 360 Grad -> safety_standard ISO 3691-4, safety_coverage "
        "'Full 3D (360 + 3D sensors)'. 3 ToF-Kameras in Hauptfahrtrichtung -> load_detection "
        "'Camera/Vision' (Muster des Schwester-Datensatzes DS AMADEUS Classic). "
        "drive_type 'Counterbalanced', load_type, forks_free_floating, manual_usage und "
        "industries_served aus dem ersetzten Sammel-Datensatz 'DS ARNY' uebernommen. "
        "HINWEIS: der ersetzte Sammel-Datensatz fuehrte 2500 kg / 8500 mm -- diese Werte werden "
        "durch die Variantentabelle abgeloest. "
    )
    for nm, pay, lift, mast, dead in [
        ("ARNY Mono", 1500, 1500, "Simplex", 4200),
        ("ARNY Duplex", 1200, 4500, "Duplex", 4800),
        ("ARNY Triplex", 1000, 7400, "Triplex", 5600),
        ("ARNY HD Triplex", 1000, 10800, "Triplex", 5990),
    ]:
        extra = (
            f"{nm}: Nutzlast {pay} kg, Hubhoehe {lift} mm, Geschwindigkeit 1,5 m/s, "
            f"Leergewicht ohne Batterie {dead} kg (kein AP0-Feld -> nur hier notiert). "
        )
        if mast == "Simplex":
            extra += ("mast_type: Quelltext sagt 'Monomast'; AP0 kennt nur Simplex/Duplex/"
                      "Triplex/Quadruplex -> auf 'Simplex' abgebildet (einstufiger Mast) -- "
                      "JUDGMENT CALL. ")
        if nm.startswith("ARNY HD"):
            extra += ("'HD' (High-Duty) hat keinen eigenen AP0-Enumwert -- die Variante ist nur "
                      "ueber den Produktnamen und diese Notiz unterscheidbar. ")
        items.append((nm, "Forklift AGV",
                      ds(max_payload=pay, lifting_height=lift, mast_type=mast, **arny_shared),
                      arny_note + extra,
                      f"Driverless counterbalanced forklift, {mast.lower()} mast; {pay} kg; "
                      f"up to {lift} mm lift"))

    # ---------------- OSCAR variants (Mobile AMR) ----------------
    oscar_shared = dict(
        max_speed=1.6,
        navigation_type=["Contour", "Magnetic Tape"],
        stacking_capability="False",
        rotation_capable=True,
        min_turning_radius=0,
        workflow_capability=["Transport"],
        picking_mechanism="None",
        top_module_type=["Lift"],
        autonomous_obstacle_bypass=True,
        infrastructure_free="True",
        autonomous_charging=True,
        load_type=["Roll Container", "Custom Carrier"],
    )
    oscar_note = (
        "Gemeinsam fuer alle OSCAR-Varianten: Navigation 'Freinavigierend mittels konturbasierter "
        "Lasernavigation (KBL) und optional Magnetpunktnavigation' -> ['Contour','Magnetic Tape'] "
        "(AP0 hat keinen Wert fuer Magnet-PUNKTE, nur 'Magnetic Tape' -- naechstliegend). "
        "min_turning_radius 0 und rotation_capable=True: 'spin' = Drehen auf der Stelle, "
        "'omni' = holonom; Wert aus dem ersetzten Sammel-Datensatz 'DS OSCAR' uebernommen. "
        "top_module_type ['Lift'] abgeleitet aus der Hub-Angabe -- JUDGMENT CALL. "
        "load_type, infrastructure_free, autonomous_obstacle_bypass, autonomous_charging, "
        "workflow_capability und picking_mechanism aus dem ersetzten Sammel-Datensatz uebernommen. "
        "Die Hoehenangabe H (Groesse LxBxH) ist bei Unterfahr-AMR das Feld min_ground_clearance "
        "(= Gesamthoehe/Unterfahrhoehe des Roboters), belegt durch den Vorgaenger-Datensatz "
        "(min_ground_clearance 320 = H des OSCAR omni). "
    )
    for nm, lift_h, gc, L, W, pay, batt, omni, extra_note in [
        ("OSCAR Spin 180", 80, 260, 1620, 560, None, None, None,
         "Schutzfeld 180 Grad (nicht 360). Batterie 48 V / 30 Ah. "
         "KEINE Nutzlast im Quelltext -> max_payload bleibt NULL (KO-Feld, nicht raten). "
         "battery_type NULL: nur Spannung/Kapazitaet genannt, keine Chemie. "
         "Das 180-Grad-Schutzfeld hat kein passendes AP0-Feld (safety_coverage beschreibt 2D/3D, "
         "nicht die horizontale Abdeckung) -> nur hier notiert. "
         "omnidirectional_movement NULL ('spin' = Drehen auf der Stelle, nicht zwingend holonom)."),
        ("OSCAR Spin 360", 130, 295, 1670, 700, None, None, None,
         "Schutzfeld 360 Grad rundum. Batterie 48 V / 30 Ah. "
         "KEINE Nutzlast im Quelltext -> max_payload bleibt NULL. battery_type NULL (keine Chemie). "
         "omnidirectional_movement NULL ('spin' = Drehen auf der Stelle)."),
        ("OSCAR Omni", 160, 320, 1520, 720, 1000, ["LiFePO4"], True,
         "Nutzlast 1,0 t. Batterie LFP -> 'LiFePO4'. Automatisches Laden. "
         "omnidirectional_movement=True ('omni' = holonom)."),
        ("OSCAR Omni XL", 200, 380, 1700, 900, 1250, None, True,
         "Nutzlast 1,25 t. Sicherheitsscanner 360 Grad -> safety_standard ISO 3691-4. "
         "Batterie 24 V / 120 Ah (Chemie nicht genannt -> battery_type NULL). "
         "Automatisches Laden. omnidirectional_movement=True."),
    ]:
        f = ds(lift_height=lift_h, min_ground_clearance=gc, vehicle_length=L, vehicle_width=W,
               **oscar_shared)
        if pay is not None:
            f["max_payload"] = pay
        if batt is not None:
            f["battery_type"] = batt
        if omni is not None:
            f["omnidirectional_movement"] = omni
        items.append((nm, "Mobile AMR", f, oscar_note + f"{nm}: " + extra_note,
                      f"Underride AMR, {lift_h} mm lift; contour laser navigation"))

    # ---------------- AMY variants (Mobile AMR) ----------------
    amy_shared = dict(
        max_payload=25, max_speed=1.8,
        navigation_type=["Contour"],
        battery_type=["LiFePO4"],
        stacking_capability="False",
        rotation_capable=True,
        infrastructure_free="True",
        autonomous_charging=True,
    )
    amy_note = (
        "Gemeinsam AMY: Navigation konturbasiert -> 'Contour'. Kommunikation WLAN (kein AP0-Wert "
        "in integration_capability -> nur hier notiert). Schutzsystem Laserscanner vorne + hinten, "
        "optionale Kamera -> safety_standard ISO 3691-4. Geschwindigkeit 1,8 m/s. "
        "Batterietyp LFP -> 'LiFePO4'. Nutzlast 25 kg. "
        "vda5050_compatible, infrastructure_free, autonomous_charging und rotation_capable aus dem "
        "ersetzten Sammel-Datensatz 'DS Automotion AMY' uebernommen. "
        "HINWEIS: der Vorgaenger fuehrte navigation_type 'Natural Feature (SLAM)'; der neue "
        "Quelltext sagt 'konturbasiert' -> auf 'Contour' geaendert (Konvention der DS-Geschwister). "
        "Variante 'AMY Flap' wurde bewusst NICHT angelegt (keine Specs vorhanden). "
    )
    items.append((
        "AMY Deck", "Mobile AMR",
        ds(vehicle_length=690, vehicle_width=453, **amy_shared),
        amy_note + "AMY Deck: L 690 x B 453 mm. Hoehe 600-900 mm (Bereich!) -> "
                   "min_ground_clearance bleibt NULL, weil das Integer-Feld keine Spanne abbilden "
                   "kann. Eigengewicht 60 kg (kein AP0-Feld). "
                   "top_module_type NULL ('Deck' passt auf keinen AP0-Wert sauber).",
        "Compact small-load AMR with flat deck; 25 kg; 1.8 m/s; contour navigation",
    ))
    items.append((
        "AMY Lift", "Mobile AMR",
        ds(vehicle_length=640, vehicle_width=520, min_ground_clearance=580,
           top_module_type=["Lift"], **amy_shared),
        amy_note + "AMY Lift: L 640 x B 520 x H 580 mm. 'Aktiv gesteuerte HubKamm-Lastaufnahme' -- "
                   "bedient passive Uebergabestationen und stationaere Foerdertechnik "
                   "-> top_module_type ['Lift']; die Foerdertechnik-Anbindung hat keinen "
                   "AP0-Wert in integration_capability. Eigengewicht 60 kg (kein AP0-Feld). "
                   "lift_height NULL (Hubhoehe nicht angegeben).",
        "Compact small-load AMR with active lifting comb; 25 kg; serves passive transfer stations",
    ))

    # ---------------- SALLY variants (Mobile AMR) ----------------
    sally_shared = dict(
        battery_type=["LiFePO4"],
        stacking_capability="False",
        omnidirectional_movement=True,
        min_turning_radius=0,
        picking_mechanism="None",
        workflow_capability=["Transport"],
        autonomous_obstacle_bypass=True,
        infrastructure_free="True",
        autonomous_charging=True,
        load_type=["Tote", "Custom Carrier"],
        industries_served=["General Manufacturing", "3PL", "Pharma"],
    )
    sally_note = (
        "Gemeinsam SALLY: Batterie LiFePo4 -> 'LiFePO4'. "
        "omnidirectional_movement, min_turning_radius, load_type, industries_served, "
        "infrastructure_free, autonomous_charging, autonomous_obstacle_bypass, "
        "workflow_capability und picking_mechanism aus dem ersetzten Sammel-Datensatz "
        "'DS SALLY' uebernommen. "
    )
    items.append((
        "SALLY", "Mobile AMR",
        ds(max_payload=100, max_speed=1.6,
           navigation_type=["Contour", "Natural Feature (SLAM)"],
           top_module_type=["Custom"], **sally_shared),
        sally_note + "SALLY (Basis): 100 kg, 1,6 m/s, Navigation autonom oder KBL -> "
                     "['Contour','Natural Feature (SLAM)'].",
        "Compact mini-AMR; 100 kg; 1.6 m/s; autonomous or contour-based navigation",
    ))
    items.append((
        "SALLY Kurier", "Mobile AMR",
        ds(max_payload=50, max_speed=1.0,
           navigation_type=["Contour"],
           top_module_type=["Custom"], **sally_shared),
        sally_note + "SALLY Kurier: 50 kg, 1,0 m/s, Navigation autonom mittels KBL "
                     "(kein SLAM genannt) -> ['Contour'].",
        "Courier variant of SALLY; 50 kg; 1.0 m/s; contour-based navigation",
    ))
    items.append((
        "SALLY Rollgang", "Mobile AMR",
        ds(max_payload=100, max_speed=1.6,
           navigation_type=["Contour", "Natural Feature (SLAM)"],
           top_module_type=["Roller"], **sally_shared),
        sally_note + "SALLY Rollgang: identisch zur Basis-SALLY (100 kg, 1,6 m/s), aber mit "
                     "Rollgang-/Foerderaufbau -> top_module_type ['Roller'].",
        "SALLY with roller-conveyor top module; 100 kg; 1.6 m/s",
    ))

    # ---------------- ROLLGANG (Mobile AMR, new base model) ----------------
    rollgang_shared = dict(
        navigation_type=["Contour", "Natural Feature (SLAM)"],
        autonomous_charging=True,
        battery_type=["Lead-Acid", "Li-Ion"],
        load_type=["Pallet EUR", "Pallet ISO"],
        top_module_type=["Roller"],
        stacking_capability="False",
        infrastructure_free="True",
    )
    rollgang_note = (
        "Gemeinsam ROLLGANG: Navigation KBL / SLAM -> ['Contour','Natural Feature (SLAM)']. "
        "Automatisches Laden. Sicherheit ISO 3691-4. Einsatz: Palettentransport EPAL/IPAL von "
        "Foerdertechnik zu Foerdertechnik -> load_type ['Pallet EUR','Pallet ISO'], "
        "top_module_type ['Roller']. Neues Base Model (existierte bisher nicht). "
        "lift_height NULL: das Fahrzeug hat keinen Hub, die Uebergabe erfolgt horizontal ueber "
        "den Rollgang. "
    )
    items.append((
        "ROLLGANG Mono", "Mobile AMR",
        ds(max_payload=1250, max_speed=1.6, **rollgang_shared),
        rollgang_note + "ROLLGANG Mono: Nutzlast 1250 kg, 1,6 m/s. Uebergabehoehe 500 mm oder "
                        "hoeher (kein sauber passendes AP0-Feld -> nur hier notiert). "
                        "Batterie Blei-Gel 24 V / 240 Ah oder Lithium 24 V / 120 Ah -> "
                        "['Lead-Acid','Li-Ion'].",
        "Roller-conveyor AMR for pallet transfer between conveyors; 1,250 kg; 1.6 m/s",
    ))
    items.append((
        "ROLLGANG Doppel", "Mobile AMR",
        ds(max_payload=2500, max_speed=1.2, battery_swap_capable=True, **rollgang_shared),
        rollgang_note + "ROLLGANG Doppel: Nutzlast 2500 kg, 1,2 m/s. Uebergabehoehe 530 mm oder "
                        "hoeher (kein sauber passendes AP0-Feld -> nur hier notiert). "
                        "Manueller Batteriewechsel -> battery_swap_capable=True. "
                        "Batterie Blei-Gel 48 V / 250 Ah oder Lithium 48 V / 150 Ah -> "
                        "['Lead-Acid','Li-Ion'].",
        "Double roller-conveyor AMR for pallet transfer; 2,500 kg; 1.2 m/s",
    ))

    for bare, ptype, ext, extra, desc in items:
        print(f"  [{bare}]")
        create_product(CO_DS, f"DS {bare}", bare, ptype, ext, DS_SRC + extra,
                       product_description=desc,
                       distribution_model=DS_DIST, service_coverage=DS_SVC,
                       batch="ds_automotion")


# ------------------------------------------------------------------- PATCHes
def run_patches():
    print("== PATCHES ==")

    # --- FLEXIHAULER: rename + enrich (never delete/recreate) ---
    before_ext = get("extensions", "rec9E0XxkjrTYrkLF")["fields"]
    before_prod = get("products", "recXGEd8bUTkwFAyU")["fields"]
    before_bm = get("base_models", "recnDArplXNN16si3")["fields"]

    fh_notes = (
        "Manual note from user research, 2026-08-06. Fahrzeugtyp: Differential FTF "
        "(kein AP0-Wert -- drive_type ist Forklift-scoped und kennt nur Counterbalanced/"
        "Reach Truck/Straddle Stacker/Pallet Mover/VNA Turret -> nur hier notiert). "
        "Abmessungen L 1750 x B 608 x H 380 mm (H mit Hubdorn eingefahren/ausgefahren; fuer "
        "Tugger AGV existiert kein Hoehenfeld in AP0 -> nur hier notiert). "
        "Nutzlast 1000 kg (unveraendert). Geschwindigkeit vorwaerts 1,2 m/s (unveraendert), "
        "manuell rueckwaerts. Lastaufnahmemittel 'Elektromechanischer Mitnahmedorn' -> "
        "coupling_type ['Retractable Pin'] (JUDGMENT CALL: Mitnahmedorn = ein- und ausfahrbarer "
        "Dorn; 'Automatic' wurde bewusst NICHT ergaenzt). Hubhoehe Dorn 80 mm: fuer product_type "
        "'Tugger AGV' existiert weder lift_height (AMR-scoped) noch lifting_height "
        "(Forklift-scoped) -> nur hier notiert, kein Out-of-Scope-Feld geschrieben. "
        "Lastwechsel automatisch -> auto_hitch=True. Docking unter mobile Gestelle -> "
        "train_configuration 'Underride/Mouse'. "
        "KONFLIKT NICHT UEBERSCHRIEBEN: Quelltext sagt Navigation 'Spurgefuehrt, optional frei "
        "navigierend'; der bestehende Datensatz fuehrt navigation_type 'Natural Feature (SLAM)'. "
        "Da der Quelltext die Spurart (Magnetband? Induktiv?) nicht nennt, wurde navigation_type "
        "UNVERAENDERT gelassen und der Widerspruch hier + im Audit-Log geflaggt. "
        "Umbenannt von 'DS Automotion FLEXIHAULER' -> product_name 'FLEXIHAULER' / "
        "base_model_name + model_name 'DS FLEXIHAULER' (Konvention der DS-Geschwister: "
        "Produkt bar, Base Model / Extension mit 'DS '-Praefix)."
    )
    ext_patch = {
        "model_name": "DS FLEXIHAULER",
        "vehicle_length": 1750,
        "vehicle_width": 608,
        "coupling_type": ["Retractable Pin"],
        "auto_hitch": "True",
        "train_configuration": "Underride/Mouse",
        "source_notes": fh_notes,
    }
    patch("extensions", "rec9E0XxkjrTYrkLF", ext_patch)
    patch("products", "recXGEd8bUTkwFAyU", {
        "product_name": "FLEXIHAULER",
        "source_notes": (before_prod.get("source_notes", "") + " | " + fh_notes)[:9000],
    })
    patch("base_models", "recnDArplXNN16si3", {
        "base_model_name": "DS FLEXIHAULER", "last_updated": TODAY})
    audit({"op": "patch", "label": "FLEXIHAULER",
           "airtable": {"extension": "rec9E0XxkjrTYrkLF", "product": "recXGEd8bUTkwFAyU",
                        "base_model": "recnDArplXNN16si3"},
           "before": {"extension": before_ext, "product": before_prod, "base_model": before_bm},
           "after_diff": {"extension": ext_patch,
                          "product": {"product_name": "FLEXIHAULER"},
                          "base_model": {"base_model_name": "DS FLEXIHAULER"}},
           "flags": ["navigation_type conflict NOT overwritten: source says 'Spurgefuehrt, "
                     "optional frei navigierend', record holds 'Natural Feature (SLAM)'"]})

    # --- AMADEUS Classic: enrich only ---
    before = get("extensions", "recz93NMqwGEMNcLr")["fields"]
    cl_patch = {
        "battery_swap_capable": True,
        "battery_type": ["Li-Ion", "Lead-Acid"],
        "navigation_type": ["Laser Reflector", "Natural Feature (SLAM)"],
        "source_notes": (before.get("source_notes", "") + " || Manual note from user research, "
                         "2026-08-06 (ENRICHMENT ONLY, no existing value overwritten): "
                         "Energieversorgung automatisches Laden + Batteriewechsel -> "
                         "battery_swap_capable=True (neu). Batterie Li-NMC (24 V/208 Ah/312 Ah) "
                         "ODER Blei/Reinblei/Blei-Gel (24 V/375 Ah) -> 'Lead-Acid' zu battery_type "
                         "ergaenzt. Navigation: Laser, SLAM -> 'Natural Feature (SLAM)' zu "
                         "navigation_type ergaenzt. Einsatz: Paletten/Gitterboxen laengs, "
                         "Bodenstellplaetze, Uebergabestationen (mit Radararmen unterfahrbar), "
                         "Regalanlagen bis 2.700 mm Hoehe. "
                         "ABWEICHUNG NICHT UEBERSCHRIEBEN: Quelltext nennt Duplex-Mast 85-2880 mm, "
                         "der Datensatz fuehrt lifting_height=2800 (KO-Feld) -- bewusst "
                         "unveraendert gelassen und geflaggt.")[:9000],
    }
    patch("extensions", "recz93NMqwGEMNcLr", cl_patch)
    audit({"op": "patch", "label": "AMADEUS Classic", "airtable": {"extension": "recz93NMqwGEMNcLr"},
           "before": before, "after_diff": cl_patch,
           "flags": ["lifting_height 2800 (DB) vs 2880 (user note, Duplex 85-2880mm) -- "
                     "KO field, deliberately NOT changed"]})

    # --- AMADEUS Counter: enrich only ---
    before = get("extensions", "rec4PtfgRTcGmsj6W")["fields"]
    ct_patch = {
        "max_speed": 1.8,
        "battery_swap_capable": True,
        "battery_type": ["Li-Ion", "Lead-Acid"],
        "navigation_type": ["Natural Feature (SLAM)", "Contour", "Laser Reflector"],
        "source_notes": (before.get("source_notes", "") + " || Manual note from user research, "
                         "2026-08-06 (ENRICHMENT ONLY, no existing value overwritten): "
                         "Nutzlast max 1,2 t (bestaetigt bestehende 1200). 'Sonst gleicher Block "
                         "wie wide' -> max_speed=1.8 (neu), battery_swap_capable=True (neu), "
                         "'Lead-Acid' zu battery_type ergaenzt, 'Laser Reflector' zu "
                         "navigation_type ergaenzt. Einsatz: Paletten/Gitterboxen quer, Gestelle "
                         "mit Staplerlaschen, Bodenstellplaetze, Uebergabestation (muss zwischen "
                         "Radarme passen). "
                         "FLAG: 'muss zwischen Radarme passen' deutet auf eine Radarm-/Straddle-"
                         "Bauform hin, waehrend der Datensatz drive_type='Counterbalanced' fuehrt "
                         "-- bewusst unveraendert gelassen und geflaggt.")[:9000],
    }
    patch("extensions", "rec4PtfgRTcGmsj6W", ct_patch)
    audit({"op": "patch", "label": "AMADEUS Counter", "airtable": {"extension": "rec4PtfgRTcGmsj6W"},
           "before": before, "after_diff": ct_patch,
           "flags": ["drive_type 'Counterbalanced' vs source 'Uebergabestation muss zwischen "
                     "Radarme passen' (straddle-style) -- deliberately NOT changed"]})


def main():
    global DRY
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="actually write to Airtable")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", choices=["del", "jh", "ds", "patch"])
    args = ap.parse_args()
    DRY = not args.run
    print(f"MODE: {'LIVE' if args.run else 'DRY RUN'}")
    steps = {"del": run_deletions, "jh": run_jungheinrich,
             "ds": run_ds_automotion, "patch": run_patches}
    order = [args.only] if args.only else ["del", "jh", "patch", "ds"]
    for s in order:
        steps[s]()


if __name__ == "__main__":
    main()
