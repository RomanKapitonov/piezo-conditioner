#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a Signal Studio style waveform CSV into a 4000-point external-arb CSV."
    )
    parser.add_argument(
        "input_csv",
        type=Path,
        help="Source waveform CSV.",
    )
    parser.add_argument(
        "output_csv",
        nargs="?",
        type=Path,
        default=Path("actual_signal_ext.csv"),
        help="Output waveform CSV for external arb upload.",
    )
    parser.add_argument(
        "--points",
        type=int,
        default=4000,
        help="Target point count.",
    )
    return parser.parse_args()


def parse_signal_studio_csv(path: Path) -> tuple[dict[str, str], list[float]]:
    values: dict[str, str] = {}
    samples: list[float] = []
    in_data = False

    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("[DATA]:"):
                _, value = line.split(":", 1)
                values["[DATA]"] = value.strip()
                in_data = True
                continue

            if not in_data and ":" in line:
                key, value = line.split(":", 1)
                values[key.strip().upper()] = value.strip()
                continue

            token = line.rstrip(",").strip()
            if not token:
                continue
            samples.append(float(token))

    return values, samples


def resample_samples(samples: list[float], target_count: int) -> list[float]:
    if len(samples) == target_count:
        return list(samples)
    if len(samples) < 2:
        raise ValueError("At least two samples are required for resampling")

    result: list[float] = []
    source_last = len(samples) - 1
    target_last = target_count - 1

    for i in range(target_count):
        position = (i * source_last) / target_last
        left = int(position)
        right = min(left + 1, source_last)
        frac = position - left
        result.append(samples[left] * (1.0 - frac) + samples[right] * frac)

    return result


def main() -> int:
    args = parse_args()
    values, samples = parse_signal_studio_csv(args.input_csv)
    source_count = len(samples)
    converted = resample_samples(samples, args.points)
    eol = "\r\n"
    source_rate_pos = float(values.get("RATEPOS", "0.000031"))
    source_rate_neg = float(values.get("RATENEG", str(source_rate_pos)))
    rate_scale = source_count / len(converted)
    rate_pos = f"{source_rate_pos * rate_scale:.9f}"
    rate_neg = f"{source_rate_neg * rate_scale:.9f}"
    channel = values.get("CHANNEL", "1")
    vpp = values.get("VPP", "2.000000")
    offset = values.get("OFFSET", "0.000000")

    header_body = (
        f"VPP:{vpp}{eol}"
        f"OFFSET:{offset}{eol}"
        f"CHANNEL:{channel}{eol}"
        f"RATEPOS:{rate_pos}{eol}"
        f"RATENEG:{rate_neg}{eol}"
        f"MAX:32767.000000{eol}"
        f"MIN:-32767.000000{eol}"
    )
    head_len = len(header_body.encode("ascii"))

    with args.output_csv.open("w", encoding="ascii", newline="") as handle:
        handle.write(f"[HEAD]:{head_len}{eol}")
        handle.write(header_body)
        handle.write(f"[DATA]:{len(converted)}{eol}")
        for sample in converted:
            handle.write(f"{sample:.8G},{eol}")

    print(f"Wrote {args.output_csv} with {len(converted)} samples from {args.input_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
