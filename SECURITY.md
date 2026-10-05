# Security policy

Thank you for helping keep the Community Edition
safe for the people who run it.

## Supported versions

The Community Edition is versioned in `VERSION`. Security fixes land on
`main` and ship in the next tagged release. Only the latest release is
supported; there are no backport branches.

## Reporting a vulnerability

Report privately. Do not open a public issue, a discussion, or a pull
request for a suspected vulnerability.

Use GitHub's private vulnerability reporting on this repository: the
**Security** tab, then **Report a vulnerability**. The report is visible
only to the maintainers until a fix is published.

Please include:

- what the issue is and which component it affects (broker, pipeline,
  lake, adaptive, bridge, web, install script, compose files)
- the version or commit you tested
- the steps to reproduce, and what you observed
- the impact you believe it has

## What to expect

- Acknowledgement within 3 business days.
- An initial assessment, including whether we agree it is a
  vulnerability and our severity read, within 10 business days.
- Progress updates on the report thread until it is resolved.
- Credit in the release notes when a fix ships, unless you ask us not
  to.

We ask that you give us a reasonable opportunity to publish a fix before
disclosing publicly.

## Scope

In scope: the code in this repository, the published `ghcr.io/scientixai/pne-ce-*`
container images, and `install.sh`.

Out of scope, because they belong to their upstream projects: the Scorpio
broker image (`scorpiobroker/all-in-one-runner`), PostgreSQL, DuckDB,
`sdtm.oak`, and any other third-party dependency. Report those upstream.
We still want to hear about it if our configuration of one of them is
what creates the exposure.

## Running this edition safely

The Community Edition is built to be stood up on a laptop in one command.
Read `docs/getting-started.md` before exposing any of it beyond
`127.0.0.1`. The compose defaults are demonstration defaults, not
deployment defaults.
