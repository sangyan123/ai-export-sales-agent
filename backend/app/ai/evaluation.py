"""Golden-set evaluation core for inquiry field extraction.

Loads the fixed annotated dataset, runs the deterministic parser offline,
and computes per-field normalized-match metrics per the acceptance doc
(markdown/08 section 5.1):

- per-field accuracy, precision, recall, F1
- misfill rate on expected-null fields (missing-field discipline)
- critical-field accuracy reported separately
- samples flagged as known_issues are reported but excluded from the gate
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.ai.parser import DeterministicInquiryParser
from app.ai.schemas import CRITICAL_FIELDS, FIELD_NAMES

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "inquiry_golden_set.json"

GATE_THRESHOLD = 0.90


@dataclass
class FieldMetrics:
    field: str
    annotated: int = 0  # expected non-null
    null_annotated: int = 0  # expected null
    correct: int = 0
    misfilled: int = 0  # predicted value where null expected
    predicted: int = 0  # predicted non-null
    true_positive: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct / self.annotated if self.annotated else 1.0

    @property
    def misfill_rate(self) -> float:
        return self.misfilled / self.null_annotated if self.null_annotated else 0.0

    @property
    def precision(self) -> float:
        return self.true_positive / self.predicted if self.predicted else 1.0

    @property
    def recall(self) -> float:
        return self.true_positive / self.annotated if self.annotated else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class SampleResult:
    sample_id: str
    category: str
    known_issue: bool
    field_results: dict[str, str] = field(default_factory=dict)  # field -> PASS/FAIL/MISS/MISFILL
    failures: list[str] = field(default_factory=list)


@dataclass
class EvaluationReport:
    total_samples: int = 0
    gated_samples: int = 0
    known_issue_samples: int = 0
    field_metrics: dict[str, FieldMetrics] = field(default_factory=dict)
    critical_accuracy: float = 0.0
    gate_passed: bool = False
    sample_results: list[SampleResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_samples": self.total_samples,
            "gated_samples": self.gated_samples,
            "known_issue_samples": self.known_issue_samples,
            "critical_accuracy": round(self.critical_accuracy, 4),
            "gate_threshold": GATE_THRESHOLD,
            "gate_passed": self.gate_passed,
            "fields": {
                name: {
                    "annotated": m.annotated,
                    "null_annotated": m.null_annotated,
                    "correct": m.correct,
                    "misfilled": m.misfilled,
                    "accuracy": round(m.accuracy, 4),
                    "precision": round(m.precision, 4),
                    "recall": round(m.recall, 4),
                    "f1": round(m.f1, 4),
                    "misfill_rate": round(m.misfill_rate, 4),
                }
                for name, m in self.field_metrics.items()
            },
            "failures": [
                {"sample_id": r.sample_id, "fields": r.field_results, "failures": r.failures}
                for r in self.sample_results
                if r.failures
            ],
        }


def load_golden_set(path: Path = FIXTURE_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


async def run_evaluation(golden_set: dict[str, Any] | None = None) -> EvaluationReport:
    if golden_set is None:
        golden_set = load_golden_set()

    parser = DeterministicInquiryParser()
    report = EvaluationReport()
    report.total_samples = len(golden_set["samples"])

    critical_correct = 0
    critical_annotated = 0

    for name in FIELD_NAMES + ("unit",):
        report.field_metrics[name] = FieldMetrics(field=name)

    for sample in golden_set["samples"]:
        result = await parser.parse(
            subject=sample["subject"],
            raw_text=sample["raw_text"],
            language=sample.get("language"),
        )
        expected: dict[str, Any] = sample["expected"]
        sample_result = SampleResult(
            sample_id=sample["id"],
            category=sample.get("category", "general"),
            known_issue=bool(sample.get("known_issue")),
        )
        if sample_result.known_issue:
            report.known_issue_samples += 1
        else:
            report.gated_samples += 1

        for field_name in FIELD_NAMES:
            metrics = report.field_metrics[field_name]
            expected_value = expected.get(field_name)
            parsed_field = getattr(result, field_name)
            predicted = (parsed_field.normalized_value or parsed_field.value or "").strip() or None

            if expected_value is None:
                metrics.null_annotated += 1
                if predicted is not None:
                    metrics.misfilled += 1
                    sample_result.field_results[field_name] = "MISFILL"
                    sample_result.failures.append(
                        f"{field_name}: expected empty, got {predicted!r}"
                    )
                else:
                    sample_result.field_results[field_name] = "PASS"
                continue

            metrics.annotated += 1
            if predicted is not None:
                metrics.predicted += 1
            if predicted == expected_value:
                metrics.correct += 1
                metrics.true_positive += 1
                sample_result.field_results[field_name] = "PASS"
                if field_name in CRITICAL_FIELDS:
                    critical_correct += 1
            else:
                sample_result.field_results[field_name] = "FAIL"
                sample_result.failures.append(
                    f"{field_name}: expected {expected_value!r}, got {predicted!r}"
                )
            if field_name in CRITICAL_FIELDS:
                critical_annotated += 1

        unit_metrics = report.field_metrics["unit"]
        expected_unit = expected.get("unit")
        if expected_unit is None:
            unit_metrics.null_annotated += 1
            if result.unit is not None:
                unit_metrics.misfilled += 1
                sample_result.field_results["unit"] = "MISFILL"
                sample_result.failures.append(f"unit: expected empty, got {result.unit!r}")
            else:
                sample_result.field_results["unit"] = "PASS"
        else:
            unit_metrics.annotated += 1
            if result.unit is not None:
                unit_metrics.predicted += 1
            if result.unit == expected_unit:
                unit_metrics.correct += 1
                unit_metrics.true_positive += 1
                sample_result.field_results["unit"] = "PASS"
                if "quantity" in CRITICAL_FIELDS:
                    critical_correct += 1
            else:
                sample_result.field_results["unit"] = "FAIL"
                sample_result.failures.append(f"unit: expected {expected_unit!r}, got {result.unit!r}")
            if "quantity" in CRITICAL_FIELDS:
                critical_annotated += 1

        report.sample_results.append(sample_result)

    report.critical_accuracy = (
        critical_correct / critical_annotated if critical_annotated else 1.0
    )
    report.gate_passed = report.critical_accuracy >= GATE_THRESHOLD
    return report
