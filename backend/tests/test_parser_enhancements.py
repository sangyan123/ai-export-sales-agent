"""Unit tests for deterministic parser enhancements (v1.1).

Covers the five golden-set known-issue fixes: fuzzy spelling tolerance
for materials and surfaces, decimal quantities, multi-product conflict
flags and diameter conflict flags.
"""

import asyncio

import pytest

from app.ai.parser import DeterministicInquiryParser


@pytest.fixture(scope="module")
def parser():
    return DeterministicInquiryParser()


def _parse(parser: DeterministicInquiryParser, raw_text: str):
    return asyncio.run(parser.parse(subject="t", raw_text=raw_text, language="en"))


def test_fuzzy_material_misspelling(parser) -> None:
    result = _parse(parser, "Need stainles steel bolts M10x50mm, 3000 pcs.")
    assert result.material.normalized_value == "STAINLESS_STEEL"
    assert result.material.confidence < 0.9  # fuzzy matches are less confident


def test_fuzzy_surface_misspelling(parser) -> None:
    result = _parse(parser, "Please quote M3x16mm zink plated screws, 10000 pcs.")
    assert result.surface_finish.normalized_value == "ZINC_PLATED"


def test_fuzzy_material_exact_still_wins(parser) -> None:
    result = _parse(parser, "stainless steel bolts M6, 100 pcs")
    assert result.material.normalized_value == "STAINLESS_STEEL"
    assert result.material.confidence == 0.95  # exact match keeps high confidence


def test_fuzzy_no_false_positive_on_unrelated_text(parser) -> None:
    result = _parse(parser, "Thank you for the catalog, we will review internally.")
    assert result.material.normalized_value is None
    assert result.surface_finish.normalized_value is None


def test_decimal_quantity(parser) -> None:
    result = _parse(parser, "Quote 0.5 kg M2 screws for our repair shop.")
    assert result.quantity.normalized_value == "0.5"
    assert result.unit == "KG"


def test_integer_quantity_unchanged(parser) -> None:
    result = _parse(parser, "12000 pcs M8 bolts")
    assert result.quantity.normalized_value == "12000"
    assert result.unit == "PCS"


def test_multi_product_conflict_flag(parser) -> None:
    result = _parse(
        parser,
        "We are sourcing hex bolts and matching nuts, DIN 933, M10x40mm, 50000 pcs.",
    )
    assert result.product_category.normalized_value == "BOLT"  # first match kept
    types = [c["type"] for c in result.conflicts]
    assert "MULTI_PRODUCT" in types


def test_diameter_conflict_flag(parser) -> None:
    result = _parse(
        parser,
        "M8 bolts but our drawing says M10, DIN 933, quantity 1000 pcs.",
    )
    assert result.diameter.normalized_value == "M8"  # first match kept
    types = [c["type"] for c in result.conflicts]
    assert "DIAMETER_CONFLICT" in types


def test_single_product_no_conflict(parser) -> None:
    result = _parse(parser, "M8x40mm bolts, 10000 pcs, DIN 933")
    assert result.conflicts == []
