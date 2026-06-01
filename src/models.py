"""
Data models for the haystacked matching engine.
All fields use None for unknown — never 0 or [] to represent missing data.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Company:
    company_id:             str
    company_name:           str
    country:                Optional[str]          = None
    hq_city:                Optional[str]          = None
    employee_count_range:   Optional[str]          = None
    founding_year:          Optional[int]          = None
    website:                Optional[str]          = None
    certifications_generic: list[str]              = field(default_factory=list)
    languages_spoken:       list[str]              = field(default_factory=list)
    export_capable:         Optional[bool]         = None
    last_updated:           Optional[str]          = None


@dataclass
class Product:
    product_id:            str
    company_id:            str
    base_model_id:         str
    product_name:          str
    agv_type:              str
    product_description:   Optional[str]          = None
    reference_count:       Optional[int]          = None
    min_project_value_eur: Optional[int]          = None
    max_project_value_eur: Optional[int]          = None
    lead_time_weeks:       Optional[int]          = None
    distribution_model:    Optional[str]          = None
    is_oem_product:        Optional[bool]         = None
    service_coverage:      list[str]              = field(default_factory=list)
    active:                Optional[bool]         = None

    # Joined from Company
    company_name:          Optional[str]          = None
    country:               Optional[str]          = None
    languages_spoken:      list[str]              = field(default_factory=list)
    certifications_generic: list[str]             = field(default_factory=list)


@dataclass
class Extension:
    extension_id:               str
    base_model_id:              str
    agv_type:                   str
    navigation_type:            list[str]     = field(default_factory=list)
    infrastructure_required:    Optional[bool]  = None
    outdoor_capable:            Optional[bool]  = None
    autonomous_obstacle_bypass: Optional[bool]  = None
    omnidirectional_movement:   Optional[bool]  = None
    max_payload_kg:             Optional[float] = None
    load_type:                  list[str]     = field(default_factory=list)
    multi_load_compatibility:   Optional[bool]  = None
    max_speed_ms:               Optional[float] = None
    length_mm:                  Optional[int]   = None
    width_mm:                   Optional[int]   = None
    operating_temp_min_c:       Optional[int]   = None
    operating_temp_max_c:       Optional[int]   = None
    operating_humidity_max_pct: Optional[int]   = None
    ingress_protection_rating:  Optional[str]   = None
    cleanroom_class:            Optional[str]   = None
    max_gradient_pct:           Optional[float] = None
    floor_flatness_req:         Optional[str]   = None
    stop_accuracy_mm:           Optional[int]   = None
    battery_type:               list[str]     = field(default_factory=list)
    battery_runtime_h:          Optional[float] = None
    charge_time_min:            Optional[int]   = None
    autonomous_charging:        Optional[bool]  = None
    battery_swap_capable:       Optional[bool]  = None
    safety_standard:            list[str]     = field(default_factory=list)
    functional_safety_level:    Optional[str]   = None
    safety_coverage:            Optional[str]   = None
    fleet_management_system:    Optional[str]   = None
    fleet_control_architecture: Optional[str]   = None
    vda5050_compatible:         Optional[bool]  = None
    max_fleet_size:             Optional[int]   = None
    multi_fleet_capable:        Optional[bool]  = None
    integration_capability:     list[str]     = field(default_factory=list)
    station_applications:       list[str]     = field(default_factory=list)
    manual_usage:               Optional[bool]  = None
    # Forklift-specific
    lifting_height_mm:          Optional[int]   = None
    min_total_height_mm:        Optional[int]   = None
    fork_type:                  list[str]     = field(default_factory=list)
    fork_spread:                Optional[str]   = None
    mast_type:                  Optional[str]   = None
    min_aisle_width_mm:         Optional[int]   = None
    vna_capable:                Optional[bool]  = None
    drive_type:                 Optional[str]   = None
    drop_accuracy_lat_mm:       Optional[int]   = None
    drop_accuracy_dep_mm:       Optional[int]   = None
    drop_accuracy_angle_deg:    Optional[int]   = None
    pick_req_accuracy_lat_mm:   Optional[int]   = None
    pick_req_accuracy_dep_mm:   Optional[int]   = None
    pick_req_accuracy_angle_deg: Optional[int]  = None
    forks_free_floating:        Optional[bool]  = None
    stacking_capability:        Optional[bool]  = None
    load_detection:             list[str]     = field(default_factory=list)
    barcode_readers:            Optional[bool]  = None
    stock_line_scanning:        Optional[bool]  = None
    trailer_loading:            Optional[bool]  = None
    trailer_unloading:          Optional[bool]  = None
    guidance:                   list[str]     = field(default_factory=list)
    busbar_compatible:          Optional[bool]  = None
    # Tugger-specific
    towing_capacity_kg:         Optional[float] = None
    max_trailers:               Optional[int]   = None
    coupling_type:              list[str]     = field(default_factory=list)
    auto_hitch:                 Optional[bool]  = None
    auto_hitch_position_tolerance_mm: Optional[int] = None
    train_configuration:        Optional[str]   = None
    load_transfer:              list[str]     = field(default_factory=list)
    trailer_compatibility:      Optional[str]   = None
    trailer_steering_technology: list[str]    = field(default_factory=list)
    route_type:                 Optional[str]   = None
    route_programming:          Optional[str]   = None
    intersection_management:    Optional[bool]  = None
    tugger_min_aisle_width_mm:  Optional[int]   = None
    turning_radius_mm:          Optional[int]   = None
    # Mobile AMR-specific
    workflow_capability:        list[str]     = field(default_factory=list)
    grid_required:              Optional[bool]  = None
    rotation_capable:           Optional[bool]  = None
    picking_mechanism:          Optional[str]   = None
    lift_height_mm:             Optional[int]   = None
    min_ground_clearance_mm:    Optional[int]   = None
    rack_pin_compatible:        Optional[bool]  = None
    free_lift_open_closed_pallet: Optional[bool] = None
    top_module_type:            list[str]     = field(default_factory=list)
    cart_pickup_height_range_mm: Optional[str]  = None
    omnidirectional:            Optional[bool]  = None
    min_turning_radius_mm:      Optional[int]   = None
    storage_system_type:        Optional[str]   = None
    shelf_height_mm:            Optional[int]   = None
    shelf_footprint_mm:         Optional[str]   = None
    min_grid_area_m2:           Optional[int]   = None
    throughput_picks_per_hour:  Optional[int]   = None
    throughput_basis:           Optional[str]   = None
    concurrent_robots_per_station: Optional[int] = None
    order_lines_per_run:        Optional[int]   = None
    task_interleaving:          Optional[bool]  = None
    storage_density_factor:     Optional[float] = None
    ergonomic_height_adjustable: Optional[bool] = None
    onboard_ui:                 Optional[bool]  = None
    onboard_container_type:     list[str]     = field(default_factory=list)
    onboard_container_count:    Optional[int]   = None
    wms_integration_native:     list[str]     = field(default_factory=list)
    extra_fields:               Optional[str]   = None


@dataclass
class SupplierRecord:
    """Fully joined view: product + company + extension."""
    product:   Product
    extension: Extension

    @property
    def display_name(self) -> str:
        return self.product.product_name

    @property
    def company_name(self) -> str:
        return self.product.company_name or ""
