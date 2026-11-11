#!/usr/bin/env python3
"""Fast, standard-library quality preflight for this project's CSI captures.

The checker validates the analyser-side container before NumPy/Matplotlib work:
    <float64 timestamp><uint16 payload length><24-byte CSI header + int16 I/Q>

Exit codes: 0 = pass, 1 = review warnings, 2 = fail.
Transmitter MAC addresses are counted but never printed.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import math
import os
import stat
import struct
import sys
import unicodedata
import uuid
from pathlib import Path


FRAME = struct.Struct("<dH")
HEADER = struct.Struct("<I6sbBBBBBHHHH")
FRAME_HEADER_BYTES = FRAME.size
CSI_HEADER_BYTES = HEADER.size


def rounded(value, digits=6):
    if value is None or not math.isfinite(float(value)):
        return None
    return round(float(value), digits)


def normalised_path(path):
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def path_key(path):
    return tuple(
        unicodedata.normalize("NFC", part).casefold()
        for part in Path(path).parts
    )


def is_ancestor(parent, child):
    parent_key = path_key(parent)
    child_key = path_key(child)
    return (
        len(parent_key) < len(child_key)
        and child_key[: len(parent_key)] == parent_key
    )


def validate_output_paths(capture, outputs):
    capture_key = path_key(capture)
    capture_stat = os.stat(capture)
    capture_identity = (capture_stat.st_dev, capture_stat.st_ino)
    seen = {}
    existing = []
    for option, path in outputs:
        key = path_key(path)
        if key == capture_key:
            raise ValueError("output paths must be different")
        if key in seen:
            raise ValueError("output paths must be different")
        if is_ancestor(path, capture) or is_ancestor(capture, path):
            raise ValueError("output paths cannot contain the capture path")
        try:
            destination_stat = path.stat()
        except FileNotFoundError:
            destination_stat = None
        if destination_stat is not None:
            if stat.S_ISDIR(destination_stat.st_mode):
                raise ValueError(f"{option} points to a directory")
            destination_identity = (
                destination_stat.st_dev,
                destination_stat.st_ino,
            )
            if destination_identity == capture_identity:
                raise ValueError("output paths must be different")
            if destination_identity in existing:
                raise ValueError("output paths must be different")
            existing.append(destination_identity)
        seen[key] = option

    entries = list(seen.items())
    for index, (left_key, left_option) in enumerate(entries):
        for right_key, right_option in entries[index + 1 :]:
            if (
                left_key == right_key
                or left_key[: len(right_key)] == right_key
                or right_key[: len(left_key)] == left_key
            ):
                raise ValueError(
                    f"{left_option} and {right_option} output paths conflict"
                )


def stage_text_file(path, text):
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(parent, flags)
    temporary_name = f".{path.name}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    created = False
    try:
        file_descriptor = os.open(
            temporary_name,
            flags,
            0o600,
            dir_fd=directory_fd,
        )
        created = True
        with os.fdopen(
            file_descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as output:
            os.fchmod(output.fileno(), 0o644)
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        if created:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)
        raise
    return {
        "path": path,
        "directory_fd": directory_fd,
        "temporary_name": temporary_name,
    }


def assert_destination_safe(path, directory_fd, capture_identity):
    try:
        destination = os.stat(
            path.name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    if stat.S_ISDIR(destination.st_mode):
        raise OSError(f"output path is a directory: {path}")
    if (
        not stat.S_ISLNK(destination.st_mode)
        and (destination.st_dev, destination.st_ino) == capture_identity
    ):
        raise OSError("output path is a hard link to the capture")


def publish_text_outputs(outputs, capture):
    capture_stat = os.stat(capture)
    capture_identity = (capture_stat.st_dev, capture_stat.st_ino)
    staged = []
    try:
        for path, text in outputs:
            staged.append(stage_text_file(path, text))
        directory_entries = {}
        for item in staged:
            directory_stat = os.fstat(item["directory_fd"])
            entry_key = (
                directory_stat.st_dev,
                directory_stat.st_ino,
                unicodedata.normalize("NFC", item["path"].name).casefold(),
            )
            if entry_key in directory_entries:
                raise OSError(
                    "two output paths resolve to the same directory entry"
                )
            directory_entries[entry_key] = item["path"]
        for item in staged:
            assert_destination_safe(
                item["path"],
                item["directory_fd"],
                capture_identity,
            )
        for item in staged:
            os.replace(
                item["temporary_name"],
                item["path"].name,
                src_dir_fd=item["directory_fd"],
                dst_dir_fd=item["directory_fd"],
            )
            item["temporary_name"] = None
    finally:
        for item in staged:
            if item["temporary_name"] is not None:
                try:
                    os.unlink(
                        item["temporary_name"],
                        dir_fd=item["directory_fd"],
                    )
                except FileNotFoundError:
                    pass
            os.close(item["directory_fd"])


def mode(counter):
    if not counter:
        return None
    return counter.most_common(1)[0][0]


def percentile(sorted_values, fraction):
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def interval_summary(values):
    if not values:
        return {
            "count": 0,
            "min_seconds": None,
            "p50_seconds": None,
            "p95_seconds": None,
            "max_seconds": None,
            "mean_seconds": None,
        }
    ordered = sorted(values)
    return {
        "count": len(values),
        "min_seconds": rounded(ordered[0]),
        "p50_seconds": rounded(percentile(ordered, 0.50)),
        "p95_seconds": rounded(percentile(ordered, 0.95)),
        "max_seconds": rounded(ordered[-1]),
        "mean_seconds": rounded(sum(values) / len(values)),
    }


def normalised_counter(counter):
    return {str(key): counter[key] for key in sorted(counter)}


def truncate_series(values, limit=2000):
    if len(values) <= limit:
        return [rounded(value) for value in values]
    step = (len(values) - 1) / (limit - 1)
    return [rounded(values[round(index * step)]) for index in range(limit)]


def audit_capture(path, min_groups=10, max_gap_seconds=5.0, min_coverage=0.98):
    station_keys = set()
    subcarrier_counts = collections.Counter()
    bandwidth_counts = collections.Counter()
    chain_pair_counts = collections.Counter()
    group_chain_counts = collections.Counter()
    group_start_times = []
    group_intervals = []

    bytes_read = 0
    records = 0
    valid_payloads = 0
    malformed_payloads = 0
    truncated_records = 0
    leftover_bytes = 0
    iq_length_mismatches = 0
    missing_iq_pairs = 0
    non_empty_iq_records = 0
    empty_iq_records = 0
    non_finite_timestamps = 0
    non_monotonic_records = 0
    min_file_timestamp = None
    max_file_timestamp = None
    last_file_timestamp = None

    closed_groups = 0
    current_group_start = None
    current_group_records = 0
    current_group_non_empty_iq = False
    current_group_pairs = set()
    last_closed_group_start = None
    duplicate_chain_pairs = 0
    non_monotonic_groups = 0
    negative_intervals = 0
    group_iq_empty = 0
    digest = hashlib.sha256()

    def finish_group(timestamp):
        nonlocal closed_groups
        nonlocal current_group_start
        nonlocal current_group_records
        nonlocal current_group_non_empty_iq
        nonlocal current_group_pairs
        nonlocal last_closed_group_start
        nonlocal non_monotonic_groups
        nonlocal negative_intervals
        nonlocal group_iq_empty

        if current_group_start is None:
            current_group_start = timestamp
        group_start_times.append(current_group_start)
        if last_closed_group_start is not None:
            interval = current_group_start - last_closed_group_start
            group_intervals.append(interval)
            if interval < 0:
                negative_intervals += 1
                non_monotonic_groups += 1
        last_closed_group_start = current_group_start
        closed_groups += 1
        group_chain_counts[current_group_records] += 1
        if not current_group_non_empty_iq:
            group_iq_empty += 1
        current_group_start = None
        current_group_records = 0
        current_group_non_empty_iq = False
        current_group_pairs = set()

    def inspect_payload(timestamp, payload):
        nonlocal valid_payloads
        nonlocal malformed_payloads
        nonlocal iq_length_mismatches
        nonlocal missing_iq_pairs
        nonlocal non_empty_iq_records
        nonlocal empty_iq_records
        nonlocal current_group_start
        nonlocal current_group_records
        nonlocal current_group_non_empty_iq
        nonlocal duplicate_chain_pairs

        if len(payload) < CSI_HEADER_BYTES:
            malformed_payloads += 1
            return
        valid_payloads += 1
        (
            _timestamp_us,
            station,
            _rssi,
            _snr,
            bandwidth,
            _channel,
            _mode,
            _epoch,
            subcarriers,
            tx,
            rx,
            chain_info,
        ) = HEADER.unpack_from(payload)
        pair = (tx, rx)
        station_keys.add(station)
        subcarrier_counts[subcarriers] += 1
        bandwidth_counts[bandwidth] += 1
        chain_pair_counts[pair] += 1

        if current_group_start is None:
            current_group_start = timestamp
        if pair in current_group_pairs:
            duplicate_chain_pairs += 1
        current_group_pairs.add(pair)
        current_group_records += 1

        expected_iq_bytes = subcarriers * 4
        actual_iq_bytes = len(payload) - CSI_HEADER_BYTES
        if actual_iq_bytes != expected_iq_bytes:
            iq_length_mismatches += 1
            if actual_iq_bytes < expected_iq_bytes:
                missing_iq_pairs += math.ceil(
                    (expected_iq_bytes - actual_iq_bytes) / 4
                )
        end = CSI_HEADER_BYTES + min(expected_iq_bytes, actual_iq_bytes)
        if any(payload[CSI_HEADER_BYTES:end]):
            non_empty_iq_records += 1
            current_group_non_empty_iq = True
        else:
            empty_iq_records += 1

        if chain_info & 0x8000:
            finish_group(timestamp)

    with path.open("rb") as stream:
        while True:
            frame_header = stream.read(FRAME_HEADER_BYTES)
            bytes_read += len(frame_header)
            digest.update(frame_header)
            if not frame_header:
                break
            if len(frame_header) < FRAME_HEADER_BYTES:
                truncated_records = 1
                leftover_bytes = len(frame_header)
                break

            try:
                timestamp, payload_length = FRAME.unpack(frame_header)
            except struct.error:
                malformed_payloads += 1
                break
            payload = stream.read(payload_length)
            bytes_read += len(payload)
            digest.update(payload)
            if len(payload) < payload_length:
                records += 1
                truncated_records = 1
                leftover_bytes = CSI_HEADER_BYTES + len(payload)
                break

            records += 1
            if not math.isfinite(timestamp):
                non_finite_timestamps += 1
            else:
                if min_file_timestamp is None or timestamp < min_file_timestamp:
                    min_file_timestamp = timestamp
                if max_file_timestamp is None or timestamp > max_file_timestamp:
                    max_file_timestamp = timestamp
                if (
                    last_file_timestamp is not None
                    and timestamp < last_file_timestamp
                ):
                    non_monotonic_records += 1
                last_file_timestamp = timestamp
            inspect_payload(timestamp, payload)

    incomplete_tail_records = current_group_records
    expected_subcarriers = mode(subcarrier_counts)
    expected_chain_count = mode(group_chain_counts)
    complete_subcarrier_records = (
        subcarrier_counts[expected_subcarriers]
        if expected_subcarriers is not None
        else 0
    )
    complete_chain_groups = (
        group_chain_counts[expected_chain_count]
        if expected_chain_count is not None
        else 0
    )
    subcarrier_coverage = (
        complete_subcarrier_records / valid_payloads if valid_payloads else 0.0
    )
    chain_coverage = (
        complete_chain_groups / closed_groups if closed_groups else 0.0
    )
    duration_seconds = (
        max(0.0, max_file_timestamp - min_file_timestamp)
        if min_file_timestamp is not None and max_file_timestamp is not None
        else 0.0
    )
    group_duration_seconds = (
        max(group_start_times) - min(group_start_times)
        if len(group_start_times) > 1
        else 0.0
    )
    intervals = interval_summary(group_intervals)
    measurement_rate_hz = (
        closed_groups / group_duration_seconds
        if group_duration_seconds > 0
        else None
    )
    records_per_second = (
        records / group_duration_seconds if group_duration_seconds > 0 else None
    )

    checks = [
        {
            "id": "framing",
            "status": (
                "fail"
                if malformed_payloads > 0 or records == 0
                else "warn"
                if truncated_records > 0
                else "pass"
            ),
        },
        {
            "id": "groups",
            "status": "pass" if closed_groups >= min_groups else "fail",
        },
        {
            "id": "chain_coverage",
            "status": (
                "fail"
                if closed_groups == 0
                else "pass"
                if chain_coverage >= min_coverage
                else "warn"
            ),
        },
        {
            "id": "timing",
            "status": (
                "warn"
                if (
                    intervals["count"] == 0
                    or non_monotonic_groups > 0
                    or intervals["max_seconds"] > max_gap_seconds
                )
                else "pass"
            ),
        },
        {
            "id": "subcarriers",
            "status": (
                "fail"
                if valid_payloads == 0
                else "pass"
                if subcarrier_coverage >= min_coverage
                else "warn"
            ),
        },
        {
            "id": "iq",
            "status": "pass" if non_empty_iq_records > 0 else "fail",
        },
    ]
    if any(check["status"] == "fail" for check in checks):
        quality = "fail"
    elif any(check["status"] == "warn" for check in checks):
        quality = "warn"
    else:
        quality = "pass"

    result = {
        "schema_version": 1,
        "bytes_read": bytes_read,
        "records": records,
        "valid_payloads": valid_payloads,
        "malformed_payloads": malformed_payloads,
        "truncated_records": truncated_records,
        "leftover_bytes": leftover_bytes,
        "closed_groups": closed_groups,
        "incomplete_tail_records": incomplete_tail_records,
        "duration_seconds": rounded(duration_seconds),
        "group_duration_seconds": rounded(group_duration_seconds),
        "file_span_seconds": rounded(duration_seconds),
        "measurement_rate_hz": rounded(measurement_rate_hz, 3),
        "records_per_second": rounded(records_per_second, 3),
        "expected_subcarriers": expected_subcarriers,
        "expected_chain_count": expected_chain_count,
        "subcarrier_coverage": rounded(subcarrier_coverage, 4),
        "chain_coverage": rounded(chain_coverage, 4),
        "complete_subcarrier_records": complete_subcarrier_records,
        "complete_chain_groups": complete_chain_groups,
        "incomplete_chain_groups": closed_groups - complete_chain_groups,
        "duplicate_chain_pairs": duplicate_chain_pairs,
        "group_iq_empty": group_iq_empty,
        "empty_iq_records": empty_iq_records,
        "non_empty_iq_records": non_empty_iq_records,
        "iq_length_mismatches": iq_length_mismatches,
        "missing_iq_pairs": missing_iq_pairs,
        "non_finite_timestamps": non_finite_timestamps,
        "non_monotonic_records": non_monotonic_records,
        "non_monotonic_groups": non_monotonic_groups,
        "negative_intervals": negative_intervals,
        "stations": len(station_keys),
        "subcarrier_counts": normalised_counter(subcarrier_counts),
        "bandwidth_counts": normalised_counter(bandwidth_counts),
        "chain_pair_counts": {
            f"{tx}:{rx}": count
            for (tx, rx), count in sorted(chain_pair_counts.items())
        },
        "group_chain_counts": normalised_counter(group_chain_counts),
        "intervals": intervals,
        "long_gaps": {
            "over_1s": sum(value > 1.0 for value in group_intervals),
            "over_5s": sum(value > 5.0 for value in group_intervals),
        },
        "timeline": {
            "group_start_seconds": truncate_series(
                [
                    value - (group_start_times[0] if group_start_times else value)
                    for value in group_start_times
                ]
            ),
            "intervals_seconds": truncate_series(group_intervals),
        },
        "thresholds": {
            "min_groups": min_groups,
            "max_gap_seconds": max_gap_seconds,
            "min_coverage": min_coverage,
        },
        "checks": checks,
        "quality": {"status": quality},
        "limitations": [
            "A timestamp gap is not proof of packet loss: it can also mean the trigger produced no CSI report.",
            "A closed measurement group does not prove every expected physical chain carried usable non-zero data.",
            "These checks validate container consistency and capture continuity, not human-event ground truth.",
        ],
    }
    return {
        "schema_version": 1,
        "tool": "Router CSI Toolkit capture quality checker",
        "generated_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "input": {
            "name": path.name,
            "size_bytes": path.stat().st_size,
            "sha256": digest.hexdigest(),
        },
        "privacy": (
            "The checker reads the capture locally. Transmitter MAC addresses "
            "are counted and omitted from reports."
        ),
        "result": result,
    }


def markdown_report(report):
    result = report["result"]
    source = report["input"]
    lines = [
        "# Router CSI Capture Quality Report",
        "",
        f"- File: `{source['name']}`",
        f"- Size: {source['size_bytes']:,} bytes",
        f"- SHA-256: `{source['sha256']}`",
        f"- Generated: {report['generated_at']}",
        f"- Verdict: **{result['quality']['status'].upper()}**",
        "",
        "## Metrics",
        "",
        "| Item | Value |",
        "| :--- | :--- |",
        f"| Records | {result['records']:,} |",
        f"| Closed groups | {result['closed_groups']:,} |",
        f"| Group rate | {result['measurement_rate_hz']} Hz |",
        f"| Maximum gap | {result['intervals']['max_seconds']} s |",
        f"| Modal chain count | {result['expected_chain_count']} |",
        f"| Modal subcarriers | {result['expected_subcarriers']} |",
        f"| Chain coverage | {result['chain_coverage']} |",
        f"| Subcarrier coverage | {result['subcarrier_coverage']} |",
        f"| I/Q length mismatches | {result['iq_length_mismatches']:,} |",
        f"| Truncated records | {result['truncated_records']:,} |",
        f"| Transmitter count | {result['stations']:,} |",
        "",
        "## Checks",
        "",
    ]
    lines.extend(
        f"- {check['status'].upper()}: `{check['id']}`"
        for check in result["checks"]
    )
    lines.extend(["", "## Limits", ""])
    lines.extend(f"- {item}" for item in result["limitations"])
    lines.extend(["", "## Privacy", "", report["privacy"], ""])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Validate framing, closed CSI groups, chain/subcarrier consistency, "
            "timestamp gaps and I/Q presence before running NumPy analysis."
        )
    )
    parser.add_argument("capture", type=Path)
    parser.add_argument(
        "--format", choices=("json", "markdown", "none"), default="markdown"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--min-groups", type=int, default=10)
    parser.add_argument("--max-gap", type=float, default=5.0)
    parser.add_argument("--min-coverage", type=float, default=0.98)
    args = parser.parse_args(argv)

    for attribute in ("output", "json_output", "markdown_output"):
        path = getattr(args, attribute)
        if path is not None:
            setattr(args, attribute, normalised_path(path))
    if not args.capture.is_file():
        parser.error(f"capture not found: {args.capture}")
    if args.output and args.format == "none":
        parser.error("--output requires --format json or markdown")
    requested_outputs = [
        ("--output", args.output),
        ("--json-output", args.json_output),
        ("--markdown-output", args.markdown_output),
    ]
    requested_outputs = [
        (option, path)
        for option, path in requested_outputs
        if path is not None
    ]
    try:
        validate_output_paths(args.capture, requested_outputs)
    except ValueError as error:
        parser.error(str(error))
    except OSError as error:
        sys.stderr.write(f"error: failed to validate output path: {error}\n")
        return 2
    try:
        report = audit_capture(
            args.capture,
            min_groups=args.min_groups,
            max_gap_seconds=args.max_gap,
            min_coverage=args.min_coverage,
        )
    except OSError as error:
        sys.stderr.write(f"error: failed to read capture: {error}\n")
        return 2
    json_output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    markdown_output = markdown_report(report)

    file_outputs = []
    if args.output:
        file_outputs.append(
            (
                args.output,
                json_output if args.format == "json" else markdown_output,
            )
        )
    if args.json_output:
        file_outputs.append((args.json_output, json_output))
    if args.markdown_output:
        file_outputs.append((args.markdown_output, markdown_output))
    if file_outputs:
        try:
            publish_text_outputs(file_outputs, args.capture)
        except OSError as error:
            sys.stderr.write(f"error: failed to write report: {error}\n")
            return 2
    if args.format == "json":
        sys.stdout.write(json_output)
    elif args.format == "markdown":
        sys.stdout.write(markdown_output)
    return {"pass": 0, "warn": 1, "fail": 2}[
        report["result"]["quality"]["status"]
    ]


if __name__ == "__main__":
    raise SystemExit(main())
