# Contributing

The Community Edition is meant to be read, run, argued with, and
improved. Interoperability in healthcare is broken for everyone, so the
method for fixing it is public on purpose. Contributions are welcome.

## Before you start

- Read `docs/getting-started.md` and stand the stack up locally. Most
  questions answer themselves once it is running.
- Read `docs/decisions.md`. It records the founding constraints and the
  calls already made on the questions they left open. A change that
  reverses one of those calls needs to argue with the recorded reasoning,
  not around it.
- For anything larger than a fix, open an issue first and describe the
  problem before the solution.

## Reporting a bug

Open an issue with the version or commit you ran, your operating system
and Docker version, the exact commands you ran, what you expected, and
what happened. Include the output of `docker compose ps` and the logs of
the service that misbehaved.

Do not report a security vulnerability in a public issue. See
`SECURITY.md`.

## Making a change

1. Fork, then branch from `main`.
2. Make the change.
3. Run the proof scripts that apply (below). They run without Docker
   and they are fast.
4. Open a pull request that says what changed and why, and names what
   you ran to check it.

### Proof scripts

This repository proves its own invariants with scripts rather than
prose. Run the ones your change could break:

```bash
./scripts/prove-no-secret-shapes.sh              # no secret-shaped values in the tree
./scripts/prove-env-example-compose-parity.sh    # every compose ${VAR} is documented
python3 scripts/prove-openapi-routes.py          # OpenAPI matches the real routes
```

These need a running stack:

```bash
./scripts/prove-lake-ownership.sh                # only the lake service writes to the lake
./infra/scripts/prove-rule7.sh                   # capability is not authority in adaptive
```

If you add an invariant, add the script that proves it. A claim in a
pull request description is not evidence; a command and its output are.

## What we look for in review

- The change does what its description says, and nothing the
  description does not mention.
- Tests or proof scripts that would fail if the change were wrong. A
  test that passes against a broken implementation is worse than no
  test.
- No secrets, keys, tokens, or personal data in code, configuration,
  fixtures, or commit history.
- Defaults that are safe when nobody reads the documentation.
- Full IRIs over bare local type strings. Linked data travels with the
  identifier.

## Licensing of contributions

This project is Apache-2.0 (`LICENSE`). Under section 5 of that license,
any contribution you intentionally submit for inclusion is licensed to
Scientix.AI under the same terms, unless you state otherwise in writing.
There is no separate contributor agreement to sign.

The license does not grant trademark rights. See `TRADEMARKS.md` before
using the project name or marks.

## Conduct

Be decent. Argue with the work, not the person. Assume the other party
is trying to get it right. Maintainers may close or lock anything that
stops being about the work.
