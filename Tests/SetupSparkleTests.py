import io
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest


class SetupSparkleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sparkle-setup-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        shutil.copyfile(Path(__file__).resolve().parents[1] / "scripts/setup-sparkle.sh",
                        self.root / "scripts/setup-sparkle.sh")
        self.dest = self.root / "Vendor/Sparkle"
        self.archive = self.root / "fixture.tar.xz"
        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode="w") as archive:
            for name, content in [("Sparkle.framework/Sparkle", b"fixture framework"),
                                  ("bin/sign_update", b"#!/bin/sh\nexit 0\n")]:
                entry = tarfile.TarInfo(name)
                entry.mode = 0o755
                entry.size = len(content)
                archive.addfile(entry, io.BytesIO(content))
        self.valid_archive = lzma.compress(archive_bytes.getvalue())
        self.archive.write_bytes(self.valid_archive)
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        curl = fake_bin / "curl"
        curl.write_text('#!/bin/sh\n'
                        'test "$1" = -fsSL && test "$2" = -o || exit 90\n'
                        'printf "download\\n" >> "$FIXTURE_DOWNLOADS"\n'
                        'cp "$FIXTURE_ARCHIVE" "$3"\n', encoding="utf-8")
        curl.chmod(0o755)
        self.downloads = self.root / "downloads"
        self.env = {"PATH": str(fake_bin) + os.pathsep + os.defpath,
                    "HOME": str(self.root), "TMPDIR": str(self.root), "LC_ALL": "C",
                    "FIXTURE_ARCHIVE": str(self.archive),
                    "FIXTURE_DOWNLOADS": str(self.downloads)}

    def setup_sparkle(self):
        return subprocess.run(["/bin/bash", str(self.root / "scripts/setup-sparkle.sh")],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def assert_installed(self):
        self.assertEqual((self.dest / "Sparkle.framework/Sparkle").read_bytes(), b"fixture framework")
        self.assertTrue(os.access(self.dest / "bin/sign_update", os.X_OK))

    def test_complete_install_is_reused_without_downloading(self):
        first = self.setup_sparkle()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assert_installed()
        self.archive.unlink()
        cached = self.setup_sparkle()
        self.assertEqual(cached.returncode, 0, cached.stderr)
        self.assertEqual(self.downloads.read_text(encoding="utf-8").splitlines(), ["download"])

    def test_failed_extraction_does_not_poison_retry(self):
        self.archive.write_bytes(self.valid_archive[:-16])
        failed = self.setup_sparkle()
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse((self.dest / "Sparkle.framework").exists())
        self.archive.write_bytes(self.valid_archive)
        retried = self.setup_sparkle()
        self.assertEqual(retried.returncode, 0, retried.stderr)
        self.assert_installed()

    def test_partial_cache_from_an_earlier_run_is_replaced(self):
        (self.dest / "Sparkle.framework").mkdir(parents=True)
        stale = self.dest / "stale-file"
        stale.write_text("unfinished extraction", encoding="utf-8")
        result = self.setup_sparkle()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_installed()
        self.assertFalse(stale.exists())


if __name__ == "__main__":
    unittest.main()
