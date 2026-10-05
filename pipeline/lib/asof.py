"""As-of questions over the broker: what was true, when, and on whose word.

The engine knows the model (pipeline/lib/model_index.json), not the data.
Given a participant, a site, and a protocol version, it finds when that site
implemented that version, walks the graph out from the participant along the
model index, reads every attribute as it stood at the moment each step
happened (NGSI-LD temporal API, observedAt), and checks each step against
the protocol, consent, delegation, training, credentials, and calibration
in effect at that moment.

A failed check is a possible issue for a person to review; the engine does
not decide whether it is a deviation.

Every fact it returns carries evidence: the entity IRI, the source system
that asserted it, and when it became true.

Standard library only. Usable as a library (web, CLI, tool use) or via
infra/scripts/ask.py.
"""

from __future__ import annotations

import json
import pathlib
import threading
import urllib.parse
from collections import Counter
from datetime import datetime, timezone

import pnehttp

NGSI = f"{pnehttp.BROKER_URL}/ngsi-ld/v1"
HEADERS = {"Accept": "application/json", "Link": pnehttp.LINK_HEADER}
MODEL = json.loads((pathlib.Path(__file__).with_name("model_index.json")).read_text())


_progress = threading.local()


def on_progress(callback) -> None:
    """Route progress lines for this thread (the web page shows them live)."""
    _progress.cb = callback


def report(message: str) -> None:
    cb = getattr(_progress, "cb", None)
    if cb:
        cb(message)


def _enc(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def parse_time(s: str) -> datetime:
    s = s.strip()
    if len(s) == 10:
        s += "T00:00:00Z"
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _instances(attr) -> list[dict]:
    if attr is None:
        return []
    return attr if isinstance(attr, list) else [attr]


def _v(inst: dict | None):
    if not inst:
        return None
    return inst.get("value", inst.get("object"))


class Graph:
    """Read-through cache over the broker: current state and full history."""

    def __init__(self):
        self._cur: dict[str, dict] = {}
        self._hist: dict[str, dict] = {}
        self._types: dict[str, list[dict]] = {}
        self._systems: set[str] = set()

    def get(self, eid: str) -> dict:
        if eid not in self._cur:
            status, body = pnehttp.request("GET", f"{NGSI}/entities/{_enc(eid)}", headers=HEADERS)
            self._cur[eid] = body if status == 200 and body else {}
        return self._cur[eid]

    def history(self, eid: str) -> dict:
        if eid not in self._hist:
            status, body = pnehttp.request("GET", f"{NGSI}/temporal/entities/{_enc(eid)}", headers=HEADERS)
            self._hist[eid] = body if status == 200 and body else {}
            new = {_v(i) for i in _instances(self._hist[eid].get("sourceSystem"))} - self._systems - {None}
            self._systems |= new
            n = len(self._hist)
            if new or n % 8 == 0:
                report(f"Read the history of {n} records from {len(self._systems)} source systems"
                       + (f" (now {', '.join(sorted(new))})" if new else ""))
        return self._hist[eid]

    def of_type(self, type_: str) -> list[dict]:
        if type_ not in self._types:
            report(f"Querying the broker for {type_} records")
            status, body = pnehttp.request(
                "GET", f"{NGSI}/entities?type={_enc(type_)}&limit=1000", headers=HEADERS)
            self._types[type_] = body if status == 200 and body else []
            for e in self._types[type_]:
                self._cur.setdefault(e["id"], e)
        return self._types[type_]

    def pointing_at(self, type_: str, attr: str, target: str) -> list[dict]:
        return [e for e in self.of_type(type_) if _v(_last(e.get(attr))) == target]

    def at(self, eid: str, attr: str, t: datetime) -> dict | None:
        """The instance of attr that was true at t (latest observedAt <= t)."""
        best = None
        for inst in _instances(self.history(eid).get(attr)):
            obs = inst.get("observedAt")
            if obs and parse_time(obs) <= t and (best is None or obs >= best["observedAt"]):
                best = inst
        return best

    def value_at(self, eid: str, attr: str, t: datetime):
        return _v(self.at(eid, attr, t))

    def evidence(self, eid: str, attr: str, t: datetime | None = None) -> dict:
        """IRI, source system, and observedAt for one fact."""
        inst = self.at(eid, attr, t) if t else _last(self.get(eid).get(attr))
        obs = (inst or {}).get("observedAt")
        system = self.value_at(eid, "sourceSystem", parse_time(obs)) if obs else None
        return {"entity": eid, "attribute": attr, "observedAt": obs, "sourceSystem": system}

    def name(self, eid: str | None) -> str | None:
        return _v(_last(self.get(eid).get("name"))) if eid else None

    def cur(self, eid: str, attr: str):
        return _v(_last(self.get(eid).get(attr)))


def _last(attr):
    inst = _instances(attr)
    return inst[-1] if inst else None


# --------------------------------------------------------------- lookups --

def find_site(g: Graph, ref: str) -> str | None:
    ref = ref.strip().lower()
    for s in g.of_type("StudySite"):
        name = (g.cur(s["id"], "name") or "").lower()
        if ref in (s["id"].lower(), name, name.replace("site ", "")) or s["id"].lower().endswith(f"site-{ref}"):
            return s["id"]
    return None


def find_protocol(g: Graph, ref: str) -> str | None:
    ref = ref.strip().lower().lstrip("v")
    for p in g.of_type("ProtocolVersion"):
        if p["id"].lower().endswith(f"-v{ref}") or p["id"].lower() == ref:
            return p["id"]
    return None


def find_participant(g: Graph, number: str, site: str | None = None) -> list[str]:
    number = str(int(number)) if str(number).isdigit() else str(number)
    out = []
    for p in g.of_type("Participant"):
        if g.cur(p["id"], "screeningNumber") == number or p["id"] == number:
            if site is None or g.cur(p["id"], "forStudySite") == site:
                out.append(p["id"])
    return out


def implementation(g: Graph, site: str, protocol: str) -> dict | None:
    for a in g.pointing_at("SiteActivation", "atSite", site):
        if g.cur(a["id"], "activates") == protocol:
            return {"date": g.cur(a["id"], "effectiveFrom"), "activation": a["id"],
                    "evidence": g.evidence(a["id"], "effectiveFrom")}
    return None


def latest_protocol(g: Graph, site: str) -> str | None:
    """The most recent protocol version a site has implemented."""
    acts = [a for a in g.pointing_at("SiteActivation", "atSite", site) if g.cur(a["id"], "effectiveFrom")]
    if not acts:
        return None
    return g.cur(max(acts, key=lambda a: g.cur(a["id"], "effectiveFrom"))["id"], "activates")


def resolve(g: Graph, participant: str | None, site_ref: str | None, protocol_ref: str | None):
    """Fill in what a question leaves out: the participant's site, the site's latest protocol."""
    site = find_site(g, site_ref) if site_ref else None
    if site_ref and not site:
        return None, None, None, f"unknown site {site_ref!r}"
    pid = None
    if participant:
        matches = find_participant(g, participant, site)
        if not matches:
            return None, None, None, f"no participant {participant!r}" + (f" at {g.name(site)}" if site else "")
        if len(matches) > 1:
            sites = ", ".join(g.name(g.cur(m, "forStudySite")) for m in matches)
            return None, None, None, f"participant {participant!r} exists at several sites ({sites}); name the site"
        pid = matches[0]
        site = site or g.cur(pid, "forStudySite")
    if not site:
        return None, None, None, "name a site or a participant"
    pv = find_protocol(g, protocol_ref) if protocol_ref else latest_protocol(g, site)
    if not pv:
        return None, None, None, f"unknown protocol {protocol_ref!r}"
    return pid, site, pv, None


def protocol_at(g: Graph, site: str, t: datetime) -> str | None:
    best = None
    for a in g.pointing_at("SiteActivation", "atSite", site):
        frm = g.cur(a["id"], "effectiveFrom")
        if frm and parse_time(frm) <= t and (best is None or frm > best[0]):
            best = (frm, g.cur(a["id"], "activates"))
    return best[1] if best else None


def _valid(g: Graph, eid: str, t: datetime) -> bool:
    frm, to = g.cur(eid, "effectiveFrom"), g.cur(eid, "effectiveTo")
    return bool(frm) and parse_time(frm) <= t and (not to or t.date() <= parse_time(to).date())


def credentials(g: Graph, holder: str) -> list[str]:
    return [c["id"] for c in g.pointing_at("Credential", "credentialOf", holder)]


def delegations(g: Graph, person: str) -> list[str]:
    return [d["id"] for d in g.pointing_at("Delegation", "delegate", person)]


# ------------------------------------------------------------------ walk --

def walk(g: Graph, start: str, depth: int = 6) -> dict[str, dict]:
    """Everything reachable from start along the model index."""
    seen: dict[str, dict] = {}
    frontier = [start]
    for _ in range(depth):
        nxt = []
        for eid in frontier:
            if eid in seen:
                continue
            ent = g.get(eid)
            if not ent:
                continue
            seen[eid] = ent
            links = MODEL["links"].get(ent.get("type"), {})
            for attr in links.get("out", []):
                for inst in _instances(ent.get(attr)):
                    if _v(inst):
                        nxt.append(_v(inst))
            for type_, attr in links.get("in", []):
                nxt.extend(e["id"] for e in g.pointing_at(type_, attr, eid))
        frontier = nxt
    return seen


# ----------------------------------------------------------------- rules --

def _check(name, ok, expected, found, evidence):
    return {"check": name, "ok": bool(ok), "expected": expected, "found": found,
            "evidence": [e for e in evidence if e]}


def _protocol_label(pid: str | None) -> str:
    return "v" + pid.rsplit("-v", 1)[-1] if pid else "none"


def check_step(g: Graph, step: str, participant: str, site: str) -> dict:
    """Check one step of a visit against what was in effect when it happened."""
    task_inst = _last(g.get(step).get("pne:task"))
    task = _v(task_inst)
    t = parse_time(task_inst["observedAt"])
    report(f"Checking {g.name(step) or task}, {iso(t)[:16].replace('T', ' ')} "
           f"({g.value_at(step, 'sourceSystem', t)}) against what was in effect then")
    pv = protocol_at(g, site, t)
    req = MODEL["taskRequirements"]
    checks = []
    performer = g.cur(step, "performedBy")

    if task == "specimen collection":
        consent = g.cur(participant, "hasConsent")
        version = g.value_at(consent, "consentVersion", t)
        need = g.cur(pv, "pne:icfVersion")
        checks.append(_check("Participant consented on the protocol in effect", version == need,
                             f"ICF v{need}", f"ICF v{version}" if version else "no consent on record",
                             [g.evidence(consent, "consentVersion", t), g.evidence(pv, "pne:icfVersion")]))
        tubes, spec = g.cur(step, "pne:tubesCollected"), g.cur(pv, "pne:pkTubeSpec")
        checks.append(_check(f"Draw matches protocol {_protocol_label(pv)}", tubes == spec, spec, tubes,
                             [g.evidence(step, "pne:tubesCollected"), g.evidence(pv, "pne:pkTubeSpec")]))

    if task == "specimen processing":
        spin, spec = g.cur(step, "pne:spin"), g.cur(pv, "pne:spinSpec")
        checks.append(_check("Processing matches protocol", spin == spec, spec, spin,
                             [g.evidence(step, "pne:spin"), g.evidence(pv, "pne:spinSpec")]))
        device = g.cur(step, "prov:used")
        cal = [c for c in credentials(g, device) if g.cur(c, "pne:kind") == "calibration" and _valid(g, c, t)]
        checks.append(_check(f"{g.name(device)} calibrated", cal, "calibration current",
                             g.name(cal[0]) if cal else "calibration lapsed or missing",
                             [g.evidence(cal[0], "effectiveTo") if cal else g.evidence(device, "name")]))

    if performer and task in req["siteTasks"]:
        who = g.name(performer)
        dl = [d for d in delegations(g, performer) if _valid(g, d, t) and task in (g.cur(d, "pne:tasks") or [])]
        checks.append(_check(f"{who} delegated for {task}", dl, f"PI delegation for {task}",
                             g.cur(dl[0], "name") if dl else "no delegation in effect",
                             [g.evidence(dl[0], "pne:tasks") if dl else None]))
        tr = [c for c in credentials(g, performer)
              if g.cur(c, "ofProtocolVersion") == pv and _valid(g, c, t)]
        later = [c for c in credentials(g, performer) if g.cur(c, "ofProtocolVersion") == pv]
        found = (g.name(tr[0]) if tr else
                 f"not until {g.cur(later[0], 'effectiveFrom')}" if later else "no training on record")
        checks.append(_check(f"{who} trained on protocol {_protocol_label(pv)}", tr,
                             f"protocol {_protocol_label(pv)} training before {iso(t)}", found,
                             [g.evidence(tr[0] if tr else (later[0] if later else performer),
                                         "effectiveFrom" if (tr or later) else "name")]))

    kind = req["credentials"].get(task)
    if performer and kind:
        who = g.name(performer)
        held = [c for c in credentials(g, performer) if g.cur(c, "pne:kind") == kind]
        ok = [c for c in held if _valid(g, c, t)]
        found = (g.name(ok[0]) if ok else
                 f"{g.name(held[0])} expired {g.cur(held[0], 'effectiveTo')}" if held else f"no {kind} credential")
        shown = {"iata": "IATA"}.get(kind, kind)
        checks.append(_check(f"{who} holds a current {shown} credential", ok, f"{shown} credential valid at {iso(t)}",
                             found, [g.evidence((ok or held or [performer])[0],
                                                "effectiveTo" if (ok or held) else "name")]))

    if task == "cold-chain transit":
        lo, hi = g.cur(pv, "pne:shipTempMinC"), g.cur(pv, "pne:shipTempMaxC")
        readings = sorted(_instances(g.history(step).get("pne:temperatureC")), key=lambda i: i["observedAt"])
        bad = [r for r in readings if not (lo <= _v(r) <= hi)]
        found = (f"{len(readings)} readings, {min(_v(r) for r in readings)} to {max(_v(r) for r in readings)} C"
                 if readings else "no logger readings")
        if bad:
            found += "; out of range at " + ", ".join(f"{r['observedAt']} ({_v(r)} C)" for r in bad)
        checks.append(_check("Cold chain within protocol limits", readings and not bad,
                             f"{lo} to {hi} C throughout", found,
                             [{"entity": step, "attribute": "pne:temperatureC",
                               "observedAt": bad[0]["observedAt"] if bad else (readings[-1]["observedAt"] if readings else None),
                               "sourceSystem": g.cur(step, "sourceSystem")},
                              g.evidence(pv, "pne:shipTempMaxC")]))
        checks.append(_check("Carrier custody trace complete", g.cur(step, "pne:custodyTrace") == "complete",
                             "complete", g.cur(step, "pne:custodyTrace"), [g.evidence(step, "pne:custodyTrace")]))

    if task == "specimen receipt":
        lo, hi = g.cur(pv, "pne:shipTempMinC"), g.cur(pv, "pne:shipTempMaxC")
        temp = g.cur(step, "pne:receiptTempC")
        checks.append(_check("Temperature on receipt in spec", temp is not None and lo <= temp <= hi,
                             f"{lo} to {hi} C", f"{temp} C", [g.evidence(step, "pne:receiptTempC")]))

    return {
        "step": g.name(step) or task, "task": task, "at": iso(t), "entity": step,
        "type": g.get(step).get("type"), "by": g.name(performer),
        "sourceSystem": g.value_at(step, "sourceSystem", t),
        "protocolInEffect": _protocol_label(pv), "recorded": _recorded(g, step), "checks": checks,
    }


SKIP = {"name", "sourceSystem", "dataSource", "dataLoader", "loadedAt", "pne:task", "pne:temperatureC"}


def _recorded(g: Graph, eid: str) -> dict:
    """The values a step's source system recorded (properties, not links)."""
    out = {}
    for attr, val in g.get(eid).items():
        inst = _last(val)
        if attr in ("id", "type") or attr in SKIP or not isinstance(inst, dict) or inst.get("type") != "Property":
            continue
        out[attr] = inst.get("value")
    readings = _instances(g.history(eid).get("pne:temperatureC"))
    if readings:
        out["pne:temperatureC"] = [{"observedAt": r["observedAt"], "value": _v(r)}
                                   for r in sorted(readings, key=lambda r: r["observedAt"])]
    return out


# --------------------------------------------------------------- answers --

def _visit_steps(g: Graph, visit: str) -> list[str]:
    out = []
    for type_ in MODEL["steps"]:
        out += [e["id"] for e in g.pointing_at(type_, "performedInVisit", visit)
                if _last(g.get(e["id"]).get("pne:task"))]
    return sorted(out, key=lambda s: _last(g.get(s)["pne:task"])["observedAt"])


def visit_report(g: Graph, visit: str, participant: str, site: str, implemented: datetime | None = None) -> dict:
    steps = [check_step(g, s, participant, site) for s in _visit_steps(g, visit)]
    start = g.cur(visit, "actualStartDate")
    trip = [dict(c, step=s["step"], at=s["at"]) for s in steps for c in s["checks"] if not c["ok"]]
    in_effect = steps[0]["protocolInEffect"] if steps else (
        _protocol_label(protocol_at(g, site, parse_time(start))) if start else None)
    return {
        "visit": g.cur(visit, "visitName"), "entity": visit, "start": start,
        "afterImplementation": bool(implemented and start and parse_time(start) >= implemented),
        "protocolInEffect": in_effect,
        "steps": steps, "observations": _observations(g, visit), "possibleIssues": trip,
    }


def _observations(g: Graph, visit: str) -> list[dict]:
    """Measurements recorded at a visit (vital signs and the like), with their evidence."""
    out = []
    for o in g.pointing_at("ClinicalObservation", "atVisit", visit):
        eid = o["id"]
        out.append({"entity": eid, "parameter": g.cur(eid, "parameterCode"),
                    "value": g.cur(eid, "numericValue"), "unit": g.cur(eid, "unit"),
                    "position": g.cur(eid, "position"),
                    "evidence": g.evidence(eid, "numericValue")})
    return sorted(out, key=lambda x: x["parameter"] or "")


def ask_participant(participant: str, site_ref: str | None = None, protocol_ref: str | None = None) -> dict:
    """What did we know about <participant> when <protocol> was implemented at <site>?

    Site defaults to the participant's site; protocol to the latest the site implemented.
    """
    g = Graph()
    pid, site, pv, err = resolve(g, participant, site_ref, protocol_ref)
    if err:
        return {"error": err}
    impl = implementation(g, site, pv)
    if not impl:
        return {"error": f"{g.name(site)} has not implemented protocol {_protocol_label(pv)}"}
    t_impl = parse_time(impl["date"])
    report(f"{g.name(site)} implemented protocol {_protocol_label(pv)} on {impl['date']} "
           f"({impl['evidence'].get('sourceSystem')})")
    report(f"Walking the graph out from Participant {g.cur(pid, 'screeningNumber')}")
    reach = walk(g, pid)
    report(f"Reached {len(reach)} linked records")
    consent = g.cur(pid, "hasConsent")
    team = []
    for eid, ent in reach.items():
        if ent.get("type") != "Person" or not delegations(g, eid):
            continue
        trained = [_protocol_label(g.cur(c, "ofProtocolVersion")) for c in credentials(g, eid)
                   if g.cur(c, "ofProtocolVersion") and _valid(g, c, t_impl)]
        team.append({"person": g.name(eid), "entity": eid, "role": g.cur(eid, "pne:role"),
                     "trainedOn": sorted(trained),
                     "readyForNewProtocol": _protocol_label(pv) in trained})
    visits = sorted((e for e, x in reach.items() if x.get("type") == "VisitOccurrence"),
                    key=lambda v: g.cur(v, "actualStartDate") or "")
    reports = [visit_report(g, v, pid, site, t_impl) for v in visits]
    since = [r for r in reports if r["afterImplementation"]]
    issues = [dict(t, visit=r["visit"]) for r in since for t in r["possibleIssues"]]

    systems = Counter()
    for r in reports:
        for s in r["steps"]:
            for c in s["checks"]:
                for e in c["evidence"]:
                    if e.get("sourceSystem"):
                        systems[e["sourceSystem"]] += 1
    n = len(issues)
    summary = (f"No possible issues: every step since {impl['date']} matched protocol {_protocol_label(pv)}."
               if n == 0 else
               f"{n} possible issue{'s' if n != 1 else ''} since {g.name(site)} implemented "
               f"protocol {_protocol_label(pv)} on {impl['date']}.")
    consent_history = [
        {"version": _v(i), "observedAt": i.get("observedAt"),
         "witness": g.name(g.value_at(consent, "witnessedBy", parse_time(i["observedAt"]))),
         "sourceSystem": g.value_at(consent, "sourceSystem", parse_time(i["observedAt"]))}
        for i in sorted(_instances(g.history(consent).get("consentVersion")), key=lambda i: i.get("observedAt", ""))
    ]
    return {
        "question": (f"What did we know about Participant {g.cur(pid, 'screeningNumber')} when Protocol "
                     f"{_protocol_label(pv)} was implemented at {g.name(site)}?"),
        "clock": "observedAt: when each fact became true in its source system",
        "participant": {"entity": pid, "number": g.cur(pid, "screeningNumber"), "site": g.name(site),
                        "study": g.cur(g.cur(pid, "forStudy"), "studyId")},
        "protocol": {"version": _protocol_label(pv), "entity": pv, "implementedAtSite": impl["date"],
                     "evidence": impl["evidence"]},
        "atImplementation": {
            "consentOnFile": {"version": g.value_at(consent, "consentVersion", t_impl),
                              "evidence": g.evidence(consent, "consentVersion", t_impl)},
            "siteTeam": sorted(team, key=lambda x: x["person"] or ""),
        },
        "consentHistory": consent_history,
        "visits": reports,
        "possibleIssues": issues,
        "summary": summary,
        "sourcesConsulted": dict(systems.most_common()),
    }


def ask_site(site_ref: str, protocol_ref: str | None = None) -> dict:
    """Which participants and visits happened at <site> after it implemented <protocol>?"""
    g = Graph()
    _, site, pv, err = resolve(g, None, site_ref, protocol_ref)
    if err:
        return {"error": err}
    impl = implementation(g, site, pv)
    if not impl:
        return {"error": f"{g.name(site)} has not implemented protocol {_protocol_label(pv)}"}
    t_impl = parse_time(impl["date"])
    rows = []
    for v in g.pointing_at("VisitOccurrence", "atStudySite", site):
        start = g.cur(v["id"], "actualStartDate")
        if not start or parse_time(start) < t_impl:
            continue
        pid = g.cur(v["id"], "forParticipant")
        r = visit_report(g, v["id"], pid, site, t_impl)
        rows.append({"participant": g.cur(pid, "screeningNumber"), "visit": r["visit"], "start": start,
                     "entity": v["id"], "possibleIssues": [f"{t['check']} ({t['found']})" for t in r["possibleIssues"]]})
    rows.sort(key=lambda r: r["start"])
    return {
        "question": (f"Which participants and visits happened at {g.name(site)} after it implemented "
                     f"protocol {_protocol_label(pv)}?"),
        "site": g.name(site), "protocol": _protocol_label(pv), "implementedAtSite": impl["date"],
        "evidence": impl["evidence"], "visits": rows,
    }


def entity_history(eid: str) -> dict:
    """Every recorded value of every attribute of one entity, with observedAt."""
    g = Graph()
    return g.history(eid)


ask_subject = ask_participant  # "subject" and "patient" are the same thing here


# --------------------------------------------------------------- JSON-LD --

ETSI_CORE_CONTEXT = "https://uri.etsi.org/ngsi-ld/v1/ngsi-ld-core-context-v1.8.jsonld"
PUBLIC_CONTEXT = pnehttp.os.environ.get("PNE_PUBLIC_CONTEXT_URL", "http://localhost:8080/context/pne-context.jsonld")
NOISE = {"dataSource", "dataLoader", "loadedAt"}


def _served_context() -> dict:
    here = pathlib.Path(__file__).resolve().parent
    # In the web image the context sits beside this file; in a checkout, under web/.
    cands = [here / "public" / "context"] + [p / "web" / "public" / "context" for p in here.parents]
    for cand in cands:
        f = cand / "pne-context.jsonld"
        if f.is_file():
            ctx = json.loads(f.read_text())["@context"]
            if isinstance(ctx, list):
                ctx = {k: v for part in ctx if isinstance(part, dict) for k, v in part.items()}
            return ctx
    return {}


def _expand(term: str, ctx: dict) -> str | None:
    val = ctx.get(term)
    iri = val.get("@id") if isinstance(val, dict) else val
    if iri is None and ":" in term:
        iri = term
    if isinstance(iri, str) and ":" in iri and not iri.startswith(("http:", "https:", "urn:")):
        prefix, local = iri.split(":", 1)
        base = ctx.get(prefix)
        base = base.get("@id") if isinstance(base, dict) else base
        if isinstance(base, str):
            return base + local
    return iri


def as_jsonld(participant: str, site_ref: str | None = None, protocol_ref: str | None = None) -> dict:
    """Everything the answer touched, as the broker holds it, in JSON-LD.

    One @graph: the broker's own temporal NGSI-LD record of each entity the
    engine walked (every value with observedAt and sourceSystem), plus one
    pne:PossibleIssue node per failed check, linked by prov:wasDerivedFrom to
    the records it was derived from. Every link is an IRI you can follow.
    """
    answer = ask_participant(participant, site_ref, protocol_ref)
    if "error" in answer:
        return answer
    g = Graph()
    pid = answer["participant"]["entity"]
    nodes, ids = [], list(walk(g, pid))
    for eid in ids:
        # Broker bookkeeping (load provenance, ngsi-ld:deletedAt from reloads) is not study data.
        rec = {k: v for k, v in g.history(eid).items() if k not in NOISE and not k.startswith("ngsi-ld:")}
        if rec:
            nodes.append(rec)
    issue_n = 0
    for v in answer["visits"]:
        for t in v["possibleIssues"]:
            issue_n += 1
            step = next((s["entity"] for s in v["steps"] if s["step"] == t["step"] and s["at"] == t["at"]), None)
            node = {
                "id": f"urn:ngsi-ld:pne:PossibleIssue:{pid.rsplit(':', 1)[-1]}-{v['visit'].lower()}-{issue_n}",
                "type": "pne:PossibleIssue",
                "pne:check": {"type": "Property", "value": t["check"]},
                "pne:expected": {"type": "Property", "value": t["expected"]},
                "pne:found": {"type": "Property", "value": t["found"], "observedAt": t["at"]},
                "prov:wasDerivedFrom": [{"type": "Relationship", "object": e["entity"]}
                                        for e in t["evidence"] if e.get("entity")],
                "pne:note": {"type": "Property",
                             "value": "Derived by the as-of engine for a person to review; not a deviation finding."},
            }
            if step:
                node["pne:atStep"] = {"type": "Relationship", "object": step}
            nodes.append(node)
    ctx = _served_context()
    used = sorted({k for n in nodes for k in n if k not in ("id", "type")} | {n["type"] for n in nodes})
    return {
        "question": answer["question"],
        "jsonld": {"@context": [ETSI_CORE_CONTEXT, PUBLIC_CONTEXT], "@graph": nodes},
        "termsUsed": {t: _expand(t, ctx) for t in used},
    }
