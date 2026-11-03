from enum import StrEnum


class WorkflowStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


CANCELLABLE_STATUSES = frozenset({WorkflowStatus.QUEUED, WorkflowStatus.RUNNING})


class WorkflowErrorCode(StrEnum):
    WORKFLOW_RUN_NOT_FOUND = "WORKFLOW_RUN_NOT_FOUND"
    INVALID_WORKFLOW_STATUS = "INVALID_WORKFLOW_STATUS"


class WorkflowError(Exception):
    def __init__(self, code: WorkflowErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


__all__ = [
    "CANCELLABLE_STATUSES",
    "WorkflowError",
    "WorkflowErrorCode",
    "WorkflowStatus",
]
