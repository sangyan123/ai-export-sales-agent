import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.ai.email import EmailGenerationError, EmailGenerationErrorCode
from app.email import EmailError, EmailErrorCode
from app.inquiries.analysis import AnalysisError, AnalysisErrorCode
from app.matching import MatchingError, MatchingErrorCode
from app.pricing import PricingError, PricingErrorCode
from app.quotes import QuoteError, QuoteErrorCode
from app.workflows import WorkflowError, WorkflowErrorCode


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []


QUOTE_ERROR_STATUS: dict[QuoteErrorCode, int] = {
    QuoteErrorCode.QUOTE_NOT_FOUND: 404,
    QuoteErrorCode.PRODUCT_NOT_FOUND: 404,
    QuoteErrorCode.INQUIRY_NOT_FOUND: 404,
    QuoteErrorCode.SELF_APPROVAL_FORBIDDEN: 403,
    QuoteErrorCode.QUOTE_VERSION_EXISTS: 409,
    QuoteErrorCode.INVALID_STATUS_TRANSITION: 409,
    QuoteErrorCode.APPROVAL_NOT_FOUND: 409,
    QuoteErrorCode.APPROVAL_AMBIGUOUS: 409,
    QuoteErrorCode.QUOTE_EMPTY: 400,
    QuoteErrorCode.INVALID_QUOTE_NO: 400,
    QuoteErrorCode.VALIDITY_NOT_REACHED: 400,
}

PRICING_ERROR_STATUS: dict[PricingErrorCode, int] = {
    PricingErrorCode.PRODUCT_NOT_FOUND: 404,
}

WORKFLOW_ERROR_STATUS: dict[WorkflowErrorCode, int] = {
    WorkflowErrorCode.WORKFLOW_RUN_NOT_FOUND: 404,
    WorkflowErrorCode.INVALID_WORKFLOW_STATUS: 409,
}

ANALYSIS_ERROR_STATUS: dict[AnalysisErrorCode, int] = {
    AnalysisErrorCode.INQUIRY_NOT_FOUND: 404,
    AnalysisErrorCode.ANALYSIS_RUN_NOT_FOUND: 404,
    AnalysisErrorCode.INQUIRY_STATUS_NOT_ANALYZABLE: 409,
    AnalysisErrorCode.INQUIRY_ANALYSIS_IN_PROGRESS: 409,
}

MATCHING_ERROR_STATUS: dict[MatchingErrorCode, int] = {
    MatchingErrorCode.INQUIRY_NOT_FOUND: 404,
    MatchingErrorCode.INQUIRY_STATUS_NOT_MATCHABLE: 409,
    MatchingErrorCode.REQUIREMENTS_NOT_READY: 409,
    MatchingErrorCode.REQUIREMENTS_INCOMPLETE: 409,
}

EMAIL_ERROR_STATUS: dict[EmailErrorCode, int] = {
    EmailErrorCode.INQUIRY_NOT_FOUND: 404,
    EmailErrorCode.EMAIL_DRAFT_NOT_FOUND: 404,
    EmailErrorCode.EMAIL_QUOTE_NOT_FOUND: 404,
    EmailErrorCode.EMAIL_QUOTE_NOT_APPROVED: 409,
    EmailErrorCode.EMAIL_DRAFT_NOT_EDITABLE: 409,
    EmailErrorCode.EMAIL_DRAFT_NOT_APPROVABLE: 409,
    EmailErrorCode.EMAIL_UNSUPPORTED_LANGUAGE: 400,
}

EMAIL_GENERATION_ERROR_STATUS: dict[EmailGenerationErrorCode, int] = {
    EmailGenerationErrorCode.CONFIGURATION_ERROR: 503,
    EmailGenerationErrorCode.UNSUPPORTED_LANGUAGE: 400,
    EmailGenerationErrorCode.PROVIDER_UNAVAILABLE: 502,
    EmailGenerationErrorCode.PROVIDER_HTTP_ERROR: 502,
    EmailGenerationErrorCode.INVALID_OUTPUT: 502,
}


def get_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        return str(request_id)
    return request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex}"


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or [],
                "request_id": get_request_id(request),
            }
        },
    )


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return _error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def quote_error_handler(request: Request, exc: QuoteError) -> JSONResponse:
    return _error_response(
        request,
        status_code=QUOTE_ERROR_STATUS.get(exc.code, 400),
        code=exc.code.value,
        message=exc.message,
    )


async def pricing_error_handler(request: Request, exc: PricingError) -> JSONResponse:
    return _error_response(
        request,
        status_code=PRICING_ERROR_STATUS.get(exc.code, 400),
        code=exc.code.value,
        message=exc.message,
    )


async def workflow_error_handler(request: Request, exc: WorkflowError) -> JSONResponse:
    return _error_response(
        request,
        status_code=WORKFLOW_ERROR_STATUS.get(exc.code, 400),
        code=exc.code.value,
        message=exc.message,
    )


async def analysis_error_handler(request: Request, exc: AnalysisError) -> JSONResponse:
    return _error_response(
        request,
        status_code=ANALYSIS_ERROR_STATUS.get(exc.code, 400),
        code=exc.code.value,
        message=exc.message,
    )


async def matching_error_handler(request: Request, exc: MatchingError) -> JSONResponse:
    return _error_response(
        request,
        status_code=MATCHING_ERROR_STATUS.get(exc.code, 400),
        code=exc.code.value,
        message=exc.message,
    )


async def email_error_handler(request: Request, exc: EmailError) -> JSONResponse:
    return _error_response(
        request,
        status_code=EMAIL_ERROR_STATUS.get(exc.code, 400),
        code=exc.code.value,
        message=exc.message,
    )


async def email_generation_error_handler(
    request: Request, exc: EmailGenerationError
) -> JSONResponse:
    return _error_response(
        request,
        status_code=EMAIL_GENERATION_ERROR_STATUS.get(exc.code, 502),
        code=exc.code.value,
        message=exc.message,
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {
            "field": ".".join(str(part) for part in error["loc"][1:]),
            "reason": error["type"],
        }
        for error in exc.errors()
    ]
    return _error_response(
        request,
        status_code=422,
        code="VALIDATION_ERROR",
        message="request validation failed",
        details=details,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(QuoteError, quote_error_handler)
    app.add_exception_handler(PricingError, pricing_error_handler)
    app.add_exception_handler(WorkflowError, workflow_error_handler)
    app.add_exception_handler(AnalysisError, analysis_error_handler)
    app.add_exception_handler(MatchingError, matching_error_handler)
    app.add_exception_handler(EmailError, email_error_handler)
    app.add_exception_handler(EmailGenerationError, email_generation_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
