"""OI-115c Phase 3C — single source of truth for the 38-field_name rename map.

Import RENAME and rewrite_field_names() from here everywhere a rewrite is
needed (AP0 edit script, CSV rewriter, DB ALTER-statement generator,
test/fixture rewriter, allowlist rewriter). Never hand-retype this map.
"""
import re

RENAME = {
    # 32 mechanical suffix strips
    "auto_hitch_position_tolerance_mm": "auto_hitch_position_tolerance",
    "battery_runtime_h": "battery_runtime",
    "cart_pickup_height_range_mm": "cart_pickup_height_range",
    "charge_time_min": "charge_time",
    "cooling_capacity_kw": "cooling_capacity",
    "drop_accuracy_angle_deg": "drop_accuracy_angle",
    "drop_accuracy_dep_mm": "drop_accuracy_dep",
    "drop_accuracy_lat_mm": "drop_accuracy_lat",
    "lift_height_mm": "lift_height",
    "lifting_height_mm": "lifting_height",
    "max_gradient_pct": "max_gradient",
    "max_payload_kg": "max_payload",
    "max_speed_ms": "max_speed",
    "min_aisle_width_mm": "min_aisle_width",
    "min_grid_area_m2": "min_grid_area",
    "min_ground_clearance_mm": "min_ground_clearance",
    "min_total_height_mm": "min_total_height",
    "min_turning_radius_mm": "min_turning_radius",
    "operating_humidity_max_pct": "operating_humidity_max",
    "operating_temp_max_c": "operating_temp_max",
    "operating_temp_min_c": "operating_temp_min",
    "pick_req_accuracy_angle_deg": "pick_req_accuracy_angle",
    "pick_req_accuracy_dep_mm": "pick_req_accuracy_dep",
    "pick_req_accuracy_lat_mm": "pick_req_accuracy_lat",
    "pulldown_time_h": "pulldown_time",
    "shelf_footprint_mm": "shelf_footprint",
    "shelf_height_mm": "shelf_height",
    "stop_accuracy_mm": "stop_accuracy",
    "temperature_stability_k": "temperature_stability",
    "towing_capacity_kg": "towing_capacity",
    "tugger_min_aisle_width_mm": "tugger_min_aisle_width",
    "turning_radius_mm": "turning_radius",
    # 6 judgment-call names (pre-approved, do not re-litigate)
    "length_mm": "vehicle_length",
    "width_mm": "vehicle_width",
    "blast_freeze_capacity_kg_h": "blast_freeze_capacity",
    "room_volume_m3_max": "room_volume_max",
    "temperature_min_celsius": "temperature_min",
    "typical_project_value_eur": "typical_project_value",
}

assert len(RENAME) == 38, f"expected 38 entries, got {len(RENAME)}"


def rewrite_field_names(s: str) -> str:
    """Apply the RENAME map to raw text, longest-key-first, word-boundary-safe
    but underscore-permissive (so 'required_max_payload_kg' and
    'required_max_payload_kg_source' both correctly rewrite)."""
    for old in sorted(RENAME, key=len, reverse=True):
        s = re.sub(
            r"(?<![A-Za-z0-9])" + re.escape(old) + r"(?![A-Za-z0-9])",
            RENAME[old],
            s,
        )
    return s
