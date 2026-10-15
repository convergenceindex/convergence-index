#!/usr/bin/env python3
"""record_calls.py — record AP race calls for Decision Night in results.json.

Usage:  python3 record_calls.py "<calls>" [--page index.html] [--results results.json] [--dry-run]

<calls> is a comma- or newline-separated list. Each item is a race and a call:
    GA Sen D          Senate race by state code (also "GA Senate D", "Georgia Senate D")
    NE Sen I          independents are I
    GA Gov R          governor race ("GA Governor R")
    PA-07 D           House district (also "PA7 D", "PA 7 D")
    House D 212 R 190 nationwide House seats called for each party (replaces the old tally)
    PA-07 -           withdraw a call (rare: AP retracted it, or it was entered by mistake)

Only races on the site can be called; anything unrecognised stops the whole update, so a
typo never publishes half a batch. The website checks results.json every 30 seconds.
"""
import json, re, sys, datetime, argparse
from zoneinfo import ZoneInfo

STATES = {"Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO", "Connecticut": "CT",
          "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
          "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
          "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH",
          "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
          "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN",
          "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"}
NAME_TO_CODE = {k.lower(): v for k, v in STATES.items()}

def load_data(page):
    s = open(page, encoding="utf-8").read()
    k = s.index("const DATA = "); st = s.index("{", k)
    return json.JSONDecoder().raw_decode(s, st)[0]

def races_on_site(D):
    senate = {r["st"]: r for r in D["senate"]["all"]["races"]}
    gov = {NAME_TO_CODE[r["id"].lower()]: r for r in D["governors"]["races"] if r["id"].lower() in NAME_TO_CODE}
    house = {r["id"]: r for r in D["house"]["races"] + D["decisionNight"]["houseMore"]}
    return {"senate": senate, "gov": gov, "house": house}

def state_code(tok):
    t = tok.strip().rstrip(".").lower()
    if t.upper() in STATES.values() and len(t) == 2: return t.upper()
    return NAME_TO_CODE.get(t)

def parse(text, RACES):
    items = [x.strip() for x in re.split(r"[,\n;]+", text) if x.strip()]
    out, errors = [], []
    for it in items:
        m = re.fullmatch(r"(?i)house\s+(?:seats\s+)?D\s*[:=]?\s*(\d{1,3})\s+R\s*[:=]?\s*(\d{1,3})", it)
        if m:
            d, r = int(m.group(1)), int(m.group(2))
            if d + r > 435: errors.append(f"'{it}': {d}+{r} is more than 435 seats"); continue
            out.append(("houseCalled", None, {"D": d, "R": r}, it)); continue
        m = re.fullmatch(r"(?i)(.+?)\s+([DRI]|-)", it)
        if not m: errors.append(f"'{it}': expected a race followed by D, R, I or -"); continue
        race, call = m.group(1).strip(), m.group(2).upper()
        h = re.fullmatch(r"(?i)([A-Z]{2})\s*-?\s*(\d{1,2}|AL)", race)
        if h and not re.search(r"(?i)sen|gov", race):
            did = f"{h.group(1).upper()}-{h.group(2).upper().zfill(2) if h.group(2).isdigit() else 'AL'}"
            if did not in RACES["house"]: errors.append(f"'{it}': {did} is not one of the House districts on the site"); continue
            if call == "I": errors.append(f"'{it}': no independent is running in {did}"); continue
            out.append(("house", did, call, it)); continue
        s = re.fullmatch(r"(?i)(.+?)\s+(sen|senate|gov|governor)(?:\s*\(special\))?", race)
        if not s: errors.append(f"'{it}': say Sen or Gov after the state (e.g. 'GA Sen D'), or give a House district like PA-07"); continue
        code = state_code(s.group(1)); kind = "senate" if s.group(2).lower().startswith("sen") else "gov"
        if not code: errors.append(f"'{it}': '{s.group(1)}' is not a state"); continue
        if code not in RACES[kind]: errors.append(f"'{it}': there is no {'Senate' if kind == 'senate' else 'governor'} race for {code} on the site"); continue
        row = RACES[kind][code]
        if call == "I" and not row.get("i"): errors.append(f"'{it}': no independent is on the ballot in that race"); continue
        if call == "D" and not row.get("d"): errors.append(f"'{it}': there is no Democratic nominee in that race"); continue
        out.append((kind, code, call, it))
    return out, errors

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("calls"); ap.add_argument("--page", default="index.html"); ap.add_argument("--results", default="results.json")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    D = load_data(a.page); RACES = races_on_site(D)
    try: R = json.load(open(a.results, encoding="utf-8"))
    except FileNotFoundError: R = dict(D["decisionNight"]["results"])
    for k in ("senate", "gov", "house"): R.setdefault(k, {})
    R.setdefault("houseCalled", {"D": 0, "R": 0}); R.setdefault("log", [])
    calls, errors = parse(a.calls, RACES)
    if errors:
        print("NOT PUBLISHED — fix these and run again (nothing was changed):"); [print("  - " + e) for e in errors]; return 2
    if not calls: print("Nothing to record."); return 2
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    changed = []
    for kind, rid, call, raw in calls:
        if kind == "houseCalled":
            if R["houseCalled"] != call: changed.append(f"House seats called: D {call['D']}, R {call['R']} (was D {R['houseCalled'].get('D', 0)}, R {R['houseCalled'].get('R', 0)})"); R["houseCalled"] = call
            continue
        label = rid if kind == "house" else f"{rid} {'Senate' if kind == 'senate' else 'Governor'}"
        if call == "-":
            if rid in R[kind]: del R[kind][rid]; changed.append(f"{label}: call withdrawn"); R["log"].append({"t": now, "race": f"{kind}:{rid}", "call": "-"})
            continue
        if R[kind].get(rid) == call: continue
        row = RACES[kind][rid]; who = row.get(call.lower()) or ""
        changed.append(f"{label}: {call}{' — ' + who if who else ''}{' (was ' + R[kind][rid] + ')' if rid in R[kind] else ''}")
        R[kind][rid] = call; R["log"].append({"t": now, "race": f"{kind}:{rid}", "call": call})
    if not changed: print("No change — those calls are already recorded."); return 3
    R["log"] = R["log"][-40:]
    R["updated"] = now
    et = datetime.datetime.now(ZoneInfo("America/New_York"))
    R["note"] = f"Race calls from the Associated Press, as of {et.strftime('%-I:%M %p')} ET."
    print(("DRY RUN — would record:" if a.dry_run else "Recorded:")); [print("  " + c) for c in changed]
    nS = len(R["senate"]); nG = len(R["gov"]); nH = len(R["house"])
    print(f"Totals: {nS} Senate, {nG} governor, {nH} battleground House calls; House seats called D {R['houseCalled']['D']} R {R['houseCalled']['R']}.")
    if not a.dry_run:
        open(a.results, "w", encoding="utf-8").write(json.dumps(R, ensure_ascii=False, indent=1) + "\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
