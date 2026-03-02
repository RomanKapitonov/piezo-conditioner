#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import struct
import time


KNOWN_UNI_T_USB_IDS = (
    "USB0::0x6656::0x0834::",
)
IO_LOGGING_ENABLED = False

REFERENCE_ARB_HEADER = (
    b"VPP:0\r\n"
    b"OFFSET:0\r\n"
    b"RATEPOS:0\r\n"
    b"RATENEG:0\r\n"
    b"MAX:32767\r\n"
    b"MIN:-32767\r\n"
)
REFERENCE_ARB_HEADER_INTRO = f"[HEAD]:{len(REFERENCE_ARB_HEADER)}\r\n".encode("ascii")


@dataclass(frozen=True)
class BsvMetadata:
    path: Path
    file_name: str
    point_count: int
    payload_bytes: int
    channel: int | None
    vpp: float | None
    offset: float | None
    rate_pos: float | None
    rate_neg: float | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload a UNI-T UTG962/UTG900E arbitrary waveform file over PyVISA."
    )
    parser.add_argument(
        "waveform",
        type=Path,
        nargs="?",
        help="Path to the waveform file to upload (.csv with normalized samples or .bsv).",
    )
    parser.add_argument(
        "--resource",
        default="auto",
        help="VISA resource string, or 'auto' to probe connected instruments",
    )
    parser.add_argument(
        "--backend",
        default=None,
        help="Optional PyVISA backend. Leave unset to use the installed VISA runtime; use '@py' only if you know the device is supported there.",
    )
    parser.add_argument(
        "--channel",
        type=int,
        default=None,
        choices=(1, 2),
        help="Target output channel. Defaults to the waveform file metadata, otherwise CH1.",
    )
    parser.add_argument(
        "--arb-index",
        type=int,
        default=0,
        choices=(0, 1),
        help="UTG external arbitrary waveform slot index to program and select.",
    )
    parser.add_argument(
        "--arb-name",
        default=None,
        help="Display name for the uploaded arbitrary waveform. Defaults to the waveform file stem.",
    )
    parser.add_argument(
        "--frequency",
        type=float,
        default=None,
        help="Output frequency in Hz after upload",
    )
    parser.add_argument(
        "--amplitude",
        type=float,
        default=None,
        help="Output amplitude in Vpp after upload",
    )
    parser.add_argument(
        "--offset",
        type=float,
        default=None,
        help="Output offset in V after upload. Defaults to the waveform file metadata, otherwise 0 V.",
    )
    parser.add_argument(
        "--phase",
        type=float,
        default=0.0,
        help="Output phase in degrees after upload",
    )
    parser.add_argument(
        "--output-on",
        action="store_true",
        help="Enable channel output after configuration",
    )
    parser.add_argument(
        "--store-only",
        action="store_true",
        help="Only upload the waveform into device storage. Skip channel selection and output setup.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=15000,
        help="VISA timeout in milliseconds",
    )
    parser.add_argument(
        "--post-upload-delay-ms",
        type=int,
        default=1000,
        help="Delay after upload before any follow-up configuration commands.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List VISA resources and detected ID strings, then exit",
    )
    parser.add_argument(
        "--log-io",
        action="store_true",
        help="Print each SCPI/VISA operation. Disabled by default because it slows transfers.",
    )
    return parser.parse_args()


def open_resource_manager(pyvisa_module, backend: str | None):
    return pyvisa_module.ResourceManager(backend) if backend else pyvisa_module.ResourceManager()


def candidate_resources(rm) -> tuple[str, ...]:
    resources: set[str] = set()

    for query in ("?*::INSTR", "?*::RAW", "?*"):
        try:
            info_map = rm.list_resources_info(query)
        except Exception:
            info_map = {}

        for listed_name, info in info_map.items():
            canonical_name = getattr(info, "resource_name", None) or listed_name
            resources.add(canonical_name)

        if not info_map:
            try:
                resources.update(rm.list_resources(query))
            except Exception:
                continue

    return tuple(sorted(resources))


def query_idn(inst) -> str:
    try:
        return visa_query(inst, "*IDN?").strip()
    except Exception as exc:  # pragma: no cover - hardware dependent
        return f"<query failed: {exc}>"


def is_known_unit_resource(resource_name: str) -> bool:
    upper_name = resource_name.upper()
    return any(token.upper() in upper_name for token in KNOWN_UNI_T_USB_IDS)


def describe_resource(resource_name: str, idn: str) -> str:
    if not idn.startswith("<query failed:"):
        return idn
    if is_known_unit_resource(resource_name):
        return "UNI-T UTG900E/UTG962 USBTMC device (IDN query timed out)"
    return idn


def list_resources(rm) -> int:
    resources = tuple(
        resource_name
        for resource_name in candidate_resources(rm)
        if resource_name.upper().startswith("USB")
    )
    if not resources:
        print("No USB VISA resources found.")
        return 1

    for resource_name in resources:
        description = "VISA resource"
        try:
            inst = rm.open_resource(resource_name)
        except Exception as exc:
            description = f"<open failed: {exc}>"
        else:
            try:
                description = describe_resource(resource_name, query_idn(inst))
            finally:
                inst.close()
        print(f"{resource_name} -> {description}")
    return 0


def probe_backends(pyvisa_module, requested_backend: str | None) -> tuple[object, str | None]:
    if requested_backend is not None:
        rm = open_resource_manager(pyvisa_module, requested_backend)
        return rm, requested_backend

    rm = open_resource_manager(pyvisa_module, None)
    return rm, None


def auto_detect_resource(rm) -> str:
    matches: list[tuple[str, str]] = []

    for resource_name in candidate_resources(rm):
        try:
            inst = rm.open_resource(resource_name)
            inst.close()
        except Exception:
            continue

        if (
            is_known_unit_resource(resource_name)
        ):
            matches.append((resource_name, "UNI-T UTG900E/UTG962 USBTMC device"))

    if not matches:
        raise RuntimeError("No UNI-T UTG instrument was detected. Pass --resource explicitly.")
    if len(matches) > 1:
        details = "\n".join(f"  {name} -> {idn}" for name, idn in matches)
        raise RuntimeError(f"Multiple candidate instruments found:\n{details}\nUse --resource explicitly.")
    return matches[0][0]


def configure_channel(
    inst,
    channel: int,
    arb_index: int,
    frequency: float | None,
    amplitude: float | None,
    offset: float | None,
    phase: float,
    output_on: bool,
) -> None:
    low = None
    high = None
    if amplitude is not None:
        dc_offset = offset or 0.0
        low = dc_offset - (amplitude / 2.0)
        high = dc_offset + (amplitude / 2.0)

    visa_write(inst, f":CHAN{channel}:MODe CONT")
    visa_write(inst, f":CHAN{channel}:BASE:WAV ARB")
    visa_write(inst, f":CHAN{channel}:ARB:SOUR EXT")
    visa_write(inst, f":CHAN{channel}:ARB:IND {arb_index}")

    if frequency is not None:
        visa_write(inst, f":CHAN{channel}:BASE:FREQ {frequency}")
    if low is not None:
        visa_write(inst, f":CHAN{channel}:BASE:LOW {low}")
    if high is not None:
        visa_write(inst, f":CHAN{channel}:BASE:HIGH {high}")
    visa_write(inst, f":CHAN{channel}:BASE:PHAS {phase}")

    if output_on:
        visa_write(inst, f":CHAN{channel}:OUTP ON")

    visa_write(inst, ":SYSTEM:LOCK OFF")


def upload_waveform(
    inst,
    waveform_bytes: bytes,
    arb_slot: int,
    arb_name: str,
) -> int:
    # Uploading via :WARB can force channels into ARB mode. Preserve their current base wave.
    chan1_wave = None
    chan2_wave = None
    try:
        chan1_wave = visa_query(inst, ":CHAN1:BASE:WAV?").strip()
    except Exception:
        pass
    try:
        chan2_wave = visa_query(inst, ":CHAN2:BASE:WAV?").strip()
    except Exception:
        pass

    visa_write(inst, f":WARB{arb_slot + 1}:CARR {arb_name}")
    written = visa_write_raw(inst, waveform_bytes)

    if chan1_wave:
        visa_write(inst, f":CHAN1:BASE:WAV {chan1_wave}")
    if chan2_wave:
        visa_write(inst, f":CHAN2:BASE:WAV {chan2_wave}")
    visa_write(inst, ":SYSTEM:LOCK OFF")
    return written


def ensure_waveform_file(path: Path) -> Path:
    if path is None:
        raise SystemExit("waveform path is required unless --list is used")
    if not path.is_file():
        raise SystemExit(f"waveform file not found: {path}")
    return path


def _preview_raw_command(data: bytes) -> str:
    return f"<raw waveform payload: {len(data)} bytes>"


def visa_write(inst, command: str) -> int:
    if IO_LOGGING_ENABLED:
        print(f"SCPI >> {command}")
    count = inst.write(command)
    if IO_LOGGING_ENABLED:
        print(f"VISA ~~ wrote {count} bytes")
    return count


def visa_query(inst, command: str) -> str:
    if IO_LOGGING_ENABLED:
        print(f"SCPI >> {command}")
    response = inst.query(command)
    if IO_LOGGING_ENABLED:
        print(f"SCPI << {response.strip()}")
    return response


def visa_write_raw(inst, payload: bytes) -> int:
    if IO_LOGGING_ENABLED:
        print(f"SCPI >> {_preview_raw_command(payload)}")
    count = inst.write_raw(payload)
    if IO_LOGGING_ENABLED:
        print(f"VISA ~~ wrote_raw {count} bytes")
    return count


def parse_optional_int(values: dict[str, str], name: str, path: Path) -> int | None:
    value = values.get(name)
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except ValueError as exc:
        raise SystemExit(f"{path} has an invalid {name} value: {value}") from exc


def parse_optional_float(values: dict[str, str], name: str, path: Path) -> float | None:
    value = values.get(name)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise SystemExit(f"{path} has an invalid {name} value: {value}") from exc


def parse_waveform_text(path: Path) -> tuple[list[float], dict[str, str]]:
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

            if line.startswith(("#", ";", "*")):
                continue

            token = line.rstrip(",").strip()
            if not token:
                continue

            try:
                samples.append(float(token))
            except ValueError as exc:
                raise SystemExit(f"{path} contains an invalid sample value: {line}") from exc

    if not samples:
        raise SystemExit(f"{path} does not contain any waveform samples")
    return samples, values


def resample_samples(samples: list[float], target_count: int) -> list[float]:
    if len(samples) == target_count:
        return list(samples)
    if len(samples) < 2:
        raise SystemExit("At least two samples are required for resampling")

    result: list[float] = []
    source_last = len(samples) - 1
    target_last = target_count - 1

    for i in range(target_count):
        position = (i * source_last) / target_last
        left = int(position)
        right = min(left + 1, source_last)
        frac = position - left
        value = samples[left] * (1.0 - frac) + samples[right] * frac
        result.append(value)

    return result


def build_reference_arb_payload(samples: list[float]) -> bytes:
    clipped = [max(-1.0, min(1.0, sample)) for sample in samples]
    scaled = [int(32767.0 * sample) for sample in clipped]
    data_intro = f"[DATA]:{len(scaled)}\r\n".encode("ascii")
    sample_bytes = struct.pack(f"<{len(scaled)}h", *scaled)
    return REFERENCE_ARB_HEADER_INTRO + REFERENCE_ARB_HEADER + data_intro + sample_bytes


def parse_waveform_file(path: Path) -> tuple[bytes, BsvMetadata]:
    suffix = path.suffix.lower()

    if suffix == ".csv":
        samples, values = parse_waveform_text(path)
        declared_count = parse_optional_int(values, "[DATA]", path)
        source_count = declared_count if declared_count is not None else len(samples)
        if source_count != len(samples):
            raise SystemExit(
                f"{path} [DATA] count says {source_count}, but {len(samples)} samples were parsed."
            )

        upload_samples = samples
        upload_count = source_count
        if source_count > 4000:
            upload_samples = resample_samples(samples, 4000)
            upload_count = 4000

        vpp = parse_optional_float(values, "VPP", path)
        offset = parse_optional_float(values, "OFFSET", path)
        waveform_bytes = build_reference_arb_payload(upload_samples)
        metadata = BsvMetadata(
            path=path,
            file_name=path.name,
            point_count=upload_count,
            payload_bytes=len(waveform_bytes),
            channel=parse_optional_int(values, "CHANNEL", path),
            vpp=vpp,
            offset=offset,
            rate_pos=parse_optional_float(values, "RATEPOS", path) if upload_count == source_count else None,
            rate_neg=parse_optional_float(values, "RATENEG", path) if upload_count == source_count else None,
        )
        return waveform_bytes, metadata

    if suffix == ".bsv":
        waveform_bytes = path.read_bytes()
        marker = b"[DATA]:"
        marker_index = waveform_bytes.find(marker)
        if marker_index == -1:
            raise SystemExit(f"{path} is not a valid UTG .bsv file: missing [DATA] marker")

        data_line_end = waveform_bytes.find(b"\n", marker_index)
        if data_line_end == -1:
            raise SystemExit(f"{path} is not a valid UTG .bsv file: missing newline after [DATA]")

        header_bytes = waveform_bytes[: data_line_end + 1]
        payload = waveform_bytes[data_line_end + 1 :]

        try:
            header_text = header_bytes.decode("ascii")
        except UnicodeDecodeError as exc:
            raise SystemExit(f"{path} is not a valid UTG .bsv file: header is not ASCII") from exc

        values: dict[str, str] = {}
        for raw_line in header_text.splitlines():
            if ":" not in raw_line:
                continue
            key, value = raw_line.split(":", 1)
            values[key.strip().upper()] = value.strip()

        point_count = parse_optional_int(values, "[DATA]", path)
        if point_count is None:
            raise SystemExit(f"{path} is not a valid UTG .bsv file: invalid [DATA] count")
        if point_count != 4096:
            raise SystemExit(
                f"{path} contains {point_count} points, but the UTG900E manual specifies 4096-point arbitrary uploads."
            )

        expected_payload_bytes = point_count * 2
        if len(payload) != expected_payload_bytes:
            raise SystemExit(
                f"{path} payload size mismatch: expected {expected_payload_bytes} bytes, got {len(payload)} bytes."
            )

        metadata = BsvMetadata(
            path=path,
            file_name=path.name,
            point_count=point_count,
            payload_bytes=len(waveform_bytes),
            channel=parse_optional_int(values, "CHANNEL", path),
            vpp=parse_optional_float(values, "VPP", path),
            offset=parse_optional_float(values, "OFFSET", path),
            rate_pos=parse_optional_float(values, "RATEPOS", path),
            rate_neg=parse_optional_float(values, "RATENEG", path),
        )
        return waveform_bytes, metadata

    raise SystemExit(f"Unsupported waveform format: {path.suffix}. Use .csv or .bsv.")


def main() -> int:
    args = parse_args()
    global IO_LOGGING_ENABLED
    IO_LOGGING_ENABLED = args.log_io

    try:
        import pyvisa
    except ImportError as exc:
        raise SystemExit(
            "PyVISA is not installed. Install it with 'pip install pyvisa' and, if needed, "
            "'pip install pyvisa-py'."
        ) from exc

    rm, backend_in_use = probe_backends(pyvisa, args.backend)

    if args.list:
        result = list_resources(rm)
        rm.close()
        return result

    waveform_path = ensure_waveform_file(args.waveform)
    resource_name = args.resource if args.resource != "auto" else auto_detect_resource(rm)
    waveform_bytes, metadata = parse_waveform_file(waveform_path)
    channel = args.channel if args.channel is not None else (metadata.channel or 1)
    arb_name = args.arb_name if args.arb_name else waveform_path.stem
    source_frequency = None
    if metadata.rate_pos is not None and metadata.rate_pos > 0:
        source_frequency = 1.0 / (metadata.point_count * metadata.rate_pos)
    frequency = args.frequency if args.frequency is not None else source_frequency
    amplitude = args.amplitude if args.amplitude is not None else metadata.vpp
    offset = args.offset if args.offset is not None else metadata.offset
    if offset is None:
        offset = 0.0

    inst = rm.open_resource(resource_name)
    inst.timeout = args.timeout_ms
    inst.write_termination = "\n"
    inst.read_termination = "\n"

    try:
        try:
            inst.clear()
        except Exception:
            pass
        idn = query_idn(inst)
        print(f"Connected: {resource_name}")
        print(f"Backend  : {backend_in_use or 'default VISA runtime'}")
        print(f"Device   : {describe_resource(resource_name, idn)}")
        print(f"File     : {waveform_path}")
        print(f"Bytes    : {len(waveform_bytes)}")
        print(f"Points   : {metadata.point_count}")
        print(f"Channel  : CH{channel}")
        print(f"ARB slot : {args.arb_index}")
        print(f"ARB name : {arb_name}")
        if source_frequency is not None:
            print(f"File Hz  : {source_frequency}")
        if amplitude is not None:
            print(f"Vpp      : {amplitude}")
        if offset is not None:
            print(f"Offset   : {offset}")
        if args.frequency is not None and source_frequency is not None:
            print(f"Warn     : requested {args.frequency} Hz overrides file timing {source_frequency} Hz")

        visa_write(inst, "*CLS")
        written = upload_waveform(inst, waveform_bytes, args.arb_index, arb_name)
        print(f"Uploaded : {written} bytes")
        print("Status   : Upload command sent to device")
        time.sleep(max(args.post_upload_delay_ms, 0) / 1000.0)

        if not args.store_only:
            configure_channel(
                inst=inst,
                channel=channel,
                arb_index=args.arb_index,
                frequency=frequency,
                amplitude=amplitude,
                offset=offset,
                phase=args.phase,
                output_on=args.output_on,
            )
            print(f"Waveform : {arb_name}")

        print("Done")
        return 0
    finally:
        try:
            visa_write(inst, ":SYSTEM:LOCK OFF")
        except Exception:
            pass
        inst.close()
        rm.close()


if __name__ == "__main__":
    raise SystemExit(main())
