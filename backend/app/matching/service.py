import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.schemas import FIELD_NAMES
from app.db.tenant import set_tenant_context
from app.inquiries import InquiryStatus
from app.matching import MatchingError, MatchingErrorCode, MatchStatus
from app.models.inquiry import Inquiry, InquiryRequirement
from app.models.matching import ProductMatch
from app.models.product import Product

FIELD_WEIGHTS: dict[str, float] = {
    "standard_code": 0.30,
    "material": 0.25,
    "diameter": 0.20,
    "length": 0.15,
    "surface_finish": 0.10,
}
HARD_FIELDS = (
    "standard_code",
    "material",
    "grade",
    "diameter",
    "length",
    "thread_pitch",
    "surface_finish",
)
CRITICAL_FIELDS = ("product_category", "material", "diameter", "quantity")
MATCHABLE_STATUSES = frozenset({InquiryStatus.READY_FOR_MATCH, InquiryStatus.MATCHED})
MAX_CANDIDATES = 10
EXACT_MIN_SCORE = 0.90
POSSIBLE_MIN_SCORE = 0.75

_STATUS_RANK = {
    MatchStatus.EXACT: 3,
    MatchStatus.POSSIBLE: 2,
    MatchStatus.CONFLICT: 1,
    MatchStatus.NO_MATCH: 0,
}
_STATUS_ORDER = case(
    (ProductMatch.match_status == MatchStatus.EXACT.value, 3),
    (ProductMatch.match_status == MatchStatus.POSSIBLE.value, 2),
    (ProductMatch.match_status == MatchStatus.CONFLICT.value, 1),
    else_=0,
)


@dataclass(frozen=True)
class MatchResult:
    inquiry: Inquiry
    requirement: InquiryRequirement
    pairs: list[tuple[ProductMatch, Product]]


@dataclass(frozen=True)
class MatchQueryResult:
    inquiry: Inquiry
    requirement: InquiryRequirement | None
    pairs: list[tuple[ProductMatch, Product]]


@dataclass
class _Candidate:
    product: Product
    score: float
    status: MatchStatus
    matched: list[str]
    conflicts: list[str]
    unknown: list[str]
    explanation: str


def _normalize(value: str | None) -> str:
    return "".join(str(value or "").split()).casefold()


def _normalize_field(name: str, value: str | None) -> str:
    normalized = _normalize(value)
    if name == "material":
        if normalized.startswith("sus"):
            return normalized[3:]
        if normalized.startswith("ss"):
            return normalized[2:]
    return normalized


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


def _quantity(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value.replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _score_candidate(values: dict[str, str], product: Product) -> _Candidate:
    matched: list[str] = []
    conflicts: list[str] = []
    unknown: list[str] = []

    for name in HARD_FIELDS:
        requested = values.get(name)
        if not requested:
            continue
        offered = getattr(product, name)
        if not offered or not str(offered).strip():
            unknown.append(name)
            continue
        if _normalize_field(name, requested) == _normalize_field(name, offered):
            matched.append(name)
        else:
            conflicts.append(name)

    specified_weight = sum(FIELD_WEIGHTS[name] for name in FIELD_WEIGHTS if values.get(name))
    matched_weight = sum(FIELD_WEIGHTS[name] for name in matched if name in FIELD_WEIGHTS)
    score = round(matched_weight / specified_weight, 4) if specified_weight else 0.0

    if conflicts:
        status = MatchStatus.CONFLICT
    elif score >= EXACT_MIN_SCORE and all(values.get(name) for name in CRITICAL_FIELDS):
        status = MatchStatus.EXACT
    elif score >= POSSIBLE_MIN_SCORE:
        status = MatchStatus.POSSIBLE
    else:
        status = MatchStatus.NO_MATCH

    explanation = _explain(matched, conflicts, unknown, values, product)
    return _Candidate(
        product=product,
        score=score,
        status=status,
        matched=matched,
        conflicts=conflicts,
        unknown=unknown,
        explanation=explanation,
    )


def _explain(
    matched: list[str],
    conflicts: list[str],
    unknown: list[str],
    values: dict[str, str],
    product: Product,
) -> str:
    parts: list[str] = []
    if matched:
        parts.append(f"Matched {', '.join(matched)}.")
    if conflicts:
        parts.append(f"Conflicts on {', '.join(conflicts)}.")
    if unknown:
        parts.append(f"Product has no value for {', '.join(unknown)}.")
    if not matched and not conflicts and not unknown:
        parts.append("No comparable specification fields.")

    quantity = _quantity(values.get("quantity"))
    if quantity is not None and product.moq is not None and quantity < product.moq:
        parts.append(f"Quantity {quantity} is below MOQ {product.moq}; special approval required.")
    return " ".join(parts)


class ProductMatchingService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def generate(self, *, tenant_id: uuid.UUID, inquiry_id: uuid.UUID) -> MatchResult:
        await set_tenant_context(self._session, tenant_id)
        inquiry = await self._lock_inquiry(tenant_id, inquiry_id)
        if inquiry is None:
            raise MatchingError(MatchingErrorCode.INQUIRY_NOT_FOUND, "inquiry not found")
        if inquiry.status not in MATCHABLE_STATUSES:
            raise MatchingError(
                MatchingErrorCode.INQUIRY_STATUS_NOT_MATCHABLE,
                f"inquiry status {inquiry.status} cannot be matched",
            )

        requirement = await self._latest_requirement(tenant_id, inquiry_id)
        if requirement is None:
            raise MatchingError(
                MatchingErrorCode.REQUIREMENTS_NOT_READY,
                "inquiry has no parsed requirements yet",
            )

        values = requirement_values(requirement)
        category = values.get("product_category")
        if not category:
            raise MatchingError(
                MatchingErrorCode.REQUIREMENTS_INCOMPLETE,
                "product_category is required to match candidates",
            )

        products = list(
            await self._session.scalars(
                select(Product).where(
                    Product.tenant_id == tenant_id,
                    Product.status == "ACTIVE",
                    func.upper(Product.category) == category.upper(),
                )
            )
        )
        candidates = sorted(
            (_score_candidate(values, product) for product in products),
            key=lambda item: (
                -_STATUS_RANK[item.status],
                -item.score,
                item.product.product_code,
            ),
        )
        selected = candidates[:MAX_CANDIDATES]

        await self._session.execute(
            delete(ProductMatch).where(
                ProductMatch.tenant_id == tenant_id,
                ProductMatch.inquiry_id == inquiry_id,
            )
        )
        pairs: list[tuple[ProductMatch, Product]] = []
        for candidate in selected:
            match = ProductMatch(
                tenant_id=tenant_id,
                requirement_id=requirement.id,
                inquiry_id=inquiry.id,
                product_id=candidate.product.id,
                score=Decimal(str(candidate.score)),
                match_status=candidate.status.value,
                matched_fields=candidate.matched,
                conflict_fields=candidate.conflicts,
                unknown_fields=candidate.unknown,
                explanation=candidate.explanation,
            )
            self._session.add(match)
            pairs.append((match, candidate.product))

        if inquiry.status == InquiryStatus.READY_FOR_MATCH and any(
            candidate.status in {MatchStatus.EXACT, MatchStatus.POSSIBLE} for candidate in selected
        ):
            inquiry.status = InquiryStatus.MATCHED.value

        await self._session.flush()
        await self._session.refresh(inquiry)
        for match, _ in pairs:
            await self._session.refresh(match)
        return MatchResult(inquiry=inquiry, requirement=requirement, pairs=pairs)

    async def list_matches(
        self, *, tenant_id: uuid.UUID, inquiry_id: uuid.UUID
    ) -> MatchQueryResult:
        await set_tenant_context(self._session, tenant_id)
        inquiry = await self._lock_inquiry(tenant_id, inquiry_id, for_update=False)
        if inquiry is None:
            raise MatchingError(MatchingErrorCode.INQUIRY_NOT_FOUND, "inquiry not found")

        requirement = await self._latest_requirement(tenant_id, inquiry_id)
        if requirement is None:
            return MatchQueryResult(inquiry=inquiry, requirement=None, pairs=[])

        rows = await self._session.execute(
            select(ProductMatch, Product)
            .join(
                Product,
                and_(
                    Product.tenant_id == ProductMatch.tenant_id,
                    Product.id == ProductMatch.product_id,
                ),
            )
            .where(
                ProductMatch.tenant_id == tenant_id,
                ProductMatch.inquiry_id == inquiry_id,
                ProductMatch.requirement_id == requirement.id,
            )
            .order_by(_STATUS_ORDER.desc(), ProductMatch.score.desc(), Product.product_code)
        )
        return MatchQueryResult(
            inquiry=inquiry,
            requirement=requirement,
            pairs=[(match, product) for match, product in rows.all()],
        )

    async def _lock_inquiry(
        self, tenant_id: uuid.UUID, inquiry_id: uuid.UUID, *, for_update: bool = True
    ) -> Inquiry | None:
        statement = select(Inquiry).where(
            Inquiry.tenant_id == tenant_id,
            Inquiry.id == inquiry_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def _latest_requirement(
        self, tenant_id: uuid.UUID, inquiry_id: uuid.UUID
    ) -> InquiryRequirement | None:
        return await self._session.scalar(
            select(InquiryRequirement)
            .where(
                InquiryRequirement.tenant_id == tenant_id,
                InquiryRequirement.inquiry_id == inquiry_id,
            )
            .order_by(InquiryRequirement.schema_version.desc())
            .limit(1)
        )


__all__ = [
    "FIELD_WEIGHTS",
    "MAX_CANDIDATES",
    "MatchQueryResult",
    "MatchResult",
    "ProductMatchingService",
    "requirement_values",
]
