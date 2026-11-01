import hashlib
import importlib.util
import io
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "package_release.py"


def load_packager():
    spec = importlib.util.spec_from_file_location("package_release", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackageReleaseTests(unittest.TestCase):
    def make_source(self, root):
        (root / "scripts").mkdir(parents=True)
        (root / "README.md").write_text("toolkit\n", encoding="utf-8")
        (root / "scripts" / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (root / "scripts" / "run.sh").chmod(0o755)
        (root / ".git").mkdir()
        (root / ".git" / "config").write_text("private\n", encoding="utf-8")
        (root / "__pycache__").mkdir()
        (root / "__pycache__" / "cache.pyc").write_bytes(b"cache")
        (root / ".DS_Store").write_bytes(b"metadata")
        (root / "dist").mkdir()
        (root / "dist" / "old.tar.gz").write_bytes(b"old")

    def test_archive_has_stable_root_permissions_and_exclusions(self):
        packager = load_packager()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            self.make_source(source)

            archive_path, checksum_path, digest = packager.build_release(
                source,
                root / "output",
                version="0.1.3",
                epoch=1_793_563_200,
            )

            with tarfile.open(archive_path, "r:gz") as archive:
                members = {member.name: member for member in archive.getmembers()}
                readme = archive.extractfile("router-csi-toolkit/README.md").read()

            self.assertEqual(readme, b"toolkit\n")
            self.assertIn("router-csi-toolkit/scripts/run.sh", members)
            self.assertNotIn("router-csi-toolkit/.git/config", members)
            self.assertNotIn("router-csi-toolkit/__pycache__/cache.pyc", members)
            self.assertNotIn("router-csi-toolkit/.DS_Store", members)
            self.assertNotIn("router-csi-toolkit/dist/old.tar.gz", members)
            self.assertEqual(members["router-csi-toolkit/README.md"].mode, 0o644)
            self.assertEqual(members["router-csi-toolkit/scripts/run.sh"].mode, 0o755)
            self.assertTrue(
                all(member.mtime == 1_793_563_200 for member in members.values())
            )
            self.assertEqual(
                checksum_path.read_text(encoding="utf-8"),
                f"{digest}  {archive_path.name}\n",
            )
            self.assertEqual(
                digest,
                hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            )

    def test_archive_bytes_are_reproducible_across_output_directories(self):
        packager = load_packager()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            self.make_source(source)

            first, _, first_digest = packager.build_release(
                source,
                root / "first",
                version="0.1.3",
                epoch=1_793_563_200,
            )
            second, _, second_digest = packager.build_release(
                source,
                root / "second",
                version="0.1.3",
                epoch=1_793_563_200,
            )

            self.assertEqual(first_digest, second_digest)
            self.assertEqual(first.read_bytes(), second.read_bytes())


if __name__ == "__main__":
    unittest.main()
