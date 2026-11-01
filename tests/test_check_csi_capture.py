#!/usr/bin/env python3
import json
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


def run_checker(capture, *args):
    return subprocess.run(
        [sys.executable, str(CHECKER), str(capture), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


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


if __name__ == "__main__":
    unittest.main()
