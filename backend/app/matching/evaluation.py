"""Offline evaluation core for product matching (acceptance doc section 5.2).

Replays the production candidate-scoring and ordering rules
(app.matching.service._score_candidate + generate ordering) against a
fixed annotated catalog, computing:

- Top-1 / Top-3 hit rates over applicable samples
- MRR (mean reciprocal rank) over applicable samples
- Hard-conflict-EXACT misjudgement count (must always be 0)
- No-match recall (annotated not-applicable samples that yield no EXACT)
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.matching.service import (
    EXACT_MIN_SCORE,
    _STATUS_RANK,
    _score_candidate,
)
from app.models.product import Product

FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "matching_golden_set.json"
)

TOP3_GATE = 0.85


@dataclass
class SampleResult:
    sample_id: str
    expected_top1: str | None = None
    expected_top3: list[str] | None = None
    expected_conflict: bool = False
    expect_no_exact: bool = False
    ranked: list[tuple[str, str, float]] = field(default_factory=list)  # code, status, score

    @property
    def top1_hit(self) -> bool:
        if self.expected_top1 is None:
            return False
        return bool(self.ranked) and self.ranked[0][0] == self.expected_top1

    @property
    def top3_hit(self) -> bool:
        codes = [code for code, _, _ in self.ranked[:3]]
        if self.expected_top3:
            return any(code in codes for code in self.expected_top3)
        if self.expected_top1:
            return self.expected_top1 in codes
        return False

    @property
    def reciprocal_rank(self) -> float:
        if self.expected_top1 is None:
            return 0.0
        for position, (code, _, _) in enumerate(self.ranked, start=1):
            if code == self.expected_top1:
                return 1.0 / position
        return 0.0

    @property
    def hard_conflict_exact(self) -> bool:
        if not self.expected_conflict:
            return False
        return any(status == "EXACT" for _, status, _ in self.ranked)

    @property
    def no_exact_on_not_applicable(self) -> bool:
        if not self.expect_no_exact:
            return False
        return not any(status == "EXACT" for _, status, _ in self.ranked)


@dataclass
class MatchingReport:
    total_samples: int = 0
    applicable_samples: int = 0  # samples with annotated correct product(s)
    top1_annotated: int = 0  # samples with expected_top1
    top1_hits: int = 0
    top3_hits: int = 0
    reciprocal_ranks: list[float] = field(default_factory=list)
    hard_conflict_exact_count: int = 0
    no_exact_recall_hits: int = 0
    no_exact_samples: int = 0
    gate_passed: bool = False
    failures: list[str] = field(default_factory=list)
    sample_results: list[SampleResult] = field(default_factory=list)

    @property
    def top1_rate(self) -> float:
        return self.top1_hits / self.top1_annotated if self.top1_annotated else 1.0

    @property
    def top3_rate(self) -> float:
        return self.top3_hits / self.applicable_samples if self.applicable_samples else 1.0

    @property
    def mrr(self) -> float:
        return (
            sum(self.reciprocal_ranks) / len(self.reciprocal_ranks)
            if self.reciprocal_ranks
            else 1.0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_samples": self.total_samples,
            "applicable_samples": self.applicable_samples,
            "top1_annotated": self.top1_annotated,
            "top1_rate": round(self.top1_rate, 4),
            "top3_rate": round(self.top3_rate, 4),
            "mrr": round(self.mrr, 4),
            "hard_conflict_exact_count": self.hard_conflict_exact_count,
            "no_exact_recall": (
                self.no_exact_recall_hits / self.no_exact_samples
                if self.no_exact_samples
                else 1.0
            ),
            "gate_threshold": TOP3_GATE,
            "gate_passed": self.gate_passed,
            "failures": self.failures,
        }


def load_matching_set(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_product(entry: dict[str, Any]) -> Product:
    product = Product()
    for key, value in entry.items():
        setattr(product, key, value)
    return product


def run_matching_evaluation(golden_set: dict[str, Any] | None = None) -> MatchingReport:
    if golden_set is None:
        golden_set = load_matching_set()

    catalog = {
        entry["product_code"].upper(): _build_product(entry)
        for entry in golden_set["catalog"]
    }
    report = MatchingReport()
    report.total_samples = len(golden_set["samples"])

    for sample in golden_set["samples"]:
        values: dict[str, str] = sample["values"]
        result = SampleResult(
            sample_id=sample["id"],
            expected_top1=sample.get("expected_top1"),
            expected_top3=sample.get("expected_top3"),
            expected_conflict=bool(sample.get("expected_conflict")),
            expect_no_exact=bool(sample.get("expect_no_exact")),
        )

        category = (values.get("product_category") or "").upper()
        candidates = [
            _score_candidate(values, product)
            for code, product in catalog.items()
            if str(product.category).upper() == category
        ]
        ranked = sorted(
            candidates,
            key=lambda item: (-_STATUS_RANK[item.status], -item.score, item.product.product_code),
        )
        result.ranked = [
            (item.product.product_code, item.status.value, float(item.score)) for item in ranked
        ]

        if result.expected_top1 is not None or result.expected_top3 is not None:
            report.applicable_samples += 1
            if result.expected_top1 is not None:
                report.top1_annotated += 1
                report.reciprocal_ranks.append(result.reciprocal_rank)
                if result.top1_hit:
                    report.top1_hits += 1
            if result.top3_hit:
                report.top3_hits += 1
        if result.hard_conflict_exact:
            report.hard_conflict_exact_count += 1
            report.failures.append(
                f"{result.sample_id}: hard conflict misjudged as EXACT "
                f"(ranked={result.ranked[:3]})"
            )
        if result.expect_no_exact:
            report.no_exact_samples += 1
            if result.no_exact_on_not_applicable:
                report.no_exact_recall_hits += 1
            else:
                report.failures.append(
                    f"{result.sample_id}: not-applicable sample produced EXACT"
                )
        report.sample_results.append(result)

    report.gate_passed = (
        report.top3_rate >= TOP3_GATE and report.hard_conflict_exact_count == 0
    )
    return report


__all__ = [
    "EXACT_MIN_SCORE",
    "FIXTURE_PATH",
    "MatchingReport",
    "TOP3_GATE",
    "load_matching_set",
    "run_matching_evaluation",
]
