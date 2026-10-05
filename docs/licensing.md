# Licensing: why Apache-2.0

The Community Edition is licensed under Apache-2.0. This was a
deliberate choice over copyleft licenses (GPLv3, AGPLv3), made and
reaffirmed with the tradeoffs in full view. This page records the
reasoning publicly.

## The decision

Apache-2.0, for the whole tree, permanently. Contributions are
accepted under the same license. The project's names are trademarks
and are governed separately by [TRADEMARKS.md](../TRADEMARKS.md);
Apache-2.0 grants no trademark rights.

## Why permissive fits this project

**Adoption is the mission.** The Community Edition exists to show
that a working provenance-aware data pipeline on an NGSI-LD broker is
commodity technology: clone it, run it, learn from it, build on it.
Clinical research is the first demonstrated domain; the audience spans
the healthcare and life sciences value chain and beyond.
Pharmaceutical companies, CROs, and vendors routinely operate under
legal policies that forbid or heavily gate copyleft code in anything
they might redistribute. A permissive license removes that friction
for exactly the audience this edition serves.

**The ecosystem is permissive.** Everything this project stands on
is Apache-2.0 or MIT: The Ontology Project (Apache-2.0), sdtm.oak
(Apache-2.0), DuckDB (MIT), rclone (MIT). The CDISC open-source
ecosystem (CORE, pharmaverse) is overwhelmingly permissive. Matching
it keeps code flowing in both directions; Apache-2.0 code can be
reused by every neighbor, and theirs by us.

**Open floor, clean boundary.** The Community Edition is deliberately
commodity and complete for local practice. A permissive license keeps
improvements flowing without contributor licensing agreements or
relicensing gymnastics, and keeps this tree's Apache-2.0 boundary clear
for contributors and downstream users.

**Patents are covered.** Apache-2.0 carries an explicit patent grant
from every contributor plus a termination clause against patent
aggression. For this project's realistic patent surface, that is the
protection that matters.

## What we gave up, knowingly

Copyleft would prevent someone from shipping a closed-source
derivative of this code. We accept that risk with open eyes: this
edition is deliberately commodity, its architecture is documented in
public, and its value is legibility, not secrecy. GPLv3's protection
also stops at distribution; a hosted service built on a private fork
owes nobody source under GPLv3, and closing that hole would take
AGPLv3, the license most likely to block the users we most want.
Protection of the project's identity comes from trademark law
instead: forks are welcome, but not under our names.

## Practical notes

- Vendored artifacts keep their upstream licensing; see
  [NOTICE](../NOTICE) for attributions.
- The architecture credits the AWS Garnet Framework as inspiration.
  No Garnet code is included, so no license relationship exists.
- Nothing in this document is legal advice; it records a project
  decision and its rationale.
