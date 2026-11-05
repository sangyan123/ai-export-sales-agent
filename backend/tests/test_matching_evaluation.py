"""Regression gate for the product matching golden set (acceptance doc 5.2).

Gate: Top-3 hit rate >= 85% AND zero hard-conflict EXACT misjudgements.
"""

from app.matching.evaluation import (
    TOP3_GATE,
    load_matching_set,
    run_matching_evaluation,
)


def test_gate_top3_and_zero_conflict_exact() -> None:
    report = run_matching_evaluation()
    assert report.top3_rate >= TOP3_GATE, (
        f"top3 hit rate {report.top3_rate:.4f} below gate {TOP3_GATE}"
    )
    assert report.hard_conflict_exact_count == 0, (
        f"{report.hard_conflict_exact_count} hard-conflict candidates misjudged EXACT: "
        + "; ".join(report.failures)
    )


def test_top1_perfect_on_annotated_catalog() -> None:
    report = run_matching_evaluation()
    assert report.top1_rate == 1.0, (
        "top1 regressed on the fixed annotated catalog: "
        + "; ".join(report.failures)
    )


def test_mrr_strong() -> None:
    report = run_matching_evaluation()
    assert report.mrr >= 0.9, f"MRR regressed: {report.mrr:.4f}"


def test_not_applicable_sample_yields_no_exact() -> None:
    report = run_matching_evaluation()
    assert report.no_exact_samples > 0, "not-applicable guard sample missing"
    assert report.no_exact_recall_hits == report.no_exact_samples, (
        "not-applicable sample produced an EXACT recommendation"
    )


def test_fixture_catalog_integrity() -> None:
    golden = load_matching_set()
    codes = [entry["product_code"] for entry in golden["catalog"]]
    assert len(codes) == len(set(codes)), "duplicate product_code in fixture catalog"
    assert len(golden["samples"]) >= 10, "golden set samples regressed"
