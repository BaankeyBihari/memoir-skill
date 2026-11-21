"""Installer tests for scripts/install.sh. Run: python3 scripts/test_install.py"""
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import tomllib
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("install.sh")
REPO_ROOT = SCRIPT.resolve().parent.parent


def expected_ui_asset() -> str:
    os_name = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        arch = "arm64"
    elif machine in ("x86_64", "amd64"):
        arch = "amd64"
    else:
        arch = "unknown"
    return f"memoir-ui-{os_name}-{arch}"


def build_mock_release(release_dir: Path, ui_bytes: bytes = b"binary", tamper_sums: bool = False) -> None:
    release_dir.mkdir(parents=True, exist_ok=True)
    skills_tar = release_dir / "memoir-skills.tar.gz"
    with tarfile.open(skills_tar, "w:gz") as tf:
        for name in ("memoir", "memoir-wiki"):
            tf.add(REPO_ROOT / "skills" / name, arcname=name)

    asset_name = expected_ui_asset()
    ui_file = release_dir / asset_name
    ui_file.write_bytes(ui_bytes)

    sums = []
    for fname in ("memoir-skills.tar.gz", asset_name):
        digest = hashlib.sha256((release_dir / fname).read_bytes()).hexdigest()
        if tamper_sums and fname == asset_name:
            digest = "0" * 64
        sums.append(f"{digest}  {fname}")
    (release_dir / "SHA256SUMS").write_text("\n".join(sums) + "\n")


def write_mock_curl(bin_dir: Path, fixture_dir: Path, expected_prefix: str) -> None:
    curl = bin_dir / "curl"
    curl.write_text(
        "#!/usr/bin/env python3\n"
        "import shutil, sys\n"
        "url = sys.argv[2]\n"
        "dest = sys.argv[4]\n"
        f"prefix = {expected_prefix!r}\n"
        "if not url.startswith(prefix):\n"
        "    sys.exit(22)\n"
        "name = url[len(prefix):]\n"
        f"src = {str(fixture_dir)!r} + '/' + name\n"
        "try:\n"
        "    shutil.copyfile(src, dest)\n"
        "except FileNotFoundError:\n"
        "    sys.exit(22)\n"
    )
    curl.chmod(0o755)


class TestInstaller(unittest.TestCase):
    def test_repeat_install_local_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            env = {**os.environ, "HOME": str(home), "MEMOIR_STORE": ""}
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
            self.assertTrue((parents[0] / "memoir-wiki/references/schema.md").is_file())
            self.assertTrue((store / "standalone").is_dir())
            self.assertFalse((home / ".local/bin").exists())

    def test_cli_configs_created_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            (home / ".claude").mkdir(parents=True)
            (home / ".codex").mkdir(parents=True)
            (home / ".gemini/antigravity-cli").mkdir(parents=True)
            (home / ".pi/agent").mkdir(parents=True)
            (home / ".pi/agent/sandbox.json").write_text("{}\n", encoding="utf-8")

            env = {**os.environ, "HOME": str(home), "MEMOIR_STORE": ""}
            for _ in range(2):
                subprocess.run(
                    [str(SCRIPT), "--skills-only"],
                    env=env,
                    check=True,
                )

            default_store = (home / ".memoir").resolve()

            claude_cfg = json.loads((home / ".claude/settings.json").read_text(encoding="utf-8"))
            self.assertEqual(claude_cfg["permissions"]["additionalDirectories"], ["~/.memoir"])
            self.assertEqual(claude_cfg["sandbox"]["filesystem"]["allowWrite"], ["~/.memoir"])
            self.assertNotIn("enabled", claude_cfg["sandbox"])

            codex_cfg = tomllib.loads((home / ".codex/config.toml").read_text(encoding="utf-8"))
            self.assertEqual(
                codex_cfg["sandbox_workspace_write"]["writable_roots"],
                [default_store.as_posix()],
            )

            agy_path = home / ".gemini/antigravity-cli/settings.json"
            agy_cfg = json.loads(agy_path.read_text(encoding="utf-8"))
            self.assertEqual(
                agy_cfg["permissions"]["allow"],
                [f"write_file({default_store.as_posix()})"],
            )
            self.assertEqual(stat.S_IMODE(agy_path.stat().st_mode), 0o600)

            pi_cfg = json.loads((home / ".pi/agent/sandbox.json").read_text(encoding="utf-8"))
            self.assertEqual(pi_cfg["allowWrite"], [default_store.as_posix()])

    def test_cli_configs_preserve_existing_and_custom_external_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            external_store = (tmp_path / "external-memoir").resolve()
            (home / ".claude").mkdir(parents=True)
            (home / ".codex").mkdir(parents=True)
            (home / ".gemini/antigravity-cli").mkdir(parents=True)
            (home / ".pi/agent").mkdir(parents=True)

            (home / ".claude/settings.json").write_text(
                json.dumps(
                    {
                        "permissions": {
                            "additionalDirectories": ["../shared"],
                            "allow": ["Bash(npm test)"],
                        },
                        "sandbox": {
                            "enabled": True,
                            "filesystem": {
                                "allowWrite": ["/tmp/build"],
                                "denyRead": ["~/.aws"],
                            },
                        },
                        "customKey": 42,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            codex_initial = (
                "# Keep top comment\n"
                'model = "gpt-5"\n\n'
                "[sandbox_workspace_write]\n"
                "# Preserve table comment\n"
                "network_access = false\n"
                "writable_roots = [\n"
                '    "/existing/root",\n'
                "]\n\n"
                "[other_section]\n"
                "flag = true\n"
            )
            (home / ".codex/config.toml").write_text(codex_initial, encoding="utf-8")

            (home / ".gemini/antigravity-cli/settings.json").write_text(
                json.dumps(
                    {
                        "agentMode": "accept-edits",
                        "permissions": {
                            "allow": ["command(git status)"],
                            "deny": ["write_file(.git/)"],
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            (home / ".pi/agent/sandbox.json").write_text(
                json.dumps({"allowWrite": ["./src"], "denyWrite": ["./.git"]}, indent=2) + "\n",
                encoding="utf-8",
            )

            env = {**os.environ, "HOME": str(home), "MEMOIR_STORE": ""}
            subprocess.run(
                [str(SCRIPT), "--skills-only", "--store", str(external_store)],
                env=env,
                check=True,
            )

            claude_expected = "//" + external_store.as_posix().lstrip("/")
            claude_cfg = json.loads((home / ".claude/settings.json").read_text(encoding="utf-8"))
            self.assertEqual(claude_cfg["customKey"], 42)
            self.assertEqual(claude_cfg["permissions"]["allow"], ["Bash(npm test)"])
            self.assertEqual(
                claude_cfg["permissions"]["additionalDirectories"],
                ["../shared", claude_expected],
            )
            self.assertTrue(claude_cfg["sandbox"]["enabled"])
            self.assertEqual(claude_cfg["sandbox"]["filesystem"]["denyRead"], ["~/.aws"])
            self.assertEqual(
                claude_cfg["sandbox"]["filesystem"]["allowWrite"],
                ["/tmp/build", claude_expected],
            )

            codex_raw = (home / ".codex/config.toml").read_text(encoding="utf-8")
            self.assertIn("# Keep top comment", codex_raw)
            self.assertIn("# Preserve table comment", codex_raw)
            codex_cfg = tomllib.loads(codex_raw)
            self.assertEqual(codex_cfg["model"], "gpt-5")
            self.assertFalse(codex_cfg["sandbox_workspace_write"]["network_access"])
            self.assertEqual(
                codex_cfg["sandbox_workspace_write"]["writable_roots"],
                ["/existing/root", external_store.as_posix()],
            )
            self.assertTrue(codex_cfg["other_section"]["flag"])

            agy_cfg = json.loads(
                (home / ".gemini/antigravity-cli/settings.json").read_text(encoding="utf-8")
            )
            self.assertEqual(agy_cfg["agentMode"], "accept-edits")
            self.assertEqual(agy_cfg["permissions"]["deny"], ["write_file(.git/)"])
            self.assertEqual(
                agy_cfg["permissions"]["allow"],
                ["command(git status)", f"write_file({external_store.as_posix()})"],
            )

            pi_cfg = json.loads((home / ".pi/agent/sandbox.json").read_text(encoding="utf-8"))
            self.assertEqual(pi_cfg["denyWrite"], ["./.git"])
            self.assertEqual(pi_cfg["allowWrite"], ["./src", external_store.as_posix()])

    def test_cli_configs_skip_absent_and_preserve_malformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            (home / ".claude").mkdir(parents=True)
            (home / ".codex").mkdir(parents=True)
            (home / ".pi/agent/skills").mkdir(parents=True)

            bad_json = "{not valid json"
            bad_toml = "sandbox_workspace_write = [broken\n"
            (home / ".claude/settings.json").write_text(bad_json, encoding="utf-8")
            (home / ".codex/config.toml").write_text(bad_toml, encoding="utf-8")

            env = {**os.environ, "HOME": str(home), "MEMOIR_STORE": ""}
            res = subprocess.run(
                [str(SCRIPT), "--skills-only"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("Warning:", res.stderr)
            self.assertEqual((home / ".claude/settings.json").read_text(encoding="utf-8"), bad_json)
            self.assertEqual((home / ".codex/config.toml").read_text(encoding="utf-8"), bad_toml)
            # Absent ~/.gemini/antigravity-cli and absent ~/.pi/agent/sandbox.json must not be created.
            self.assertFalse((home / ".gemini").exists())
            self.assertFalse((home / ".pi/agent/sandbox.json").exists())
            # Skills themselves still installed cleanly.
            self.assertTrue((home / ".agents/skills/memoir/SKILL.md").is_file())

    def test_ui_only_skips_cli_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            home = tmp_path / "home"
            (home / ".claude").mkdir(parents=True)
            (home / ".codex").mkdir(parents=True)
            release_dir = tmp_path / "release"
            build_mock_release(release_dir, ui_bytes=b"verified-binary")

            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            write_mock_curl(
                bin_dir,
                release_dir,
                "https://github.com/BaankeyBihari/memoir-skill/releases/latest/download/",
            )
            env = {
                **os.environ,
                "HOME": str(home),
                "MEMOIR_STORE": "",
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
            }
            subprocess.run([str(SCRIPT), "--ui-only"], env=env, check=True)
            self.assertEqual((home / ".local/bin/memoir-ui").read_bytes(), b"verified-binary")
            self.assertFalse((home / ".claude/settings.json").exists())
            self.assertFalse((home / ".codex/config.toml").exists())

    def test_unwritable_store_exits_3(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores chmod 0o555")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ro_parent = tmp_path / "readonly"
            ro_parent.mkdir()
            ro_parent.chmod(0o555)
            try:
                res = subprocess.run(
                    [str(SCRIPT), "--skills-only", "--store", str(ro_parent / "memoir")],
                    env={**os.environ, "HOME": str(tmp_path / "home")},
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(res.returncode, 3)
                self.assertIn("No write access", res.stderr)
            finally:
                ro_parent.chmod(0o755)

    def test_remote_release_bundle_and_pinned_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            standalone_script = tmp_path / "install.sh"
            shutil.copy2(SCRIPT, standalone_script)

            release_dir = tmp_path / "release"
            build_mock_release(release_dir, ui_bytes=b"ui-2026.11.1")

            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            write_mock_curl(
                bin_dir,
                release_dir,
                "https://github.com/BaankeyBihari/memoir-skill/releases/download/2026.11.1/",
            )

            home = tmp_path / "home"
            home.mkdir()
            env = {
                **os.environ,
                "HOME": str(home),
                "MEMOIR_STORE": "",
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
            }
            subprocess.run(
                [str(standalone_script), "--version", "2026.11.1"],
                env=env,
                check=True,
            )
            self.assertTrue((home / ".agents/skills/memoir/SKILL.md").is_file())
            self.assertTrue((home / ".agents/skills/memoir-wiki/SKILL.md").is_file())
            self.assertEqual((home / ".local/bin/memoir-ui").read_bytes(), b"ui-2026.11.1")

    def test_ui_only_with_checksum_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            release_dir = tmp_path / "release"
            build_mock_release(release_dir, ui_bytes=b"verified-binary")

            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            write_mock_curl(
                bin_dir,
                release_dir,
                "https://github.com/BaankeyBihari/memoir-skill/releases/latest/download/",
            )
            env = {
                **os.environ,
                "HOME": str(tmp_path),
                "MEMOIR_STORE": "",
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
            }
            subprocess.run([str(SCRIPT), "--ui-only"], env=env, check=True)
            self.assertEqual((tmp_path / ".local/bin/memoir-ui").read_bytes(), b"verified-binary")
            self.assertFalse((tmp_path / ".agents").exists())

    def test_checksum_mismatch_aborts_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            release_dir = tmp_path / "release"
            build_mock_release(release_dir, ui_bytes=b"bad-binary", tamper_sums=True)

            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            write_mock_curl(
                bin_dir,
                release_dir,
                "https://github.com/BaankeyBihari/memoir-skill/releases/latest/download/",
            )
            home = tmp_path / "home"
            home.mkdir()
            env = {
                **os.environ,
                "HOME": str(home),
                "MEMOIR_STORE": "",
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
            }
            res = subprocess.run(
                [str(SCRIPT), "--ui-only"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("Checksum mismatch", res.stderr)
            self.assertFalse((home / ".local/bin/memoir-ui").exists())

    def test_invalid_version_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = subprocess.run(
                [str(SCRIPT), "--version", "v1.0.0"],
                env={**os.environ, "HOME": tmp},
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 2)

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
                "MEMOIR_STORE": "",
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
            }
            subprocess.run([str(SCRIPT), "--ui-only"], env=env, check=True)
            self.assertEqual((home / ".local/bin/memoir-ui").read_text(), "built-binary")


if __name__ == "__main__":
    unittest.main()
