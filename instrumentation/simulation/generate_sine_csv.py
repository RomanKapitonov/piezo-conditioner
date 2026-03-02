#!/usr/bin/env python3

from __future__ import annotations

import argparse
import math
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a UTG-compatible 4096-point sine waveform CSV."
    )
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        default=Path("sine_test.csv"),
        help="Output waveform CSV path.",
    )
    parser.add_argument(
        "--points",
        type=int,
        default=4000,
        help="Number of waveform points. External UTG custom waves work reliably at 4000.",
    )
    parser.add_argument(
        "--vpp",
        type=float,
        default=2.0,
        help="Header VPP value.",
    )
    parser.add_argument(
        "--offset",
        type=float,
        default=0.0,
        help="Header offset value.",
    )
    parser.add_argument(
        "--channel",
        type=int,
        default=1,
        choices=(1, 2),
        help="Header channel value.",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=0.000031,
        help="Header RATEPOS/RATENEG value in seconds.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    eol = "\r\n"
    samples = [math.sin(2.0 * math.pi * i / args.points) for i in range(args.points)]
    header_body = (
        f"VPP:{args.vpp:.6f}{eol}"
        f"OFFSET:{args.offset:.6f}{eol}"
        f"CHANNEL:{args.channel}{eol}"
        f"RATEPOS:{args.rate:.6f}{eol}"
        f"RATENEG:{args.rate:.6f}{eol}"
        f"MAX:32767.000000{eol}"
        f"MIN:-32767.000000{eol}"
    )
    head_len = len(header_body.encode("ascii"))

    with args.output.open("w", encoding="ascii", newline="") as handle:
        handle.write(f"[HEAD]:{head_len}{eol}")
        handle.write(header_body)
        handle.write(f"[DATA]:{args.points}{eol}")
        for sample in samples:
            handle.write(f"{sample:.8G},{eol}")

    print(f"Wrote {args.output} with {args.points} sine samples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
