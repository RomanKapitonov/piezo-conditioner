#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract the amplitude/value column from a two-column CSV."
    )
    parser.add_argument(
        "input_csv",
        nargs="?",
        type=Path,
        default=Path("input.csv"),
        help="Source CSV file. Defaults to input.csv",
    )
    parser.add_argument(
        "output_csv",
        nargs="?",
        type=Path,
        default=Path("amplitude.csv"),
        help="Output file containing only amplitude values. Defaults to amplitude.csv",
    )
    return parser.parse_args()


def extract_values(input_csv: Path, output_csv: Path) -> int:
    written = 0

    with input_csv.open("r", encoding="utf-8", errors="ignore", newline="") as src:
        reader = csv.reader(src, delimiter=";")

        with output_csv.open("w", encoding="utf-8", newline="") as dst:
            for row in reader:
                if len(row) < 2:
                    continue

                value = row[1].strip()
                if not value or value == "V(TRIG_T1)":
                    continue

                dst.write(value)
                dst.write("\n")
                written += 1

    return written


def main() -> int:
    args = parse_args()
    count = extract_values(args.input_csv, args.output_csv)
    print(f"Wrote {count} values to {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
