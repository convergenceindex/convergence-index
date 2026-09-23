#!/usr/bin/env python3
"""
update_markets.py — refreshes the PREDICTION-MARKET numbers inside index.html.

Run by the GitHub workflow "Update market data" every 6 hours, on GitHub's servers
(which can reach Kalshi's and Polymarket's public APIs). It edits ONLY values inside
`const DATA = {...}`; the page code is never touched. The workflow then runs
check_page.py and publishes only if that prints PASS.

What it updates (from public JSON APIs, no keys needed):
  - House / Senate control: Kalshi CONTROLH / CONTROLS, Polymarket "Democratic Party" market
  - Seat brackets: Kalshi KXDHOUSESEATS / KXDSENATESEATS (the "-27" event = the Congress elected in 2026)
  - Race markets: every row's Kalshi mkt.url (the "-26" event = the 2026 election)
  - DATA.prev (for the "What changed" box), DATA.history (one new entry), DATA.asOf
What it does NOT touch: polling numbers, names, ratings, composition, weights, model settings,
decisionNight.results. Anything it cannot fetch or match cleanly keeps its previous value.

Exit codes: 0 = page updated, 3 = nothing could be updated (page left unchanged), 1 = error.
"""
import datetime, json, re, sys, time, urllib.request, urllib.error

UA = {"User-Agent": "convergence-index-updater/1.0 (+https://convergence-index.com)", "Accept": "application/json"}
LOG = []
def log(msg): LOG.append(msg); print(msg, flush=True)

def get_json(url, tries=3):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e; time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {last}")

def dollars(m, side):
    """Kalshi price in dollars (0–1). New API: yes_bid_dollars '0.5500'; old API: yes_bid 55 (cents)."""
    v = m.get(f"yes_{side}_dollars")
    if v not in (None, ""): return float(v)
    v = m.get(f"yes_{side}")
    return None if v is None else float(v) / 100.0

def good_quote(b, a, max_spread=0.25):
    return b is not None and a is not None and 0 <= b <= a <= 1 and (a - b) <= max_spread and a > 0

def r4(x): return round(x, 4)

# ------------------------------------------------------------------ chamber control
def update_control(D, ch):
    C = D[ch]["markets"]; changed = 0
    k = C["kalshi"]
    try:
        js = get_json(k["url"])
        mk = next((m for m in js.get("markets", []) if m.get("ticker") == k["ticker"]), None)
        if mk is None: raise RuntimeError(f"ticker {k['ticker']} not in response")
        b, a = dollars(mk, "bid"), dollars(mk, "ask")
        if not good_quote(b, a): raise RuntimeError(f"bad quote {b}/{a}")
        k["bid"], k["ask"] = round(b * 100, 1), round(a * 100, 1); changed += 1
        log(f"  {ch} Kalshi control: {k['bid']}¢ / {k['ask']}¢")
    except Exception as e:
        log(f"  ! {ch} Kalshi control kept at {k['bid']}/{k['ask']}: {e}")
    p = C["polymarket"]
    try:
        js = get_json(p["url"])
        ev = js[0] if isinstance(js, list) and js else js
        mk = next((m for m in ev.get("markets", []) if "democrat" in (m.get("groupItemTitle") or m.get("question") or "").lower()), None)
        if mk is None: raise RuntimeError("no Democratic market in event")
        b, a = float(mk["bestBid"]), float(mk["bestAsk"])
        if not good_quote(b, a): raise RuntimeError(f"bad quote {b}/{a}")
        p["bid"], p["ask"] = round(b * 100, 1), round(a * 100, 1); changed += 1
        log(f"  {ch} Polymarket control: {p['bid']}¢ / {p['ask']}¢")
    except Exception as e:
        log(f"  ! {ch} Polymarket control kept at {p['bid']}/{p['ask']}: {e}")
    return changed

# ------------------------------------------------------------------ seat brackets
def label_range(s):
    s = s.strip().replace("–", "-").replace("—", "-").lower()
    n = [int(x) for x in re.findall(r"\d+", s)]
    if not n: return None
    if s.startswith(("below", "under", "fewer", "less")): return (-1, n[0] - 1)
    if s.startswith(("above", "over", "more")): return (n[0] + 1, 10**6)
    if s.endswith("+") or "or more" in s: return (n[0], 10**6)
    if len(n) >= 2: return (n[0], n[1])
    return (n[0], n[0])

def update_seats(D, ch):
    sm = D[ch]["seatMarket"]
    try:
        js = get_json(sm["url"])
        evs = [e for e in js.get("events", []) if str(e.get("event_ticker", "")).endswith("-27")]
        if len(evs) != 1: raise RuntimeError(f"expected one '-27' event, found {[e.get('event_ticker') for e in js.get('events', [])]}")
        by_range = {}
        for m in evs[0].get("markets", []):
            rg = label_range(m.get("yes_sub_title") or m.get("subtitle") or "")
            if rg: by_range[rg] = m
        new = []
        for b in sm["brackets"]:
            m = by_range.get(label_range(b[0]))
            if m is None: raise RuntimeError(f"no Kalshi bracket matches '{b[0]}'")
            bid, ask = dollars(m, "bid"), dollars(m, "ask")
            if not good_quote(bid, ask, 0.3): raise RuntimeError(f"bad quote for '{b[0]}': {bid}/{ask}")
            new.append([b[0], b[1], r4(bid), r4(ask)])
        sm["brackets"] = new
        log(f"  {ch} seat brackets: {len(new)} updated ({evs[0]['event_ticker']})")
        return 1
    except Exception as e:
        log(f"  ! {ch} seat brackets kept: {e}")
        return 0

# ------------------------------------------------------------------ race markets
def last_name(full):
    if not full: return None
    parts = re.sub(r"\(.*?\)", "", full.split(",")[0]).replace(" Jr.", "").replace(" Sr.", "").split()
    return parts[-1].lower() if parts else None

def side_of(m, row):
    t = str(m.get("ticker", "")).upper()
    suf = t.rsplit("-", 1)[-1] if "-" in t else ""
    if suf in ("D", "R", "I"): return suf.lower()
    text = " ".join(str(m.get(k) or "") for k in ("yes_sub_title", "subtitle", "title")).lower()
    for s in ("d", "r", "i"):
        ln = last_name(row.get(s))
        if ln and ln in text: return s
    if "democrat" in text: return "d"
    if "republican" in text: return "r"
    if "independent" in text: return "i"
    return None

def race_event_markets(url):
    js = get_json(url)
    if "event" in js:                                   # /events/<TICKER>
        mk = js.get("markets") or js["event"].get("markets") or []
        return js["event"].get("event_ticker", ""), mk
    evs = [e for e in js.get("events", []) if str(e.get("event_ticker", "")).endswith("-26")]
    if len(evs) != 1: raise RuntimeError(f"expected one '-26' event, found {[e.get('event_ticker') for e in js.get('events', [])]}")
    return evs[0]["event_ticker"], evs[0].get("markets", [])

def update_race(row, label):
    m0 = row.get("mkt")
    if not isinstance(m0, dict) or not m0.get("url") or "kalshi.com" not in m0["url"]:
        return 0, False                                   # no market, or a non-Kalshi market: leave as is
    try:
        ev, markets = race_event_markets(m0["url"])
        got = {}
        for m in markets:
            if str(m.get("status", "active")).lower() not in ("active", "open"): continue
            s = side_of(m, row)
            if s is None: continue
            if s in got: raise RuntimeError(f"two markets map to side {s}")
            b, a = dollars(m, "bid"), dollars(m, "ask")
            if not good_quote(b, a, 0.3): raise RuntimeError(f"bad quote for {s}: {b}/{a}")
            got[s] = [r4(b), r4(a)]
        needed = [s for s in ("d", "r", "i") if m0.get(s) is not None]
        missing = [s for s in needed if s not in got]
        if missing: raise RuntimeError(f"no market for side(s) {missing} in {ev}")
        for s in needed: m0[s] = got[s]
        return 1, True
    except Exception as e:
        log(f"  ! {label}: kept previous prices ({e})")
        return 0, True

# ------------------------------------------------------------------ main
def main(path):
    src = open(path, encoding="utf-8").read()
    k = src.index("const DATA = "); st = src.index("{", k)
    D, end = json.JSONDecoder().raw_decode(src, st)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # snapshot for the "What changed" box — taken BEFORE any price changes
    prev = {"t": D["asOf"], "races": {}}
    for ch, key in (("house", "house"), ("senate", "senate"), ("governors", "gov")):
        for r in D[ch]["races"]:
            m = r.get("mkt") or {}
            prev["races"][f"{key}:{r['id']}"] = {"d": m.get("d"), "r": m.get("r"), "i": m.get("i"), "pm": (r.get("poll") or {}).get("m")}

    log("Chamber control")
    n = update_control(D, "house") + update_control(D, "senate")
    log("Seat brackets")
    n += update_seats(D, "house") + update_seats(D, "senate")
    log("Race markets")
    tried = ok = 0
    groups = [("house", D["house"]["races"], "id"), ("senate", D["senate"]["races"], "id"), ("governors", D["governors"]["races"], "id"),
              ("senate.all", D["senate"]["all"]["races"], "name"), ("houseMore", D["decisionNight"]["houseMore"], "id")]
    cache = {}
    for g, rows, idk in groups:
        for r in rows:
            u = (r.get("mkt") or {}).get("url") if isinstance(r.get("mkt"), dict) else None
            if u in cache and cache[u] is not None:     # same market used twice (e.g. senate row and senate.all row)
                for s in ("d", "r", "i"):
                    if r["mkt"].get(s) is not None and cache[u].get(s) is not None: r["mkt"][s] = cache[u][s]
                continue
            got, attempted = update_race(r, f"{g} {r.get(idk)}")
            tried += attempted; ok += got
            if u: cache[u] = dict(r["mkt"]) if got else None
    log(f"  {ok} of {tried} race markets updated")
    n += ok

    if n == 0:
        log("Nothing could be updated — page left unchanged."); return 3
    if n < 4 + (tried // 2):
        log("Fewer than half of the markets updated — treating this run as failed; page left unchanged."); return 3

    D["prev"] = prev
    D["asOf"] = now
    H, S = D["house"]["markets"], D["senate"]["markets"]
    D["history"].append({"t": now,
        "house": {"k": [H["kalshi"]["bid"], H["kalshi"]["ask"]], "p": [H["polymarket"]["bid"], H["polymarket"]["ask"]], "gb": [g.get("m") for g in D["house"]["genericBallot"]]},
        "senate": {"k": [S["kalshi"]["bid"], S["kalshi"]["ask"]], "p": [S["polymarket"]["bid"], S["polymarket"]["ask"]], "m": [r["m"] for r in D["senate"]["model"]["races"]]}})
    open(path, "w", encoding="utf-8").write(src[:st] + json.dumps(D, ensure_ascii=False, separators=(",", ":")) + src[end:])
    log(f"Updated {path}: asOf {now}")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "index.html"))
    except Exception as e:
        print(f"ERROR: {e}"); sys.exit(1)
