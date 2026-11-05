"""Shared LLM usage tracking types for AI parsers and email generators."""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMUsage:
    """Token usage reported by the LLM provider for a single call."""

    model_id: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    duration_ms: int


UsageSink = Callable[[LLMUsage], Awaitable[None]]


class UsageTracker:
    """Accumulates wall-clock duration and captures provider-reported usage."""

    def __init__(self) -> None:
        self._started = time.monotonic()
        self.usage: LLMUsage | None = None

    def mark_usage(self, usage: LLMUsage) -> None:
        self.usage = usage

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._started) * 1000)
