#!/usr/bin/env python3
"""Ask the broker as-of questions from the terminal.

  python3 infra/scripts/ask.py --participant 204 --site 123 --protocol 3.0
      What did we know about Participant 204 when Protocol v3.0 was
      implemented at Site 123?

  python3 infra/scripts/ask.py --site 123 --protocol 3.0
      Which participants and visits happened at Site 123 after it implemented
      protocol v3.0?

--subject and --patient work as synonyms for --participant; --site and
--protocol default to the participant's site and its latest protocol.
--sdtm and --fhir project the participant answer to a standard; --jsonld
prints the broker records behind it as one JSON-LD graph.
Add --json for the whole answer as one JSON object. The same answers are
served to Claude Desktop and other MCP clients by mcp/server.py.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "lib"))
import asof  # noqa: E402
import projections  # noqa: E402

TTY = sys.stdout.isatty()


def c(s: str, code: str) -> str:
    return f"\033[{code}m{s}\033[0m" if TTY else s


def hhmm(s: str) -> str:
    return s.replace("T", " ")[:16] if s else ""


def show_participant(a: dict) -> None:
    print(c(a["question"], "1"))
    p = a["protocol"]
    print(f"\n{p['version']} implemented at {a['participant']['site']}: {p['implementedAtSite']}"
          f"   [{p['evidence']['sourceSystem']}, {p['evidence']['entity']}]")
    at = a["atImplementation"]
    ce = at["consentOnFile"]["evidence"]
    print(c(f"\nOn {p['implementedAtSite']}:", "1"))
    print(f"  Consent on file: ICF v{at['consentOnFile']['version']}   [{ce['sourceSystem']}, {ce['observedAt']}]")
    for m in at["siteTeam"]:
        ready = c("ready", "32") if m["readyForNewProtocol"] else c(f"not trained on {p['version']}", "31")
        print(f"  {m['person']} ({m['role']}): trained on {', '.join(m['trainedOn']) or 'nothing'}; {ready}")
    for v in a["visits"]:
        tag = "after implementation" if v["afterImplementation"] else "before implementation"
        print(c(f"\n{v['visit']}  {hhmm(v['start'])}  protocol {v['protocolInEffect']} in effect  ({tag})", "1"))
        for s in v["steps"]:
            by = f" by {s['by']}" if s["by"] else ""
            print(f"  {hhmm(s['at'])}  {s['step']}{by}   [{s['sourceSystem']}]")
            for chk in s["checks"]:
                mark = c("ok", "32") if chk["ok"] else c("XX", "31")
                detail = "" if chk["ok"] else f": expected {chk['expected']}, found {chk['found']}"
                print(f"      {mark}  {chk['check']}{detail}")
    print(c(f"\n{a['summary']}", "1"))
    print("Sources consulted: " + ", ".join(f"{k} ({v})" for k, v in a["sourcesConsulted"].items()))


def show_site(a: dict) -> None:
    print(c(a["question"], "1"))
    ev = a["evidence"]
    print(f"\n{a['protocol']} implemented at {a['site']}: {a['implementedAtSite']}   "
          f"[{ev['sourceSystem']}, {ev['entity']}]\n")
    for r in a["visits"]:
        status = c("no possible issues", "32") if not r["possibleIssues"] else c(f"{len(r['possibleIssues'])} possible issue(s)", "31")
        print(f"  Participant {r['participant']}  {r['visit']}  {hhmm(r['start'])}  {status}")
        for t in r["possibleIssues"]:
            print(f"      - {t}")
    if not a["visits"]:
        print("  No visits since implementation.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--participant", "--subject", "--patient", dest="participant")
    ap.add_argument("--site")
    ap.add_argument("--protocol")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--sdtm", action="store_true", help="project the participant answer to SDTM-shaped domains")
    ap.add_argument("--fhir", action="store_true", help="project the participant answer to a FHIR R4 Bundle")
    ap.add_argument("--jsonld", action="store_true", help="the broker records behind the answer, as one JSON-LD graph")
    args = ap.parse_args()
    if not args.participant and not args.site:
        ap.error("name a participant or a site")
    ans = (asof.ask_participant(args.participant, args.site, args.protocol) if args.participant
           else asof.ask_site(args.site, args.protocol))
    if "error" in ans:
        print(ans["error"])
        return 1
    if args.participant and args.jsonld:
        print(json.dumps(asof.as_jsonld(args.participant, args.site, args.protocol)["jsonld"], indent=2))
        return 0
    if args.participant and (args.sdtm or args.fhir):
        out = projections.project(ans, "sdtm" if args.sdtm else "fhir")
        if args.fhir or args.json:
            print(json.dumps(out, indent=2))
        else:
            for name, rows in out["domains"].items():
                print(c(f"\n{name}", "1"))
                if rows:
                    cols = list(rows[0])
                    print("  " + " | ".join(cols))
                    for r in rows:
                        print("  " + " | ".join(str(r.get(k, "")) for k in cols))
        return 0
    if args.json:
        print(json.dumps(ans, indent=2))
    elif args.participant:
        show_participant(ans)
    else:
        show_site(ans)
    return 0


if __name__ == "__main__":
    sys.exit(main())
