import json

import httpx
import pytest

from app.ai import (
    DeterministicInquiryParser,
    InquiryParseResult,
    OpenAICompatibleInquiryParser,
    ParserError,
    get_inquiry_parser,
)
from app.core.config import settings


async def test_deterministic_parser_extracts_core_fields() -> None:
    result = await DeterministicInquiryParser().parse(
        subject="RFQ - stainless steel bolts",
        raw_text="We need 5000 pcs of SS304 M8 x 50mm hex bolts for Germany, FOB Shanghai.",
        language="en",
    )

    assert result.product_category.normalized_value == "BOLT"
    assert result.material.normalized_value == "SS304"
    assert result.diameter.normalized_value == "M8"
    assert result.length.normalized_value == "50mm"
    assert result.quantity.value == "5000"
    assert result.unit == "PCS"
    assert result.destination_country.normalized_value == "DE"
    assert result.incoterm == "FOB"
    assert result.evidence_map()["material"] == "SS304"
    assert result.critical_missing_fields() == []
    assert "packaging" in result.missing_field_names()
    assert result.overall_confidence > 0.8


async def test_deterministic_parser_reports_missing_fields_for_sparse_text() -> None:
    result = await DeterministicInquiryParser().parse(
        subject="Price list request",
        raw_text="Please send your latest price list.",
        language="en",
    )

    assert result.missing_field_names() == [
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
    ]
    assert set(result.critical_missing_fields()) == {
        "product_category",
        "material",
        "diameter",
        "quantity",
        "unit",
    }
    assert result.overall_confidence == 0.0


async def test_openai_parser_retries_once_on_invalid_json() -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        content = (
            "not json"
            if len(calls) == 1
            else json.dumps(
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
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    parser = OpenAICompatibleInquiryParser(
        api_key="test-key",
        base_url="http://llm.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    result = await parser.parse(subject="RFQ", raw_text="hex bolts", language="en")

    assert result.product_category.normalized_value == "BOLT"
    assert len(calls) == 2
    assert calls[0]["model"] == "test-model"
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[1]["messages"][-1]["role"] == "user"
    assert "JSON" in calls[1]["messages"][-1]["content"]


async def test_openai_parser_accepts_code_fenced_json() -> None:
    payload = json.dumps({"overall_confidence": 0.4})
    fenced = f"```json\n{payload}\n```"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": fenced}}]})

    parser = OpenAICompatibleInquiryParser(
        api_key="test-key",
        base_url="http://llm.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    result = await parser.parse(subject="RFQ", raw_text="text", language="en")

    assert result.overall_confidence == 0.4


async def test_openai_parser_maps_provider_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    parser = OpenAICompatibleInquiryParser(
        api_key="test-key",
        base_url="http://llm.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ParserError) as excinfo:
        await parser.parse(subject="RFQ", raw_text="text", language="en")
    assert excinfo.value.code == "PROVIDER_HTTP_ERROR"


def test_parser_factory_selects_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_provider", "fake")
    assert isinstance(get_inquiry_parser(), DeterministicInquiryParser)

    monkeypatch.setattr(settings, "llm_provider", "unsupported")
    with pytest.raises(ParserError) as excinfo:
        get_inquiry_parser()
    assert excinfo.value.code == "PARSER_CONFIGURATION_ERROR"


def test_parse_result_helpers() -> None:
    result = InquiryParseResult(overall_confidence=0.5)
    assert result.confidence_map() == {"overall": 0.5}
    assert result.evidence_map() == {}
