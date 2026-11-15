"""CLI helpers: executables are resolved through shutil.which so Windows (npm.cmd) works."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import manage  # noqa: E402


def test_exe_resolves_through_shutil_which(monkeypatch):
    monkeypatch.setattr(manage.shutil, "which", lambda t: r"C:\Program Files\nodejs\npm.cmd" if t == "npm" else None)
    assert manage._exe("npm") == r"C:\Program Files\nodejs\npm.cmd"
    assert manage._exe("not-installed") == "not-installed"             # bare name when it is not on PATH


def test_run_starts_the_resolved_executable(monkeypatch):
    calls = []

    class Done:
        returncode = 0

    monkeypatch.setattr(manage.shutil, "which", lambda t: f"/resolved/{t}")
    monkeypatch.setattr(manage.subprocess, "run", lambda args, **kw: calls.append(args) or Done())
    manage._run("npm", "run", "build")
    assert calls == [["/resolved/npm", "run", "build"]]


def test_require_uses_shutil_which_not_the_unix_which(monkeypatch):
    seen = []
    monkeypatch.setattr(manage.shutil, "which", lambda t: seen.append(t) or "/x")
    monkeypatch.setattr(manage.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run `which`")))
    manage._require("npm", "install node")                              # does not raise nor spawn a process
    assert seen == ["npm"]
