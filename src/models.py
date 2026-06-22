"""
Data models for the haystacked matching engine.
All fields use None for unknown — never 0 or [] to represent missing data.

Extension is generated from AP0 schema — see src/generated_models.py.
To add/change Extension fields: edit the AP0 xlsx, run generate_all.py.
"""
from dataclasses import dataclass, field
from typing import Optional

from src.generated_models import Extension  # noqa: F401 — re-exported for callers


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
