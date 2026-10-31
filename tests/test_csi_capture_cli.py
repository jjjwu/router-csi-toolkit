#!/usr/bin/env python3
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "scripts" / "csi_capture.py"
HEADER = struct.Struct("<I6sbBBBBBHHHH")
RECORD = struct.Struct("<dH")


class CaptureCliTest(unittest.TestCase):
    def test_default_port_receives_the_documented_udp_port(self):
        payload = HEADER.pack(1, bytes.fromhex("020000000001"), -40, 50, 80, 44, 0, 0, 64, 1, 0, 0x8000)

        with tempfile.TemporaryDirectory() as tmp:
            outfile = Path(tmp) / "capture.bin"
            process = subprocess.Popen(
                [sys.executable, str(CAPTURE), str(outfile), "--seconds", "0.6"],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    deadline = time.time() + 0.45
                    while time.time() < deadline:
                        udp.sendto(payload, ("127.0.0.1", 8888))
                        time.sleep(0.03)
                finally:
                    udp.close()
                stdout, stderr = process.communicate(timeout=3)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

            self.assertEqual(0, process.returncode, stdout + stderr)
            data = outfile.read_bytes()
            self.assertGreaterEqual(len(data), RECORD.size + HEADER.size)
            _, length = RECORD.unpack_from(data)
            self.assertEqual(HEADER.size, length)


if __name__ == "__main__":
    unittest.main()
