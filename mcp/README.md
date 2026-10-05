# PNE CE MCP server

One small, standard-library MCP server over the running broker. Tools:

| Tool | What it answers |
|---|---|
| `ask_participant_as_of` | What did we know about a participant when a protocol version was implemented at a site? One object: consent and site-team readiness at that moment, every visit step checked against what was in effect, possible issues, and evidence (entity, source system, observedAt) on every fact. |
| `visits_since_protocol` | Which participants and visits happened at a site after it implemented a protocol version, with their possible issues. |
| `project_participant` | The same answer as SDTM-shaped domains (DM, DS, SV, BE, PC) or a FHIR R4 Bundle with Provenance per fact. |
| `entity_history` | Every recorded value of one entity, with observedAt. |
| `broker_health`, `list_entities`, `get_entity` | Raw broker reads. |

Load the example data first (`examples/cvrm-118/README.md`).

## Claude Desktop (stdio, nothing leaves the laptop)

Settings > Developer > Edit Config, merge `claude_desktop_config.example.json`,
and set `args` to the absolute path of this directory's `server.py`. `BROKER`
is the broker's host URL (`http://127.0.0.1:9090` with the default compose;
`http://127.0.0.1:19091` with `docker-compose.local-run.yaml`). Restart Claude
Desktop.

## Clients that connect by URL (for example ChatGPT developer mode)

```bash
BROKER=http://127.0.0.1:9090 python3 mcp/server.py --http 8765
```

serves MCP at `http://127.0.0.1:8765/mcp` (Streamable HTTP, JSON responses).
ChatGPT connects only to a public HTTPS URL, so it needs a tunnel to this
port (for example `cloudflared tunnel --url http://127.0.0.1:8765`), and the
connector URL is the tunnel's HTTPS address plus `/mcp`. While the tunnel is
up, the tools are reachable from the internet: they are read-only, but run it
only with demo data and stop it afterwards.

Both clients call the same tools and get the same JSON; their prose differs.
