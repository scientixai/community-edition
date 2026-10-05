# pne-community-edition

Installer for the Scientix.AI Provenance Neural Engine Community Edition: an
NGSI-LD context broker and web workbench that run on your laptop, demonstrated
on clinical research.

It has no npm dependencies. It downloads the matching release from
[github.com/scientixai/community-edition](https://github.com/scientixai/community-edition)
and drives `docker compose`.

## Requirements

- Docker with Compose v2 (`docker compose version`)
- Node.js 18 or later
- Free ports 8080 (web) and 9090 (broker)

## Install and run

```bash
npx pne-community-edition install
```

This downloads the release into `./pne-community-edition`, starts the stack
and waits for the broker. Then open:

- `http://localhost:8080`: the walkthrough
- `http://localhost:8080/asof.html`: ask "What did we know about Participant
  204 when Protocol v3.0 was implemented at Site 123?" across nine synthetic
  source systems, with the evidence, JSON-LD, SDTM and FHIR views

## Commands

| Command | What it does |
|---|---|
| `install` (default) | Download the release, build or pull images, start the stack |
| `up` | Start an existing install |
| `down` | Stop the stack |
| `status` | Show the running containers |
| `demo` | Run the scripted demo against the running stack |

Run each from the directory that holds `pne-community-edition`, or set
`PNE_DIR`.

## Plain-language questions with Claude

Without a key, an offline parser answers the example question shapes. To let
Claude answer free-form questions using the engine's tools, put your key in
`pne-community-edition/.env` and restart:

```bash
cp pne-community-edition/.env.example pne-community-edition/.env
# set ANTHROPIC_API_KEY=... in .env
npx pne-community-edition down && npx pne-community-edition up
```

## Environment overrides

| Variable | Default |
|---|---|
| `PNE_VERSION` | the version of this package |
| `PNE_REPO` | `scientixai/community-edition` |
| `PNE_DIR` | `./pne-community-edition` |

## Learn more

- Site and getting started: [community.scientix.ai](https://community.scientix.ai)
- Source, issues and the shell installer (`install.sh`):
  [github.com/scientixai/community-edition](https://github.com/scientixai/community-edition)

Apache-2.0. All example data is synthetic.
