#!/usr/bin/env python3
"""Export an anonymized snapshot of this repo for double-blind review.

Pulls a clean tree straight from git (no .git/, no commit history, no
author metadata -- via `git archive`) and applies a literal, case-sensitive
find/replace map (scripts/anonymize_repo.config.json) to strip author names,
emails, this repo's own GitHub URLs, project branding, and funding/grant
identifiers from every text file. Genuinely external third-party
dependencies (fastapi, pandas, ...) are left alone by construction -- the
replacement map only ever targets this project's own identity, never
generic package names -- and anything that still needs protecting from an
overly broad rule can be listed in "protected_substrings", verified intact
before finishing.

This script and its own config are excluded from the snapshot outright
(`exclude_paths`), rather than relying on the substitution pass to redact
its own rule definitions when it encounters itself as one more file in the
tree -- config.json's real values are literal JSON data there, not prose,
and self-redaction is order-dependent and not guaranteed. As a final safety
net, `verify_no_leaks()` hard-fails the whole run (non-zero exit, no zip
produced) if any of the redaction map's real values are found anywhere in
the output regardless.

The replacement list can only ever narrow what it matches (longer, more
specific strings), never widen it, so it cannot be "smart" about phrasing it
has never seen. Treat its output as a strong first pass, not a guarantee:
always read scripts/anonymize_repo.config.json to see exactly what it looks
for, and always check the report printed at the end (also saved to
<output>.report.txt) before submitting anything.

Sibling WildINTEL repos depended on via a real git URL (e.g.
wildintel-trapper-sdk in pyproject.toml's [tool.uv.sources]) aren't "third
party" the way fastapi/pandas are -- that URL reveals the org just as much
as anything else -- but can't just be text-substituted like a doc mention,
since the dependency has to actually resolve. `--vendor NAME=SOURCE[#REF]`
exports and anonymizes a real (redacted) copy of it too, under vendor/, and
the main config's replacement rules rewrite [tool.uv.sources] to a local
path pointing at it; uv.lock is then regenerated against the vendored copy.

Two more artifacts can optionally be produced from the anonymized snapshot:

  --pdf                  Render the anonymized docs to a single PDF manual
                          (same `mkdocs`/WeasyPrint pipeline as a real release).
  --packages-repo O/R     Push the snapshot to a private scratch GitHub repo
                          (O/R = owner/name; must already carry this repo's own
                          .github/workflows/, which the snapshot does by
                          default), tag it, and wait for its Release workflow
                          to build .deb/.rpm/.AppImage/.exe/.dmg, then download
                          them. --packages-create creates O/R (private) first
                          if it doesn't exist yet. This is NOT the anonymous
                          code link submitted to a venue -- see "Submitting
                          it" in docs/_snippets/anonymize-repo.md -- it's
                          throwaway CI compute under an account you control.

--bundle turns --output from "the snapshot itself" into a single directory
containing snapshot/ (+ .zip/.report.txt), manual.pdf (if --pdf), packages/
(if --packages-repo), and an auto-generated README.md explaining it all.

Usage:
    python scripts/anonymize_repo.py --output /path/to/anon-snapshot
    python scripts/anonymize_repo.py --ref main --output ../anon-snapshot --zip
    python scripts/anonymize_repo.py --source https://github.com/org/repo.git \\
        --ref main --output /tmp/anon-snapshot
    python scripts/anonymize_repo.py --output ../anon-snapshot \\
        --vendor wildintel-trapper-sdk=../wildintel-trapper-sdk#v0.1.0
    python scripts/anonymize_repo.py --ref v0.4.2 --output ../anon-bundle-v0.4.2 \\
        --vendor wildintel-trapper-sdk=../wildintel-trapper-sdk#v0.1.0 \\
        --pdf --packages-repo yourname/anon-ci-build-tmp --bundle
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "anonymize_repo.config.json"


def run(cmd: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout.strip()


def resolve_local_repo_root(source: str) -> Path:
    return Path(run(["git", "-C", source, "rev-parse", "--show-toplevel"]))


def export_snapshot(source: str, ref: str, dest: Path) -> Path:
    """Extract a clean working tree for `ref` into `dest`, no .git/ included."""
    dest.mkdir(parents=True, exist_ok=True)
    is_url = source.startswith(("http://", "https://", "git@", "ssh://"))
    if is_url:
        with tempfile.TemporaryDirectory() as tmp:
            clone_dir = Path(tmp) / "clone"
            print(f"Cloning {source} ...")
            run(["git", "clone", "--quiet", source, str(clone_dir)])
            run(["git", "-C", str(clone_dir), "archive", "--format=tar", ref, "-o", str(Path(tmp) / "snap.tar")])
            run(["tar", "-xf", str(Path(tmp) / "snap.tar"), "-C", str(dest)])
    else:
        repo_root = resolve_local_repo_root(source)
        with tempfile.TemporaryDirectory() as tmp:
            tar_path = Path(tmp) / "snap.tar"
            run(["git", "-C", str(repo_root), "archive", "--format=tar", ref, "-o", str(tar_path)])
            run(["tar", "-xf", str(tar_path), "-C", str(dest)])
        return repo_root
    return Path(source)


def load_config() -> dict:
    config = json.loads(CONFIG_PATH.read_text())
    config["replacements"] = [r for r in config["replacements"] if "old" in r]
    return config


def is_probably_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def exclude_paths(root: Path, paths: list[str]) -> list[str]:
    """Delete files that must never ship inside the snapshot -- the
    anonymization tooling itself, whose config contains the real identity
    (org/repo URL, etc.) as literal data, not prose. Relying on the
    substitution pass to redact its own rule definitions when it encounters
    them as one more file in the tree is fragile (order-dependent, breaks
    silently if a rule is ever added that doesn't happen to self-match) --
    deleting them outright removes the whole risk class instead.
    """
    removed = []
    for rel in paths:
        p = root / rel
        if p.exists():
            p.unlink()
            removed.append(rel)
            parent = p.parent
            if parent != root and not any(parent.iterdir()):
                parent.rmdir()
    return removed


def strip_sections(root: Path, specs: list[dict]) -> list[str]:
    """Remove a markdown section (heading line through, but not including,
    the next '## ' heading, or EOF) that documents the anonymization process
    itself -- shipping a description of how/why a copy was anonymized is a
    weaker version of the same leak `exclude_paths` fixes for the tooling.
    """
    stripped = []
    for spec in specs:
        path = root / spec["file"]
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        heading = spec["heading"] + "\n"
        try:
            start = next(i for i, line in enumerate(lines) if line == heading)
        except StopIteration:
            continue
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if lines[i].startswith("## "):
                end = i
                break
        path.write_text("".join(lines[:start] + lines[end:]), encoding="utf-8")
        stripped.append(f"{spec['file']} ({spec['heading']})")
    return stripped


def strip_lines(root: Path, specs: list[dict]) -> list[str]:
    """Remove single lines (e.g. a CHANGELOG bullet) that reference the
    anonymization process by name."""
    stripped = []
    for spec in specs:
        path = root / spec["file"]
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        kept = [line for line in lines if spec["contains"] not in line]
        if len(kept) != len(lines):
            path.write_text("".join(kept), encoding="utf-8")
            stripped.append(f"{spec['file']} (line containing {spec['contains']!r})")
    return stripped


def apply_replacements(root: Path, replacements: list[dict], skip_extensions: set[str]) -> int:
    changed_files = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in skip_extensions:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if is_probably_binary(data):
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue

        original = text
        for rule in replacements:
            if rule["old"] in text:
                text = text.replace(rule["old"], rule["new"])
        if text != original:
            path.write_text(text, encoding="utf-8")
            changed_files += 1
    return changed_files


def build_local_docs(root: Path) -> bool:
    """Build backend/mkdocs.yml into backend/site/ inside the snapshot.

    main.py already mounts backend/site/ at /docs when it exists (and
    vite.config.ts already proxies /docs to the backend in dev mode) -- the
    Help button is repointed at that relative path by the redaction map, so
    this makes it actually resolve to the (now-anonymized) manual instead of
    either the real public docs site or a dead link.
    """
    mkdocs_cfg = root / "backend" / "mkdocs.yml"
    if not mkdocs_cfg.exists():
        return False
    cmd = ["mkdocs", "build", "--config-file", str(mkdocs_cfg)]
    try:
        result = subprocess.run(cmd, cwd=root / "backend", capture_output=True, text=True)
    except FileNotFoundError:
        cmd = [sys.executable, "-m", "mkdocs", "build", "--config-file", str(mkdocs_cfg)]
        result = subprocess.run(cmd, cwd=root / "backend", capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Warning: `mkdocs build` failed, /docs won't be available in the exported app:\n{result.stderr}", file=sys.stderr)
        return False
    return True


def apply_renames(root: Path, renames: list[dict]) -> list[str]:
    applied = []
    for rule in renames:
        src = root / rule["old_path"]
        dst = root / rule["new_path"]
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            applied.append(f"{rule['old_path']} -> {rule['new_path']}")
    return applied


def vendor_dependency(output_root: Path, spec: dict, source: str, ref: str) -> tuple[list[dict], list[str]]:
    """Export `source`@`ref` into output_root/spec['target_path'] and apply
    its own redaction config -- for a sibling WildINTEL repo depended on via
    a real git URL (e.g. wildintel-trapper-sdk), leaving that URL in the
    snapshot would reveal the org just as much as anything else, but it
    can't just be text-substituted like a doc mention: the dependency has to
    actually resolve, so a real (redacted) copy is vendored in and
    pyproject.toml's `[tool.uv.sources]` entry is rewritten to a local path
    by the main config's own replacement rules.

    Returns (replacements, protected_substrings) from the vendor's own
    config, so the caller can fold them into the final verify_no_leaks scan
    of the whole tree.
    """
    target = output_root / spec["target_path"]
    is_url = source.startswith(("http://", "https://", "git@", "ssh://"))
    print(f"Vendoring {spec['dependency_name']} from {source}@{ref} ...")
    local_root = export_snapshot(source, ref, target)

    vendor_config = json.loads((Path(__file__).parent / spec["redaction_config"]).read_text())
    vendor_config["replacements"] = [r for r in vendor_config["replacements"] if "old" in r]
    replacements = list(vendor_config["replacements"])
    if local_root is not None and not is_url:
        replacements = [{"old": str(local_root), "new": "/home/user/project"}] + replacements

    changed = apply_replacements(target, replacements, set(vendor_config["skip_extensions"]))
    print(f"  Rewrote {changed} file(s) in vendored {spec['dependency_name']}.")

    for r in apply_renames(target, vendor_config.get("renames", [])):
        print(f"  Renamed asset: {r}")

    protected = vendor_config.get("protected_substrings", [])
    missing = verify_protected(target, protected)
    if missing:
        print(f"  !! WARNING: protected strings missing in vendored {spec['dependency_name']}: {missing}", file=sys.stderr)

    return replacements, protected


def regenerate_lock(root: Path) -> bool:
    """Rebuild uv.lock (excluded from the snapshot -- see exclude_paths)
    against the now-vendored dependency graph.

    Required, not advisory: a stale or missing lock referencing the old git
    source means `uv sync`/`uv run` fails in the delivered snapshot, which
    defeats the entire point of vendoring rather than just leaving a broken
    dependency -- main() treats a failure here as fatal, same as a leak.
    """
    cmd = ["uv", "lock"]
    try:
        result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    except FileNotFoundError:
        print("`uv` not found on PATH -- cannot regenerate uv.lock.", file=sys.stderr)
        return False
    if result.returncode != 0:
        print(f"`uv lock` failed against the anonymized snapshot:\n{result.stderr}", file=sys.stderr)
        return False
    return True


def patch_dockerfile_for_vendor(root: Path) -> bool:
    """When a dependency was vendored under vendor/ (see vendor_dependency()),
    backend/Dockerfile.build's Linux package build needs that directory copied
    into the Docker build context too -- it only copies pyproject.toml/uv.lock/
    backend/ by default, since the real repo never has a vendor/ directory to
    begin with (the real pyproject.toml points at a git URL, not a local path).

    Patching this unconditionally in the *real* Dockerfile.build would break
    normal, non-anonymized builds -- COPY of a path that doesn't exist in the
    build context is a hard Docker error -- so this only ever touches the
    already-exported snapshot copy, and only when vendoring actually happened.
    """
    dockerfile = root / "backend" / "Dockerfile.build"
    if not dockerfile.exists():
        return False
    text = dockerfile.read_text(encoding="utf-8")
    if "COPY vendor/ ./vendor/" in text:
        return True
    marker = "COPY pyproject.toml uv.lock ./\nCOPY backend/ ./"
    if marker not in text:
        print(
            "Warning: backend/Dockerfile.build doesn't match the expected COPY layout -- "
            "couldn't patch it to include vendor/ in the Linux build context.",
            file=sys.stderr,
        )
        return False
    dockerfile.write_text(
        text.replace(marker, "COPY pyproject.toml uv.lock ./\nCOPY vendor/ ./vendor/\nCOPY backend/ ./"),
        encoding="utf-8",
    )
    return True


def build_pdf(root: Path) -> Path | None:
    """Render root/mkdocs.yml (the combined user + developer manual) to a
    single PDF via WeasyPrint, the same `ENABLE_PDF_EXPORT=1 mkdocs build`
    pipeline `manage.py docs pdf` uses for a real release -- just pointed at
    the already-anonymized docs tree. Returns the built PDF's path, or None
    if the build failed (a warning is printed either way; this never aborts
    the whole run, same as build_local_docs()).
    """
    mkdocs_cfg = root / "mkdocs.yml"
    if not mkdocs_cfg.exists():
        return None
    print("Building anonymized PDF manual (uv sync + mkdocs build) ...")
    sync = subprocess.run(["uv", "sync"], cwd=root, capture_output=True, text=True)
    if sync.returncode != 0:
        print(f"Warning: `uv sync` failed, cannot build the PDF manual:\n{sync.stderr}", file=sys.stderr)
        return None
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env["ENABLE_PDF_EXPORT"] = "1"
    result = subprocess.run(
        ["uv", "run", "mkdocs", "build", "--config-file", "mkdocs.yml"],
        cwd=root, capture_output=True, text=True, env=env,
    )
    if result.returncode != 0:
        print(f"Warning: PDF build failed:\n{result.stderr}", file=sys.stderr)
        return None
    pdf_dir = root / "site" / "pdf"
    candidates = sorted(pdf_dir.glob("*.pdf")) if pdf_dir.exists() else []
    if not candidates:
        print("Warning: PDF build reported success but produced no PDF file.", file=sys.stderr)
        return None
    return candidates[0]


def _run_ok(cmd: list[str], cwd: Path | None = None) -> bool:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Command failed: {' '.join(cmd)}\n{result.stderr}", file=sys.stderr)
        return False
    return True


def _replace_git_worktree(clone_dir: Path, source: Path) -> None:
    """Replace every tracked/untracked file in clone_dir (except .git/) with
    the contents of source -- used to push a fresh anonymized snapshot into
    the scratch packages repo each run, overwriting whatever was there
    before (e.g. a previous version's snapshot)."""
    for item in clone_dir.iterdir():
        if item.name == ".git":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    for item in source.iterdir():
        dst = clone_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dst)
        else:
            shutil.copy2(item, dst)


def _ensure_packages_repo(repo: str, create: bool) -> bool:
    exists = subprocess.run(["gh", "repo", "view", repo], capture_output=True, text=True).returncode == 0
    if exists:
        return True
    if not create:
        print(f"Error: {repo} does not exist and --packages-create was not given.", file=sys.stderr)
        return False
    print(f"Creating private scratch repo {repo} ...")
    return _run_ok(["gh", "repo", "create", repo, "--private", "--description", "temp build"])


def _find_release_run(repo: str, tag: str, timeout_s: int = 120) -> str | None:
    """Poll `gh run list` for the Release workflow run triggered by pushing
    `tag` -- GitHub Actions can take a few seconds to register a run after
    the push lands, so this retries instead of checking just once."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["gh", "run", "list", "--repo", repo, "--workflow", "release.yml",
             "--branch", tag, "--limit", "1", "--json", "databaseId"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout or "[]")
            if data:
                return str(data[0]["databaseId"])
        time.sleep(5)
    return None


def build_packages(root: Path, repo: str, tag: str, create: bool) -> Path | None:
    """Push the anonymized snapshot at `root` (which already carries this
    repo's own `.github/workflows/` -- release.yml included -- redacted like
    everything else) to `repo`'s `development` branch, tag it `tag`, and wait
    for the Release workflow to build .deb/.rpm/.AppImage/.exe/.dmg and
    publish them as GitHub Release assets. Downloads those assets to a fresh
    temp directory and returns its path, or None if any step failed.

    `repo` (OWNER/NAME) must be a private, throwaway scratch repo under an
    account you control, used purely as free GitHub Actions compute -- it is
    NOT the anonymous code link submitted to a venue, which has its own,
    stricter "brand new identity-less account" requirement (see the
    "Submitting it" section of docs/_snippets/anonymize-repo.md). This
    function only ever creates a *private* repo and never touches that real
    submission link.
    """
    if not _ensure_packages_repo(repo, create):
        return None

    print(f"Pushing anonymized snapshot to {repo} (branch development, tag {tag}) ...")
    with tempfile.TemporaryDirectory() as tmp:
        clone_dir = Path(tmp) / "clone"
        if not _run_ok(["gh", "repo", "clone", repo, str(clone_dir)]):
            return None
        run(["git", "-C", str(clone_dir), "config", "user.name", "anonymize_repo.py"])
        run(["git", "-C", str(clone_dir), "config", "user.email", "actions@users.noreply.github.com"])
        run(["git", "-C", str(clone_dir), "checkout", "-B", "development"])

        _replace_git_worktree(clone_dir, root)

        run(["git", "-C", str(clone_dir), "add", "-A"])
        status = run(["git", "-C", str(clone_dir), "status", "--porcelain"])
        if status:
            if not _run_ok(
                ["git", "-C", str(clone_dir), "commit", "-m",
                 "Anonymized snapshot for CI build (temporary, to be deleted)"]
            ):
                return None
        if not _run_ok(["git", "-C", str(clone_dir), "push", "-f", "origin", "development"]):
            return None
        run(["git", "-C", str(clone_dir), "tag", "-f", tag])
        if not _run_ok(["git", "-C", str(clone_dir), "push", "origin", tag, "--force"]):
            return None

    print(f"Pushed. Waiting for the Release workflow on tag {tag} to start ...")
    run_id = _find_release_run(repo, tag)
    if run_id is None:
        print(f"Error: no Release run for tag {tag} appeared on {repo} within the timeout.", file=sys.stderr)
        return None

    print(f"Building packages (run {run_id}) -- this typically takes several minutes ...")
    watch = subprocess.run(
        ["gh", "run", "watch", run_id, "--repo", repo, "--interval", "20", "--exit-status"],
        capture_output=True, text=True,
    )
    if watch.returncode != 0:
        print(
            f"Error: the Release run failed. See https://github.com/{repo}/actions/runs/{run_id}\n{watch.stdout}",
            file=sys.stderr,
        )
        return None

    packages_dir = Path(tempfile.mkdtemp(prefix="anon-packages-"))
    if not _run_ok(["gh", "release", "download", tag, "--repo", repo, "--dir", str(packages_dir), "--clobber"]):
        return None
    return packages_dir


def generate_readme(ref: str, has_pdf: bool, has_packages: bool) -> str:
    lines = [
        f"# Anonymized snapshot — {ref}",
        "",
        "Contents of this directory, generated by `scripts/anonymize_repo.py` for",
        "double-blind review.",
        "",
        "## Contents",
        "",
        "- **`snapshot/`** (+ `snapshot.zip`, `snapshot.report.txt`)",
        "  The anonymized source tree: full codebase, docs, and any vendored",
        "  dependency under `snapshot/vendor/` (also redacted) instead of a real",
        "  git URL. No git history, no author metadata -- exported via `git archive`.",
        "  `snapshot.report.txt` lists every string the tool's own scan flagged as",
        "  a possible leftover -- read it before submitting anything.",
    ]
    if has_pdf:
        lines += [
            "",
            "- **`manual.pdf`**",
            "  User + developer documentation, rendered from the anonymized docs tree.",
        ]
    if has_packages:
        lines += [
            "",
            "- **`packages/`**",
            "  Built, installable packages (.deb/.rpm/.AppImage/.exe/.dmg) compiled",
            "  from the anonymized source tree above.",
        ]
    lines += [
        "",
        "**This is a strong first pass, not a guarantee.** Read `snapshot.report.txt`",
        "and skim the source diff against the real repository before submitting",
        "anything for review.",
        "",
    ]
    return "\n".join(lines)


def assemble_bundle(
    output: Path,
    zip_path: Path | None,
    report_path: Path,
    pdf_path: Path | None,
    packages_dir: Path | None,
    ref: str,
) -> None:
    """Reorganize everything this run produced into a single directory at
    `output`: output/snapshot/ (+ .zip/.report.txt siblings renamed to match),
    output/manual.pdf, output/packages/, output/README.md. `output` currently
    *is* the exported snapshot tree; this moves it aside into a temp bundle
    directory being assembled, then swaps that into place at `output`.
    """
    bundle_tmp = Path(tempfile.mkdtemp(prefix="anon-bundle-", dir=str(output.parent)))
    shutil.move(str(output), str(bundle_tmp / "snapshot"))
    if zip_path is not None and zip_path.exists():
        shutil.move(str(zip_path), str(bundle_tmp / "snapshot.zip"))
    if report_path.exists():
        shutil.move(str(report_path), str(bundle_tmp / "snapshot.report.txt"))
    if pdf_path is not None:
        shutil.move(str(pdf_path), str(bundle_tmp / "manual.pdf"))
    if packages_dir is not None:
        shutil.move(str(packages_dir), str(bundle_tmp / "packages"))
    (bundle_tmp / "README.md").write_text(
        generate_readme(ref, pdf_path is not None, packages_dir is not None), encoding="utf-8"
    )
    shutil.move(str(bundle_tmp), str(output))


def verify_protected(root: Path, protected_substrings: list[str]) -> list[str]:
    """Return the list of protected strings that did NOT survive -- should be empty."""
    missing = []
    for needle in protected_substrings:
        found = False
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if is_probably_binary(data):
                continue
            if needle.encode("utf-8") in data:
                found = True
                break
        if not found:
            missing.append(needle)
    return missing


def verify_no_leaks(root: Path, replacements: list[dict], protected_substrings: list[str]) -> list[tuple[str, str]]:
    """Hard gate: none of the redaction map's own `old` (real) values should
    survive anywhere in the final tree -- e.g. because a file containing them
    verbatim (not just in prose) was missed by exclude_paths/strip_sections,
    the actual leak this whole safety net exists for. protected_substrings
    are exempt: those are third-party dependency references that are
    *supposed* to survive untouched.

    Returns a list of (old_value, file) for every leak found -- empty means
    clean. Unlike verify_protected (soft, printed as a warning),
    main() treats a non-empty result here as a hard failure.
    """
    leaks = []
    for rule in replacements:
        needle = rule["old"]
        if not needle or needle in protected_substrings:
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if is_probably_binary(data):
                continue
            if needle.encode("utf-8") in data:
                leaks.append((needle, str(path.relative_to(root))))
    return leaks


def scan_report(root: Path, patterns: list[str]) -> list[tuple[str, int, str, str]]:
    compiled = [re.compile(p) for p in patterns]
    hits = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if is_probably_binary(data):
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for regex in compiled:
                m = regex.search(line)
                if m:
                    hits.append((str(path.relative_to(root)), lineno, regex.pattern, line.strip()[:160]))
    return hits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=".", help="Local repo path or git URL to export from (default: current repo)")
    parser.add_argument("--ref", default="HEAD", help="Branch/tag/commit to export (default: HEAD)")
    parser.add_argument("--output", required=True, help="Destination directory for the anonymized snapshot")
    parser.add_argument("--zip", action="store_true", help="Also produce <output>.zip")
    parser.add_argument("--force", action="store_true", help="Overwrite --output if it already exists and is non-empty")
    parser.add_argument(
        "--vendor", action="append", default=[], metavar="NAME=SOURCE[#REF]",
        help="Vendor a dependency locally (repeatable) instead of leaving its real git URL in "
             "the snapshot. NAME must match a 'dependency_name' in the config's "
             "vendor_dependencies. REF defaults to HEAD. "
             "Example: --vendor wildintel-trapper-sdk=../wildintel-trapper-sdk#v0.1.0",
    )
    parser.add_argument("--pdf", action="store_true", help="Also build the anonymized docs into a single PDF manual")
    parser.add_argument(
        "--packages-repo", metavar="OWNER/NAME",
        help="Push the snapshot to this private scratch GitHub repo, tag it, and wait for its "
             "Release workflow to build .deb/.rpm/.AppImage/.exe/.dmg, then download them. "
             "Requires the `gh` CLI to be authenticated.",
    )
    parser.add_argument(
        "--packages-create", action="store_true",
        help="Create --packages-repo (private) first if it doesn't already exist",
    )
    parser.add_argument(
        "--packages-tag",
        help="Tag to push/release under in --packages-repo (default: --ref, if it looks like vX.Y.Z)",
    )
    parser.add_argument(
        "--bundle", action="store_true",
        help="Assemble the snapshot, manual.pdf (if --pdf), and packages/ (if --packages-repo) "
             "into a single directory at --output, with an auto-generated README.md",
    )
    args = parser.parse_args()

    packages_tag = args.packages_tag
    if args.packages_repo and not packages_tag:
        if re.match(r"^v\d+\.\d+\.\d+", args.ref):
            packages_tag = args.ref
        else:
            print(
                "Error: --packages-tag is required when --ref doesn't look like a version tag "
                "(vX.Y.Z) for --packages-repo to tag/release under.",
                file=sys.stderr,
            )
            sys.exit(1)

    output = Path(args.output).resolve()
    if output.exists() and any(output.iterdir()) and not args.force:
        print(f"Error: {output} already exists and is not empty. Use --force to overwrite.", file=sys.stderr)
        sys.exit(1)
    if output.exists() and args.force:
        shutil.rmtree(output)

    config = load_config()

    print(f"Exporting {args.ref} from {args.source} (git archive, no history) ...")
    local_repo_root = export_snapshot(args.source, args.ref, output)

    excluded = exclude_paths(output, config.get("exclude_paths", []))
    for e in excluded:
        print(f"Excluded from snapshot: {e}")

    replacements = list(config["replacements"])
    if local_repo_root is not None and not args.source.startswith(("http://", "https://", "git@", "ssh://")):
        replacements = [{"old": str(local_repo_root), "new": "/home/user/project"}] + replacements

    skip_extensions = set(config["skip_extensions"])
    changed = apply_replacements(output, replacements, skip_extensions)
    print(f"Rewrote {changed} file(s) with the redaction map.")

    for s in strip_sections(output, config.get("strip_sections", [])):
        print(f"Stripped section: {s}")
    for s in strip_lines(output, config.get("strip_lines", [])):
        print(f"Stripped line: {s}")

    renamed = apply_renames(output, config["renames"])
    for r in renamed:
        print(f"Renamed asset: {r}")

    vendor_args = {}
    for raw in args.vendor:
        name, _, rest = raw.partition("=")
        vsource, _, vref = rest.partition("#")
        vendor_args[name] = (vsource, vref or "HEAD")

    vendor_replacements: list[dict] = []
    vendor_protected: list[str] = []
    for spec in config.get("vendor_dependencies", []):
        dep_name = spec["dependency_name"]
        if dep_name not in vendor_args:
            print(
                f"Warning: config declares '{dep_name}' as a vendor dependency but no "
                f"--vendor {dep_name}=... was given -- its real git URL stays in the snapshot.",
                file=sys.stderr,
            )
            continue
        vsource, vref = vendor_args[dep_name]
        v_repl, v_prot = vendor_dependency(output, spec, vsource, vref)
        vendor_replacements.extend(v_repl)
        vendor_protected.extend(v_prot)

    if vendor_replacements:
        print("Regenerating uv.lock against the vendored dependency ...")
        if not regenerate_lock(output):
            print("\n!! FAILED: could not regenerate uv.lock -- the snapshot would not `uv sync`/`uv run`.", file=sys.stderr)
            sys.exit(1)
        print("uv.lock regenerated.")
        if patch_dockerfile_for_vendor(output):
            print("Patched backend/Dockerfile.build to copy vendor/ into the Linux package build context.")

    if build_local_docs(output):
        print("Built backend/site/ so the in-app Help button (/docs/) resolves to the local, anonymized manual.")

    missing_protected = verify_protected(output, config["protected_substrings"])
    if missing_protected:
        print("\n!! WARNING: the following strings were supposed to survive untouched but are missing:", file=sys.stderr)
        for s in missing_protected:
            print(f"  - {s}", file=sys.stderr)
        print("This likely means a replacement rule accidentally matched a protected dependency reference.", file=sys.stderr)
    else:
        print("Protected strings (third-party dependency refs) verified intact.")

    hits = scan_report(output, config["report_patterns"])
    report_path = output.parent / f"{output.name}.report.txt"
    with report_path.open("w", encoding="utf-8") as f:
        if hits:
            f.write(f"{len(hits)} potential leftover(s) to review manually:\n\n")
            for file, lineno, pattern, line in hits:
                f.write(f"{file}:{lineno}  [{pattern}]\n    {line}\n")
        else:
            f.write("No leftover matches found by the report patterns.\n")
    print(f"\n{len(hits)} potential leftover(s) flagged for manual review -- see {report_path}")

    # Hard gate, checked last (after every other pass had a chance to fix
    # things): none of the redaction map's real values may survive anywhere
    # in the tree. Unlike everything above, this is not advisory -- a
    # non-empty result means the snapshot actually leaks and must not be
    # shipped, so it aborts before zipping and before the success message.
    leaks = verify_no_leaks(
        output,
        replacements + vendor_replacements,
        config["protected_substrings"] + vendor_protected,
    )
    if leaks:
        print(f"\n!! FAILED: {len(leaks)} real value(s) from the redaction map survived in the output:", file=sys.stderr)
        for needle, file in leaks:
            print(f"  - {needle!r} in {file}", file=sys.stderr)
        print(f"\nNot zipping. Fix the leak(s) above (likely a missing entry in exclude_paths/strip_sections/strip_lines) and re-run.", file=sys.stderr)
        sys.exit(1)

    zip_path = None
    if args.zip:
        zip_path = Path(shutil.make_archive(str(output), "zip", root_dir=output))
        print(f"Zipped: {zip_path}")

    pdf_path = None
    if args.pdf:
        pdf_path = build_pdf(output)
        # Move the PDF out of output/site/pdf/ (and drop that whole transient
        # docs build) right away, before --packages-repo might push `output`
        # to a scratch repo -- it's a build artifact, not source, and pushing
        # it would bloat/slow that push for no reason.
        transient_site = output / "site"
        if pdf_path is not None:
            holder = Path(tempfile.mkdtemp(prefix="anon-manual-")) / "manual.pdf"
            shutil.move(str(pdf_path), str(holder))
            pdf_path = holder
            print(f"Built PDF manual: {pdf_path}")
        else:
            print("PDF manual was not built (see warning above).", file=sys.stderr)
        if transient_site.exists():
            shutil.rmtree(transient_site)

    packages_dir = None
    if args.packages_repo:
        packages_dir = build_packages(output, args.packages_repo, packages_tag, args.packages_create)
        if packages_dir is not None:
            print(f"Downloaded packages to: {packages_dir}")
        else:
            print("Packages were not built (see error above).", file=sys.stderr)

    if args.bundle:
        assemble_bundle(output, zip_path, report_path, pdf_path, packages_dir, args.ref)
        print(f"\nDone. Anonymized bundle at: {output}")
        print(f"  {output}/snapshot/  {output}/snapshot.zip  {output}/snapshot.report.txt")
        if pdf_path is not None:
            print(f"  {output}/manual.pdf")
        if packages_dir is not None:
            print(f"  {output}/packages/")
        print(f"  {output}/README.md")
    else:
        print(f"\nDone. Anonymized snapshot at: {output}")
        if pdf_path is not None:
            final_pdf = output.parent / f"{output.name}.manual.pdf"
            shutil.move(str(pdf_path), str(final_pdf))
            print(f"PDF manual at: {final_pdf}")
        if packages_dir is not None:
            final_packages = output.parent / f"{output.name}-packages"
            if final_packages.exists():
                shutil.rmtree(final_packages)
            shutil.move(str(packages_dir), str(final_packages))
            print(f"Packages at: {final_packages}")
    print("This is a strong first pass, not a guarantee -- read the report and skim the diff before submitting.")


if __name__ == "__main__":
    main()
