#!/usr/bin/env python3
import json
import importlib.util
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_csi_capture.py"
FRAME = struct.Struct("<dH")
HEADER = struct.Struct("<I6sbBBBBBHHHH")


def make_record(
    timestamp,
    *,
    station=bytes.fromhex("020000000001"),
    subcarriers=2,
    tx=0,
    rx=0,
    last=False,
    iq_pairs=((10, -3), (7, 4)),
):
    iq = b"".join(struct.pack("<hh", i, q) for i, q in iq_pairs)
    payload = HEADER.pack(
        int(timestamp * 1_000_000) & 0xFFFFFFFF,
        station,
        -42,
        45,
        2,
        44,
        1,
        0,
        subcarriers,
        tx,
        rx,
        0x8000 if last else 0,
    ) + iq
    return FRAME.pack(timestamp, len(payload)) + payload


def run_checker(capture, *args, cwd=ROOT, env=None):
    return subprocess.run(
        [sys.executable, str(CHECKER), str(capture), *args],
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def load_checker():
    spec = importlib.util.spec_from_file_location("check_csi_capture", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CaptureQualityCliTest(unittest.TestCase):
    def test_json_report_counts_known_groups_and_chain_records(self):
        capture = b"".join(
            [
                make_record(1000.0, tx=0, rx=0),
                make_record(1000.2, tx=0, rx=1, last=True),
                make_record(1001.0, tx=0, rx=0),
                make_record(1001.2, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            path.write_bytes(capture)
            process = run_checker(path, "--format", "json", "--min-groups", "2")

        self.assertEqual(0, process.returncode, process.stderr)
        report = json.loads(process.stdout)
        result = report["result"]
        self.assertEqual(4, result["records"])
        self.assertEqual(2, result["closed_groups"])
        self.assertEqual(2, result["expected_chain_count"])
        self.assertEqual(2, result["expected_subcarriers"])
        self.assertEqual("pass", result["quality"]["status"])
        self.assertEqual(1, result["stations"])

    def test_malformed_payload_fails_even_when_outer_frame_is_complete(self):
        payload = b"abc"
        capture = FRAME.pack(1.0, len(payload)) + payload
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.bin"
            path.write_bytes(capture)
            process = run_checker(path, "--format", "json")

        self.assertEqual(2, process.returncode, process.stderr)
        result = json.loads(process.stdout)["result"]
        self.assertEqual(1, result["records"])
        self.assertEqual(1, result["malformed_payloads"])
        self.assertEqual("fail", result["quality"]["status"])

    def test_markdown_report_never_prints_the_transmitter_mac(self):
        mac = "02:11:22:33:44:55"
        capture = b"".join(
            [
                make_record(
                    20.0,
                    station=bytes.fromhex(mac.replace(":", "")),
                    tx=0,
                    rx=0,
                ),
                make_record(
                    20.2,
                    station=bytes.fromhex(mac.replace(":", "")),
                    tx=0,
                    rx=1,
                    last=True,
                ),
                make_record(
                    21.0,
                    station=bytes.fromhex(mac.replace(":", "")),
                    tx=0,
                    rx=0,
                ),
                make_record(
                    21.2,
                    station=bytes.fromhex(mac.replace(":", "")),
                    tx=0,
                    rx=1,
                    last=True,
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            path.write_bytes(capture)
            process = run_checker(
                path,
                "--format",
                "markdown",
                "--min-groups",
                "1",
            )

        self.assertEqual(0, process.returncode, process.stderr)
        self.assertNotIn(mac, process.stdout)
        self.assertNotIn(mac.replace(":", ""), process.stdout)
        self.assertIn("Transmitter count", process.stdout)

    def test_partial_tail_is_quarantined_and_returns_review_exit_code(self):
        complete = b"".join(
            [
                make_record(30.0, tx=0, rx=0),
                make_record(30.2, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "partial.bin"
            path.write_bytes(complete + b"\x01\x02\x03\x04")
            process = run_checker(
                path,
                "--format",
                "json",
                "--min-groups",
                "1",
            )

        self.assertEqual(1, process.returncode, process.stderr)
        result = json.loads(process.stdout)["result"]
        self.assertEqual(1, result["truncated_records"])
        self.assertEqual("warn", result["quality"]["status"])

    def test_both_report_formats_can_be_written_in_one_quiet_run(self):
        capture = b"".join(
            [
                make_record(40.0, tx=0, rx=0),
                make_record(40.2, tx=0, rx=1, last=True),
                make_record(41.0, tx=0, rx=0),
                make_record(41.2, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            json_path = Path(tmp) / "reports" / "quality.json"
            markdown_path = Path(tmp) / "reports" / "quality.md"
            path.write_bytes(capture)
            process = run_checker(
                path,
                "--format",
                "none",
                "--json-output",
                str(json_path),
                "--markdown-output",
                str(markdown_path),
                "--min-groups",
                "2",
            )

            self.assertEqual(0, process.returncode, process.stderr)
            self.assertEqual("", process.stdout)
            report = json.loads(json_path.read_text())
            self.assertEqual(2, report["result"]["closed_groups"])
            self.assertIn("Verdict: **PASS**", markdown_path.read_text())

    def test_duplicate_report_paths_are_rejected_without_overwriting(self):
        capture = b"".join(
            [
                make_record(50.0, tx=0, rx=0),
                make_record(50.2, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            report_path = Path(tmp) / "quality-report"
            path.write_bytes(capture)
            process = run_checker(
                path,
                "--format",
                "none",
                "--json-output",
                str(report_path),
                "--markdown-output",
                str(report_path),
                "--min-groups",
                "1",
            )

            self.assertEqual(2, process.returncode)
            self.assertIn("output paths must be different", process.stderr)
            self.assertFalse(report_path.exists())

    def test_report_output_cannot_overwrite_the_capture(self):
        capture = b"".join(
            [
                make_record(60.0, tx=0, rx=0),
                make_record(60.2, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            path.write_bytes(capture)
            process = run_checker(
                path,
                "--format",
                "none",
                "--json-output",
                str(path),
                "--min-groups",
                "1",
            )

            self.assertEqual(2, process.returncode)
            self.assertIn("output paths must be different", process.stderr)
            self.assertEqual(capture, path.read_bytes())

    def test_report_output_cannot_overwrite_a_hardlink_to_the_capture(self):
        capture = b"".join(
            [
                make_record(65.0, tx=0, rx=0),
                make_record(65.2, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            hardlink = Path(tmp) / "quality.json"
            path.write_bytes(capture)
            os.link(path, hardlink)
            process = run_checker(
                path,
                "--format",
                "none",
                "--json-output",
                str(hardlink),
                "--min-groups",
                "1",
            )

            self.assertEqual(2, process.returncode)
            self.assertIn("output paths must be different", process.stderr)
            self.assertEqual(capture, path.read_bytes())

    def test_quoted_tilde_output_uses_home_for_both_check_and_write(self):
        capture = b"".join(
            [
                make_record(66.0, tx=0, rx=0),
                make_record(66.2, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            work = root / "work"
            home.mkdir()
            (work / "~").mkdir(parents=True)
            path = root / "capture.bin"
            path.write_bytes(capture)
            os.link(path, work / "~" / "quality.json")
            env = os.environ.copy()
            env["HOME"] = str(home)
            process = run_checker(
                path,
                "--format",
                "none",
                "--json-output",
                "~/quality.json",
                "--min-groups",
                "1",
                cwd=work,
                env=env,
            )

            self.assertEqual(1, process.returncode, process.stderr)
            self.assertEqual(capture, path.read_bytes())
            self.assertTrue((home / "quality.json").is_file())
            self.assertEqual(capture, (work / "~" / "quality.json").read_bytes())

    def test_output_link_created_during_audit_cannot_overwrite_capture(self):
        capture = b"".join(
            [
                make_record(68.0, tx=0, rx=0),
                make_record(68.2, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            output_path = Path(tmp) / "quality.json"
            path.write_bytes(capture)
            checker = load_checker()
            original_audit = checker.audit_capture

            def racing_audit(*args, **kwargs):
                output_path.symlink_to(path)
                return original_audit(*args, **kwargs)

            checker.audit_capture = racing_audit
            try:
                returncode = checker.main(
                    [
                        str(path),
                        "--format",
                        "none",
                        "--json-output",
                        str(output_path),
                        "--min-groups",
                        "1",
                    ]
                )
            finally:
                checker.audit_capture = original_audit

            self.assertEqual(1, returncode)
            self.assertEqual(capture, path.read_bytes())
            self.assertFalse(output_path.is_symlink())
            self.assertEqual(1, json.loads(output_path.read_text())["schema_version"])

    def test_output_hardlink_created_during_audit_is_rejected(self):
        capture = b"".join(
            [
                make_record(69.0, tx=0, rx=0),
                make_record(69.2, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            output_path = Path(tmp) / "quality.json"
            path.write_bytes(capture)
            checker = load_checker()
            original_audit = checker.audit_capture

            def racing_audit(*args, **kwargs):
                os.link(path, output_path)
                return original_audit(*args, **kwargs)

            checker.audit_capture = racing_audit
            try:
                returncode = checker.main(
                    [
                        str(path),
                        "--format",
                        "none",
                        "--json-output",
                        str(output_path),
                        "--min-groups",
                        "1",
                    ]
                )
            finally:
                checker.audit_capture = original_audit

            self.assertEqual(2, returncode)
            self.assertEqual(capture, path.read_bytes())
            self.assertEqual(capture, output_path.read_bytes())

    def test_casefold_aliases_are_rejected_before_creating_output(self):
        capture = b"".join(
            [
                make_record(72.0, tx=0, rx=0),
                make_record(72.2, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            reports = Path(tmp) / "reports"
            json_path = reports / "Quality.json"
            markdown_path = reports / "quality.json"
            path.write_bytes(capture)
            process = run_checker(
                path,
                "--format",
                "none",
                "--json-output",
                str(json_path),
                "--markdown-output",
                str(markdown_path),
                "--min-groups",
                "1",
            )

            self.assertEqual(2, process.returncode)
            self.assertIn("paths must be different", process.stderr)
            self.assertFalse(reports.exists())

    def test_parent_child_output_paths_are_rejected(self):
        capture = b"".join(
            [
                make_record(73.0, tx=0, rx=0),
                make_record(73.2, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            reports = Path(tmp) / "reports"
            path.write_bytes(capture)
            process = run_checker(
                path,
                "--format",
                "none",
                "--json-output",
                str(reports),
                "--markdown-output",
                str(reports / "quality.md"),
                "--min-groups",
                "1",
            )

            self.assertEqual(2, process.returncode)
            self.assertIn("output paths conflict", process.stderr)
            self.assertFalse(reports.exists())

    def test_symlinked_parent_aliases_cannot_target_the_same_output(self):
        capture = b"".join(
            [
                make_record(73.5, tx=0, rx=0),
                make_record(73.7, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            real = Path(tmp) / "real"
            alias_a = Path(tmp) / "alias-a"
            alias_b = Path(tmp) / "alias-b"
            path.write_bytes(capture)
            real.mkdir()
            alias_a.symlink_to(real, target_is_directory=True)
            alias_b.symlink_to(real, target_is_directory=True)
            process = run_checker(
                path,
                "--format",
                "none",
                "--json-output",
                str(alias_a / "quality.out"),
                "--markdown-output",
                str(alias_b / "quality.out"),
                "--min-groups",
                "1",
            )

            self.assertEqual(2, process.returncode)
            self.assertIn("same directory entry", process.stderr)
            self.assertFalse((real / "quality.out").exists())

    def test_output_is_a_directory_returns_io_failure_not_warn(self):
        capture = b"".join(
            [
                make_record(74.0, tx=0, rx=0),
                make_record(74.2, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            output_path = Path(tmp) / "reports"
            path.write_bytes(capture)
            output_path.mkdir()
            process = run_checker(
                path,
                "--format",
                "none",
                "--json-output",
                str(output_path),
                "--min-groups",
                "1",
            )

            self.assertEqual(2, process.returncode)
            self.assertIn("points to a directory", process.stderr)
            self.assertNotIn("Traceback", process.stderr)

    def test_output_parent_file_returns_io_failure_without_partial_report(self):
        capture = b"".join(
            [
                make_record(75.0, tx=0, rx=0),
                make_record(75.2, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            blocker = Path(tmp) / "blocked"
            json_path = blocker / "quality.json"
            markdown_path = Path(tmp) / "quality.md"
            path.write_bytes(capture)
            blocker.write_text("not a directory", encoding="utf-8")
            process = run_checker(
                path,
                "--format",
                "none",
                "--json-output",
                str(json_path),
                "--markdown-output",
                str(markdown_path),
                "--min-groups",
                "1",
            )

            self.assertEqual(2, process.returncode)
            self.assertIn("failed to", process.stderr)
            self.assertNotIn("Traceback", process.stderr)
            self.assertFalse(markdown_path.exists())

    def test_output_validation_io_error_returns_two(self):
        capture = b"".join(
            [
                make_record(75.5, tx=0, rx=0),
                make_record(75.7, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            output_path = Path(tmp) / "quality.json"
            path.write_bytes(capture)
            checker = load_checker()
            original_validate = checker.validate_output_paths

            def failing_validate(*args, **kwargs):
                raise OSError("simulated stat failure")

            checker.validate_output_paths = failing_validate
            try:
                returncode = checker.main(
                    [
                        str(path),
                        "--format",
                        "none",
                        "--json-output",
                        str(output_path),
                        "--min-groups",
                        "1",
                    ]
                )
            finally:
                checker.validate_output_paths = original_validate

            self.assertEqual(2, returncode)
            self.assertEqual(capture, path.read_bytes())
            self.assertFalse(output_path.exists())

    def test_both_reports_omit_transmitter_mac(self):
        mac = "02:11:22:33:44:55"
        capture = b"".join(
            [
                make_record(
                    76.0,
                    station=bytes.fromhex(mac.replace(":", "")),
                    tx=0,
                    rx=0,
                ),
                make_record(
                    76.2,
                    station=bytes.fromhex(mac.replace(":", "")),
                    tx=0,
                    rx=1,
                    last=True,
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            json_path = Path(tmp) / "quality.json"
            markdown_path = Path(tmp) / "quality.md"
            path.write_bytes(capture)
            process = run_checker(
                path,
                "--format",
                "none",
                "--json-output",
                str(json_path),
                "--markdown-output",
                str(markdown_path),
                "--min-groups",
                "1",
            )

            self.assertEqual(1, process.returncode, process.stderr)
            self.assertNotIn(mac, json_path.read_text())
            self.assertNotIn(mac.replace(":", ""), json_path.read_text())
            self.assertNotIn(mac, markdown_path.read_text())
            self.assertNotIn(mac.replace(":", ""), markdown_path.read_text())

    def test_mixed_four_and_eight_chain_groups_return_warn(self):
        capture = b"".join(
            [
                make_record(77.0, tx=0, rx=0),
                make_record(77.1, tx=0, rx=1),
                make_record(77.2, tx=1, rx=0),
                make_record(77.3, tx=1, rx=1, last=True),
                make_record(78.0, tx=0, rx=0),
                make_record(78.1, tx=0, rx=1),
                make_record(78.2, tx=1, rx=0),
                make_record(78.3, tx=1, rx=1),
                make_record(78.4, tx=0, rx=2),
                make_record(78.5, tx=0, rx=3),
                make_record(78.6, tx=1, rx=2),
                make_record(78.7, tx=1, rx=3, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mixed.bin"
            path.write_bytes(capture)
            process = run_checker(
                path,
                "--format",
                "json",
                "--min-groups",
                "2",
            )

            self.assertEqual(1, process.returncode, process.stderr)
            result = json.loads(process.stdout)["result"]
            self.assertEqual("warn", result["quality"]["status"])
            self.assertEqual({"4": 1, "8": 1}, result["group_chain_counts"])

    def test_hardlinked_outputs_are_rejected_before_writing(self):
        capture = b"".join(
            [
                make_record(67.0, tx=0, rx=0),
                make_record(67.2, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            json_path = Path(tmp) / "quality.out"
            markdown_path = Path(tmp) / "quality-link.out"
            path.write_bytes(capture)
            json_path.write_text("sentinel", encoding="utf-8")
            os.link(json_path, markdown_path)
            process = run_checker(
                path,
                "--format",
                "none",
                "--json-output",
                str(json_path),
                "--markdown-output",
                str(markdown_path),
                "--min-groups",
                "1",
            )

            self.assertEqual(2, process.returncode)
            self.assertIn("output paths must be different", process.stderr)
            self.assertEqual("sentinel", json_path.read_text())

    def test_legacy_format_and_output_still_prints_and_writes(self):
        capture = b"".join(
            [
                make_record(70.0, tx=0, rx=0),
                make_record(70.2, tx=0, rx=1, last=True),
                make_record(71.0, tx=0, rx=0),
                make_record(71.2, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            output_path = Path(tmp) / "quality.json"
            path.write_bytes(capture)
            process = run_checker(
                path,
                "--format",
                "json",
                "--output",
                str(output_path),
                "--min-groups",
                "2",
            )

            self.assertEqual(0, process.returncode, process.stderr)
            self.assertEqual(process.stdout, output_path.read_text())

    def test_format_none_rejects_the_legacy_output_option(self):
        capture = b"".join(
            [
                make_record(80.0, tx=0, rx=0),
                make_record(80.2, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.bin"
            path.write_bytes(capture)
            process = run_checker(
                path,
                "--format",
                "none",
                "--output",
                str(Path(tmp) / "ambiguous-output"),
            )

            self.assertEqual(2, process.returncode)
            self.assertIn("--output requires", process.stderr)

    def test_warning_exit_still_writes_both_reports(self):
        complete = b"".join(
            [
                make_record(90.0, tx=0, rx=0),
                make_record(90.2, tx=0, rx=1, last=True),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "partial.bin"
            json_path = Path(tmp) / "quality.json"
            markdown_path = Path(tmp) / "quality.md"
            path.write_bytes(complete + b"\x01\x02")
            process = run_checker(
                path,
                "--format",
                "none",
                "--json-output",
                str(json_path),
                "--markdown-output",
                str(markdown_path),
                "--min-groups",
                "1",
            )

            self.assertEqual(1, process.returncode, process.stderr)
            report = json.loads(json_path.read_text())
            self.assertEqual("warn", report["result"]["quality"]["status"])
            self.assertIn("Verdict: **WARN**", markdown_path.read_text())


if __name__ == "__main__":
    unittest.main()
