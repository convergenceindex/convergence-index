#!/usr/bin/env python3
"""
update_polls.py — refreshes the POLLING numbers inside index.html from individual polls.

Run by the GitHub workflow "Update market data" every 6 hours, right after update_markets.py.
It edits ONLY values inside `const DATA = {...}`; the page code is never touched.

Where the polls come from
  VoteHub polling API (free, no key, CC BY 4.0): https://api.votehub.com/polls
  Optional: Cook Political Report ratings (needs COOK_EMAIL / COOK_PASSWORD secrets).

How each race's polling margin is computed (Dem minus Rep; for Nebraska, Osborn minus Ricketts)
  1. Take every poll of that state's race that names BOTH of the row's candidates.
  2. Window: polls that ended in the last 30 days; if fewer than 2, the last 60 days.
  3. One poll per pollster — its most recent; when a pollster released likely- and
     registered-voter versions of the same poll, the likely-voter one.
  4. Weighted mean. Weight = recency (half-life 14 days) x sample size (square root, capped)
     x population (likely voters 1, registered 0.85, adults 0.7)
     x sponsorship (campaign/party internal polls 0.5; pollsters VoteHub flags as partisan 0.75).
  5. Cook rating, if available, is converted to a margin (Toss-up 0, Lean 5, Likely 8, Solid 13)
     and blended in: 25% when the race has 3+ recent polls, 50% when it has fewer, 100% when none.
Safety: a race whose number would move more than 10 points in one run is left unchanged and
reported. If VoteHub cannot be reached, nothing changes.

What it updates: poll {m, basis, url, date, partisan} of house/senate/governors rows,
senate.model.races[].m, and (only when markets did not already do it this run) prev/asOf/history.
It does NOT touch market prices, the generic ballot, names, ratings, weights or model parameters.

Usage: python update_polls.py index.html [--after-markets] [--dry-run]
Exit codes: 0 = page updated, 3 = nothing changed (or dry run), 1 = error.
"""
import base64, datetime, difflib, json, math, os, re, sys, time, urllib.parse, urllib.request

API = "https://api.votehub.com/polls"
UA = {"User-Agent": "convergence-index-updater/1.0 (+https://convergence-index.com)", "Accept": "application/json"}
TODAY = datetime.datetime.now(datetime.timezone.utc).date()
STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
  "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
  "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
  "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
  "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
  "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
  "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
  "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"}
ABBR = {v: k for k, v in STATES.items()}
COOK_MARGIN = {"toss": 0.0, "lean": 5.0, "likely": 8.0, "solid": 13.0}
MAX_MOVE = 10.0

def log(msg): print(msg, flush=True)

def get_json(url, headers=None, tries=3):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={**UA, **(headers or {})}), timeout=40) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e; time.sleep(3 * (i + 1))
    raise RuntimeError(f"{url}: {last}")

# ------------------------------------------------------------------ fetching
def fetch_votehub(poll_type, days=75):
    """All polls of one type that ended in the last `days` days, fetched in 10-day slices so a
    server-side page cap can never silently drop polls."""
    out, seen = [], set()
    start = TODAY - datetime.timedelta(days=days)
    while start <= TODAY:
        end = min(start + datetime.timedelta(days=9), TODAY)
        q = urllib.parse.urlencode({"poll_type": poll_type, "from_date": start.isoformat(), "to_date": end.isoformat()})
        js = get_json(f"{API}?{q}")
        rows = js if isinstance(js, list) else (js.get("polls") or js.get("data") or js.get("results") or [])
        if not isinstance(rows, list): raise RuntimeError(f"unexpected VoteHub response for {poll_type}")
        for p in rows:
            pid = p.get("id") or json.dumps(p, sort_keys=True)
            if pid not in seen: seen.add(pid); out.append(p)
        start = end + datetime.timedelta(days=1)
    return out

def fetch_cook():
    em, pw = os.environ.get("COOK_EMAIL"), os.environ.get("COOK_PASSWORD")
    if not em or not pw: return None
    auth = {"Authorization": "Basic " + base64.b64encode(f"{em}:{pw}".encode()).decode()}
    ratings = {}
    for kind in ("house", "senate", "governor"):
        try:
            js = get_json(f"https://cookpolitical.com/api/race/{kind}", auth)
            rows = js if isinstance(js, list) else (js.get("data") or js.get("races") or [])
            n = 0
            for r in rows:
                if str(r.get("Cycle") or "2026") != "2026" and "2026" not in str(r.get("Title", "")): continue
                key = r.get("District") if kind == "house" else r.get("State")
                if key and r.get("Rating"):
                    ratings[(kind, str(key).strip())] = {"rating": r["Rating"].strip(), "date": (r.get("Rating_date") or "")[:10]}; n += 1
            log(f"  Cook {kind}: {n} ratings")
        except Exception as e:
            log(f"  ! Cook {kind} not available: {e}")
    return ratings

def cook_margin(rating):
    """'Lean R' -> -5, 'Likely D' -> +8, 'Toss Up' -> 0. None if not understood."""
    s = rating.lower().replace("-", " ")
    if "toss" in s: return 0.0
    for k, v in COOK_MARGIN.items():
        if k in s:
            if re.search(r"\bd\b|dem", s): return v
            if re.search(r"\br\b|rep", s): return -v
    return None

# ------------------------------------------------------------------ matching
def norm(s): return re.sub(r"[^a-z ]", " ", (s or "").lower().replace("-", " ")).split()

def last_name(full):
    if not full: return None
    first = re.sub(r"\(.*?\)", "", full.split(",")[0])
    parts = [p for p in norm(first) if p not in ("jr", "sr", "ii", "iii", "iv")]
    return parts[-1] if parts else None

def same_name(cand_full, choice):
    ln = last_name(cand_full)
    if not ln: return False
    toks = norm(choice)
    if ln in toks: return True
    return len(ln) >= 5 and any(len(t) >= 5 and difflib.SequenceMatcher(None, ln, t).ratio() >= 0.85 for t in toks)

def pct_for(poll, cand):
    hits = [a for a in poll.get("answers") or [] if same_name(cand, a.get("choice", ""))]
    if len(hits) != 1: return None
    try: return float(hits[0]["pct"])
    except Exception: return None

def poll_in_place(poll, state, district=None):
    text = " ".join(str(poll.get(k) or "") for k in ("subject", "seat_name"))
    if district:
        seat = str(poll.get("seat_name") or "")
        if seat and re.sub(r"\W", "", seat.upper()) != re.sub(r"\W", "", district.upper()): return False
    return state.lower() in text.lower() or re.search(rf"\b{ABBR.get(state, '??')}\b", text) is not None

def days_old(p):
    try: return (TODAY - datetime.date.fromisoformat(str(p.get("end_date"))[:10])).days
    except Exception: return None

POP_W = {"lv": 1.0, "rv": 0.85, "a": 0.7}
def weight(p):
    w = 0.5 ** (max(days_old(p), 0) / 14)
    n = p.get("sample_size") or 600
    w *= min(max(math.sqrt(min(float(n), 2000) / 600), 0.5), 1.8)
    w *= POP_W.get(str(p.get("population") or "").lower(), 0.8)
    if p.get("internal") or (p.get("partisan") and p.get("sponsors")): w *= 0.5   # campaign / party / PAC-sponsored
    elif p.get("partisan"): w *= 0.75                                              # pollster with a partisan lean
    return w

SHORT = [("The New York Times", "NYT"), ("New York Times", "NYT"), ("Texas Southern University Barbara Jordan", "Texas Southern"), ("University of Massachusetts Lowell", "UMass Lowell"), ("Washington Post", "WaPo"),
         ("Center for Public Opinion", ""), ("Survey Research Center", ""), ("Barbara Jordan Center", ""), (" University", ""),
         (" College", ""), (" Research", ""), (" Polling", ""), (" Group", ""), (" Insights", ""), (" & Associates", ""),
         (", Lee", ""), ("Associates", "")]
def short_pollster(name):
    s = name or "?"
    for a, b in SHORT: s = s.replace(a, b)
    s = re.sub(r"\s+", " ", s).replace(" /", "/").strip(" /,")
    if len(s) > 26: s = s[:26].rsplit(" ", 1)[0]
    return s or (name or "?")[:26]

def fmt_m(m, a="D", b="R"):
    if abs(m) < 0.05: return "tie"
    return (a if m > 0 else b) + "+" + f"{abs(m):.1f}".rstrip("0").rstrip(".")

def race_average(polls, state, a, b, district=None, labels=("D", "R")):
    """Margin a - b from the polls that name both a and b. Returns dict or None."""
    cands = []
    for p in polls:
        if not poll_in_place(p, state, district): continue
        age = days_old(p)
        if age is None or age < 0 or age > 60: continue
        pa, pb = pct_for(p, a), pct_for(p, b)
        if pa is None or pb is None: continue
        others = [float(x.get("pct") or 0) for x in p.get("answers") or [] if not same_name(a, x.get("choice", "")) and not same_name(b, x.get("choice", ""))]
        if others and max(others) >= 15: continue          # a multi-candidate first-round ballot, not a head-to-head
        cands.append((p, pa - pb))
    for window in (30, 60):
        pool = [(p, m) for p, m in cands if days_old(p) <= window]
        if len({(p.get("pollster") or "").lower() for p, _ in pool}) >= 2 or window == 60: break
    best = {}
    for p, m in pool:
        k = re.sub(r"\W", "", (p.get("pollster") or "?").lower())
        rank = (str(p.get("end_date")), {"lv": 2, "rv": 1}.get(str(p.get("population")).lower(), 0))
        if k not in best or rank > best[k][0]: best[k] = (rank, p, m)
    use = [(p, m, weight(p)) for _, p, m in best.values()]
    if not use: return None
    W = sum(w for _, _, w in use)
    mean = sum(m * w for _, m, w in use) / W
    use.sort(key=lambda t: -t[2])
    newest = max(use, key=lambda t: str(t[0].get("end_date")))[0]
    # the page's "P" flag means sponsored by a campaign, party or PAC — not merely a pollster with a lean
    sponsored = sum(w for p, _, w in use if p.get("internal") or (p.get("partisan") and p.get("sponsors"))) / W
    d0 = min(str(p.get("end_date"))[:10] for p, _, _ in use); d1 = str(newest.get("end_date"))[:10]
    return {"m": round(mean, 1), "n": len(use), "from": d0, "to": d1, "url": newest.get("url"),
            "partisan": sponsored > 0.5,
            "top": ", ".join(f"{short_pollster(p.get('pollster'))} {fmt_m(m, *labels)}" for p, m, _ in use[:4]) + (" …" if len(use) > 4 else "")}

def newer_by(a, b):
    """Days by which date a is newer than date b (0 if unknown)."""
    try: return (datetime.date.fromisoformat(str(a)[:10]) - datetime.date.fromisoformat(str(b)[:10])).days
    except Exception: return 0

def md(d):
    try: return datetime.date.fromisoformat(d).strftime("%b %-d")
    except Exception: return d
def span(a, b):
    if a == b: return md(a)
    if a[:7] == b[:7]: return f"{md(a)}–{md(b).split()[-1]}"
    return f"{md(a)}–{md(b)}"

# ------------------------------------------------------------------ main
def main(path, after_markets, dry):
    src = open(path, encoding="utf-8").read()
    k = src.index("const DATA = "); st = src.index("{", k)
    D, end = json.JSONDecoder().raw_decode(src, st)
    orig = json.loads(json.dumps(D))

    log("Fetching polls from VoteHub")
    try:
        polls = {t: fetch_votehub(t) for t in ("us-senator", "governor", "us-representative")}
    except Exception as e:
        log(f"VoteHub unavailable — polling left unchanged: {e}"); return 3
    for t, v in polls.items(): log(f"  {t}: {len(v)} polls in the last 75 days")
    if sum(len(v) for v in polls.values()) < 20:
        log("Suspiciously few polls returned — polling left unchanged."); return 3
    cook = fetch_cook()
    log("  Cook ratings: " + ("not configured (COOK_EMAIL / COOK_PASSWORD secrets not set)" if cook is None else f"{len(cook)} loaded"))

    changes, held, table = 0, [], []
    def update_row(row, kind, state, district=None, label=None):
        nonlocal changes
        label = label or row.get("id")
        d, r, i = row.get("d"), row.get("r"), row.get("i")
        a, b, who = (d, r, None) if d else (i, r, i)
        if not a or not b: return None
        labels = ("D", "R") if d else (last_name(i).title(), "R")
        avg = race_average(polls[{"senate": "us-senator", "governor": "governor", "house": "us-representative"}[kind]], state, a, b, district, labels)
        cr = cook.get((kind, district or state)) if cook else None
        cm = cook_margin(cr["rating"]) if cr else None
        if avg is None and cm is None: table.append((label, (row.get("poll") or {}).get("m"), None, "no recent polls — kept")); return None
        if avg is None:
            m, w = cm, 1.0
        elif cm is None:
            m, w = avg["m"], 0.0
        else:
            w = 0.25 if avg["n"] >= 3 and days_old({"end_date": avg["to"]}) <= 21 else 0.5
            m = round((1 - w) * avg["m"] + w * cm, 1)
        old = row.get("poll") or {}
        if avg and cm is None and old.get("m") is not None and newer_by(old.get("date"), avg["to"]) > 3:
            # VoteHub hasn't picked up the polls the current number is based on — never replace with older data
            table.append((label, old.get("m"), old.get("m"), f"kept — current number uses newer polls (to {old['date']}) than VoteHub has (to {avg['to']})"))
            return old.get("m")
        if old.get("m") is not None and abs(m - old["m"]) > MAX_MOVE:
            held.append(f"{label}: {fmt_m(old['m'])} → {fmt_m(m)} (move > {MAX_MOVE:g} pts — left unchanged, please review)")
            table.append((label, old.get("m"), m, "HELD")); return None
        if avg:
            basis = f"Our average of {avg['n']} poll{'s' if avg['n'] != 1 else ''}, {span(avg['from'], avg['to'])}: {avg['top']}"
        else:
            basis = "No recent polls"
        if cm is not None:
            basis += f" · Cook: {cr['rating']}" + (f" ({int(w * 100)}% weight)" if avg else "")
        new = {"m": m, "basis": basis, "url": (avg or {}).get("url") or old.get("url") or "https://www.cookpolitical.com/ratings",
               "date": (avg or {}).get("to") or (cr or {}).get("date") or old.get("date"), "partisan": bool(avg and avg["partisan"])}
        if who: new["who"] = last_name(who).title() if not old.get("who") else old["who"]
        table.append((label, old.get("m"), m, basis[:110]))
        if any(new.get(x) != old.get(x) for x in ("m", "basis", "date", "url", "partisan")):
            row["poll"] = {**old, **new}; changes += 1
        return m

    log("Senate")
    senate_m = {}
    for row in D["senate"]["races"]:
        state = row["id"].replace(" (special)", "")
        m = update_row(row, "senate", state)
        senate_m[state] = (row.get("poll") or {}).get("m")
    for row in D["senate"]["all"]["races"]:           # model-only states (e.g. Georgia, North Carolina, Minnesota)
        if row["name"] in senate_m: continue
        if not any(x["st"] == row["name"] for x in D["senate"]["model"]["races"]): continue
        avg = race_average(polls["us-senator"], row["name"], row["d"], row["r"])
        cr = cook.get(("senate", row["name"])) if cook else None
        cm = cook_margin(cr["rating"]) if cr else None
        if avg:
            w = 0 if cm is None else (0.25 if avg["n"] >= 3 else 0.5)
            senate_m[row["name"]] = round((1 - w) * avg["m"] + w * (cm or 0), 1)
            table.append((row["name"] + " (model)", None, senate_m[row["name"]], f"{avg['n']} polls: {avg['top']}"[:110]))
        elif cm is not None:
            senate_m[row["name"]] = cm
    for mr in D["senate"]["model"]["races"]:
        v = senate_m.get(mr["st"])
        if v is None: continue
        if abs(v - mr["m"]) > MAX_MOVE: held.append(f"Senate model {mr['st']}: {fmt_m(mr['m'])} → {fmt_m(v)} held"); continue
        if v != mr["m"]: mr["m"] = v; changes += 1
    log("Governors")
    for row in D["governors"]["races"]: update_row(row, "governor", row["id"])
    log("House")
    for row in D["house"]["races"]:
        st_ = STATES.get(row["id"][:2])
        if st_: update_row(row, "house", st_, district=row["id"])

    log("")
    log(f"{'Race':28} {'old':>7} {'new':>7}  basis")
    for lab, o, n, b in table:
        log(f"{lab[:28]:28} {fmt_m(o) if o is not None else '—':>7} {fmt_m(n) if n is not None else '—':>7}  {b}")
    for h in held: log("  ! " + h)
    log(f"\n{changes} polling values changed.")

    if dry:
        log("DRY RUN — nothing was written. (Scheduled runs are live unless the repository variable POLLS_LIVE is set to 'no'.)"); return 3
    if changes == 0: return 3

    # sources list: credit VoteHub (and Cook when used)
    srcs = D.get("sources") or []
    for grp in srcs:
        if isinstance(grp, list) and grp and grp[0] == "Polling averages":
            items = grp[1]
            want = [["VoteHub — individual Senate, governor and House polls (CC BY 4.0)", "https://votehub.com/polls/"]]
            if cook: want.append(["Cook Political Report — race ratings", "https://www.cookpolitical.com/ratings"])
            for w_ in want:
                if not any(x[1] == w_[1] for x in items): items.append(w_)

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    S = D["senate"]
    if after_markets and D["history"] and D["history"][-1].get("t") == D["asOf"]:
        D["history"][-1]["senate"]["m"] = [r["m"] for r in S["model"]["races"]]   # the entry markets appended this run
    else:
        prev = {"t": orig["asOf"], "races": {}}
        for ch, key in (("house", "house"), ("senate", "senate"), ("governors", "gov")):
            for r in orig[ch]["races"]:
                m = r.get("mkt") or {}
                prev["races"][f"{key}:{r['id']}"] = {"d": m.get("d"), "r": m.get("r"), "i": m.get("i"), "pm": (r.get("poll") or {}).get("m")}
        D["prev"] = prev; D["asOf"] = now
        H = D["house"]["markets"]; SM = S["markets"]
        D["history"].append({"t": now,
            "house": {"k": [H["kalshi"]["bid"], H["kalshi"]["ask"]], "p": [H["polymarket"]["bid"], H["polymarket"]["ask"]], "gb": [g.get("m") for g in D["house"]["genericBallot"]]},
            "senate": {"k": [SM["kalshi"]["bid"], SM["kalshi"]["ask"]], "p": [SM["polymarket"]["bid"], SM["polymarket"]["ask"]], "m": [r["m"] for r in S["model"]["races"]]}})
    open(path, "w", encoding="utf-8").write(src[:st] + json.dumps(D, ensure_ascii=False, separators=(",", ":")) + src[end:])
    log(f"Updated {path}")
    return 0

if __name__ == "__main__":
    args = sys.argv[1:]
    path = next((a for a in args if not a.startswith("--")), "index.html")
    try:
        sys.exit(main(path, "--after-markets" in args, "--dry-run" in args))
    except Exception as e:
        import traceback; traceback.print_exc(); print(f"ERROR: {e}"); sys.exit(1)
