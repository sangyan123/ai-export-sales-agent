from enum import StrEnum


class ProductImportErrorCode(StrEnum):
    PRODUCT_IMPORT_NOT_FOUND = "PRODUCT_IMPORT_NOT_FOUND"
    IMPORT_FILE_REQUIRED = "IMPORT_FILE_REQUIRED"
    IMPORT_FILE_UNSUPPORTED = "IMPORT_FILE_UNSUPPORTED"
    IMPORT_FILE_TOO_LARGE = "IMPORT_FILE_TOO_LARGE"
    IMPORT_TEMPLATE_INVALID = "IMPORT_TEMPLATE_INVALID"
    IMPORT_EMPTY = "IMPORT_EMPTY"
    IMPORT_TOO_MANY_ROWS = "IMPORT_TOO_MANY_ROWS"


class ProductImportRowErrorCode(StrEnum):
    REQUIRED = "REQUIRED"
    TOO_LONG = "TOO_LONG"
    INVALID_CATEGORY = "INVALID_CATEGORY"
    INVALID_MOQ = "INVALID_MOQ"
    DUPLICATE_PRODUCT_CODE = "DUPLICATE_PRODUCT_CODE"
    PRODUCT_CODE_EXISTS = "PRODUCT_CODE_EXISTS"


class ProductImportError(Exception):
    def __init__(self, code: ProductImportErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


__all__ = [
    "ProductImportError",
    "ProductImportErrorCode",
    "ProductImportRowErrorCode",
]
