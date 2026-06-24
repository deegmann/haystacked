"""
Data models for the haystacked matching engine.
All fields use None for unknown — never 0 or [] to represent missing data.
"""
from dataclasses import dataclass, field
from typing import Any, Optional

from src.field_spec import FieldSpec


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
class FieldValue:
    """One supplier capability value, self-describing via its FieldSpec."""
    spec: FieldSpec
    value: Any  # coerced to correct Python type; None if unknown


@dataclass
class ExtractionValue:
    """One LLM-extracted field value. spec is frozen at time of run."""
    spec: Optional[FieldSpec]  # None only for orphaned UUIDs (AP0 field removed after run)
    value: Any
    source: Optional[str]

@dataclass
class TenderRun:
    """Complete record of one tender analysis pipeline run."""
    run_id: str
    source_file: str
    captured_at: str
    vehicle_type: Optional[str]  # display label only — never use for config/AP0 lookup
    in_scope: bool
    values: dict[str, ExtractionValue]  # uuid → ExtractionValue
    basic_info: dict                    # buyer, project_name, summary etc. (allowlisted keys)


@dataclass
class SupplierRecord:
    """Fully joined view: product + company + all AP0 fields."""
    product: Product
    values: dict[str, FieldValue]  # uuid → FieldValue, covers ALL AP0 fields

    @property
    def display_name(self) -> str:
        return self.product.product_name

    @property
    def company_name(self) -> str:
        return self.product.company_name or ""
