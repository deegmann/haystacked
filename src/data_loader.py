"""
AP-I1 — Data Loader
Loads SupplierRecords from SQLite via a 3-way JOIN.
Parsing rules per spec v1.2 LL-06 and Blank != Zero principle.
"""
import sqlite3
from pathlib import Path
from typing import Optional

from src.models import Company, Extension, Product, SupplierRecord

DB_PATH = Path(__file__).parent.parent / "data" / "haystacked.db"


JOIN_SQL = """
SELECT
    p.product_id, p.company_id, p.base_model_id, p.product_name, p.agv_type,
    p.product_description, p.reference_count, p.min_project_value_eur,
    p.max_project_value_eur, p.lead_time_weeks, p.distribution_model,
    p.is_oem_product, p.service_coverage, p.active,
    c.company_name, c.country, c.languages_spoken, c.certifications_generic,
    bme.*
FROM products p
JOIN companies c ON p.company_id = c.company_id
JOIN base_model_extensions bme ON p.base_model_id = bme.base_model_id
WHERE p.active = 1
"""


def _parse_multiselect(val) -> list[str]:
    if val is None or val == "":
        return []
    return [v.strip() for v in str(val).split("|") if v.strip()]


def _parse_bool(val) -> Optional[bool]:
    if val is None:
        return None
    if isinstance(val, int):
        return bool(val)
    s = str(val).lower().strip()
    if s in ("1", "true", "yes"):
        return True
    if s in ("0", "false", "no"):
        return False
    return None


def _parse_int(val) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _parse_float(val) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        v = float(val)
        return None if v != v else v  # reject NaN
    except (ValueError, TypeError):
        return None


def load_suppliers(db_path: Path = DB_PATH) -> list[SupplierRecord]:
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found: {db_path}\n"
            "Run sync_airtable.py first to create it."
        )

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(JOIN_SQL)
    rows = cur.fetchall()
    con.close()

    records: list[SupplierRecord] = []
    for row in rows:
        d = dict(row)

        product = Product(
            product_id            = d["product_id"],
            company_id            = d["company_id"],
            base_model_id         = d["base_model_id"],
            product_name          = d["product_name"],
            agv_type              = d["agv_type"],
            product_description   = d.get("product_description"),
            reference_count       = _parse_int(d.get("reference_count")),
            min_project_value_eur = _parse_int(d.get("min_project_value_eur")),
            max_project_value_eur = _parse_int(d.get("max_project_value_eur")),
            lead_time_weeks       = _parse_int(d.get("lead_time_weeks")),
            distribution_model    = d.get("distribution_model"),
            is_oem_product        = _parse_bool(d.get("is_oem_product")),
            service_coverage      = _parse_multiselect(d.get("service_coverage")),
            active                = _parse_bool(d.get("active")),
            company_name          = d.get("company_name"),
            country               = d.get("country"),
            languages_spoken      = _parse_multiselect(d.get("languages_spoken")),
            certifications_generic= _parse_multiselect(d.get("certifications_generic")),
        )

        ext = Extension(
            extension_id               = d["extension_id"],
            base_model_id              = d["base_model_id"],
            agv_type                   = d["agv_type"],
            navigation_type            = _parse_multiselect(d.get("navigation_type")),
            infrastructure_required    = _parse_bool(d.get("infrastructure_required")),
            outdoor_capable            = _parse_bool(d.get("outdoor_capable")),
            autonomous_obstacle_bypass = _parse_bool(d.get("autonomous_obstacle_bypass")),
            omnidirectional_movement   = _parse_bool(d.get("omnidirectional_movement")),
            max_payload_kg             = _parse_float(d.get("max_payload_kg")),
            load_type                  = _parse_multiselect(d.get("load_type")),
            multi_load_compatibility   = _parse_bool(d.get("multi_load_compatibility")),
            max_speed_ms               = _parse_float(d.get("max_speed_ms")),
            length_mm                  = _parse_int(d.get("length_mm")),
            width_mm                   = _parse_int(d.get("width_mm")),
            operating_temp_min_c       = _parse_int(d.get("operating_temp_min_c")),
            operating_temp_max_c       = _parse_int(d.get("operating_temp_max_c")),
            operating_humidity_max_pct = _parse_int(d.get("operating_humidity_max_pct")),
            ingress_protection_rating  = d.get("ingress_protection_rating"),
            cleanroom_class            = d.get("cleanroom_class"),
            max_gradient_pct           = _parse_float(d.get("max_gradient_pct")),
            floor_flatness_req         = d.get("floor_flatness_req"),
            stop_accuracy_mm           = _parse_int(d.get("stop_accuracy_mm")),
            battery_type               = _parse_multiselect(d.get("battery_type")),
            battery_runtime_h          = _parse_float(d.get("battery_runtime_h")),
            charge_time_min            = _parse_int(d.get("charge_time_min")),
            autonomous_charging        = _parse_bool(d.get("autonomous_charging")),
            battery_swap_capable       = _parse_bool(d.get("battery_swap_capable")),
            safety_standard            = _parse_multiselect(d.get("safety_standard")),
            functional_safety_level    = d.get("functional_safety_level"),
            safety_coverage            = d.get("safety_coverage"),
            fleet_management_system    = d.get("fleet_management_system"),
            fleet_control_architecture = d.get("fleet_control_architecture"),
            vda5050_compatible         = _parse_bool(d.get("vda5050_compatible")),
            max_fleet_size             = _parse_int(d.get("max_fleet_size")),
            multi_fleet_capable        = _parse_bool(d.get("multi_fleet_capable")),
            integration_capability     = _parse_multiselect(d.get("integration_capability")),
            station_applications       = _parse_multiselect(d.get("station_applications")),
            manual_usage               = _parse_bool(d.get("manual_usage")),
            lifting_height_mm          = _parse_int(d.get("lifting_height_mm")),
            min_total_height_mm        = _parse_int(d.get("min_total_height_mm")),
            special_fork_option        = _parse_multiselect(d.get("special_fork_option")),
            fork_spread                = d.get("fork_spread"),
            mast_type                  = d.get("mast_type"),
            min_aisle_width_mm         = _parse_int(d.get("min_aisle_width_mm")),
            vna_capable                = _parse_bool(d.get("vna_capable")),
            drive_type                 = d.get("drive_type"),
            drop_accuracy_lat_mm       = _parse_int(d.get("drop_accuracy_lat_mm")),
            drop_accuracy_dep_mm       = _parse_int(d.get("drop_accuracy_dep_mm")),
            drop_accuracy_angle_deg    = _parse_int(d.get("drop_accuracy_angle_deg")),
            pick_req_accuracy_lat_mm   = _parse_int(d.get("pick_req_accuracy_lat_mm")),
            pick_req_accuracy_dep_mm   = _parse_int(d.get("pick_req_accuracy_dep_mm")),
            pick_req_accuracy_angle_deg= _parse_int(d.get("pick_req_accuracy_angle_deg")),
            forks_free_floating        = _parse_bool(d.get("forks_free_floating")),
            stacking_capability        = _parse_bool(d.get("stacking_capability")),
            load_detection             = _parse_multiselect(d.get("load_detection")),
            barcode_readers            = _parse_bool(d.get("barcode_readers")),
            stock_line_scanning        = _parse_bool(d.get("stock_line_scanning")),
            trailer_loading            = _parse_bool(d.get("trailer_loading")),
            trailer_unloading          = _parse_bool(d.get("trailer_unloading")),
            guidance                   = _parse_multiselect(d.get("guidance")),
            busbar_compatible          = _parse_bool(d.get("busbar_compatible")),
            towing_capacity_kg         = _parse_float(d.get("towing_capacity_kg")),
            max_trailers               = _parse_int(d.get("max_trailers")),
            coupling_type              = _parse_multiselect(d.get("coupling_type")),
            auto_hitch                 = _parse_bool(d.get("auto_hitch")),
            auto_hitch_position_tolerance_mm = _parse_int(d.get("auto_hitch_position_tolerance_mm")),
            train_configuration        = d.get("train_configuration"),
            load_transfer              = _parse_multiselect(d.get("load_transfer")),
            trailer_compatibility      = d.get("trailer_compatibility"),
            trailer_steering_technology= _parse_multiselect(d.get("trailer_steering_technology")),
            route_type                 = d.get("route_type"),
            route_programming          = d.get("route_programming"),
            intersection_management    = _parse_bool(d.get("intersection_management")),
            tugger_min_aisle_width_mm  = _parse_int(d.get("tugger_min_aisle_width_mm")),
            turning_radius_mm          = _parse_int(d.get("turning_radius_mm")),
            workflow_capability        = _parse_multiselect(d.get("workflow_capability")),
            grid_required              = _parse_bool(d.get("grid_required")),
            rotation_capable           = _parse_bool(d.get("rotation_capable")),
            picking_mechanism          = d.get("picking_mechanism"),
            lift_height_mm             = _parse_int(d.get("lift_height_mm")),
            min_ground_clearance_mm    = _parse_int(d.get("min_ground_clearance_mm")),
            rack_pin_compatible        = _parse_bool(d.get("rack_pin_compatible")),
            free_lift_open_closed_pallet = _parse_bool(d.get("free_lift_open_closed_pallet")),
            top_module_type            = _parse_multiselect(d.get("top_module_type")),
            cart_pickup_height_range_mm= d.get("cart_pickup_height_range_mm"),
            min_turning_radius_mm      = _parse_int(d.get("min_turning_radius_mm")),
            storage_system_type        = d.get("storage_system_type"),
            shelf_height_mm            = _parse_int(d.get("shelf_height_mm")),
            shelf_footprint_mm         = d.get("shelf_footprint_mm"),
            min_grid_area_m2           = _parse_int(d.get("min_grid_area_m2")),
            throughput_picks_per_hour  = _parse_int(d.get("throughput_picks_per_hour")),
            throughput_basis           = d.get("throughput_basis"),
            concurrent_robots_per_station = _parse_int(d.get("concurrent_robots_per_station")),
            order_lines_per_run        = _parse_int(d.get("order_lines_per_run")),
            task_interleaving          = _parse_bool(d.get("task_interleaving")),
            storage_density_factor     = _parse_float(d.get("storage_density_factor")),
            ergonomic_height_adjustable= _parse_bool(d.get("ergonomic_height_adjustable")),
            onboard_ui                 = _parse_bool(d.get("onboard_ui")),
            onboard_container_type     = _parse_multiselect(d.get("onboard_container_type")),
            onboard_container_count    = _parse_int(d.get("onboard_container_count")),
            wms_integration_native     = _parse_multiselect(d.get("wms_integration_native")),
            extra_fields               = d.get("extra_fields"),
        )

        records.append(SupplierRecord(product=product, extension=ext))

    return records
