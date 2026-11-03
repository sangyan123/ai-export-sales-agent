import json

import httpx
import pytest

from app.ai.email import (
    DeterministicEmailGenerator,
    EmailGenerationError,
    EmailGenerationErrorCode,
    EmailGenerationInput,
    EmailQuote,
    EmailQuoteItem,
    OpenAICompatibleEmailGenerator,
    get_email_generator,
)
from app.core.config import settings


def _quote(**overrides: object) -> EmailQuote:
    values: dict[str, object] = {
        "quote_no": "Q-1001",
        "version_no": 1,
        "currency": "USD",
        "subtotal": "617.00",
        "discount_total": "0.00",
        "freight_total": "0.00",
        "grand_total": "617.00",
        "valid_until": "2026-12-31",
        "incoterm": None,
        "payment_terms": "T/T 30% deposit",
        "lead_time": None,
    }
    values.update(overrides)
    return EmailQuote(**values)  # type: ignore[arg-type]


def _item(**overrides: object) -> EmailQuoteItem:
    values: dict[str, object] = {
        "product_code": "BOLT-EXT",
        "product_name": "Hex bolt SS316 M8x50",
        "standard_code": "DIN 933",
        "material": "SS316",
        "grade": "8.8",
        "diameter": "M8",
        "length": "50mm",
        "thread_pitch": None,
        "surface_finish": "PLAIN",
        "quantity": "5000.0000",
        "unit": "PCS",
        "price_unit": "PCS",
        "unit_price": "0.1234",
        "line_total": "617.00",
        "price_basis": "PER_PIECE",
    }
    values.update(overrides)
    return EmailQuoteItem(**values)  # type: ignore[arg-type]


def _input(**overrides: object) -> EmailGenerationInput:
    values: dict[str, object] = {
        "inquiry_subject": "RFQ - hex bolts",
        "inquiry_raw_body": "We need 5000 pcs M8 x 50mm bolts.",
        "customer_company": "Fastener Buyer GmbH",
        "requirements": {"material": "SS316", "diameter": "M8", "quantity": "5000"},
        "missing_requirements": ("packaging",),
        "quote": _quote(),
        "items": (_item(),),
        "language": "en",
    }
    values.update(overrides)
    return EmailGenerationInput(**values)  # type: ignore[arg-type]


async def test_deterministic_generator_uses_quote_and_requirements() -> None:
    content = await DeterministicEmailGenerator().generate(_input())

    assert content.subject == "Re: RFQ - hex bolts"
    assert "Fastener Buyer GmbH" in content.body
    assert "Q-1001 (version 1)" in content.body
    assert "Hex bolt SS316 M8x50 (BOLT-EXT)" in content.body
    assert "Quantity: 5000.0000 PCS" in content.body
    assert "Total: USD 617.00" in content.body
    assert "- Material: SS316" in content.body
    assert "Incoterm: To be confirmed" in content.body
    assert "quote:Q-1001:v1" in content.claims_used
    assert "product:BOLT-EXT" in content.claims_used
    assert "requirement:material" in content.claims_used
    assert "Incoterm" in content.missing_information
    assert "Lead time" in content.missing_information
    assert "Requirement: Packaging" in content.missing_information
    assert "MISSING_INFORMATION" in content.review_flags


async def test_deterministic_generator_flags_discount() -> None:
    content = await DeterministicEmailGenerator().generate(
        _input(quote=_quote(discount_total="10.00", grand_total="607.00"))
    )

    assert "DISCOUNT_INCLUDED" in content.review_flags
    assert "Discount: USD 10.00" in content.body


async def test_deterministic_generator_rejects_other_languages() -> None:
    with pytest.raises(EmailGenerationError) as excinfo:
        await DeterministicEmailGenerator().generate(_input(language="zh"))

    assert excinfo.value.code is EmailGenerationErrorCode.UNSUPPORTED_LANGUAGE


async def test_openai_generator_retries_invalid_output() -> None:
    calls = 0
    valid = {
        "subject": "Quotation Q-1001",
        "body": "Dear buyer, please find our quotation attached.",
        "claims_used": ["quote:Q-1001:v1"],
        "missing_information": [],
        "review_flags": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = "not json" if calls == 1 else json.dumps(valid)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
        )

    generator = OpenAICompatibleEmailGenerator(
        api_key="test-key",
        base_url="https://llm.example/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    content = await generator.generate(_input())

    assert calls == 2
    assert content.subject == "Quotation Q-1001"
    assert generator.model_id == "test-model"


async def test_openai_generator_maps_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    generator = OpenAICompatibleEmailGenerator(
        api_key="test-key",
        base_url="https://llm.example/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(EmailGenerationError) as excinfo:
        await generator.generate(_input())

    assert excinfo.value.code is EmailGenerationErrorCode.PROVIDER_HTTP_ERROR


def test_openai_generator_requires_api_key() -> None:
    with pytest.raises(EmailGenerationError) as excinfo:
        OpenAICompatibleEmailGenerator(
            api_key="",
            base_url="https://llm.example/v1",
            model="test-model",
        )

    assert excinfo.value.code is EmailGenerationErrorCode.CONFIGURATION_ERROR


def test_email_generator_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_provider", "deterministic")
    assert isinstance(get_email_generator(), DeterministicEmailGenerator)

    monkeypatch.setattr(settings, "llm_provider", "unsupported")
    with pytest.raises(EmailGenerationError) as excinfo:
        get_email_generator()
    assert excinfo.value.code is EmailGenerationErrorCode.CONFIGURATION_ERROR
