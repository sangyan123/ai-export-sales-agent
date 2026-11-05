"""Unit tests for LLM usage capture in AI parser and email generator (no DB required)."""

import json

import httpx
import pytest

from app.ai.email import (
    DeterministicEmailGenerator,
    EmailGenerationInput,
    EmailQuote,
    EmailQuoteItem,
    OpenAICompatibleEmailGenerator,
)
from app.ai.parser import (
    DeterministicInquiryParser,
    OpenAICompatibleInquiryParser,
)
from app.ai.usage import LLMUsage


async def test_openai_parser_captures_usage_via_sink() -> None:
    captured: list[LLMUsage] = []

    async def usage_sink(usage: LLMUsage) -> None:
        captured.append(usage)

    payload = json.dumps(
        {
            "product_category": {
                "value": "hex bolts",
                "normalized_value": "BOLT",
                "confidence": 0.9,
                "evidence": "hex bolts",
            },
            "overall_confidence": 0.8,
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": payload}}],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 45,
                    "total_tokens": 165,
                },
            },
        )

    parser = OpenAICompatibleInquiryParser(
        api_key="test-key",
        base_url="http://llm.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    await parser.parse(
        subject="RFQ",
        raw_text="hex bolts",
        language="en",
        usage_sink=usage_sink,
    )

    assert len(captured) == 1
    usage = captured[0]
    assert usage.model_id == "test-model"
    assert usage.prompt_tokens == 120
    assert usage.completion_tokens == 45
    assert usage.total_tokens == 165
    assert usage.duration_ms >= 0


async def test_openai_parser_without_sink_still_works() -> None:
    payload = json.dumps({"overall_confidence": 0.5})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": payload}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    parser = OpenAICompatibleInquiryParser(
        api_key="test-key",
        base_url="http://llm.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    result = await parser.parse(subject="RFQ", raw_text="bolts", language="en")
    assert result is not None


async def test_deterministic_parser_accepts_sink_and_never_calls_it() -> None:
    captured: list[LLMUsage] = []

    async def usage_sink(usage: LLMUsage) -> None:
        captured.append(usage)

    parser = DeterministicInquiryParser()
    result = await parser.parse(
        subject="RFQ",
        raw_text="M8x40 hex bolts SS304 quantity 10000",
        language="en",
        usage_sink=usage_sink,
    )
    assert result is not None
    assert captured == []


async def test_openai_email_generator_captures_usage_via_sink() -> None:
    captured: list[LLMUsage] = []

    async def usage_sink(usage: LLMUsage) -> None:
        captured.append(usage)

    payload = json.dumps(
        {
            "subject": "Re: RFQ",
            "body": "Thank you for your inquiry.",
            "claims_used": [],
            "missing_information": [],
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": payload}}],
                "usage": {
                    "prompt_tokens": 200,
                    "completion_tokens": 80,
                    "total_tokens": 280,
                },
            },
        )

    generator = OpenAICompatibleEmailGenerator(
        api_key="test-key",
        base_url="http://llm.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    input_payload = EmailGenerationInput(
        inquiry_subject="RFQ",
        inquiry_raw_body="Please quote bolts",
        customer_company="ACME",
        requirements={},
        missing_requirements=[],
        quote=None,
        items=(),
        language="en",
    )
    await generator.generate(input_payload, usage_sink=usage_sink)

    assert len(captured) == 1
    assert captured[0].total_tokens == 280


async def test_deterministic_email_generator_accepts_sink_and_never_calls_it() -> None:
    captured: list[LLMUsage] = []

    async def usage_sink(usage: LLMUsage) -> None:
        captured.append(usage)

    generator = DeterministicEmailGenerator()
    input_payload = EmailGenerationInput(
        inquiry_subject="RFQ",
        inquiry_raw_body="Please quote bolts",
        customer_company="ACME",
        requirements={},
        missing_requirements=[],
        quote=EmailQuote(
            quote_no="Q-001",
            version_no=1,
            currency="USD",
            subtotal="100.00",
            discount_total="0.00",
            freight_total="0.00",
            grand_total="100.00",
            valid_until="2026-12-31",
            incoterm="FOB",
            payment_terms="T/T",
            lead_time="30 days",
        ),
        items=(
            EmailQuoteItem(
                product_code="M8x40",
                product_name="Hex Bolt",
                standard_code="DIN933",
                material="SS304",
                grade="A2-70",
                diameter="M8",
                length="40",
                thread_pitch=None,
                surface_finish=None,
                quantity="1000",
                unit="PCS",
                price_unit="PCS",
                unit_price="0.10",
                line_total="100.00",
                price_basis="PER_PIECE",
            ),
        ),
        language="en",
    )
    result = await generator.generate(input_payload, usage_sink=usage_sink)
    assert result is not None
    assert captured == []
