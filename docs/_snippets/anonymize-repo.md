`scripts/anonymize_repo.py` (repo root) exports a clean copy of the codebase for double-blind submission: no git history, no author metadata, and author names/emails, this repo's own GitHub URLs, project branding, and funding/grant identifiers stripped out via a literal find/replace map. Genuinely external dependencies (fastapi, pandas, ...) are left alone. `wildintel-trapper-sdk` is not treated as external -- it's another WildINTEL repo, so its real git URL would out the org just as much as anything else here -- see "Vendoring sibling dependencies" below.

### Generating it

```bash
python scripts/anonymize_repo.py --ref development --output ../anon-snapshot \
  --vendor wildintel-trapper-sdk=../wildintel-trapper-sdk#v0.1.0 --zip
```

| Flag | Meaning |
|------|---------|
| `--source` | Local repo path or git URL to export from (default: current repo) |
| `--ref` | Branch/tag/commit to export (default: `HEAD`) |
| `--output` | Destination directory (required) |
| `--vendor NAME=SOURCE[#REF]` | Vendor a dependency locally instead of leaving its real git URL in the snapshot (repeatable). See below. |
| `--zip` | Also produce `<output>.zip` |
| `--force` | Overwrite `--output` if it already exists |
| `--pdf` | Also render the anonymized docs into a single PDF manual. See "Building the PDF manual" below. |
| `--packages-repo OWNER/NAME` | Push the snapshot to a private scratch GitHub repo, tag it, and wait for its Release workflow to build installable packages, then download them. See "Building installable packages" below. |
| `--packages-create` | Create `--packages-repo` (private) first if it doesn't already exist |
| `--packages-tag TAG` | Tag to push/release under in `--packages-repo` (default: `--ref`, if it looks like `vX.Y.Z`) |
| `--bundle` | Assemble the snapshot, PDF, and packages into a single directory at `--output`, with an auto-generated `README.md`. See "Assembling a full review bundle" below. |

Under the hood: `git archive` extracts the chosen ref with no `.git/` at all (history and commit authorship are gone by construction, not by scrubbing), then the redaction map in `scripts/anonymize_repo.config.json` is applied to every text file, a couple of brand-carrying asset files are renamed, and `backend/mkdocs.yml` is built into `backend/site/` so the in-app Help button — repointed at the local `/docs/` mount instead of the public docs site — still resolves to something.

### Vendoring sibling dependencies

`wildintel-trapper-sdk` is depended on via a real git URL in `pyproject.toml`'s `[tool.uv.sources]` -- since it's another WildINTEL repo, not a package like `fastapi`, that URL is as identifying as anything else, but it can't just be text-substituted like a doc mention: the dependency has to actually resolve for `uv sync`/`uv run` to work. `--vendor wildintel-trapper-sdk=<path-or-url>[#ref]` exports and anonymizes a real copy of it too, under `vendor/anon-trapper-sdk/` (its own redaction map is `scripts/anonymize_trapper_sdk.config.json` -- author identity, brand, and funding sections are duplicated from the main config on purpose, since they're the same facts about the same org; keep them in sync if either changes), rewrites `[tool.uv.sources]` to point at that local path, and regenerates `uv.lock` against it. If `--vendor wildintel-trapper-sdk=...` is omitted, the run prints a warning and the real git URL stays in the snapshot -- don't submit that copy.

### Reviewing before you submit

The run prints a summary and writes `<output>.report.txt` listing every line that still matches a "might still be identifying" pattern (emails, leftover `wildintel` mentions, absolute home paths, grant-ID shapes). This is a first pass, not a guarantee — always:

1. Read the report; most hits are expected noise (third-party JS library copyrights bundled by mkdocs-material, `example.com` placeholder emails already substituted in).
2. Check `img/*.png`/`*.webp` screenshots by eye — the script only rewrites text, never image pixels, so a browser tab title, OS username in a file dialog, or window titlebar baked into a screenshot survives untouched.
3. If you edit `scripts/anonymize_repo.config.json` or `scripts/anonymize_trapper_sdk.config.json` to add redaction rules, avoid bracket/brace-wrapped replacement values (`[LIKE THIS]`) — they can parse as YAML flow sequences if the value ever lands as a bare scalar (e.g. `name: [PROJECT] website` breaks `mkdocs.yml`). Test fixtures are a common place to find real names/emails that comments and prose-focused searches miss -- see the `pedro.garcia@dci.uhu.es`-style entries already in `anonymize_trapper_sdk.config.json` for the kind of thing to look for.

### Running the anonymized copy

```bash
unzip anon-snapshot.zip -d anon-test && cd anon-test
./setup.sh          # Windows: .\setup.ps1
uv run cli dev
```

Confirm the Help button opens the local (anonymized) manual rather than a dead link, and that no page title, footer, or copyright string still shows the real project name.

If `uv run cli` prints the wrong help text (e.g. some other package's CLI instead of this one) after re-running the script against the same `--output` path, that's `uv`'s own build cache reusing a stale wheel for that local path -- `uv sync --reinstall-package <name>` (the anonymized `name` from `pyproject.toml`) forces a rebuild. A reviewer unzipping to a fresh path of their own shouldn't hit this.

### Submitting it

- If the venue accepts a **file upload** (OpenReview, CMT, etc.), submit `<output>.zip` directly as supplementary material — nothing is exposed publicly.
- If the venue requires an **anonymous code link** (e.g. `anonymous.4open.science`), that expects a git remote, not a zip — push the exported snapshot to a **brand-new account/repo with no connection to your real GitHub identity**. Never push it to the same account or org that hosts this repo; that alone would deanonymize it.

### Building the PDF manual

`--pdf` runs the same `ENABLE_PDF_EXPORT=1 mkdocs build` pipeline as `manage.py docs pdf` for a real release, just pointed at the already-anonymized `mkdocs.yml`/`docs/` in the snapshot (`uv sync` first, to install the `dev` group's `mkdocs-with-pdf`/WeasyPrint). The resulting PDF ends up at `<output>.manual.pdf` (or `manual.pdf` inside the bundle with `--bundle`); the transient `site/` build directory it's rendered into is deleted afterwards rather than shipped as part of the source snapshot. A build failure only prints a warning — it never aborts the rest of the run.

### Building installable packages

`--packages-repo OWNER/NAME` pushes the finished snapshot (which already carries this repo's own `.github/workflows/release.yml`, redacted like everything else) to that repo's `development` branch, tags it (`--packages-tag`, or `--ref` if that looks like `vX.Y.Z`), and waits for the Release workflow — the exact same one this repo ships with — to build `.deb`/`.rpm`/`.AppImage`/`.exe`×2/`.dmg` and publish them as release assets, then downloads them.

**This is not the anonymous code link you submit to a venue.** `OWNER/NAME` must be a **private**, throwaway scratch repo under an account you control — it exists purely as free GitHub Actions compute to produce binaries, and is never made public or referenced anywhere in the submission. `--packages-create` creates it (always `--private`) if it doesn't exist yet; reuse the same repo across versions rather than creating a new one each time.

If a dependency was vendored (`--vendor`), `backend/Dockerfile.build`'s Linux package build needs `vendor/` copied into its Docker build context — the real repo never has a `vendor/` directory, so that `COPY` line only ever gets added to the exported snapshot, never to the real `Dockerfile.build` (which would then fail to build normally).

### Assembling a full review bundle

`--bundle` changes what `--output` means: instead of *being* the snapshot, it becomes a directory containing everything this run produced --

```
<output>/
├── snapshot/               # the anonymized source tree
├── snapshot.zip
├── snapshot.report.txt
├── manual.pdf              # only if --pdf
├── packages/                # only if --packages-repo
│   ├── camtrap-verify_<version>_amd64.deb
│   ├── camtrap-verify-<version>-1.x86_64.rpm
│   ├── camtrap-verify-<version>-linux-x86_64.AppImage
│   ├── camtrap-verify-<version>-windows-x64.exe
│   ├── camtrap-verify-installer-<version>-windows-x64.exe
│   └── camtrap-verify-<version>-macos-arm64.dmg
└── README.md                # auto-generated, describes the above
```

Full example, producing everything needed for a v0.4.2 double-blind review bundle in one command:

```bash
python scripts/anonymize_repo.py --ref v0.4.2 --output ../anon-bundle-v0.4.2 \
  --vendor wildintel-trapper-sdk=../wildintel-trapper-sdk#v0.1.0 \
  --pdf --packages-repo yourname/anon-ci-build-tmp --bundle --zip
```
