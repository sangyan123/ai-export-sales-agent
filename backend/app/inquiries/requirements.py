from app.ai.schemas import FIELD_NAMES
from app.models.inquiry import InquiryRequirement


def requirement_values(requirement: InquiryRequirement) -> dict[str, str]:
    """Merge confirmed values over parsed evidence; confirmed always wins."""
    parsed = requirement.parsed_json or {}
    confirmed = requirement.confirmed_json or {}
    values: dict[str, str] = {}
    for name in (*FIELD_NAMES, "unit", "incoterm"):
        value = _confirmed_value(confirmed.get(name))
        if value is None:
            field = parsed.get(name)
            if isinstance(field, dict):
                value = _first_text(field.get("normalized_value"), field.get("value"))
            elif isinstance(field, str):
                value = field.strip() or None
        if value:
            values[name] = value
    return values


def _first_text(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _confirmed_value(raw: object) -> str | None:
    if isinstance(raw, str):
        return raw.strip() or None
    if isinstance(raw, dict):
        return _first_text(raw.get("normalized_value"), raw.get("value"))
    return None
