"""Regression gate for the inquiry extraction golden set (markdown/08 5.1).

The fixed annotated dataset must keep critical-field normalized accuracy
at or above the 90% gate. Known-issue samples are excluded from the gate
but must remain explicitly flagged so they cannot silently regress.
As of parser v1.1 all original known issues are fixed; the gate now
covers the full 30-sample set.
"""

import pytest

from app.ai.evaluation import GATE_THRESHOLD, run_evaluation


@pytest.fixture(scope="module")
def report():
    import asyncio

    return asyncio.run(run_evaluation())


def test_gate_overall_critical_accuracy(report) -> None:
    assert report.gate_passed, (
        f"critical accuracy {report.critical_accuracy:.4f} below gate {GATE_THRESHOLD}"
    )


def test_no_gate_sample_failures(report) -> None:
    gate_failures = [
        r for r in report.sample_results if r.failures and not r.known_issue
    ]
    assert not gate_failures, (
        "gated samples regressed: "
        + "; ".join(f"{r.sample_id}: {r.failures}" for r in gate_failures)
    )


def test_known_issues_remain_flagged(report) -> None:
    expected_known: set[str] = set()
    flagged = {r.sample_id for r in report.sample_results if r.known_issue}
    assert flagged == expected_known


def test_misfill_rate_is_zero(report) -> None:
    for name, metrics in report.field_metrics.items():
        assert metrics.misfill_rate == 0.0, (
            f"field {name} misfilled empty expectations "
            f"({metrics.misfilled}/{metrics.null_annotated})"
        )
