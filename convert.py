import csv
import shutil
import time
from pathlib import Path

import numpy as np
from rigol_ds1000z import Rigol_DS1000Z, process_waveform

# ============================================================
# CONFIG
# ============================================================

# Scope/channel
CHANNEL = 1
VISA_RESOURCE = None  # None = auto-detect

# Trigger loop behavior
POLL_INTERVAL_S = 0.05
TRIGGER_WAIT_TIMEOUT_S = 30.0
REARM_ON_TIMEOUT = True

# Waveform read settings
WAVEFORM_MODE = "RAW"      # "NORM" or "RAW"
WAVEFORM_FORMAT = "BYTE"   # "ASC" or "BYTE" (RAW is chunked only for BYTE below)
POST_STOP_SETTLE_S = 0.15  # scope settle after STOP before reading

# RAW chunked read settings (used when WAVEFORM_MODE="RAW" and WAVEFORM_FORMAT="BYTE")
RAW_CHUNK_POINTS = 250_000
RAW_CHUNK_RETRIES = 4
RAW_RETRY_DELAY_S = 0.03

# VISA tuning
VISA_TIMEOUT_MS = 60000
VISA_CHUNK_SIZE = 102400

# Keep capture size sane
ACQ_MEMORY_DEPTH = "1.2M"   # None keeps the current scope setting
MAX_EXPORT_POINTS = 500_000  # 0/None disables export downsampling
EXPORT_DOWNSAMPLE_MODE = "block_mean"  # "block_mean" (anti-alias) or "stride"

# Output directory + naming
CAPTURES_DIR = Path("captures")
HISTORY_DIRNAME = "history"
KEEP_HISTORY = True
HISTORY_KEEP_COUNT = 5  # logrotate: keep only latest N archived captures

# "Latest" files (overwritten every successful capture)
LATEST_NGSPICE_FILE = "latest_capture.txt"      # KiCad points here
LATEST_SCOPE_STYLE_CSV = "latest_scope.csv"     # Sequence/VOLT style (raw)
LATEST_RAW_XY_CSV = "latest_raw_xy.csv"         # time/voltage (raw)
LATEST_JITTER_FILE = "latest_jitter.csv"        # detected jitter frequency metadata
LATEST_SPECTRUM_FILE = "latest_spectrum.csv"    # dominant bins of KiCad-fed signal

# Save these files
SAVE_SCOPE_STYLE_CSV = True
SAVE_RAW_XY_CSV = True
SAVE_NGSPICE_FILE = True
SAVE_JITTER_FILE = True
SAVE_SPECTRUM_FILE = True

# SCPI command logging
SCPI_LOG_ENABLED = True
SCPI_LOG_FILENAME = "latest_scpi.log"
SCPI_LOG_ECHO_TO_CONSOLE = False
SCPI_LOG_MAX_RESPONSE_CHARS = 220
SCPI_LOG_MAX_BYTES = 5_000_000  # truncate in-place when exceeded; 0 disables
CHECK_SCOPE_ERRORS_AFTER_CAPTURE = True

# Jitter-frequency analysis
JITTER_ANALYSIS_ENABLED = True
JITTER_MIN_FRACTION_OF_NYQUIST = 0.10  # search band starts at 10% of Nyquist
JITTER_MIN_FREQ_HZ = 0.0               # absolute floor; 0 = auto from fraction
JITTER_TOP_N = 3                       # number of strongest bins to record
SPECTRUM_TOP_N = 12                    # strongest bins to log for KiCad-fed signal
SPECTRUM_PRINT_TOP_N = 5               # strongest bins to print each capture
SPECTRUM_MIN_FREQ_HZ = 0.0             # set >0 to hide near-DC bins

# Alignment / offset handling for SIMULATION output only (raw CSV stays untouched)
# Keep scope X origin (pre-trigger/left context), but remove display vertical offset.
PRESERVE_SCOPE_ORIGIN = False
ZERO_VERTICAL_BY_CHANNEL_OFFSET = True
ZERO_VERTICAL_BY_PREHIT_MEAN = True
PREHIT_MEAN_FRACTION = 0.05   # first 5% of samples used for residual baseline trim
SHIFT_TIME_TO_ZERO = True
MANUAL_TIME_SHIFT_S = 0.0

# Baseline correction (applied only to ngspice export)
BASELINE_MODE = "none"          # "none", "first_sample", "head_mean", "negative_time"
BASELINE_HEAD_SAMPLES = 64
MANUAL_VOLT_SHIFT_V = 0.0

# Filtering
MIN_VALID_SAMPLES = 2
EXPORT_LOWPASS_ENABLED = True
EXPORT_LOWPASS_CUTOFF_HZ = 10_000.0  # remove components above this in KiCad export

# Trigger configuration (optional)
ENABLE_TRIGGER_SETUP = False
TRIGGER_LEVEL_V = -0.2
TRIGGER_SLOPE = "NEG"     # "POS", "NEG", "RFAL"
TRIGGER_COUPLING = "DC"
TRIGGER_SWEEP = "NORM"

# ============================================================
# HELPERS
# ============================================================

def ensure_output_dirs() -> tuple[Path, Path]:
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    hist = CAPTURES_DIR / HISTORY_DIRNAME
    hist.mkdir(parents=True, exist_ok=True)
    return CAPTURES_DIR, hist

def make_capture_stem(capture_idx: int) -> str:
    t = time.time()
    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(t))
    ms = int((t % 1.0) * 1000)
    return f"capture_{capture_idx:04d}_{ts}_{ms:03d}"

def rotate_history_dirs(history_root: Path, keep_count: int) -> None:
    """
    Keep only the newest N capture folders in captures/history.
    """
    if keep_count <= 0:
        return

    dirs = [p for p in history_root.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    for old_dir in dirs[keep_count:]:
        try:
            shutil.rmtree(old_dir)
            print(f"Rotated out:   {old_dir}")
        except Exception as e:
            print(f"Rotate warning ({old_dir}): {e!r}")

class ScopeScpiLogger:
    """
    Logged SCPI transport that avoids the library's auto-appended ';*WAI'.
    """

    def __init__(self, oscope, log_path: Path | None = None):
        self.oscope = oscope
        self.log_path = log_path
        self._fp = None
        self._max_bytes = int(SCPI_LOG_MAX_BYTES) if SCPI_LOG_MAX_BYTES else 0

        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._fp = self.log_path.open("w", encoding="utf-8", buffering=1)
            self._log("# SCPI log start")

    def close(self):
        if self._fp is not None:
            self._log("# SCPI log end")
            self._fp.close()
            self._fp = None

    def _log(self, msg: str):
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        line = f"{ts} {msg}"
        payload = line + "\n"
        if self._fp is not None:
            self._truncate_if_needed(len(payload.encode("utf-8")))
            self._fp.write(payload)
        if SCPI_LOG_ECHO_TO_CONSOLE:
            print(line)

    def _truncate_if_needed(self, incoming_bytes: int = 0):
        if self._fp is None or self._max_bytes <= 0:
            return
        if self._fp.tell() + incoming_bytes <= self._max_bytes:
            return
        self._fp.seek(0)
        self._fp.truncate(0)
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        self._fp.write(f"{ts} # SCPI log truncated at {self._max_bytes} bytes\n")

    def write(self, cmd: str):
        cmd = str(cmd).strip()
        self._log(f">> {cmd}")
        return self.oscope.visa_rsrc.write(cmd)

    def query(self, cmd: str, delay=None):
        cmd = str(cmd).strip()
        self._log(f"?? {cmd}")
        rsp = self.oscope.visa_rsrc.query(cmd, delay).strip()
        preview = rsp
        if len(preview) > SCPI_LOG_MAX_RESPONSE_CHARS:
            preview = preview[:SCPI_LOG_MAX_RESPONSE_CHARS] + "...(truncated)"
        self._log(f"<< {preview}")
        return rsp

    def query_binary_values(self, cmd: str, datatype="B", container=np.array):
        cmd = str(cmd).strip()
        self._log(f"??BIN {cmd} datatype={datatype}")
        arr = self.oscope.visa_rsrc.query_binary_values(
            cmd,
            datatype=datatype,
            container=container,
        )
        self._log(f"<<BIN points={len(arr)}")
        return arr

def install_scpi_transport(oscope, log_path: Path | None):
    logger = ScopeScpiLogger(oscope, log_path=log_path if SCPI_LOG_ENABLED else None)

    # Monkey-patch instance methods so library helpers are logged too.
    oscope.write = logger.write
    oscope.query = logger.query
    oscope.query_binary_values = logger.query_binary_values
    return logger

def configure_memory_depth_if_requested(oscope):
    if not ACQ_MEMORY_DEPTH:
        return
    try:
        oscope.write(f":ACQ:MDEP {ACQ_MEMORY_DEPTH}")
        actual = oscope.query(":ACQ:MDEP?")
        print(f"Memory depth: requested={ACQ_MEMORY_DEPTH} actual={actual}")
    except Exception as e:
        print(f"Memory depth setup warning: {e!r}")

def read_channel_offset_v(oscope, channel: int) -> float:
    """
    Read channel vertical offset in volts. Returns 0.0 on failure.
    """
    try:
        return float(oscope.query(f":CHAN{int(channel)}:OFFS?"))
    except Exception as e:
        print(f"Channel offset read warning (CH{channel}): {e!r}")
        return 0.0

def write_xy_csv(xdata, ydata, path: Path):
    xdata = np.asarray(xdata, dtype=float).reshape(-1)
    ydata = np.asarray(ydata, dtype=float).reshape(-1)

    if len(xdata) == 0 or len(ydata) == 0:
        raise RuntimeError("No samples available for x/y CSV.")
    if len(xdata) != len(ydata):
        raise RuntimeError(f"x/y length mismatch: {len(xdata)} vs {len(ydata)}")

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_s", "voltage_v"])
        for x, y in zip(xdata, ydata):
            w.writerow([f"{float(x):.12e}", f"{float(y):.12e}"])

def write_scope_style_csv(xdata, ydata, path: Path, channel: int = 1):
    """
    Write CSV in a scope-like format:
    X,CH1,Start,Increment
    Sequence,VOLT,<start>,<increment>
    0,<v0>
    ...
    """
    xdata = np.asarray(xdata, dtype=float).reshape(-1)
    ydata = np.asarray(ydata, dtype=float).reshape(-1)

    if len(xdata) == 0 or len(ydata) == 0:
        raise RuntimeError("No samples available for scope-style CSV.")
    if len(xdata) != len(ydata):
        raise RuntimeError(f"x/y length mismatch: {len(xdata)} vs {len(ydata)}")

    start = float(xdata[0])
    increment = float(xdata[1] - xdata[0]) if len(xdata) >= 2 else 0.0

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["X", f"CH{channel}", "Start", "Increment"])
        w.writerow(["Sequence", "VOLT", f"{start:.12e}", f"{increment:.12e}"])
        for i, v in enumerate(ydata):
            w.writerow([i, f"{float(v):.12e}"])

def write_ngspice_filesource(xdata, ydata, path: Path):
    """
    Write ngspice XSPICE filesource:
    <time_seconds> <volts>
    """
    xdata = np.asarray(xdata, dtype=float).reshape(-1)
    ydata = np.asarray(ydata, dtype=float).reshape(-1)

    if len(xdata) == 0 or len(ydata) == 0:
        raise RuntimeError("No samples available for ngspice file.")
    if len(xdata) != len(ydata):
        raise RuntimeError(f"x/y length mismatch: {len(xdata)} vs {len(ydata)}")

    with path.open("w", encoding="utf-8") as out:
        out.write("# Auto-generated for ngspice XSPICE filesource\n")
        out.write("# time(s) voltage(V)\n")

        last_t = None
        for t, v in zip(xdata, ydata):
            t = float(t)
            v = float(v)
            if last_t is not None and t <= last_t:
                t = last_t + 1e-15
            out.write(f"{t:.12e} {v:.12e}\n")
            last_t = t

def analyze_jitter_frequency(xdata, ydata):
    """
    Estimate dominant high-frequency jitter using an FFT on detrended data.
    """
    x = np.asarray(xdata, dtype=float).reshape(-1)
    y = np.asarray(ydata, dtype=float).reshape(-1)

    if len(x) < 32 or len(y) < 32 or len(x) != len(y):
        return None

    dt = np.diff(x)
    dt = dt[np.isfinite(dt) & (dt > 0)]
    if len(dt) == 0:
        return None

    dt_s = float(np.median(dt))
    fs_hz = 1.0 / dt_s
    nyquist_hz = 0.5 * fs_hz

    # Remove DC and linear trend before spectrum estimation.
    y0 = y - np.mean(y)
    t = np.arange(len(y0), dtype=float)
    slope, intercept = np.polyfit(t, y0, 1)
    yd = y0 - (slope * t + intercept)
    window = np.hanning(len(yd))
    yw = yd * window

    spec = np.fft.rfft(yw)
    freqs = np.fft.rfftfreq(len(yw), d=dt_s)
    mags = np.abs(spec)

    min_hz = max(float(JITTER_MIN_FREQ_HZ), float(JITTER_MIN_FRACTION_OF_NYQUIST) * nyquist_hz)
    mask = (freqs >= min_hz) & (freqs <= nyquist_hz)
    if not np.any(mask):
        return None

    band_idx = np.where(mask)[0]
    band_mags = mags[band_idx]
    if len(band_mags) == 0:
        return None

    peak_pos = int(np.argmax(band_mags))
    peak_idx = int(band_idx[peak_pos])
    peak_hz = float(freqs[peak_idx])
    peak_mag = float(mags[peak_idx])
    peak_period_s = 1.0 / peak_hz if peak_hz > 0 else float("inf")

    # Report top-N peaks in-band for easier diagnostics.
    n_top = max(1, int(JITTER_TOP_N))
    top_order = np.argsort(band_mags)[-n_top:][::-1]
    top_peaks = [
        {"freq_hz": float(freqs[int(band_idx[i])]), "magnitude": float(band_mags[int(i)])}
        for i in top_order
    ]

    return {
        "points": int(len(y)),
        "dt_s": dt_s,
        "fs_hz": fs_hz,
        "nyquist_hz": nyquist_hz,
        "search_min_hz": min_hz,
        "dominant_hz": peak_hz,
        "dominant_period_s": peak_period_s,
        "dominant_magnitude": peak_mag,
        "top_peaks": top_peaks,
    }

def write_jitter_csv(path: Path, capture_idx: int, jitter):
    if jitter is None:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["capture_idx", "status"])
            w.writerow([capture_idx, "unavailable"])
        return

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "capture_idx",
                "points",
                "dt_s",
                "fs_hz",
                "nyquist_hz",
                "search_min_hz",
                "dominant_hz",
                "dominant_period_s",
                "dominant_magnitude",
            ]
        )
        w.writerow(
            [
                capture_idx,
                jitter["points"],
                f"{jitter['dt_s']:.12e}",
                f"{jitter['fs_hz']:.12e}",
                f"{jitter['nyquist_hz']:.12e}",
                f"{jitter['search_min_hz']:.12e}",
                f"{jitter['dominant_hz']:.12e}",
                f"{jitter['dominant_period_s']:.12e}",
                f"{jitter['dominant_magnitude']:.12e}",
            ]
        )
        w.writerow([])
        w.writerow(["rank", "freq_hz", "magnitude"])
        for i, p in enumerate(jitter["top_peaks"], start=1):
            w.writerow([i, f"{p['freq_hz']:.12e}", f"{p['magnitude']:.12e}"])

def analyze_frequency_bins(xdata, ydata, min_freq_hz=0.0, top_n=12):
    """
    Dominant frequency bins for the signal that is exported to KiCad.
    """
    x = np.asarray(xdata, dtype=float).reshape(-1)
    y = np.asarray(ydata, dtype=float).reshape(-1)

    if len(x) < 32 or len(y) < 32 or len(x) != len(y):
        return None

    dt = np.diff(x)
    dt = dt[np.isfinite(dt) & (dt > 0)]
    if len(dt) == 0:
        return None

    dt_s = float(np.median(dt))
    fs_hz = 1.0 / dt_s
    nyquist_hz = 0.5 * fs_hz

    # Detrend + window so peak ranking reflects periodic content.
    y0 = y - np.mean(y)
    t = np.arange(len(y0), dtype=float)
    slope, intercept = np.polyfit(t, y0, 1)
    yd = y0 - (slope * t + intercept)
    yw = yd * np.hanning(len(yd))

    spec = np.fft.rfft(yw)
    freqs = np.fft.rfftfreq(len(yw), d=dt_s)
    mags = np.abs(spec)

    min_hz = max(0.0, float(min_freq_hz))
    mask = (freqs >= min_hz) & (freqs <= nyquist_hz)
    if not np.any(mask):
        return None

    idx = np.where(mask)[0]
    if len(idx) == 0:
        return None

    n_top = max(1, min(int(top_n), len(idx)))
    order = np.argsort(mags[idx])[-n_top:][::-1]
    peaks = [
        {"rank": i + 1, "freq_hz": float(freqs[int(idx[o])]), "magnitude": float(mags[int(idx[o])])}
        for i, o in enumerate(order)
    ]

    return {
        "points": int(len(y)),
        "dt_s": dt_s,
        "fs_hz": fs_hz,
        "nyquist_hz": nyquist_hz,
        "min_freq_hz": min_hz,
        "peaks": peaks,
    }

def write_spectrum_csv(path: Path, capture_idx: int, spec):
    if spec is None:
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["capture_idx", "status"])
            w.writerow([capture_idx, "unavailable"])
        return

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "capture_idx",
                "points",
                "dt_s",
                "fs_hz",
                "nyquist_hz",
                "min_freq_hz",
            ]
        )
        w.writerow(
            [
                capture_idx,
                spec["points"],
                f"{spec['dt_s']:.12e}",
                f"{spec['fs_hz']:.12e}",
                f"{spec['nyquist_hz']:.12e}",
                f"{spec['min_freq_hz']:.12e}",
            ]
        )
        w.writerow([])
        w.writerow(["rank", "freq_hz", "magnitude"])
        for p in spec["peaks"]:
            w.writerow([p["rank"], f"{p['freq_hz']:.12e}", f"{p['magnitude']:.12e}"])

def apply_alignment_and_offsets_for_sim(xdata, ydata):
    """
    Apply baseline/time shifts for the ngspice export only.
    Raw CSV exports remain untouched.
    """
    x = np.asarray(xdata, dtype=float).copy().reshape(-1)
    y = np.asarray(ydata, dtype=float).copy().reshape(-1)

    meta = {
        "baseline_applied_v": 0.0,
        "time_shift_applied_s": 0.0,
        "channel_offset_removed_v": 0.0,
        "prehit_mean_removed_v": 0.0,
        "preserved_scope_origin": bool(PRESERVE_SCOPE_ORIGIN),
    }

    baseline = 0.0
    mode = BASELINE_MODE.lower()

    if mode == "none":
        baseline = 0.0
    elif mode == "first_sample":
        baseline = float(y[0]) if len(y) else 0.0
    elif mode == "head_mean":
        n = max(1, min(BASELINE_HEAD_SAMPLES, len(y)))
        baseline = float(np.mean(y[:n])) if len(y) else 0.0
    elif mode == "negative_time":
        neg = y[x < 0]
        if len(neg) > 0:
            baseline = float(np.mean(neg))
        else:
            n = max(1, min(BASELINE_HEAD_SAMPLES, len(y)))
            baseline = float(np.mean(y[:n])) if len(y) else 0.0
    else:
        raise ValueError(
            f"Unknown BASELINE_MODE={BASELINE_MODE!r}. "
            "Use: none, first_sample, head_mean, negative_time"
        )

    if baseline != 0.0:
        y = y - baseline
        meta["baseline_applied_v"] += baseline

    if MANUAL_VOLT_SHIFT_V:
        y = y - MANUAL_VOLT_SHIFT_V
        meta["baseline_applied_v"] += MANUAL_VOLT_SHIFT_V

    time_shift = 0.0
    if (not PRESERVE_SCOPE_ORIGIN) and SHIFT_TIME_TO_ZERO and len(x):
        time_shift += float(x[0])
    if MANUAL_TIME_SHIFT_S:
        time_shift += float(MANUAL_TIME_SHIFT_S)

    if time_shift != 0.0:
        x = x - time_shift
        meta["time_shift_applied_s"] = time_shift

    for i in range(1, len(x)):
        if x[i] <= x[i - 1]:
            x[i] = x[i - 1] + 1e-15

    return x, y, meta

def lowpass_for_export(xdata, ydata, cutoff_hz):
    """
    FFT low-pass for the KiCad-export signal.
    """
    x = np.asarray(xdata, dtype=float).reshape(-1)
    y = np.asarray(ydata, dtype=float).reshape(-1)
    meta = {
        "applied": False,
        "cutoff_hz": float(cutoff_hz),
        "nyquist_hz": 0.0,
    }

    if len(x) < 8 or len(y) < 8 or len(x) != len(y):
        return y, meta

    dt = np.diff(x)
    dt = dt[np.isfinite(dt) & (dt > 0)]
    if len(dt) == 0:
        return y, meta

    dt_s = float(np.median(dt))
    fs_hz = 1.0 / dt_s
    nyquist_hz = 0.5 * fs_hz
    meta["nyquist_hz"] = nyquist_hz

    cutoff = float(cutoff_hz)
    if cutoff <= 0.0 or cutoff >= nyquist_hz:
        return y, meta

    spec = np.fft.rfft(y)
    freqs = np.fft.rfftfreq(len(y), d=dt_s)
    spec[freqs > cutoff] = 0.0
    yf = np.fft.irfft(spec, n=len(y))

    meta["applied"] = True
    return yf, meta

def maybe_downsample_for_export(raw_x, raw_y, sim_x, sim_y):
    """
    Keep all processing in full resolution, then cap exported point count.
    """
    n = len(raw_x)
    cap = int(MAX_EXPORT_POINTS) if MAX_EXPORT_POINTS else 0

    if cap <= 0 or n <= cap:
        return raw_x, raw_y, sim_x, sim_y, {
            "applied": False,
            "original_points": n,
            "final_points": n,
            "step": 1,
            "mode": "none",
        }

    step = int(np.ceil(n / float(cap)))
    mode = str(EXPORT_DOWNSAMPLE_MODE).strip().lower()

    if mode == "block_mean":
        # Anti-aliasing by averaging each decimation block before export.
        idx = np.arange(0, n, step, dtype=np.int64)
        counts = np.diff(np.append(idx, n)).astype(float)

        def block_mean(arr):
            arr = np.asarray(arr, dtype=float)
            return np.add.reduceat(arr, idx) / counts

        raw_x_ds = block_mean(raw_x)
        raw_y_ds = block_mean(raw_y)
        sim_x_ds = block_mean(sim_x)
        sim_y_ds = block_mean(sim_y)

        return raw_x_ds, raw_y_ds, sim_x_ds, sim_y_ds, {
            "applied": True,
            "original_points": n,
            "final_points": len(raw_x_ds),
            "step": step,
            "mode": mode,
        }

    if mode == "stride":
        idx = np.arange(0, n, step, dtype=np.int64)
        if idx[-1] != (n - 1):
            idx = np.append(idx, n - 1)
        return raw_x[idx], raw_y[idx], sim_x[idx], sim_y[idx], {
            "applied": True,
            "original_points": n,
            "final_points": len(idx),
            "step": step,
            "mode": mode,
        }

    raise ValueError(
        f"Unknown EXPORT_DOWNSAMPLE_MODE={EXPORT_DOWNSAMPLE_MODE!r}. "
        "Use: block_mean, stride"
    )

def configure_trigger_if_requested(oscope):
    if not ENABLE_TRIGGER_SETUP:
        return
    try:
        trig = oscope.trigger(
            mode="EDGE",
            source=CHANNEL,
            coupling=TRIGGER_COUPLING,
            slope=TRIGGER_SLOPE,
            level=TRIGGER_LEVEL_V,
            sweep=TRIGGER_SWEEP,
        )
        print(
            f"Trigger configured: mode={trig.mode} source={trig.source} "
            f"level={trig.level:.6g} slope={trig.slope} sweep={trig.sweep}"
        )
    except Exception as e:
        print(f"Trigger setup warning: {e!r}")

def arm_single_trigger(oscope):
    """
    Arm SINGLE using the library.
    """
    oscope.single()  # library method

def wait_for_trigger_complete(oscope, timeout_s=10.0, poll_s=0.05):
    """
    Wait for trigger completion using the library.
    Does NOT arm. Just polls status.
    """
    deadline = time.monotonic() + timeout_s
    last_status = None

    while time.monotonic() < deadline:
        status = str(oscope.query(":TRIG:STAT?")).strip().upper()

        if status != last_status:
            print("Trigger status:", status)
            last_status = status

        if status in ("STOP", "TD"):
            return status

        time.sleep(poll_s)

    raise TimeoutError(
        f"Trigger did not complete within {timeout_s:.2f}s "
        f"(last status={last_status})"
    )

def _parse_waveform_preamble(pre: str):
    """
    Rigol WAV:PRE? -> 10 comma-separated fields:
    format,type,points,count,xinc,xorig,xref,yinc,yorig,yref
    """
    parts = [p.strip() for p in str(pre).strip().split(",")]
    if len(parts) < 10:
        raise RuntimeError(f"Unexpected WAV:PRE? response: {pre!r}")

    # Keep fields explicit so debugging is less miserable
    _fmt = int(float(parts[0]))
    _typ = int(float(parts[1]))
    points = int(float(parts[2]))
    _count = int(float(parts[3]))
    xinc = float(parts[4])
    xorig = float(parts[5])
    xref = float(parts[6])
    yinc = float(parts[7])
    yorig = float(parts[8])
    yref = float(parts[9])

    return {
        "format": _fmt,
        "type": _typ,
        "points": points,
        "xinc": xinc,
        "xorig": xorig,
        "xref": xref,
        "yinc": yinc,
        "yorig": yorig,
        "yref": yref,
    }

def read_waveform_raw_chunked(oscope, channel=1, max_chunk_points=250_000, retries=4):
    """
    Deep-memory RAW waveform read (BYTE) in chunks using :WAV:STAR/:WAV:STOP.
    Uses library for SCPI commands/queries and the underlying visa resource
    only for binary payload reads.
    Returns xdata, ydata as numpy arrays.
    """
    oscope.write(f":WAV:SOUR CHAN{channel}")
    oscope.write(":WAV:MODE RAW")
    oscope.write(":WAV:FORM BYTE")

    pre = _parse_waveform_preamble(oscope.query(":WAV:PRE?"))
    total_points = int(pre["points"])

    if total_points < 2:
        raise RuntimeError(f"RAW preamble reports too few points: {total_points}")

    print(
        f"RAW preamble: points={total_points}, xinc={pre['xinc']:.3e}, "
        f"xorig={pre['xorig']:.3e}, yinc={pre['yinc']:.3e}"
    )

    chunks = []
    start = 1  # Rigol uses 1-based STAR/STOP indexes

    while start <= total_points:
        stop = min(start + max_chunk_points - 1, total_points)
        expected = stop - start + 1

        oscope.write(f":WAV:STAR {start}")
        oscope.write(f":WAV:STOP {stop}")

        got = None
        last_err = None

        for _ in range(retries):
            try:
                arr = oscope.query_binary_values(
                    ":WAV:DATA?",
                    datatype="B",
                    container=np.array,
                )
                if len(arr) == expected:
                    got = arr
                    break
                last_err = RuntimeError(f"Chunk len {len(arr)} != expected {expected}")
            except Exception as e:
                last_err = e

            time.sleep(RAW_RETRY_DELAY_S)

        if got is None:
            raise RuntimeError(f"RAW chunk {start}:{stop} failed: {last_err!r}")

        chunks.append(got)
        start = stop + 1

    raw_codes = np.concatenate(chunks).astype(float)

    if len(raw_codes) != total_points:
        raise RuntimeError(
            f"RAW total length mismatch: got {len(raw_codes)}, expected {total_points}"
        )

    # Rigol scaling from preamble
    ydata = (raw_codes - pre["yorig"] - pre["yref"]) * pre["yinc"]
    x_idx = np.arange(len(raw_codes), dtype=float)
    xdata = (x_idx - pre["xref"]) * pre["xinc"] + pre["xorig"]

    return xdata, ydata

def capture_waveform_once(oscope):
    """
    Stop, read one waveform, return:
      raw_x, raw_y, sim_x, sim_y
    """
    oscope.stop()
    time.sleep(POST_STOP_SETTLE_S)

    mode = WAVEFORM_MODE.upper()
    fmt = WAVEFORM_FORMAT.upper()

    if mode == "RAW" and fmt == "BYTE":
        raw_x, raw_y = read_waveform_raw_chunked(
            oscope,
            channel=CHANNEL,
            max_chunk_points=RAW_CHUNK_POINTS,
            retries=RAW_CHUNK_RETRIES,
        )
    else:
        # Fallback library path (works well for NORM, and can be used for ASC)
        waveform = oscope.waveform(source=CHANNEL, mode=mode, format=fmt)
        raw_x, raw_y = process_waveform(waveform, show=False, filename=None)

    raw_x = np.atleast_1d(np.asarray(raw_x, dtype=float))
    raw_y = np.atleast_1d(np.asarray(raw_y, dtype=float))

    print(f"Returned samples: x={len(raw_x)}, y={len(raw_y)}")

    if len(raw_x) < MIN_VALID_SAMPLES or len(raw_y) < MIN_VALID_SAMPLES:
        raise RuntimeError(
            f"Invalid capture: too few samples (x={len(raw_x)}, y={len(raw_y)})"
        )
    if len(raw_x) != len(raw_y):
        raise RuntimeError(f"Invalid capture: x/y mismatch ({len(raw_x)} vs {len(raw_y)})")

    sim_x, sim_y, meta = apply_alignment_and_offsets_for_sim(raw_x, raw_y)
    if ZERO_VERTICAL_BY_CHANNEL_OFFSET:
        ch_offset_v = read_channel_offset_v(oscope, CHANNEL)
        if ch_offset_v != 0.0:
            sim_y = sim_y - ch_offset_v
            meta["channel_offset_removed_v"] = ch_offset_v

    if ZERO_VERTICAL_BY_PREHIT_MEAN and len(sim_y) > 0:
        n0 = max(1, int(len(sim_y) * float(PREHIT_MEAN_FRACTION)))
        prehit_mean = float(np.mean(sim_y[:n0]))
        if prehit_mean != 0.0:
            sim_y = sim_y - prehit_mean
            meta["prehit_mean_removed_v"] = prehit_mean

    lpf_meta = {"applied": False, "cutoff_hz": float(EXPORT_LOWPASS_CUTOFF_HZ), "nyquist_hz": 0.0}
    if EXPORT_LOWPASS_ENABLED:
        sim_y, lpf_meta = lowpass_for_export(sim_x, sim_y, EXPORT_LOWPASS_CUTOFF_HZ)

    jitter = analyze_jitter_frequency(raw_x, raw_y) if JITTER_ANALYSIS_ENABLED else None
    raw_x, raw_y, sim_x, sim_y, ds = maybe_downsample_for_export(raw_x, raw_y, sim_x, sim_y)
    kicad_spec = analyze_frequency_bins(
        sim_x,
        sim_y,
        min_freq_hz=SPECTRUM_MIN_FREQ_HZ,
        top_n=SPECTRUM_TOP_N,
    )

    dt_raw = float(raw_x[1] - raw_x[0]) if len(raw_x) >= 2 else 0.0
    print(
        f"RAW dt≈{dt_raw:.6e}s  duration≈{(raw_x[-1]-raw_x[0]):.6e}s  "
        f"Vmin={np.min(raw_y):.6g}  Vmax={np.max(raw_y):.6g}"
    )
    print(
        f"SIM shifts: baseline={meta['baseline_applied_v']:.6g} V, "
        f"time={meta['time_shift_applied_s']:.6g} s, "
        f"chan_offset={meta.get('channel_offset_removed_v', 0.0):.6g} V, "
        f"prehit_mean={meta.get('prehit_mean_removed_v', 0.0):.6g} V, "
        f"preserve_scope_origin={meta.get('preserved_scope_origin', False)}"
    )
    if EXPORT_LOWPASS_ENABLED:
        print(
            f"Export low-pass: cutoff={lpf_meta['cutoff_hz']:.6g} Hz "
            f"nyquist={lpf_meta['nyquist_hz']:.6g} Hz applied={lpf_meta['applied']}"
        )
    if jitter is not None:
        print(
            f"Jitter freq: f≈{jitter['dominant_hz']:.6e} Hz "
            f"(T≈{jitter['dominant_period_s']:.6e} s, search>{jitter['search_min_hz']:.6e} Hz)"
        )
    else:
        print("Jitter freq: unavailable (not enough valid points)")
    if ds["applied"]:
        print(
            f"Downsampled export: {ds['original_points']} -> {ds['final_points']} "
            f"(step={ds['step']}, mode={ds['mode']})"
        )
    if kicad_spec is not None and len(kicad_spec["peaks"]) > 0:
        top = kicad_spec["peaks"][: max(1, int(SPECTRUM_PRINT_TOP_N))]
        bins = ", ".join(f"{p['freq_hz']:.3e}Hz" for p in top)
        print(f"KiCad signal top bins: {bins}")
    else:
        print("KiCad signal top bins: unavailable")

    return raw_x, raw_y, sim_x, sim_y, jitter, kicad_spec

def save_outputs(raw_x, raw_y, sim_x, sim_y, capture_idx: int, jitter=None, kicad_spec=None):
    outdir, history_root = ensure_output_dirs()
    stem = make_capture_stem(capture_idx)

    # Latest files in captures/
    latest_ng = outdir / LATEST_NGSPICE_FILE
    latest_scope = outdir / LATEST_SCOPE_STYLE_CSV
    latest_xy = outdir / LATEST_RAW_XY_CSV
    latest_jitter = outdir / LATEST_JITTER_FILE
    latest_spectrum = outdir / LATEST_SPECTRUM_FILE

    # Archived files grouped in captures/history/<stem>/
    archive_dir = history_root / stem
    if KEEP_HISTORY:
        archive_dir.mkdir(parents=True, exist_ok=True)

    # Save RAW (unmodified) debug files
    if SAVE_SCOPE_STYLE_CSV:
        write_scope_style_csv(raw_x, raw_y, latest_scope, channel=CHANNEL)
        print(f"Saved latest:   {latest_scope}")
        if KEEP_HISTORY:
            write_scope_style_csv(raw_x, raw_y, archive_dir / "scope.csv", channel=CHANNEL)
            print(f"Saved archive:  {archive_dir / 'scope.csv'}")

    if SAVE_RAW_XY_CSV:
        write_xy_csv(raw_x, raw_y, latest_xy)
        print(f"Saved latest:   {latest_xy}")
        if KEEP_HISTORY:
            write_xy_csv(raw_x, raw_y, archive_dir / "raw_xy.csv")
            print(f"Saved archive:  {archive_dir / 'raw_xy.csv'}")

    # Save processed KiCad/ngspice file
    if SAVE_NGSPICE_FILE:
        write_ngspice_filesource(sim_x, sim_y, latest_ng)
        print(f"Saved latest:   {latest_ng}")
        if KEEP_HISTORY:
            write_ngspice_filesource(sim_x, sim_y, archive_dir / "capture.txt")
            print(f"Saved archive:  {archive_dir / 'capture.txt'}")

    if SAVE_JITTER_FILE and JITTER_ANALYSIS_ENABLED:
        write_jitter_csv(latest_jitter, capture_idx, jitter)
        print(f"Saved latest:   {latest_jitter}")
        if KEEP_HISTORY:
            write_jitter_csv(archive_dir / "jitter.csv", capture_idx, jitter)
            print(f"Saved archive:  {archive_dir / 'jitter.csv'}")

    if SAVE_SPECTRUM_FILE:
        write_spectrum_csv(latest_spectrum, capture_idx, kicad_spec)
        print(f"Saved latest:   {latest_spectrum}")
        if KEEP_HISTORY:
            write_spectrum_csv(archive_dir / "spectrum.csv", capture_idx, kicad_spec)
            print(f"Saved archive:  {archive_dir / 'spectrum.csv'}")

    if KEEP_HISTORY:
        rotate_history_dirs(history_root, HISTORY_KEEP_COUNT)

def print_scope_errors(oscope, max_count=5):
    """
    Query and print scope error queue (if any).
    """
    try:
        for _ in range(max_count):
            err = oscope.query(":SYST:ERR?")
            if not err:
                break
            msg = str(err).strip()
            print("SCPI ERR:", msg)
            if msg.startswith("0") or "No error" in msg:
                break
    except Exception as e:
        print(f"Could not read scope error queue: {e!r}")

# ============================================================
# MAIN LOOP
# ============================================================

def main():
    outdir, history_root = ensure_output_dirs()
    print("Opening Rigol scope...")

    oscope = Rigol_DS1000Z(VISA_RESOURCE) if VISA_RESOURCE else Rigol_DS1000Z()
    with oscope:
        scpi_log_path = outdir / SCPI_LOG_FILENAME if SCPI_LOG_ENABLED else None
        scpi_logger = install_scpi_transport(oscope, scpi_log_path)

        # PyVISA tuning (under the library object)
        try:
            oscope.visa_rsrc.timeout = VISA_TIMEOUT_MS
            oscope.visa_rsrc.chunk_size = VISA_CHUNK_SIZE
        except Exception:
            pass

        try:
            print(f"Output dir:   {outdir.resolve()}")
            print(f"History dir:  {history_root.resolve()}")
            print(f"KiCad file:   {(outdir / LATEST_NGSPICE_FILE).as_posix()}")
            print(f"SCPI log:     {(outdir / SCPI_LOG_FILENAME).as_posix()}")
            if JITTER_ANALYSIS_ENABLED:
                print(f"Jitter file:  {(outdir / LATEST_JITTER_FILE).as_posix()}")
            if SAVE_SPECTRUM_FILE:
                print(f"Spectrum:     {(outdir / LATEST_SPECTRUM_FILE).as_posix()}")
            print(f"Waveform:     mode={WAVEFORM_MODE.upper()} format={WAVEFORM_FORMAT.upper()}")
            print(
                f"Alignment:    preserve_scope_origin={PRESERVE_SCOPE_ORIGIN} "
                f"zero_by_chan_offset={ZERO_VERTICAL_BY_CHANNEL_OFFSET} "
                f"zero_by_prehit_mean={ZERO_VERTICAL_BY_PREHIT_MEAN} "
                f"shift_time_to_zero={SHIFT_TIME_TO_ZERO}"
            )
            print(
                f"Filtering:    export_lowpass={EXPORT_LOWPASS_ENABLED} "
                f"cutoff={EXPORT_LOWPASS_CUTOFF_HZ:.6g}Hz"
            )
            if SHIFT_TIME_TO_ZERO:
                print("Time origin:   rebased to first sample (pre-trigger shown, left shift preserved)")
            if WAVEFORM_MODE.upper() == "RAW" and WAVEFORM_FORMAT.upper() == "BYTE":
                print(f"RAW chunking: {RAW_CHUNK_POINTS} pts/chunk, retries={RAW_CHUNK_RETRIES}")
            if MAX_EXPORT_POINTS:
                print(f"Export cap:   {MAX_EXPORT_POINTS} points")

            configure_memory_depth_if_requested(oscope)
            configure_trigger_if_requested(oscope)

            capture_idx = 0

            # Arm once before entering the loop
            print("Arming SINGLE...")
            arm_single_trigger(oscope)

            while True:
                capture_idx += 1
                print(f"\n=== Capture {capture_idx} ===")

                try:
                    final_status = wait_for_trigger_complete(
                        oscope,
                        timeout_s=TRIGGER_WAIT_TIMEOUT_S,
                        poll_s=POLL_INTERVAL_S,
                    )
                    print("Trigger complete, final status:", final_status)

                    raw_x, raw_y, sim_x, sim_y, jitter, kicad_spec = capture_waveform_once(oscope)
                    save_outputs(
                        raw_x,
                        raw_y,
                        sim_x,
                        sim_y,
                        capture_idx,
                        jitter=jitter,
                        kicad_spec=kicad_spec,
                    )
                    if CHECK_SCOPE_ERRORS_AFTER_CAPTURE:
                        print_scope_errors(oscope, max_count=10)

                    # Re-arm immediately after transfer/save
                    print("Re-arming SINGLE...")
                    arm_single_trigger(oscope)

                except TimeoutError as e:
                    print("Timeout:", e)
                    if not REARM_ON_TIMEOUT:
                        break

                    # Re-arm on timeout too
                    try:
                        print("Re-arming SINGLE after timeout...")
                        arm_single_trigger(oscope)
                    except Exception as re:
                        print(f"Re-arm error: {re!r}")
                    continue

                except KeyboardInterrupt:
                    print("Stopped by user.")
                    break

                except Exception as e:
                    print("Capture error:", repr(e))
                    if CHECK_SCOPE_ERRORS_AFTER_CAPTURE:
                        print_scope_errors(oscope, max_count=10)

                    # Try to re-arm so the loop recovers cleanly
                    try:
                        print("Re-arming SINGLE after capture error...")
                        arm_single_trigger(oscope)
                    except Exception as re:
                        print(f"Re-arm error: {re!r}")

                    time.sleep(0.2)
                    continue
        finally:
            scpi_logger.close()

if __name__ == "__main__":
    main()
