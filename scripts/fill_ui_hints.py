#!/usr/bin/env python3
"""
Fill UI Hint column (col Q) in all 4 data sheets of the AP0 xlsx,
then apply format cleanup.

IMPORTANT: Opens with openpyxl (no read_only, no data_only) to preserve formulas.
Only modifies column Q (UI Hint) and formatting — no other content changes.
"""

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

XLSX_PATH = "Spec/haystacked_AP0_field_spec_v0_10.xlsx"

# ── UI Hints by field_name ──────────────────────────────────────────────────
# Key = field_name as it appears in column A of the data sheets.
# Value = German buyer-facing hint string.

UI_HINTS = {
    # ── SHARED – All AGV Types ──────────────────────────────────────────────

    # K.O. fields
    "max_payload_kg": (
        "What is the maximum load weight per carrier? The AGV must be able to carry at least this weight."
    ),
    "load_type": (
        "What type of load carriers will be transported? (e.g. Euro pallet, wire mesh box, container)"
    ),
    "agv_type": (
        "What AGV type is required? (automatically detected from the document)"
    ),

    # Cond. K.O. fields
    "navigation_type": (
        "What navigation type is intended or allowed? (e.g. Natural Feature/SLAM, magnetic tape, QR code)"
    ),
    "infrastructure_required": (
        "Is installation of infrastructure (guide wires, reflectors, QR codes) acceptable or explicitly not desired?"
    ),
    "outdoor_capable": (
        "Is outdoor operation required?"
    ),
    "multi_load_compatibility": (
        "Must the AGV be able to transport multiple load carriers simultaneously?"
    ),
    "operating_temp_min_c": (
        "What is the minimum temperature at the operating site? (°C; e.g. -20°C for cold storage)"
    ),
    "operating_temp_max_c": (
        "What is the maximum temperature at the operating site? (°C; e.g. 30°C for production hall)"
    ),
    "operating_humidity_max_pct": (
        "What is the maximum relative humidity at the operating site? (%)"
    ),
    "ingress_protection_rating": (
        "What ingress protection rating (IP class) is required at the operating site? (e.g. IP54 for splash water protection)"
    ),
    "cleanroom_class": (
        "Are there cleanroom requirements at the operating site? (ISO class; only fill in if cleanroom is present)"
    ),
    "max_gradient_pct": (
        "How steep is the steepest driving route in the operating area? (% gradient; e.g. 1.5 for a 1.5% ramp)"
    ),
    "floor_flatness_req": (
        "Are there special requirements for floor quality or flatness?"
    ),
    "fleet_management_system": (
        "Is there an existing fleet management system that must be compatible?"
    ),
    "vda5050_compatible": (
        "Must the AGV support the VDA 5050 interface standard?"
    ),
    "station_applications": (
        "What special station applications are required? (e.g. charging station, transfer station)"
    ),
    "service_coverage": (
        "In which countries or regions is service and support required?"
    ),
    "country": (
        "In which country is the operating site located?"
    ),
    "languages_spoken": (
        "Which language(s) must the manufacturer support for service and documentation?"
    ),

    # Scoring fields
    "autonomous_obstacle_bypass": (
        "Can the AGV autonomously navigate around obstacles?"
    ),
    "omnidirectional_movement": (
        "Must the AGV be able to move in all directions without turning (omnidirectional)?"
    ),
    "max_speed_ms": (
        "What maximum speed should the AGV achieve? (m/s)"
    ),
    "stop_accuracy_mm": (
        "How precisely must the AGV position at transfer or pickup points? (mm deviation)"
    ),
    "battery_type": (
        "What battery type is preferred or required?"
    ),
    "battery_runtime_h": (
        "How many hours of operating time per charge are required as a minimum? (h)"
    ),
    "charge_time_min": (
        "What is the maximum acceptable duration of a full charging cycle? (min)"
    ),
    "autonomous_charging": (
        "Must the AGV autonomously navigate to the charging station and charge itself?"
    ),
    "battery_swap_capable": (
        "Is fast manual battery swapping desired instead of charging?"
    ),
    "safety_standard": (
        "Which safety standards must be met? (e.g. EN ISO 3691-4)"
    ),
    "functional_safety_level": (
        "What functional safety level is required? (e.g. PLd, SIL2)"
    ),
    "safety_coverage": (
        "Which areas must be covered by safety sensors?"
    ),
    "fleet_control_architecture": (
        "What control architecture is intended for the fleet? (centralised, decentralised)"
    ),
    "max_fleet_size": (
        "How many AGVs should be in simultaneous operation?"
    ),
    "multi_fleet_capable": (
        "Must AGVs from different manufacturers be able to coexist in the same area?"
    ),
    "integration_capability": (
        "Which existing systems must the AGV integrate with? (WMS, ERP, MES)"
    ),
    "installation_process": (
        "Are there requirements for the installation process of the AGV system?"
    ),
    "modification_process": (
        "How easy must later modifications or expansions be?"
    ),
    "reference_count": (
        "Number of reference projects from the supplier. (filled automatically)"
    ),
    "lead_time_weeks": (
        "How many weeks lead time until commissioning is acceptable?"
    ),
    "employee_count_range": (
        "Number of employees at the manufacturer. (filled automatically)"
    ),
    "certifications_generic": (
        "Which certifications must the manufacturer hold? (e.g. ISO 9001)"
    ),

    # Context fields
    "length_mm": (
        "Vehicle length. (mm; for reference only)"
    ),
    "width_mm": (
        "Vehicle width. (mm; for reference only)"
    ),
    "min_fleet_size": (
        "How many AGVs are needed as a minimum?"
    ),
    "typical_project_value_eur": (
        "What budget is available for the AGV project? (EUR)"
    ),
    "manual_usage": (
        "Should the vehicle also be manually operable?"
    ),
    "industries_served": (
        "In which industry will the AGV be used?"
    ),
    "distribution_model": (
        "How is the AGV sold or delivered?"
    ),
    "hq_city": (
        "Manufacturer headquarters. (filled automatically)"
    ),
    "founding_year": (
        "Manufacturer founding year. (filled automatically)"
    ),

    # ── Forklift AGV ────────────────────────────────────────────────────────

    # K.O. fields
    "lifting_height_mm": (
        "How high must the device lift loads? Enter the maximum pick height in the rack. "
        "(mm; e.g. 10,000 mm = 10 m for high-bay storage)"
    ),
    "min_aisle_width_mm": (
        "How wide are the narrowest aisles in your facility? The AGV must manoeuvre within this width. "
        "(mm; e.g. 1,800 mm for narrow-aisle operation)"
    ),

    # Cond. K.O. fields
    "min_total_height_mm": (
        "What is the height of the lowest doorways or passages in the operating area? (mm)"
    ),
    "special_fork_option": (
        "Is a special fork attachment required? (e.g. side-shift, clamp)"
    ),
    "fork_spread": (
        "What fork spacing is required for the load carriers? (mm)"
    ),
    "vna_capable": (
        "Is VNA (Very Narrow Aisle) capability required — or explicitly not desired?"
    ),
    "forks_free_floating": (
        "Must the forks be laterally shiftable or free-floating?"
    ),
    "stacking_capability": (
        "Must the device be able to stack loads on top of each other?"
    ),
    "barcode_readers": (
        "Are integrated barcode scanners for load identification required?"
    ),
    "trailer_loading": (
        "Must the AGV be able to enter and load truck trailers?"
    ),
    "trailer_unloading": (
        "Must the AGV be able to unload from truck trailers?"
    ),
    "guidance": (
        "What guidance concept should the racking vehicle use in the VNA aisle?"
    ),

    # Scoring fields
    "drop_accuracy_lat_mm": (
        "How precisely must the AGV deposit loads laterally? (mm lateral deviation)"
    ),
    "drop_accuracy_dep_mm": (
        "How precisely must the AGV deposit loads in depth? (mm)"
    ),
    "drop_accuracy_angle_deg": (
        "How precisely must the AGV deposit loads angularly? (degrees)"
    ),
    "pick_req_accuracy_lat_mm": (
        "What lateral precision is required when picking up loads? (mm)"
    ),
    "pick_req_accuracy_dep_mm": (
        "What depth precision is required when picking up loads? (mm)"
    ),
    "pick_req_accuracy_angle_deg": (
        "What angular precision is required when picking up loads? (degrees)"
    ),
    "stock_line_scanning": (
        "Must the AGV be able to automatically scan inventory in the racks?"
    ),
    "busbar_compatible": (
        "Is a rail-based power supply system (busbar) planned?"
    ),

    # Context fields
    "mast_type": (
        "What mast type is intended? (e.g. duplex, triplex, quad)"
    ),
    "drive_type": (
        "What drive type is intended? (e.g. counterbalanced, reach truck, VNA)"
    ),
    "load_detection": (
        "How should load pickup be detected?"
    ),

    # ── Tugger AGV ──────────────────────────────────────────────────────────

    # K.O. fields
    "towing_capacity_kg": (
        "What is the maximum total weight of the train? "
        "(kg; sum of all trailers including load; e.g. 5,000 kg)"
    ),
    "max_trailers": (
        "How many trailers must be able to be towed simultaneously?"
    ),
    "coupling_type": (
        "What coupling type do the existing or planned trailers use?"
    ),
    "route_type": (
        "What type of route is planned? (fixed route, flexible route)"
    ),
    "turning_radius_mm": (
        "How much space is available for cornering? (mm; vehicle turning radius must be smaller)"
    ),
    "tugger_min_aisle_width_mm": (
        "How wide are the narrowest passages in the entire travel area including trailers? (mm)"
    ),

    # Cond. K.O. fields
    "auto_hitch": (
        "Must the tugger be able to automatically couple trailers?"
    ),

    # Scoring fields
    "auto_hitch_position_tolerance_mm": (
        "What positioning tolerance is acceptable for automatic coupling? (mm)"
    ),
    "load_transfer": (
        "How should the load handover at the trailer be performed?"
    ),
    "trailer_steering_technology": (
        "What steering technology do the trailers use? (e.g. passive steering, active steering)"
    ),
    "route_programming": (
        "How should routes be programmed or adjusted?"
    ),
    "intersection_management": (
        "How should intersection situations between multiple AGVs be handled?"
    ),

    # Context fields
    "train_configuration": (
        "What train configuration is intended? (e.g. trailers in line, carousel)"
    ),
    "trailer_compatibility": (
        "Which trailer types will be used?"
    ),

    # ── Mobile AMR ──────────────────────────────────────────────────────────

    # K.O. fields
    "lift_height_mm": (
        "How high must the AMR lift loads or shelving units? (mm)"
    ),
    "min_ground_clearance_mm": (
        "What minimum ground clearance is required? (mm; e.g. for floor unevenness)"
    ),
    "min_turning_radius_mm": (
        "How much space is available for turning movements? (mm; turning radius must be smaller)"
    ),

    # Cond. K.O. fields
    "workflow_capability": (
        "What workflows should the AMR support?"
    ),
    "grid_required": (
        "Is a physical grid system (e.g. storage robot grid) part of the solution?"
    ),
    "picking_mechanism": (
        "What mechanism should the AMR use for picking or gripping?"
    ),
    "rack_pin_compatible": (
        "Must the AMR work with pin-compatible storage racks?"
    ),
    "free_lift_open_closed_pallet": (
        "Must the AMR be able to pick up pallets without fork openings?"
    ),
    "shelf_height_mm": (
        "How high are the storage racks the AMR should serve? (mm)"
    ),
    "shelf_footprint_mm": (
        "What is the footprint of the storage units? (mm)"
    ),

    # Scoring fields
    "rotation_capable": (
        "Must the AMR be able to rotate loads during travel?"
    ),
    "top_module_type": (
        "What top module is required? (e.g. conveyor belt, lifting table, robotic arms)"
    ),
    "cart_pickup_height_range_mm": (
        "At what height range must the AMR pick up carts or carriers? (mm)"
    ),
    "pick_req_accuracy_dep_mm": (
        "What depth precision is required during order picking? (mm)"
    ),
    "pick_req_accuracy_angle_deg": (
        "What angular precision is required during order picking? (degrees)"
    ),
    "drop_accuracy_lat_mm": (
        "How precisely must the AMR deposit loads laterally? (mm)"
    ),
    "drop_accuracy_dep_mm": (
        "How precisely must the AMR deposit loads in depth? (mm)"
    ),
    "drop_accuracy_angle_deg": (
        "How precisely must the AMR deposit loads angularly? (degrees)"
    ),
    "throughput_picks_per_hour": (
        "How many picks per hour are required as a minimum?"
    ),
    "concurrent_robots_per_station": (
        "How many AMRs must be able to work at one station simultaneously?"
    ),
    "order_lines_per_run": (
        "How many order lines should be processed per trip?"
    ),
    "task_interleaving": (
        "Should AMRs be able to alternate between different task types?"
    ),
    "storage_density_factor": (
        "How important is high storage density for your system?"
    ),
    "ergonomic_height_adjustable": (
        "Must the working height be ergonomically adjustable for operators?"
    ),
    "onboard_ui": (
        "Is a display or control panel on the vehicle required?"
    ),
    "onboard_container_type": (
        "What container type should be transported on the AMR?"
    ),
    "onboard_container_count": (
        "How many containers should the AMR transport simultaneously?"
    ),
    "wms_integration_native": (
        "Is a direct native integration with the Warehouse Management System required?"
    ),

    # Context fields
    "storage_system_type": (
        "What storage system should the AMR serve?"
    ),
    "min_grid_area_m2": (
        "What is the minimum storage area for the AMR system? (m²)"
    ),
    "throughput_basis": (
        "On what basis is throughput measured?"
    ),
    "multi_language_display": (
        "Must the display support multiple languages?"
    ),
    "gamification": (
        "Are gamification elements for operator motivation desired?"
    ),
}

# ── Column widths ────────────────────────────────────────────────────────────
# Col A=Field Name, B=Data Type, C=Allowed Values, D=Unit, E=Level, F=Entity,
# G=LLM Hint, H=Matching Operator, I=Scoring Weight, J=Score Function,
# K=Threshold A, L=Threshold B, M=Plaus Min, N=Plaus Max,
# O=result_card, P=Display Mode, Q=UI Hint, R=UUID

COLUMN_WIDTHS = {
    "A": 30,   # Field Name
    "B": 14,   # Data Type
    "C": 28,   # Allowed Values — wrap
    "D": 8,    # Unit
    "E": 12,   # Level
    "F": 10,   # Entity
    "G": 50,   # LLM Hint — wrap
    "H": 20,   # Matching Operator
    "I": 10,   # Scoring Weight
    "J": 16,   # Score Function
    "K": 13,   # Score Threshold A
    "L": 13,   # Score Threshold B
    "M": 13,   # Plausibility Min
    "N": 13,   # Plausibility Max
    "O": 13,   # result_card
    "P": 14,   # Display Mode
    "Q": 52,   # UI Hint — wrap
    "R": 12,   # UUID
}

WRAP_COLUMNS = {"C", "G", "Q"}  # Allowed Values, LLM Hint, UI Hint

HEADER_FILL = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
HEADER_FONT = Font(bold=True)
HEADER_ROW_HEIGHT = 30
DATA_ROW_HEIGHT = 15


def apply_formatting(ws):
    """Apply column widths, wrap text, and header styling to a data sheet."""
    # Set column widths
    for col_letter, width in COLUMN_WIDTHS.items():
        ws.column_dimensions[col_letter].width = width

    # Wrap text for designated columns (all rows)
    for col_letter in WRAP_COLUMNS:
        col_idx = ord(col_letter) - ord("A") + 1
        for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=col_idx, max_col=col_idx):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")

    # Header row (row 2) — bold + fill + height
    for cell in ws[2]:
        if cell.value is not None:
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    ws.row_dimensions[2].height = HEADER_ROW_HEIGHT

    # Data rows — modest height; content height determined by wrap
    for row_idx in range(3, ws.max_row + 1):
        ws.row_dimensions[row_idx].height = DATA_ROW_HEIGHT


DATA_SHEETS = [
    "SHARED – All AGV Types",
    "Forklift AGV",
    "Tugger AGV",
    "Mobile AMR",
]

UI_HINT_COL = 17   # column Q = index 17 (1-based)
FIELD_NAME_COL = 1 # column A


def main():
    print(f"Loading {XLSX_PATH} …")
    wb = openpyxl.load_workbook(XLSX_PATH)  # NO read_only, NO data_only

    filled_total = 0
    skipped_total = 0
    missing_total = []

    for sheet_name in DATA_SHEETS:
        if sheet_name not in wb.sheetnames:
            print(f"  WARNING: sheet '{sheet_name}' not found — skipping")
            continue

        ws = wb[sheet_name]
        filled = 0
        skipped = 0

        for row in ws.iter_rows(min_row=3):
            field_name_cell = row[FIELD_NAME_COL - 1]   # 0-based index
            ui_hint_cell = row[UI_HINT_COL - 1]

            fn = field_name_cell.value
            if not fn or not isinstance(fn, str) or fn.startswith("──"):
                # Skip empty rows and section separator rows
                continue

            hint = UI_HINTS.get(fn)
            if hint:
                ui_hint_cell.value = hint
                filled += 1
            else:
                skipped += 1
                missing_total.append(f"{sheet_name}/{fn}")

        print(f"  {sheet_name}: {filled} filled, {skipped} no-hint")
        apply_formatting(ws)
        filled_total += filled
        skipped_total += skipped

    if missing_total:
        print(f"\n  Fields with no UI Hint defined ({len(missing_total)}):")
        for m in missing_total:
            print(f"    {m}")

    print(f"\nSaving {XLSX_PATH} …")
    wb.save(XLSX_PATH)
    print(f"Done. {filled_total} UI Hints written, {skipped_total} fields without hint.")


if __name__ == "__main__":
    main()
