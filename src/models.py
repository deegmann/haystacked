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
    last_updated:           Optional[str]          = None


@dataclass
class Product:
    product_id:            str
    company_id:            str
    base_model_id:         str
    product_name:          str
    product_type:          str
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
    # D1 provenance (all optional — None for pre-D1 runs and any run where the
    # producing/nulling step wasn't tracked). produced_by/nulled_by are flat TEXT
    # values drawn from the closed vocabularies in src/tender_store.py.
    produced_by: Optional[str] = None
    nulled_by: Optional[str] = None
    # Loose diagnostic dict (raw_value, raw_source, pass_4c_state, notes, ...) —
    # deliberately NOT a dataclass so old stored blobs stay readable across shape
    # changes (see src/tender_store.py for rationale). Never reconstructed into a
    # typed object; read back with .get(key) only. "notes" (if present) is
    # write-only — no pipeline code may ever read, parse, or branch on it.
    provenance: Optional[dict] = None

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
