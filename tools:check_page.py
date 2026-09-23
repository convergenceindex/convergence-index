#!/usr/bin/env python3
"""
check_page.py — safety gate for The Convergence Index.

Run it BEFORE publishing an updated page. It refuses (exit code 1) unless:
  1. CODE FREEZE: everything outside the `const DATA = {...};` object is byte-for-byte
     identical to the previously published page (updates may change data only).
  2. DATA SHAPE: the data has the structure the page's code expects.
  3. RENDER: the page loads in headless Chromium with no JavaScript errors, the
     headline percentages render, and no NaN / undefined / Infinity appears.

Usage:
  python3 check_page.py --prev PREVIOUS.html --new NEW.html
  python3 check_page.py --new NEW.html            (skip the code-freeze comparison)
"""
import argparse, json, math, re, sys, os, datetime

def load(path):
    return open(path, encoding="utf-8").read()

def split_data(src):
    """Return (before, data_obj, after) around the DATA object."""
    k = src.find("const DATA = ")
    if k < 0:
        raise ValueError("`const DATA = ` not found")
    start = src.index("{", k)
    obj, end = json.JSONDecoder().raw_decode(src, start)
    return src[:start], obj, src[end:]

def page_part(src):
    """The artifact viewer may wrap the page; compare from <title> onward."""
    i = src.find("<title>")
    body = src[i:] if i >= 0 else src
    return re.sub(r"\s*</body>\s*</html>\s*$", "", body).rstrip()

# ---------------------------------------------------------------- shape checks
def is_num(x): return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)

def check_shape(D, errs):
    def need(cond, msg):
        if not cond: errs.append(msg)
    for key in ["asOf", "weights", "house", "senate", "governors", "sources", "history", "decisionNight"]:
        need(key in D, f"DATA.{key} missing")
    if errs: return
    try: datetime.datetime.fromisoformat(D["asOf"].replace("Z", "+00:00"))
    except Exception: errs.append(f"DATA.asOf is not an ISO time: {D.get('asOf')!r}")
    for ch in ["house", "senate"]:
        C = D[ch]
        for m in ["kalshi", "polymarket"]:
            mk = C.get("markets", {}).get(m, {})
            need(is_num(mk.get("bid")) and is_num(mk.get("ask")) and 0 <= mk["bid"] <= 100 and 0 <= mk["ask"] <= 100,
                 f"{ch}.markets.{m} bid/ask must be numbers in cents 0–100, got {mk.get('bid')!r}/{mk.get('ask')!r}")
        sm = C.get("seatMarket", {})
        br = sm.get("brackets")
        need(isinstance(br, list) and len(br) >= 5, f"{ch}.seatMarket.brackets missing or too short")
        for b in br or []:
            ok = (isinstance(b, list) and len(b) == 4 and isinstance(b[0], str) and is_num(b[1])
                  and is_num(b[2]) and is_num(b[3]) and 0 <= b[2] <= 1 and 0 <= b[3] <= 1)
            if not ok:
                errs.append(f"{ch}.seatMarket bracket must be [label, midpoint, bid, ask] with bid/ask in dollars 0–1; got {b!r}")
                break
        need(is_num(sm.get("majority")), f"{ch}.seatMarket.majority missing")
    for g in D["house"].get("genericBallot", []):
        need(isinstance(g, dict) and "src" in g and (g.get("m") is None or is_num(g["m"])), f"bad genericBallot entry {g!r}")
    need(len(D["house"].get("genericBallot", [])) == 4, "house.genericBallot must have the 4 sources")
    for r in D["senate"].get("model", {}).get("races", []):
        need(is_num(r.get("m")), f"senate.model race margin not a number: {r!r}")
    for ch in ["house", "senate", "governors"]:
        races = D[ch].get("races", [])
        need(len(races) > 0, f"{ch}.races is empty")
        seen = set()
        for r in races:
            rid = r.get("id")
            need(isinstance(rid, str) and rid, f"{ch} race without id")
            need(rid not in seen, f"duplicate {ch} race {rid}"); seen.add(rid)
            m = r.get("mkt")
            if m is None: continue
            for side in ["d", "r", "i"]:
                v = m.get(side)
                if v is None: continue
                if not (isinstance(v, list) and len(v) == 2 and all(is_num(x) and 0 <= x <= 1 for x in v)):
                    errs.append(f"{ch} {rid}: mkt.{side} must be [bid, ask] in dollars 0–1, got {v!r}")
            need((m.get("d") or m.get("i")) is not None and m.get("r") is not None, f"{ch} {rid}: market needs r and d (or i)")
            p = r.get("poll")
            if p is not None:
                need(is_num(p.get("m")), f"{ch} {rid}: poll.m not a number")
    prev = D.get("prev")
    if prev:
        keys = list((prev.get("races") or {}).keys())
        bad = [k for k in keys if not re.match(r"^(house|senate|gov):", k)]
        need(not bad, f"prev.races keys must be '<house|senate|gov>:<id>' (Iowa and Alaska each have a Senate AND a governor race); bad keys: {bad[:5]}")
    H = D["history"]
    need(isinstance(H, list) and len(H) >= 1, "history must be a non-empty list")
    ts = [h.get("t") for h in H]
    need(ts == sorted(ts), "history must be in time order")

def check_history_append_only(P, D, errs):
    ph, nh = P.get("history", []), D.get("history", [])
    if nh[:len(ph)] != ph:
        errs.append("history entries were edited or removed (only appending one new entry is allowed)")
    if len(nh) > len(ph) + 1:
        errs.append(f"more than one history entry added ({len(nh) - len(ph)})")

# ---------------------------------------------------------------- render check
def render(path, errs):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        os.system(f"{sys.executable} -m pip install -q playwright --break-system-packages >/dev/null 2>&1")
        from playwright.sync_api import sync_playwright
    exe = "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(**({"executable_path": exe} if exe else {}))
        except Exception:
            b = p.chromium.launch()
        for vp in [{"width": 1200, "height": 900}, {"width": 390, "height": 844}]:
            pg = b.new_page(viewport=vp)
            jserr = []
            pg.on("pageerror", lambda e: jserr.append(str(e)))
            pg.goto("file://" + os.path.abspath(path))
            pg.wait_for_timeout(2500)
            for t in ["senate", "governors", "house"]:
                pg.click(f'.tab-btn[data-chamber="{t}"]'); pg.wait_for_timeout(300)
            hv, sv = pg.inner_text("#houseBlendValue").strip(), pg.inner_text("#senateBlendValue").strip()
            if not re.fullmatch(r"\d{1,3}%", hv): errs.append(f"House headline did not render (shows {hv!r}) at width {vp['width']}")
            if not re.fullmatch(r"\d{1,3}%", sv): errs.append(f"Senate headline did not render (shows {sv!r}) at width {vp['width']}")
            bad = pg.evaluate("(document.body.innerText.match(/\\bNaN\\b|\\bundefined\\b|Infinity/g) || []).slice(0,5)")
            if bad: errs.append(f"page text contains {bad} at width {vp['width']}")
            for sel, what in [("#chamber-house .race-row", "House race rows"), ("#chamber-senate .race-row", "Senate race rows"),
                              ("#endnotesList li", "source endnotes")]:
                if pg.locator(sel).count() == 0: errs.append(f"no {what} rendered")
            if jserr: errs.append(f"JavaScript error(s): {jserr[:3]}")
            pg.close()
            if errs: break
        b.close()
    return hv, sv

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prev"); ap.add_argument("--new", required=True)
    ap.add_argument("--no-render", action="store_true")
    a = ap.parse_args()
    errs = []
    new = load(a.new)
    try:
        nb, D, na = split_data(new)
    except Exception as e:
        print(f"FAIL: cannot read DATA from new page: {e}"); return 1
    if a.prev:
        prev = load(a.prev)
        try:
            pb, P, pa = split_data(prev)
        except Exception as e:
            print(f"FAIL: cannot read DATA from previous page: {e}"); return 1
        if page_part(pb) != page_part(nb) or page_part(pa) != page_part(na):
            import difflib
            d = list(difflib.unified_diff(page_part(pb + "@@DATA@@" + pa).splitlines(),
                                          page_part(nb + "@@DATA@@" + na).splitlines(), "previous", "new", n=0, lineterm=""))
            errs.append("CODE FREEZE: page code outside DATA changed (updates may edit DATA only). First differences:\n    "
                        + "\n    ".join(x[:160] for x in d[:12]))
        check_history_append_only(P, D, errs)
    check_shape(D, errs)
    hv = sv = None
    if not errs and not a.no_render:
        hv, sv = render(a.new, errs)
    if errs:
        print("FAIL — do NOT publish:"); [print(" -", e) for e in errs]; return 1
    print(f"PASS — safe to publish. asOf {D['asOf']}" + (f"; House {hv}, Senate {sv}" if hv else ""))
    return 0

if __name__ == "__main__":
    sys.exit(main())
