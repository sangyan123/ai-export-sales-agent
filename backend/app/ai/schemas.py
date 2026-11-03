from typing import Any

from pydantic import BaseModel, Field

INQUIRY_REQUIREMENTS_SCHEMA_VERSION = "inquiry_requirements.v1"

FIELD_NAMES = (
    "product_category",
    "standard_code",
    "material",
    "grade",
    "diameter",
    "length",
    "thread_pitch",
    "surface_finish",
    "quantity",
    "destination_country",
    "packaging",
)

CRITICAL_FIELDS = ("product_category", "material", "diameter", "quantity")


class ParsedField(BaseModel):
    value: str | None = None
    normalized_value: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str | None = None


class InquiryParseResult(BaseModel):
    schema_version: str = INQUIRY_REQUIREMENTS_SCHEMA_VERSION
    product_category: ParsedField = Field(default_factory=ParsedField)
    standard_code: ParsedField = Field(default_factory=ParsedField)
    material: ParsedField = Field(default_factory=ParsedField)
    grade: ParsedField = Field(default_factory=ParsedField)
    diameter: ParsedField = Field(default_factory=ParsedField)
    length: ParsedField = Field(default_factory=ParsedField)
    thread_pitch: ParsedField = Field(default_factory=ParsedField)
    surface_finish: ParsedField = Field(default_factory=ParsedField)
    quantity: ParsedField = Field(default_factory=ParsedField)
    unit: str | None = None
    destination_country: ParsedField = Field(default_factory=ParsedField)
    incoterm: str | None = None
    packaging: ParsedField = Field(default_factory=ParsedField)
    missing_fields: list[str] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    overall_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    def missing_field_names(self) -> list[str]:
        return [name for name in FIELD_NAMES if not _has_value(getattr(self, name))]

    def critical_missing_fields(self) -> list[str]:
        missing = [name for name in CRITICAL_FIELDS if not _has_value(getattr(self, name))]
        if not self.unit:
            missing.append("unit")
        return missing

    def confidence_map(self) -> dict[str, float]:
        values = {
            name: getattr(self, name).confidence
            for name in FIELD_NAMES
            if _has_value(getattr(self, name))
        }
        values["overall"] = self.overall_confidence
        return values

    def evidence_map(self) -> dict[str, str]:
        evidence: dict[str, str] = {}
        for name in FIELD_NAMES:
            field = getattr(self, name)
            if _has_value(field) and field.evidence:
                evidence[name] = field.evidence
        return evidence


def _has_value(field: ParsedField) -> bool:
    return bool((field.normalized_value or field.value or "").strip())


__all__ = [
    "CRITICAL_FIELDS",
    "FIELD_NAMES",
    "INQUIRY_REQUIREMENTS_SCHEMA_VERSION",
    "InquiryParseResult",
    "ParsedField",
]
