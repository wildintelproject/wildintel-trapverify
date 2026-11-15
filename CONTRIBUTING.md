# Contributing to CamTrap Verify

Thank you for your interest in CamTrap Verify! The project is maintained within the
[WildINTEL project](https://wildintel.eu/) and is open to contributions from the community. Please read our
[Code of Conduct](CODE_OF_CONDUCT.md) before taking part.

## Ways to contribute

- **Report a bug or request a feature:** open an [issue](https://github.com/wildintelproject/wildintel-trapverify/issues)
  with the matching template. For security problems, follow [`SECURITY.md`](SECURITY.md) instead.
- **Improve the documentation, translations or examples.**
- **Fix a bug or add a feature** through a pull request. Look for issues labelled `good first issue`.

For anything larger than a small fix, please open an issue first so we can agree on the approach.

## Setting up

The [Developer Manual](docs/developer-manual.md) explains the architecture, the project structure and how to run
everything. In short:

```bash
git clone https://github.com/<your-fork>/wildintel-trapverify.git
cd wildintel-trapverify
./setup.sh                 # Windows (PowerShell): .\setup.ps1
uv run cli dev             # backend + frontend
```

## Pull requests

1. Fork the repository and create a branch **from `development`** (`feat/…`, `fix/…`, `docs/…`, `chore/…`).
2. Keep the change focused and add or update tests.
3. Run the checks locally:
   ```bash
   uv run cli backend test      # backend tests
   uv run cli frontend lint     # frontend lint
   ```
4. Add a line under **Upcoming release** in [`CHANGELOG.md`](CHANGELOG.md).
5. Open a pull request against **`development`** and fill in the template. CI must be green.

Follow [Conventional Commits](https://www.conventionalcommits.org/) for commit messages (`feat:`, `fix:`, `docs:`, `chore:`).

## Licence

By contributing you agree that your contribution is licensed under the project's licence,
GNU General Public License v3.0 or later.
