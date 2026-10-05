# CVRM-118: as-of questions across source systems

A fictitious phase 3 study (ExampleBiotech, CVRM-118) with three sites,
six participants and eighteen PK blood draws, exported from nine source systems
in their own formats. Nothing here is real: every person, site, participant and
reading is synthetic.

The question this example answers:

> What did we know about Participant 204 when Protocol v3.0 was implemented
> at Site 123?

## Source systems

| File | System | What it holds | How it names a participant |
|---|---|---|---|
| `protocol_versions.json` | Protocol authoring | Protocol versions, the ICF version, PK draw and shipping requirements | n/a |
| `ctms_site_activations.csv` | CTMS | Which protocol version each site activated, and when | n/a |
| `ctms_site_staff.csv` | CTMS | Site staff roster and their LMS user names | n/a |
| `etmf_delegation_log.csv` | eTMF | Investigator delegation logs: who may do which task, from when | n/a |
| `lms_training_records.csv` | LMS | Protocol training, phlebotomy and IATA certifications | n/a |
| `cmms_equipment_calibration.csv` | CMMS | Centrifuge calibration and next due date | n/a |
| `econsent_signatures.csv` | eConsent | Every ICF signature and its witness | `CVRM118-123-0204` |
| `edc_crf_items.csv` | EDC | CRF items: visit dates, PK collection, processing, packaging | `123-204` |
| `courier_shipments.csv`, `courier_temperature_log.csv` | Courier | Shipments by kit, and the data logger's readings in transit | kit id |
| `lims_results.csv`, `lims_analyst_certifications.csv` | LIMS | Receipt, assay, results, medical review | `SITE123` / `0204` |

No file says whether anything went wrong. There is no outcome column, no
deviation log, and no scenario file.

## How the answer is built

1. **Connectors** (`pipeline/lib/connectors.py`) read each export in its own
   shape, resolve each system's identifiers to one IRI per participant, person,
   site, visit and specimen, and stamp every fact with `observedAt` (when it
   became true in that system) and `sourceSystem`.
2. **The broker** stores current state and history (NGSI-LD temporal API).
3. **The model index** (`pipeline/lib/model_index.json`) says which links to
   follow from each entity type. It names types, never instances.
4. **The engine** (`pipeline/lib/asof.py`) finds when the site implemented
   the protocol, walks out from the participant, reads every value as it stood
   when each step happened, and checks each step against what was in effect
   then: the protocol at that site, the participant's consent version, the
   performer's delegation, training and credentials, the equipment's
   calibration, and the cold chain. A failed check is a possible issue for a
   person to review; the engine does not decide whether it is a deviation.
   Every fact in the answer carries its evidence: entity, source system and
   `observedAt`.

5. **Projections** (`pipeline/lib/projections.py`) turn the same answer into
   SDTM-shaped domains (DM, DS, SV, BE, PC)
   or a FHIR R4 Bundle with a Provenance resource per fact. Standards are views
   of the graph, not the stored model. Both are shaped after the standards for
   demonstration and are not validated against SDTMIG terminology or FHIR
   profiles.

The rules are generic. Ask about any participant, site or protocol version in the
data and the engine answers the same way.

## Run it

With the stack up:

```bash
python3 infra/scripts/load-sources.py examples/cvrm-118/sources

python3 infra/scripts/ask.py --site 123 --protocol 3.0
python3 infra/scripts/ask.py --participant 204 --site 123 --protocol 3.0
python3 infra/scripts/ask.py --participant 207 --site 123 --protocol 3.0
python3 infra/scripts/ask.py --participant 204 --site 123 --protocol 3.0 --json
python3 infra/scripts/ask.py --patient 204 --sdtm
python3 infra/scripts/ask.py --patient 207 --fhir
```

In the browser, `http://localhost:8080/asof.html` takes plain-language
questions ("show me 204", "show me 207", "compare 204 and 201", "show me 204
as SDTM"). With `ANTHROPIC_API_KEY` set, Claude answers using only the
engine's tools; without it, an offline parser handles the same question
shapes, and the page says which one answered. Every answer opens to its JSON,
its SDTM and FHIR projections, and the broker records each stop cites.

The same questions are tools in the MCP server (`mcp/README.md`), so Claude,
ChatGPT or any MCP client can ask them in plain language and cite the
evidence.

## Change the data, change the answer

Edit a row and reload. Move J. Moreno's v3.0 training in
`lms_training_records.csv` to before 2026-08-05 and two of Participant 204's
possible issues clear. Add an ICF v3.0 signature for `CVRM118-123-0204` dated
before the visit and the consent issue clears.

## What this does not do yet

It answers with one clock: when each fact was true. NGSI-LD has no second
clock for what we knew and when we knew it (a fact entered late carries the
time it became true, not the time the system learned it).
