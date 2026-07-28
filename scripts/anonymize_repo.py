#!/usr/bin/env python3
"""Export an anonymized snapshot of this repo for double-blind review.

Pulls a clean tree straight from git (no .git/, no commit history, no
author metadata -- via `git archive`) and applies a literal, case-sensitive
find/replace map (scripts/anonymize_repo.config.json) to strip author names,
emails, this repo's own GitHub URLs, project branding, and funding/grant
identifiers from every text file. Third-party dependencies (e.g. the
wildintel-trapper-sdk git dependency in pyproject.toml) are deliberately
left untouched -- see "protected_substrings" in the config -- and the script
verifies they survived intact before finishing.

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

Usage:
    python scripts/anonymize_repo.py --output /path/to/anon-snapshot
    python scripts/anonymize_repo.py --ref main --output ../anon-snapshot --zip
    python scripts/anonymize_repo.py --source https://github.com/org/repo.git \\
        --ref main --output /tmp/anon-snapshot
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
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
    args = parser.parse_args()

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
    leaks = verify_no_leaks(output, replacements, config["protected_substrings"])
    if leaks:
        print(f"\n!! FAILED: {len(leaks)} real value(s) from the redaction map survived in the output:", file=sys.stderr)
        for needle, file in leaks:
            print(f"  - {needle!r} in {file}", file=sys.stderr)
        print(f"\nNot zipping. Fix the leak(s) above (likely a missing entry in exclude_paths/strip_sections/strip_lines) and re-run.", file=sys.stderr)
        sys.exit(1)

    if args.zip:
        archive_path = shutil.make_archive(str(output), "zip", root_dir=output)
        print(f"Zipped: {archive_path}")

    print(f"\nDone. Anonymized snapshot at: {output}")
    print("This is a strong first pass, not a guarantee -- read the report and skim the diff before submitting.")


if __name__ == "__main__":
    main()
