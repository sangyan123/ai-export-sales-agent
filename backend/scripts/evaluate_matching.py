"""Offline evaluation CLI for product matching (acceptance doc section 5.2).

Usage:
    uv run python scripts/evaluate_matching.py            # full report
    uv run python scripts/evaluate_matching.py --gate     # exit 1 if gate fails
"""

import argparse
import sys

from app.matching.evaluation import TOP3_GATE, load_matching_set, run_matching_evaluation


def print_report(report) -> None:
    golden = load_matching_set()
    print(f"Matching golden set: {golden['version']} ({len(golden['samples'])} samples, {len(golden['catalog'])} catalog SKUs)")
    print("=" * 76)
    print(f"Applicable samples: {report.applicable_samples} (annotated correct product)")
    print(f"Top-1 hit rate:     {report.top1_rate:.2%}  ({report.top1_hits}/{report.top1_annotated})")
    print(f"Top-3 hit rate:     {report.top3_rate:.2%}  ({report.top3_hits}/{report.applicable_samples})")
    print(f"MRR:                {report.mrr:.4f}")
    print(f"Hard-conflict EXACT misjudgements: {report.hard_conflict_exact_count} (must be 0)")
    if report.no_exact_samples:
        print(
            f"Not-applicable recall: {report.no_exact_recall_hits}/{report.no_exact_samples}"
            " (no EXACT produced)"
        )
    print(f"Gate: top3 >= {TOP3_GATE:.0%} AND conflict_exact == 0 -> {'PASS' if report.gate_passed else 'FAIL'}")

    if report.failures:
        print()
        print("Failures:")
        for failure in report.failures:
            print(f"  {failure}")

    print()
    print("Per-sample ranking (top candidate):")
    for result in report.sample_results:
        if result.ranked:
            code, status, score = result.ranked[0]
            print(f"  {result.sample_id}: {code} [{status}] score={score:.2f}")
        else:
            print(f"  {result.sample_id}: no candidates")


def main() -> int:
    arg_parser = argparse.ArgumentParser(description=__doc__)
    arg_parser.add_argument(
        "--gate",
        action="store_true",
        help="exit with code 1 when the gate fails",
    )
    args = arg_parser.parse_args()

    report = run_matching_evaluation()
    print_report(report)
    if args.gate and not report.gate_passed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
