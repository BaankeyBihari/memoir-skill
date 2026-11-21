"""Installer tests for scripts/install.sh. Run: python3 scripts/test_install.py"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("install.sh")


class TestInstaller(unittest.TestCase):
    def test_repeat_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            env = {**os.environ, "HOME": str(home)}
            parents = [
                home / p
                for p in (
                    ".claude/skills",
                    ".codex/skills",
                    ".pi/agent/skills",
                    ".gemini/antigravity/skills",
                )
            ]
            for parent in parents:
                parent.mkdir(parents=True)
            store = tmp_path / "custom store"
            for _ in range(2):
                subprocess.run(
                    [str(SCRIPT), "--skills-only", "--store", str(store)],
                    env=env,
                    check=True,
                )
            for parent in parents:
                for name in ("memoir", "memoir-wiki"):
                    self.assertEqual(
                        (parent / name).resolve(),
                        (home / ".agents/skills" / name).resolve(),
                    )
            self.assertTrue((parents[0] / "memoir/scripts/memoir.py").is_file())
            self.assertTrue((store / "standalone").is_dir())
            self.assertFalse((home / ".local/bin").exists())

    def test_ui_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            curl = tmp_path / "curl"
            curl.write_text('#!/bin/sh\nprintf "%s" binary > "$4"\n')
            curl.chmod(0o755)
            env = {
                **os.environ,
                "HOME": str(tmp_path),
                "PATH": f"{tmp_path}:{os.environ['PATH']}",
            }
            subprocess.run([str(SCRIPT), "--ui-only"], env=env, check=True)
            self.assertEqual((tmp_path / ".local/bin/memoir-ui").read_text(), "binary")
            self.assertFalse((tmp_path / ".agents").exists())

    def test_local_go_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            curl = bin_dir / "curl"
            curl.write_text("#!/bin/sh\nexit 22\n")
            curl.chmod(0o755)
            go = bin_dir / "go"
            go.write_text(
                '#!/bin/sh\nset -e\ntest -f go.mod\nprintf "%s" built-binary > "$GOBIN/memoir-ui"\n'
            )
            go.chmod(0o755)
            home = tmp_path / "home"
            home.mkdir()
            env = {
                **os.environ,
                "HOME": str(home),
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
            }
            subprocess.run([str(SCRIPT), "--ui-only"], env=env, check=True)
            self.assertEqual(
                (home / ".local/bin/memoir-ui").read_text(),
                "built-binary",
            )


if __name__ == "__main__":
    unittest.main()
