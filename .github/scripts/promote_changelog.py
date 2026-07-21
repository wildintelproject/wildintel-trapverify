#!/usr/bin/env python3
"""
Promote CHANGELOG.md's "Upcoming release" section to a dated, versioned entry
under "Released", and write its content (without the version heading) to a
separate notes file for use as the GitHub Release body.

Used by .github/workflows/release.yml on a tag push — no manual CHANGELOG.md
edit is required before tagging: the content of "## Upcoming release" at the
tagged commit is what gets released.

This repo's existing convention (see past 0.1.0/0.2.0/0.3.0 entries) nests
each version's subsections one level deeper than "Upcoming release" does
(`#### Added` under `### [X.Y.Z]`, vs. plain `### Added` under
`## Upcoming release`), and ends each entry with a "**Full Changelog:**"
compare link — this script reproduces both when promoting.
"""
from __future__ import annotations

import argparse
import sys

UPCOMING_HEADING = "## Upcoming release"
RELEASED_HEADING = "## Released"
PLACEHOLDER_MARKER = "may have been superseded by newer releases"


def find_section(lines: list[str], heading: str) -> tuple[int, int]:
    """Return (start, end) line indices for the section starting at `heading`.

    `start` is the index of the heading line itself; `end` is the index of
    the next top-level ("## ") heading, or len(lines) if there is none.
    Heading comparison ignores trailing whitespace (this file has at least
    one heading, "## Released ", with a stray trailing space).
    """
    start = next(i for i, line in enumerate(lines) if line.rstrip() == heading)
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return start, end


def build_link(repo: str, tag_name: str, prev_tag: str | None) -> str:
    if prev_tag:
        return f"https://github.com/{repo}/compare/{prev_tag}...{tag_name}"
    return f"https://github.com/{repo}/releases/tag/{tag_name}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changelog", default="CHANGELOG.md")
    parser.add_argument("--version", required=True, help="e.g. 0.4.0")
    parser.add_argument("--tag-name", required=True, help="e.g. v0.4.0")
    parser.add_argument("--date", required=True, help="ISO date, e.g. 2026-07-22")
    parser.add_argument("--repo", required=True, help="e.g. wildintelproject/wildintel-trapverify")
    parser.add_argument("--prev-tag", default="", help="Previous tag, empty for the first release")
    parser.add_argument("--notes-out", required=True)
    args = parser.parse_args()

    with open(args.changelog, encoding="utf-8") as f:
        lines = f.readlines()

    up_start, up_end = find_section(lines, UPCOMING_HEADING)
    upcoming_body = lines[up_start + 1:up_end]

    while upcoming_body and upcoming_body[0].strip() == "":
        upcoming_body.pop(0)
    while upcoming_body and upcoming_body[-1].strip() == "":
        upcoming_body.pop()

    if not upcoming_body:
        print("Nothing under 'Upcoming release' — aborting promotion.", file=sys.stderr)
        sys.exit(1)

    # Shift "### Subsection" (Upcoming release's level) one level deeper to
    # "#### Subsection", matching how every past version entry nests its
    # own subsections under "### [X.Y.Z]".
    promoted_body = [
        f"#{line}" if line.startswith("### ") else line
        for line in upcoming_body
    ]

    link = build_link(args.repo, args.tag_name, args.prev_tag or None)
    compare_label = f"{args.prev_tag}...{args.tag_name}" if args.prev_tag else args.tag_name
    full_changelog_line = f"**Full Changelog:** [`{compare_label}`]({link})\n"

    with open(args.notes_out, "w", encoding="utf-8") as f:
        f.writelines(promoted_body)
        f.write("\n")
        f.write(full_changelog_line)

    new_heading = f"### [{args.version}]({link}) - {args.date}\n"

    rel_start, _ = find_section(lines, RELEASED_HEADING)
    released_rest = lines[rel_start + 1:]

    # Split into: the preamble (blank lines / the permanent "past release
    # notes may be superseded" disclaimer, if present) and the list of
    # already-released version entries that follows it.
    first_version_idx = next(
        (i for i, line in enumerate(released_rest) if line.startswith("### [")),
        len(released_rest),
    )
    preamble = released_rest[:first_version_idx]
    existing_entries = released_rest[first_version_idx:]

    if not existing_entries:
        # Nothing released yet: the preamble is just a disposable "nothing
        # here" placeholder, not the permanent disclaimer — drop it so the
        # first real entry doesn't inherit stray placeholder text.
        preamble = [line for line in preamble if PLACEHOLDER_MARKER not in line]
        while preamble and preamble[0].strip() == "":
            preamble.pop(0)

    body_after_released_heading = preamble if preamble else ["\n"]

    new_lines = (
        lines[:up_start]
        + [UPCOMING_HEADING + "\n", "\n"]
        + lines[rel_start:rel_start + 1]
        + body_after_released_heading
        + [new_heading, "\n"]
        + promoted_body
        + ["\n", full_changelog_line, "\n"]
        + existing_entries
    )

    with open(args.changelog, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"Promoted 'Upcoming release' to {new_heading.strip()}")


if __name__ == "__main__":
    main()
