`scripts/anonymize_repo.py` (repo root) exports a clean copy of the codebase for double-blind submission: no git history, no author metadata, and author names/emails, this repo's own GitHub URLs, project branding, and funding/grant identifiers stripped out via a literal find/replace map. Third-party dependencies (e.g. `wildintel-trapper-sdk`) are deliberately left untouched so the export still builds.

### Generating it

```bash
python scripts/anonymize_repo.py --ref development --output ../anon-snapshot --zip
```

| Flag | Meaning |
|------|---------|
| `--source` | Local repo path or git URL to export from (default: current repo) |
| `--ref` | Branch/tag/commit to export (default: `HEAD`) |
| `--output` | Destination directory (required) |
| `--zip` | Also produce `<output>.zip` |
| `--force` | Overwrite `--output` if it already exists |

Under the hood: `git archive` extracts the chosen ref with no `.git/` at all (history and commit authorship are gone by construction, not by scrubbing), then the redaction map in `scripts/anonymize_repo.config.json` is applied to every text file, a couple of brand-carrying asset files are renamed, and `backend/mkdocs.yml` is built into `backend/site/` so the in-app Help button — repointed at the local `/docs/` mount instead of the public docs site — still resolves to something.

### Reviewing before you submit

The run prints a summary and writes `<output>.report.txt` listing every line that still matches a "might still be identifying" pattern (emails, leftover `wildintel` mentions, absolute home paths, grant-ID shapes). This is a first pass, not a guarantee — always:

1. Read the report; most hits are expected noise (the protected `wildintel-trapper-sdk` dependency line, third-party JS library copyrights bundled by mkdocs-material).
2. Check `img/*.png`/`*.webp` screenshots by eye — the script only rewrites text, never image pixels, so a browser tab title, OS username in a file dialog, or window titlebar baked into a screenshot survives untouched.
3. If you edit `scripts/anonymize_repo.config.json` to add redaction rules, avoid bracket/brace-wrapped replacement values (`[LIKE THIS]`) — they can parse as YAML flow sequences if the value ever lands as a bare scalar (e.g. `name: [PROJECT] website` breaks `mkdocs.yml`).

### Running the anonymized copy

```bash
unzip anon-snapshot.zip -d anon-test && cd anon-test
./setup.sh          # Windows: .\setup.ps1
uv run cli dev
```

Confirm the Help button opens the local (anonymized) manual rather than a dead link, and that no page title, footer, or copyright string still shows the real project name.

### Submitting it

- If the venue accepts a **file upload** (OpenReview, CMT, etc.), submit `<output>.zip` directly as supplementary material — nothing is exposed publicly.
- If the venue requires an **anonymous code link** (e.g. `anonymous.4open.science`), that expects a git remote, not a zip — push the exported snapshot to a **brand-new account/repo with no connection to your real GitHub identity**. Never push it to the same account or org that hosts this repo; that alone would deanonymize it.
