"""Offline evaluation CLI for inquiry field extraction (markdown/08 section 5.1).

Usage:
    uv run python scripts/evaluate_ai_parsing.py            # full report
    uv run python scripts/evaluate_ai_parsing.py --gate     # exit 1 if gate fails
"""

import argparse
import asyncio
import sys

from app.ai.evaluation import GATE_THRESHOLD, load_golden_set, run_evaluation


def print_report(report) -> None:
    golden = load_golden_set()
    print(f"Golden set: {golden['version']} ({len(golden['samples'])} samples)")
    print("=" * 78)
    print(
        f"Samples: {report.total_samples} total | {report.gated_samples} gated"
        f" | {report.known_issue_samples} known issues (excluded from gate)"
    )
    print(f"Critical-field normalized accuracy: {report.critical_accuracy:.2%}")
    print(f"Gate threshold: >= {GATE_THRESHOLD:.0%} -> {'PASS' if report.gate_passed else 'FAIL'}")
    print()
    header = f"{'field':22s} {'acc':>6s} {'prec':>6s} {'rec':>6s} {'f1':>6s} {'misfill':>8s} {'ann':>4s} {'null':>5s}"
    print(header)
    print("-" * len(header))
    for name, m in report.field_metrics.items():
        print(
            f"{name:22s} {m.accuracy:6.2%} {m.precision:6.2%} {m.recall:6.2%}"
            f" {m.f1:6.2%} {m.misfill_rate:8.2%} {m.annotated:4d} {m.null_annotated:5d}"
        )
    print()
    known = [r for r in report.sample_results if r.known_issue]
    if known:
        print("Known issues (tracked, excluded from gate):")
        for r in known:
            status = "OK" if not r.failures else "; ".join(r.failures)
            print(f"  {r.sample_id}: {status}")
    failures = [r for r in report.sample_results if r.failures and not r.known_issue]
    if failures:
        print()
        print("Gate failures:")
        for r in failures:
            print(f"  {r.sample_id}: {'; '.join(r.failures)}")


def main() -> int:
    arg_parser = argparse.ArgumentParser(description=__doc__)
    arg_parser.add_argument(
        "--gate",
        action="store_true",
        help="exit with code 1 when the accuracy gate fails",
    )
    args = arg_parser.parse_args()

    report = asyncio.run(run_evaluation())
    print_report(report)

    if args.gate and not report.gate_passed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
