#!/usr/bin/env python3
"""Calculate HWPX table column widths in HWPUNIT.

Column widths must sum to the document body width exactly. This script
computes integer widths from ratios, distributing any rounding remainder
to the first column(s).

Usage:
    # Equal columns
    python calc_col_widths.py 3
    # → 14174 14173 14173  (sum=42520)

    # Ratio-based (label:content = 1:4)
    python calc_col_widths.py 1:4
    # → 8504 34016  (sum=42520)

    # Custom body width (e.g. table nested inside a wider margin)
    python calc_col_widths.py 2:3:5 --body 21260
    # → 4252 6378 10630  (sum=21260)

    # Verify an existing set of widths
    python calc_col_widths.py --verify 14174 14173 14173

Default body width: 42520 HWPUNIT = A4 (210mm) − 30mm left/right margins
"""
# Windows console: emit UTF-8 (avoid cp949 mojibake)
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8")
    _sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import argparse
import sys

A4_BODY_WIDTH = 42520  # 150mm in HWPUNIT


def calc_widths(ratios: list[int], body_width: int) -> list[int]:
    total = sum(ratios)
    widths = [body_width * r // total for r in ratios]
    remainder = body_width - sum(widths)
    for i in range(remainder):
        widths[i] += 1
    return widths


def parse_spec(spec: str) -> list[int]:
    if ":" in spec:
        parts = spec.split(":")
        return [int(p) for p in parts]
    n = int(spec)
    if n <= 0:
        raise ValueError("Column count must be positive")
    return [1] * n


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calculate HWPX table column widths (HWPUNIT) summing to body width"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "spec",
        nargs="?",
        help="Column count (e.g. 3) or ratio spec (e.g. 1:4 or 1:2:3)",
    )
    group.add_argument(
        "--verify",
        nargs="+",
        type=int,
        metavar="WIDTH",
        help="Verify that provided widths sum to body width",
    )
    parser.add_argument(
        "--body",
        type=int,
        default=A4_BODY_WIDTH,
        help=f"Body width in HWPUNIT (default: {A4_BODY_WIDTH} = A4 150mm)",
    )
    args = parser.parse_args()

    if args.verify:
        total = sum(args.verify)
        if total == args.body:
            print(f"OK: sum={total} == body width {args.body}")
        else:
            diff = total - args.body
            print(
                f"ERROR: sum={total}, body={args.body}, diff={diff:+d}",
                file=sys.stderr,
            )
            sys.exit(1)
        return

    try:
        ratios = parse_spec(args.spec)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    widths = calc_widths(ratios, args.body)
    print(" ".join(str(w) for w in widths))
    print(f"# {len(widths)} columns, sum={sum(widths)}, body={args.body}", file=sys.stderr)


if __name__ == "__main__":
    main()
