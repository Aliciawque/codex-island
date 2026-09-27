import io
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import threading
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
        self.fake_bin = fake_bin
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

    def test_transient_download_failure_is_retried_within_one_run(self):
        count = self.root / "curl-count"
        (self.fake_bin / "curl").write_text(
            '#!/bin/sh\n'
            'test "$1" = -fsSL && test "$2" = -o || exit 90\n'
            'n=$(cat "$FIXTURE_COUNT" 2>/dev/null || echo 0)\n'
            'n=$((n + 1))\n'
            'printf "%s" "$n" > "$FIXTURE_COUNT"\n'
            'printf "download\\n" >> "$FIXTURE_DOWNLOADS"\n'
            'if [ "$n" -lt 3 ]; then exit 22; fi\n'
            'cp "$FIXTURE_ARCHIVE" "$3"\n', encoding="utf-8")
        env = dict(self.env, FIXTURE_COUNT=str(count))
        result = subprocess.run(["/bin/bash", str(self.root / "scripts/setup-sparkle.sh")],
                                env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_installed()
        self.assertEqual(count.read_text(encoding="utf-8"), "3")

    def test_verified_legacy_cache_is_adopted_without_downloading(self):
        (self.dest / "Sparkle.framework").mkdir(parents=True)
        (self.dest / "Sparkle.framework/Sparkle").write_bytes(b"legacy framework")
        bin_dir = self.dest / "bin"
        bin_dir.mkdir()
        sign_update = bin_dir / "sign_update"
        sign_update.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        sign_update.chmod(0o755)
        self.archive.unlink()
        result = self.setup_sparkle()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.dest / ".version").read_text(encoding="utf-8").strip(), "2.9.1")
        self.assertEqual((self.dest / "Sparkle.framework/Sparkle").read_bytes(), b"legacy framework")
        self.assertFalse(self.downloads.exists())

    def test_concurrent_runs_are_serialized(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.setup_sparkle()))
                   for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_installed()


if __name__ == "__main__":
    unittest.main()
