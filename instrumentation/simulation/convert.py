#!/usr/bin/env python3

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

import numpy as np


def parse_input_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """
    Parse a two-column input file.
    Supports comma, tab, semicolon, or whitespace separated data.
    Skips header lines like:
        time,V(TRIG_T1)
        time\tV(TRIG_T1)
    """
    times = []
    values = []

    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue

            # Skip obvious section/header lines
            if line.startswith(("[", "#", ";", "*")):
                continue

            parts = re.split(r"[\t,; ]+", line)
            if len(parts) < 2:
                continue

            try:
                t = float(parts[0])
                v = float(parts[1])
            except ValueError:
                # probably header line
                continue

            times.append(t)
            values.append(v)

    if len(times) < 2:
        raise ValueError("Could not parse at least 2 numeric rows from input file.")

    t = np.asarray(times, dtype=np.float64)
    v = np.asarray(values, dtype=np.float64)

    # Sort by time
    order = np.argsort(t)
    t = t[order]
    v = v[order]

    # Remove duplicate timestamps, keep last occurrence
    keep = np.ones(len(t), dtype=bool)
    keep[:-1] = t[:-1] != t[1:]
    t = t[keep]
    v = v[keep]

    if len(t) < 2:
        raise ValueError("Not enough unique timestamps after deduplication.")

    return t, v


def crop_range(
    t: np.ndarray,
    v: np.ndarray,
    t_start: float | None,
    t_end: float | None,
) -> tuple[np.ndarray, np.ndarray]:
    if t_start is None:
        t_start = float(t[0])
    if t_end is None:
        t_end = float(t[-1])

    if t_end <= t_start:
        raise ValueError("t_end must be greater than t_start.")

    # Clamp to source range
    t_start = max(t_start, float(t[0]))
    t_end = min(t_end, float(t[-1]))

    if t_end <= t_start:
        raise ValueError("Requested crop range does not overlap input data.")

    mask = (t >= t_start) & (t <= t_end)
    tc = t[mask]
    vc = v[mask]

    # Ensure exact boundary samples exist
    if len(tc) == 0 or tc[0] > t_start:
        vc0 = np.interp(t_start, t, v)
        tc = np.insert(tc, 0, t_start)
        vc = np.insert(vc, 0, vc0)

    if tc[-1] < t_end:
        vc1 = np.interp(t_end, t, v)
        tc = np.append(tc, t_end)
        vc = np.append(vc, vc1)

    return tc, vc


def resample_bin_mean(t: np.ndarray, v: np.ndarray, points: int) -> np.ndarray:
    """
    Average over each output time bin.
    Better than naive decimation for non-uniform SPICE data.
    """
    t0 = float(t[0])
    t1 = float(t[-1])
    edges = np.linspace(t0, t1, points + 1, endpoint=True, dtype=np.float64)
    out = np.empty(points, dtype=np.float64)

    for i in range(points):
        a = edges[i]
        b = edges[i + 1]

        va = np.interp(a, t, v)
        vb = np.interp(b, t, v)

        lo = np.searchsorted(t, a, side="right")
        hi = np.searchsorted(t, b, side="left")

        seg_t = np.concatenate(([a], t[lo:hi], [b]))
        seg_v = np.concatenate(([va], v[lo:hi], [vb]))

        area = np.trapz(seg_v, seg_t)
        out[i] = area / (b - a)

    return out


def resample_interp(t: np.ndarray, v: np.ndarray, points: int) -> np.ndarray:
    """
    Uniform linear interpolation resampling.
    """
    t0 = float(t[0])
    t1 = float(t[-1])
    tu = np.linspace(t0, t1, points, endpoint=False, dtype=np.float64)
    return np.interp(tu, t, v)


def compute_vpp(v: np.ndarray) -> float:
    """
    Compute peak-to-peak voltage from the full signal range.
    """
    vmin = float(np.min(v))
    vmax = float(np.max(v))
    return vmax - vmin


def normalize_waveform(v: np.ndarray) -> tuple[np.ndarray, float, float]:
    """
    Convert waveform to the bipolar normalized sample values used by the
    reference UNI-T CSV format.
    Returns:
        normalized_samples, vpp, offset
    """
    vmin = float(np.min(v))
    vmax = float(np.max(v))
    vpp = compute_vpp(v)
    center = 0.5 * (vmax + vmin)

    if math.isclose(vpp, 0.0, abs_tol=1e-18):
        norm = np.zeros_like(v)
        vpp = 0.0
    else:
        norm = (v - center) / (0.5 * vpp)
        norm = np.clip(norm, -1.0, 1.0)

    return norm, vpp, 0.0


def fmt_sample(x: float) -> str:
    return f"{x:.8G},"


def write_signal_studio_csv(
    path: Path,
    samples: np.ndarray,
    channel: int,
    vpp: float,
    offset: float,
    rate_pos: float,
    rate_neg: float,
) -> None:
    """
    Write the UNI-T arbitrary waveform CSV format seen in the reference file.
    """
    eol = "\r\n"
    header_body = (
        f"VPP:{vpp:.6f}{eol}"
        f"OFFSET:{offset:.6f}{eol}"
        f"CHANNEL:{channel}{eol}"
        f"RATEPOS:{rate_pos:.6f}{eol}"
        f"RATENEG:{rate_neg:.6f}{eol}"
        f"MAX:32767.000000{eol}"
        f"MIN:-32767.000000{eol}"
    )

    head_len = len(header_body.encode("ascii"))

    with path.open("w", encoding="ascii", newline="") as f:
        f.write(f"[HEAD]:{head_len}{eol}")
        f.write(header_body)
        f.write(f"[DATA]:{len(samples)}{eol}")
        for x in samples:
            f.write(fmt_sample(float(x)))
            f.write(eol)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert 2-column waveform CSV to UNI-T Signal Studio CSV format."
    )
    parser.add_argument("input_csv", type=Path, help="Input CSV/text file with time and value columns")
    parser.add_argument("output_csv", type=Path, help="Output Signal Studio CSV file")
    parser.add_argument("--points", type=int, default=4000, help="Number of output points")
    parser.add_argument("--channel", type=int, default=1, help="Channel number")
    parser.add_argument(
        "--mode",
        choices=("mean", "interp"),
        default="mean",
        help="Resampling mode: mean or interp",
    )
    parser.add_argument("--t-start", type=float, default=None, help="Start time in seconds")
    parser.add_argument("--t-end", type=float, default=None, help="End time in seconds")

    args = parser.parse_args()

    t, v = parse_input_csv(args.input_csv)
    t, v = crop_range(t, v, args.t_start, args.t_end)

    if args.mode == "mean":
        resampled = resample_bin_mean(t, v, args.points)
    else:
        resampled = resample_interp(t, v, args.points)

    samples, vpp, offset = normalize_waveform(resampled)
    duration = float(t[-1] - t[0])

    write_signal_studio_csv(
        path=args.output_csv,
        samples=samples,
        channel=args.channel,
        vpp=vpp,
        offset=offset,
        rate_pos=duration / args.points if duration > 0 else 0.0,
        rate_neg=duration / args.points if duration > 0 else 0.0,
    )

    sample_rate = args.points / duration if duration > 0 else float("nan")

    print(f"Input points      : {len(t)}")
    print(f"Output points     : {args.points}")
    print(f"Duration          : {duration:.9f} s")
    print(f"Equivalent Fs     : {sample_rate:.3f} Sa/s")
    print(f"Computed VPP      : {vpp:.6f} V")
    print(f"Computed OFFSET   : {offset:.6f} V")
    print(f"Written file      : {args.output_csv}")


if __name__ == "__main__":
    main()
