"""On-demand Python 3.11+ compatibility matrix. Run: mise run test:compat"""

import re
import shutil
import subprocess

import nox

nox.options.default_venv_backend = "uv"
nox.options.reuse_existing_virtualenvs = True
nox.options.sessions = ["compat"]

FALLBACK_PYTHONS = ["3.11", "3.12", "3.13", "3.14", "3.15"]


def discover_python_versions() -> list[str]:
    uv_bin = shutil.which("uv")
    if not uv_bin:
        return FALLBACK_PYTHONS
    try:
        out = subprocess.run(
            [uv_bin, "python", "list"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return FALLBACK_PYTHONS

    minors: set[int] = set()
    for line in out.splitlines():
        m = re.match(r"^cpython-3\.(\d+)\.\d+-", line.strip())
        if m:
            minor = int(m.group(1))
            if minor >= 11:
                minors.add(minor)
    if not minors:
        return FALLBACK_PYTHONS
    return [f"3.{minor}" for minor in sorted(minors)]


PYTHON_VERSIONS = discover_python_versions()


@nox.session(python=PYTHON_VERSIONS)
def compat(session: nox.Session) -> None:
    """Verify zero-dependency CLI and installer suites on Python 3.11 through latest stable."""
    session.run(
        "python3",
        "-c",
        f"import sys; v = f'{{sys.version_info.major}}.{{sys.version_info.minor}}'; "
        f"assert v == {session.python!r}, f'expected {session.python}, got {{v}}'",
    )
    session.run("python3", "test_memoir.py")
    session.run("python3", "scripts/test_install.py")
