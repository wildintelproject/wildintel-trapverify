# Maintenance and support

## Who maintains CamTrap Verify

CamTrap Verify is maintained within the [WildINTEL project](https://wildintel.eu/), which initially ends at the
end of 2027. The code is open source (GPL-3.0-or-later) and open to contributions on
[GitHub](https://github.com/wildintelproject/wildintel-trapverify), so the tool can be kept alive by the community
after the project ends: anyone can fork it, report problems, and propose changes through pull requests.

The [Developer Manual](developer-manual.md) is written to make that easy for other developers: it describes the
architecture, the project structure, how to set up a development environment, how to run the tests, how the CI/CD
workflows work and how to publish a release.

## Supported versions

| Version | Supported |
|---|---|
| Latest release | Yes — bug fixes and security fixes |
| `development` branch | Yes — where changes are integrated before the next release |
| Older releases | No — please upgrade to the latest release |

## Getting help and reporting problems

- **Bugs and feature requests:** open an [issue](https://github.com/wildintelproject/wildintel-trapverify/issues)
  using the templates provided.
- **Security problems:** see [`SECURITY.md`](https://github.com/wildintelproject/wildintel-trapverify/blob/main/SECURITY.md)
  and do not open a public issue.
- **Response times:** support is provided on a best-effort basis while the WildINTEL project is running and by the
  community afterwards. There is no guaranteed response time.

## Keeping the software working

Scientific software often stops working when its dependencies change. To reduce that risk:

- The test suite runs on every push and pull request (`ci.yml`).
- A scheduled workflow (`scheduled.yml`) runs the tests every week against the **latest compatible versions** of the
  Python and Node dependencies, and opens an issue if they fail.
- Dependabot proposes dependency, GitHub Actions and Docker image updates (`.github/dependabot.yml`).
- Every user-visible change is recorded in the [`CHANGELOG`](https://github.com/wildintelproject/wildintel-trapverify/blob/main/CHANGELOG.md).

## Releases and citation

Releases follow [Semantic Versioning](https://semver.org/) and are built and published by the `release.yml` workflow
(see [Releasing a New Version](developer-manual.md#13-releasing-a-new-version)). Each GitHub Release can be archived on
[Zenodo](https://zenodo.org/) to obtain a DOI per version; cite the version you used, together with its DOI when
available.

## Contributing

See [`CONTRIBUTING.md`](https://github.com/wildintelproject/wildintel-trapverify/blob/main/CONTRIBUTING.md) and the
[Code of Conduct](https://github.com/wildintelproject/wildintel-trapverify/blob/main/CODE_OF_CONDUCT.md). New
contributors can start with issues labelled `good first issue`.
