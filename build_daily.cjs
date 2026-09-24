#!/usr/bin/env node
/* Daily social graphics for The Convergence Index — Monday–Friday rotation, news-weighted.
 *
 *   node build_daily.cjs <repoDir> <outDir> [--theme board|spotlight|pvm|path|week] [--yesterday page.html] [--week page.html]
 *
 * <repoDir> is a git clone of the site repo (clone WITH history, e.g. `git clone --filter=blob:none ...`).
 * Today's numbers come from <repoDir>/index.html. "Yesterday" and "a week ago" are earlier versions of
 * index.html found in the git history (chosen by each page's own DATA.asOf). Every page is loaded in
 * headless Chromium so the page's OWN code computes the numbers — graphics always match the site.
 *
 * Rotation:  Mon board (+ what changed since Friday) · Tue race spotlight · Wed polls vs markets
 *            · Thu Senate path to 51 · Fri week in review.  Weekends: nothing (exit 0, no files).
 * News weight (vs. yesterday):
 *   BIG  = a chamber moved ≥3 pts, or a race's favorite flipped, or a race moved ≥10 pts
 *          → main post becomes the "What changed" carousel; the day's theme moves to the story.
 *   SOME = a chamber moved ≥1.5 pts or a race moved ≥6 pts → theme is the main post, story = what changed.
 *   QUIET → theme is the main post, story = the day's theme story.
 * Framing is non-partisan: races/chambers are described by whoever is favored.
 *
 * Output (outDir): post-1.png … (1080x1080; several = carousel), story.png (1080x1920),
 *                  captions.md, plan.json, social-kit.html (everything, for the Social kit page).
 */
const fs = require('fs'), path = require('path'), os = require('os'), cp = require('child_process');
let chromium;
try { chromium = require('playwright').chromium; } catch (e) { console.error('npm install playwright'); process.exit(2); }

const argv = process.argv.slice(2);
const REPO = argv[0], OUT = argv[1];
const opt = k => { const i = argv.indexOf('--' + k); return i > 0 ? argv[i + 1] : null; };
if (!REPO || !OUT) { console.error('usage: node build_daily.cjs <repoDir> <outDir> [--theme X] [--yesterday f] [--week f]'); process.exit(2); }
fs.mkdirSync(OUT, { recursive: true });

// ---------------------------------------------------------------- fonts & style
const FDIR = [path.join(__dirname, 'fonts'), path.join(REPO, 'fonts'), path.join(__dirname, 'tools', 'fonts')].find(d => fs.existsSync(path.join(d, 'newsreader.woff2')));
const b64 = f => fs.readFileSync(path.join(FDIR, f)).toString('base64');
const FONTS = `
@font-face{font-family:'Newsreader';src:url(data:font/woff2;base64,${b64('newsreader.woff2')});font-weight:200 800;font-style:normal}
@font-face{font-family:'Newsreader';src:url(data:font/woff2;base64,${b64('newsreader-italic.woff2')});font-weight:200 800;font-style:italic}
@font-face{font-family:'IBM Plex Mono';src:url(data:font/woff2;base64,${b64('plex-400.woff2')});font-weight:400}
@font-face{font-family:'IBM Plex Mono';src:url(data:font/woff2;base64,${b64('plex-500.woff2')});font-weight:500}
@font-face{font-family:'IBM Plex Mono';src:url(data:font/woff2;base64,${b64('plex-600.woff2')});font-weight:600}`;
const LOGO = '<svg viewBox="0 0 120 60"><path d="M6 12 C40 12,44 28,60 30" fill="none" stroke="#2c4a7a" stroke-width="5" stroke-linecap="round"/><path d="M6 48 C40 48,44 32,60 30" fill="none" stroke="#17171a" stroke-width="5" stroke-linecap="round"/><circle cx="62" cy="30" r="8" fill="#2c4a7a"/></svg>';
const DEM = '#2c4a7a', REP = '#9b3a2e', GOLD = '#9a7016', POLL = '#6b5b95', MKT = '#2f6f73';
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const CSS = `${FONTS}
:root{--paper:#fcfbf8;--ink:#17171a;--ink2:#5d5b56;--ink3:#75726b;--hair:#dcd9d2;--dem:${DEM};--rep:${REP};--gold:${GOLD};--poll:${POLL};--mkt:${MKT};--serif:'Newsreader',Georgia,serif;--mono:'IBM Plex Mono',monospace}
*{box-sizing:border-box;margin:0}
body{background:#333}
.card{background:var(--paper);color:var(--ink);position:relative;overflow:hidden;display:flex;flex-direction:column}
.sq{width:1080px;height:1080px;padding:84px 84px 76px}
.st{width:1080px;height:1920px;padding:150px 96px 130px}
.top{border-top:4px solid var(--ink)}
.kick{font-family:var(--mono);font-size:23px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink2);font-weight:500;margin-top:20px;display:flex;justify-content:space-between}
.brand{display:flex;align-items:center;gap:15px;margin-top:20px}
.brand svg{width:54px;height:auto;flex:none}
.brand .nm{font-family:var(--serif);font-size:33px}
.foot{margin-top:auto;padding-top:26px;border-top:1px solid var(--hair);display:flex;justify-content:space-between;align-items:baseline;font-family:var(--mono);font-size:22px;color:var(--ink3)}
.foot b{color:var(--ink);font-weight:600}
.tag{font-family:var(--serif);font-style:italic;color:var(--ink2)}
.head{font-family:var(--serif);font-weight:300;font-size:84px;line-height:1.06;letter-spacing:-.02em;margin-top:56px}
.st .head{font-size:100px}
.sub{font-family:var(--serif);font-style:italic;font-size:30px;color:var(--ink2);margin-top:18px;line-height:1.35}
.mono{font-family:var(--mono);font-size:22px;color:var(--ink3);letter-spacing:.06em;text-transform:uppercase}
.ch{padding:30px 0;border-bottom:1px solid var(--hair)}
.ch:last-child{border-bottom:none}
.ch .lab{font-family:var(--mono);font-size:23px;text-transform:uppercase;letter-spacing:.08em;color:var(--ink2);display:flex;justify-content:space-between}
.ch .lab .dl{font-weight:600;letter-spacing:.04em}
.ch .nums{display:flex;align-items:baseline;gap:26px;margin-top:14px;font-family:var(--serif);font-weight:300;letter-spacing:-.03em}
.ch .from{font-size:76px;color:var(--ink3)}
.ch .arr{font-family:var(--mono);font-size:44px;color:var(--ink3)}
.ch .to{font-size:112px;line-height:1}
.ch .u{font-size:34px;font-style:italic;color:var(--ink2);letter-spacing:0;margin-left:4px}
.mv{display:grid;grid-template-columns:1fr auto;column-gap:20px;padding:22px 0;border-bottom:1px solid var(--hair);align-items:center}
.mv:last-child{border-bottom:none}
.mv .nm{font-family:var(--serif);font-size:38px;line-height:1.1}
.mv .who{font-family:var(--mono);font-size:20px;color:var(--ink2);margin-top:6px;letter-spacing:.02em}
.mv .ft{font-family:var(--mono);font-size:30px;text-align:right;white-space:nowrap}
.mv .ft .a{color:var(--ink3)} .mv .ft .b{font-weight:600}
.mv .dd{font-family:var(--mono);font-size:21px;text-align:right;margin-top:6px}
.flip{display:inline-block;font-family:var(--mono);font-size:17px;font-weight:600;letter-spacing:.1em;padding:3px 9px;border:2px solid currentColor;margin-left:12px;vertical-align:middle}
.bar{position:relative;height:16px;background:var(--hair);margin-top:26px}
.bar .f{position:absolute;top:0;bottom:0}
.bar .m50{position:absolute;left:50%;top:-10px;bottom:-10px;width:2px;background:var(--ink)}
.big{font-family:var(--serif);font-weight:300;font-size:200px;line-height:.95;letter-spacing:-.04em}
.st .big{font-size:240px}
.db{position:relative;height:84px;margin:44px 0 8px}
.db .track{position:absolute;left:0;right:0;top:34px;height:2px;background:var(--hair)}
.db .seg{position:absolute;top:32px;height:6px;background:color-mix(in srgb,var(--gold) 55%,transparent)}
.db .pt{position:absolute;top:26px;width:20px;height:20px;border-radius:50%;transform:translateX(-50%);box-shadow:0 0 0 4px var(--paper)}
.db .pt.p{background:var(--poll)} .db .pt.m{background:var(--mkt)}
.db .cap{position:absolute;top:56px;transform:translateX(-50%);font-family:var(--mono);font-size:21px;white-space:nowrap}
.db .cap.p{color:var(--poll)} .db .cap.m{color:var(--mkt)}
.db .mid{position:absolute;left:50%;top:18px;height:36px;width:1px;background:var(--ink3)}
.db .end{position:absolute;top:-6px;font-family:var(--mono);font-size:18px;color:var(--ink3)}
.gr{padding:18px 0 26px;border-bottom:1px solid var(--hair)}
.gr:last-child{border-bottom:none}
.gr .t{display:flex;justify-content:space-between;align-items:baseline}
.gr .nm{font-family:var(--serif);font-size:34px}
.gr .gap{font-family:var(--mono);font-size:22px;font-weight:600;color:var(--gold)}
.gr .db{height:70px;margin:22px 0 2px}
.kv{display:grid;grid-template-columns:1fr auto;gap:10px 20px;margin-top:30px;font-family:var(--mono);font-size:24px;color:var(--ink2)}
.kv b{color:var(--ink);font-weight:600;text-align:right}
.legend{display:flex;gap:28px;font-family:var(--mono);font-size:20px;margin-top:16px}
.legend .l{display:flex;align-items:center;gap:10px}
.legend .d{width:16px;height:16px;border-radius:50%}
.seats{display:flex;gap:4px;margin-top:34px;flex-wrap:wrap}
.seats i{display:block;width:16px;height:30px;border-radius:2px}
.card>*{position:relative;z-index:1}
`;
const header = (kLeft, kRight) => `<div class="top"></div><div class="kick"><span>${kLeft}</span><span>${kRight}</span></div><div class="brand">${LOGO}<span class="nm">The Convergence Index</span></div>`;
const footer = left => `<div class="foot"><span class="tag">${left}</span><b>convergence-index.com</b></div>`;

// ---------------------------------------------------------------- helpers
const pct = s => { const m = String(s || '').match(/(\d+(?:\.\d+)?)%/); return m ? +m[1] : null; };
const govCount = s => { const m = String(s || '').match(/(Democrats|Republicans)\s+in\s+(\d+)\s+of\s+(\d+)/i); return m ? { party: m[1], n: +m[2], of: +m[3] } : null; };
const partyWord = p => ({ D: 'Democratic', R: 'Republican', I: 'Independent' }[p]);
const pColor = p => ({ D: DEM, R: REP, I: GOLD }[p]);
const last = n => String(n || '').split(',')[0].trim().split(/\s+/).slice(-1)[0];
const raceLabel = x => x.chamber === 'house' ? x.id : x.chamber === 'senate' ? `${x.id} Senate` : `${x.id} Governor`;
const chamberFavor = dem => dem >= 50 ? { p: 'D', v: dem } : { p: 'R', v: 100 - dem };
const signed = d => (d > 0 ? '+' : d < 0 ? '−' : '±') + Math.abs(d).toFixed(0);
function lead(r) { const o = r.dem != null ? { p: 'D', v: r.dem, name: r.d } : { p: 'I', v: r.ind, name: r.i }; return o.v >= r.rep ? o : { p: 'R', v: r.rep, name: r.r }; }
const sideV = r => r.dem != null ? r.dem : r.ind;       // chance of the non-Republican side
function oddsNote(v) { const lose = 100 - v; const f = lose >= 45 ? 'about half the time' : lose >= 15 ? `about ${Math.round(lose / 10)} times in 10` : lose >= 5 ? `about 1 time in ${Math.round(100 / lose)}` : 'rarely';
  return `${v < 70 ? 'Still close: a' : 'A'} ${Math.round(v)}% favorite loses ${f}.`; }
const etDay = t => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(new Date(t));
const fmtDate = t => new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric' }).format(new Date(t)).toUpperCase();
const weekday = t => new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'long' }).format(new Date(t));
function periodLabel(earlierISO, todayISO) {
  const e = etDay(earlierISO), t = etDay(todayISO), y = etDay(new Date(new Date(todayISO) - 864e5));
  const days = (new Date(todayISO) - new Date(earlierISO)) / 864e5;
  if (e === t) return { short: 'Since this morning', long: "since this morning's update", on: 'This morning' };
  if (e === y) return { short: 'Since yesterday', long: "since yesterday's update", on: 'Yesterday' };
  if (days >= 6 && days <= 8) return { short: 'This week', long: 'over the past week', on: 'A week ago' };
  const wd = weekday(earlierISO);
  return { short: `Since ${wd}`, long: `since ${wd}'s update`, on: `On ${wd}` };
}

// ---------------------------------------------------------------- read a page with its own code
async function readPage(browser, file) {
  const pg = await browser.newPage(); const errs = [];
  pg.on('pageerror', e => errs.push(e.message));
  await pg.route(/fonts\.googleapis|fonts\.gstatic/, r => r.abort());
  await pg.goto('file://' + path.resolve(file)); await pg.waitForTimeout(2500);
  let d = null;
  try {
    d = await pg.evaluate(() => {
      const q = id => (document.getElementById(id) || {}).innerText || '';
      const Phi0 = typeof Phi === 'function' ? Phi : null;
      const Wt = typeof W === 'function' ? W() : 40;
      const rows = {};
      for (const [ch, key] of [['house', 'house'], ['senate', 'senate'], ['governors', 'gov']])
        for (const r of DATA[ch].races) {
          if (!r.mkt) continue; const c = raceChance(r);
          const dem = c.d != null ? c.d * 100 : null, ind = c.i != null ? c.i * 100 : null;
          const side = dem != null ? dem : ind;
          const pollP = (r.poll && Phi0) ? Phi0(r.poll.m / 5) * 100 : null;
          rows[key + ':' + r.id] = { chamber: key, id: r.id, d: r.d, r: r.r, i: r.i || null, dem, ind, rep: c.r * 100,
            poll: r.poll ? { m: r.poll.m, basis: r.poll.basis, date: r.poll.date, partisan: !!r.poll.partisan } : null,
            pollP, blend: pollP != null ? (pollP * Wt + side * (100 - Wt)) / 100 : side };
        }
      // Senate seat market
      const sm = DATA.senate.seatMarket; let seat = null;
      if (sm && sm.brackets && sm.brackets.length && sm.brackets[0].length === 4) {
        const pr = sm.brackets.map(b => (b[2] + b[3]) / 2), tot = pr.reduce((a, b) => a + b, 0), n = pr.map(x => x / tot);
        let c = 0, med = null; sm.brackets.forEach((b, i) => { c += n[i]; if (med == null && c >= 0.5) med = b[0]; });
        const maj = sm.brackets.reduce((a, b, i) => a + (b[1] >= sm.majority ? n[i] : 0), 0);
        seat = { median: med, majority: maj * 100, need: sm.majority };
      }
      const tally = (q('pathTally').match(/Democrats\s+(\d+)\s*·\s*Republicans\s+(\d+)/) || []).slice(1).map(Number);
      return { asOf: DATA.asOf, house: q('houseBlendValue'), senate: q('senateBlendValue'), gov: q('govHeadline'),
        cur: (typeof CUR !== 'undefined') ? CUR : null, W: Wt, rows, seat, tally, pathTip: q('pathTip').trim(),
        composition: DATA.senate.composition && DATA.senate.composition.text };
    });
  } catch (e) { errs.push(String(e)); }
  await pg.close();
  if (errs.length || !d || pct(d.house) == null || pct(d.senate) == null) throw new Error(`${file}: page did not render (${errs[0] || 'no headline'})`);
  return d;
}

// ---------------------------------------------------------------- earlier pages from git history
function gitPages(repo) {
  try {
    const log = cp.execSync(`git -C "${repo}" log --format=%H -n 300 -- index.html`, { encoding: 'utf8' }).trim().split('\n').filter(Boolean);
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ci-hist-'));
    const out = [];
    for (const sha of log) {
      let src; try { src = cp.execSync(`git -C "${repo}" show ${sha}:index.html`, { encoding: 'utf8', maxBuffer: 64 << 20 }); } catch (e) { continue; }
      const m = src.match(/"asOf":\s*"([^"]+)"/); if (!m || !src.includes('const DATA')) continue;
      const f = path.join(tmp, sha + '.html'); fs.writeFileSync(f, src);
      out.push({ sha, asOf: m[1], file: f });
    }
    return out;
  } catch (e) { console.error('git history unavailable:', e.message.split('\n')[0]); return []; }
}
async function pickEarlier(browser, pages, todayAsOf, minHours, preferHours) {
  const t = new Date(todayAsOf).getTime();
  const cands = pages.filter(p => (t - new Date(p.asOf).getTime()) / 36e5 >= minHours)
    .sort((a, b) => Math.abs((t - new Date(a.asOf)) / 36e5 - preferHours) - Math.abs((t - new Date(b.asOf)) / 36e5 - preferHours));
  const seen = new Set();
  for (const c of cands) { if (seen.has(c.asOf)) continue; seen.add(c.asOf);
    try { return await readPage(browser, c.file); } catch (e) { console.error('  skip', c.sha.slice(0, 7), e.message.slice(0, 80)); } }
  return null;
}

// ---------------------------------------------------------------- comparisons
function compare(T, Y) {
  const movers = [];
  for (const k in T.rows) { const t = T.rows[k], y = Y.rows[k]; if (!y) continue;
    const tv = sideV(t), yv = sideV(y); if (tv == null || yv == null) continue;
    movers.push({ key: k, t, y, delta: tv - yv, flip: lead(t).p !== lead(y).p }); }
  movers.sort((a, b) => (b.flip - a.flip) || (Math.abs(b.delta) - Math.abs(a.delta)));
  const hY = pct(Y.house), hT = pct(T.house), sY = pct(Y.senate), sT = pct(T.senate);
  return { per: periodLabel(Y.asOf, T.asOf), hY, hT, sY, sT, gY: govCount(Y.gov), gT: govCount(T.gov), movers,
    flips: movers.filter(m => m.flip), top: movers.filter(m => Math.abs(m.delta) >= 2).slice(0, 5),
    maxChamber: Math.max(Math.abs(hT - hY), Math.abs(sT - sY)), maxRace: movers.reduce((a, m) => Math.max(a, Math.abs(m.delta)), 0) };
}
function newsLevel(c) {
  if (!c) return 'quiet';
  if (c.maxChamber >= 3 || c.flips.length || c.maxRace >= 10) return 'big';
  if (c.maxChamber >= 1.5 || c.maxRace >= 6) return 'some';
  return 'quiet';
}

// ---------------------------------------------------------------- building blocks
function chamberBlock(label, y, t, big = false) {
  const Y = chamberFavor(y), T = chamberFavor(t), d = t - y;
  const who = Y.p !== T.p ? `now ${partyWord(T.p)}` : `${partyWord(T.p)} favored`;
  const dl = Math.abs(d) < 0.5 ? 'no change' : `${d > 0 ? 'Dem' : 'GOP'} ${signed(Math.abs(d))} pts`;
  return `<div class="ch"><div class="lab"><span>${label} — ${who}</span><span class="dl" style="color:${Math.abs(d) < 0.5 ? 'var(--ink3)' : pColor(d > 0 ? 'D' : 'R')}">${dl}</span></div>
    <div class="nums"><span class="from">${Math.round(Y.v)}%</span><span class="arr">→</span><span class="to" style="color:${pColor(T.p)}${big ? ';font-size:140px' : ''}">${Math.round(T.v)}%<span class="u">${partyWord(T.p)}</span></span></div></div>`;
}
function moverRow(m) {
  const y = lead(m.y), t = lead(m.t), gainer = m.delta > 0 ? (m.t.dem != null ? 'D' : 'I') : 'R';
  return `<div class="mv"><div><div class="nm">${esc(raceLabel(m.t))}${m.flip ? `<span class="flip" style="color:${pColor(t.p)}">FLIP</span>` : ''}</div><div class="who">${esc(t.name)} (${t.p}) favored</div></div>
    <div><div class="ft"><span class="a">${Math.round(m.flip ? 100 - y.v : y.v)}%</span> → <span class="b" style="color:${pColor(t.p)}">${Math.round(t.v)}%</span></div>
    <div class="dd" style="color:${pColor(gainer)}">${gainer === 'R' ? 'GOP' : gainer === 'D' ? 'Dem' : 'Ind'} ${signed(Math.abs(m.delta))} pts</div></div></div>`;
}
function raceBar(r) { const s = sideV(r); return `<div class="bar"><div class="f" style="left:0;width:${s.toFixed(1)}%;background:${pColor(r.dem != null ? 'D' : 'I')}"></div><div class="f" style="left:${s.toFixed(1)}%;right:0;background:${REP};opacity:.85"></div><div class="m50"></div></div>`; }
// dumbbell of market vs polling on a 0–100 "chance the Dem/Ind side wins" axis
function dumbbell(mk, pl, small = false, sideName = 'Dem') {
  const lo = Math.min(mk, pl), hi = Math.max(mk, pl);
  return `<div class="db"${small ? ' style="height:70px;margin:10px 0 2px"' : ''}>
    ${small ? '' : `<span class="end" style="left:0">${sideName} 0%</span><span class="end" style="right:0">100%</span>`}
    <div class="track"></div><div class="mid"></div><div class="seg" style="left:${lo}%;width:${hi - lo}%"></div>
    <div class="pt p" style="left:${pl}%"></div><div class="pt m" style="left:${mk}%"></div>
    <div class="cap p" style="left:${Math.min(Math.max(pl, 7), 93)}%">polls ${Math.round(pl)}%</div>
    <div class="cap m" style="left:${Math.min(Math.max(mk, 7), 93)}%;${Math.abs(mk - pl) < 24 ? 'top:-14px' : ''}">markets ${Math.round(mk)}%</div></div>`;
}
const legend = `<div class="legend"><span class="l"><span class="d" style="background:${MKT}"></span>Prediction markets</span><span class="l"><span class="d" style="background:${POLL}"></span>Polling-implied chance</span></div>`;

// ---------------------------------------------------------------- themes
// Each theme returns { post: [html...] (1 = single, 2+ = carousel), story: html, caption: {linkedin, instagram, x, alt}, title }
function themeChanges(T, c, dateT, kind = 'daily') {
  const { per } = c; const week = kind === 'week';
  const label = week ? 'Week in review' : 'What moved';
  const govLine = (c.gY && c.gT) ? (c.gY.n === c.gT.n && c.gY.party === c.gT.party ? `Governors: ${c.gT.party} still lead ${c.gT.n} of ${c.gT.of}` : `Governors: ${c.gY.party} ${c.gY.n} of ${c.gY.of} → ${c.gT.party} ${c.gT.n} of ${c.gT.of}`) : '';
  const star = c.flips[0] || c.movers.slice().sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))[0];
  const posts = [
    `<div class="card sq">${header(`${label} · 1 / 3`, dateT)}
      <div class="head" style="font-size:72px;margin-top:40px">${week ? 'The week in the midterm odds.' : `${per.short}, the markets moved.`}</div>
      <div style="margin-top:34px">${chamberBlock('U.S. House', c.hY, c.hT)}${chamberBlock('U.S. Senate', c.sY, c.sT)}</div>
      <div class="sub" style="font-size:26px;margin-top:6px">${esc(govLine)}</div>${footer('swipe for the biggest movers →')}</div>`,
    `<div class="card sq">${header(`Biggest movers · 2 / 3`, dateT)}
      <div class="sub" style="margin-top:30px;font-size:28px">Chance each race's favorite wins, from prediction markets — ${per.long}.</div>
      <div style="margin-top:18px">${c.top.map(moverRow).join('') || '<div class="sub">No race moved 2 points or more.</div>'}</div>${footer('swipe →')}</div>`];
  if (star) {
    const t = lead(star.t), y = lead(star.y);
    posts.push(`<div class="card sq">${header('Spotlight · 3 / 3', dateT)}
      <div class="head" style="margin-top:44px">${esc(raceLabel(star.t))}${star.flip ? ': the favorite flips.' : ' moves.'}</div>
      <div class="sub">${star.flip ? `Markets now favor ${esc(t.name)} (${t.p}). ${per.on}, ${esc(last(y.name))} (${y.p}) was the ${Math.abs(y.v - 50) < 5 ? 'narrow ' : ''}favorite.`
        : `${esc(t.name)} (${t.p}) ${t.v > y.v ? 'strengthened' : 'slipped'} ${per.long}.`}</div>
      <div style="display:flex;align-items:baseline;gap:26px;margin-top:40px"><span class="big" style="color:${pColor(t.p)}">${Math.round(t.v)}%</span><span class="tag" style="font-size:34px">${esc(last(t.name))} (${t.p})</span></div>
      <div class="mono" style="margin-top:10px">${per.on}: ${Math.round(star.flip ? 100 - y.v : y.v)}% · market chance</div>
      ${raceBar(star.t)}<div class="sub" style="font-size:28px;margin-top:34px">${oddsNote(t.v)}</div>${footer('prediction markets × polls')}</div>`);
  } else posts[1] = posts[1].replace('2 / 3', '2 / 2'), posts[0] = posts[0].replace('1 / 3', '1 / 2');
  const story = `<div class="card st">${header(per.short, dateT)}
    <div class="head" style="margin-top:70px">${week ? 'This week in the odds.' : 'The odds moved.'}</div>
    <div style="margin-top:40px">${chamberBlock('U.S. House', c.hY, c.hT)}${chamberBlock('U.S. Senate', c.sY, c.sT, true)}</div>
    <div class="mono" style="margin-top:54px;color:var(--ink2)">Biggest movers</div>
    <div>${c.top.slice(0, 4).map(moverRow).join('') || '<div class="sub">No race moved 2 points or more.</div>'}</div>${footer('link in bio')}</div>`;
  const mvC = (y, t) => { const Y = chamberFavor(y), T = chamberFavor(t); return Y.p === T.p ? `${Math.round(Y.v)}% → ${Math.round(T.v)}% ${partyWord(T.p)}` : `${partyWord(Y.p)} ${Math.round(Y.v)}% → ${partyWord(T.p)} ${Math.round(T.v)}%`; };
  const mvTxt = m => { const t = lead(m.t), y = lead(m.y); return `${raceLabel(m.t)}: ${last(t.name)} (${t.p}) ${Math.round(y.p === t.p ? y.v : 100 - y.v)}% → ${Math.round(t.v)}%`; };
  const flipTxt = m => { const t = lead(m.t); return `markets now favor ${t.name} (${t.p}) in the ${raceLabel(m.t)} race, ${Math.round(t.v)}%`; };
  const others = c.top.filter(m => !m.flip);
  const cap1 = x => x[0].toUpperCase() + x.slice(1);
  return { title: week ? 'Week in review' : `What changed ${per.long}`, post: posts, story,
    caption: {
      linkedin: `${week ? 'The week in the 2026 midterm odds.' : `The midterm odds moved ${per.long}.`}\n\nSenate control: ${mvC(c.sY, c.sT)}. House control: ${mvC(c.hY, c.hT)}.\n${c.flips.length ? `The headline: ${c.flips.map(flipTxt).join('; ')}.\n` : ''}${others.length ? `Other big market moves: ${others.slice(0, 3).map(mvTxt).join('; ')}.\n` : ''}\nThe Convergence Index blends prediction-market prices with the major polling averages, with every figure linked to its source.\nconvergence-index.com`,
      instagram: `${week ? 'The week in the odds 🗓️' : 'The odds moved 📈'}\nSenate: ${mvC(c.sY, c.sT)} · House: ${mvC(c.hY, c.hT)}\n${c.flips.length ? c.flips.map(m => `${raceLabel(m.t)}: ${lead(m.t).name} (${lead(m.t).p}) now favored`).join(' · ') + '\n' : ''}Swipe for the biggest movers. Link in bio.`,
      x: `${per.short}: Senate ${mvC(c.sY, c.sT)}, House ${mvC(c.hY, c.hT)}.\n${c.flips.length ? c.flips.map(flipTxt).map(cap1).join('; ') + '.\n' : ''}convergence-index.com`,
      alt: `${per.short}, the Convergence Index moved: Senate control ${mvC(c.sY, c.sT)}; House ${mvC(c.hY, c.hT)}. ${c.flips.length ? c.flips.map(flipTxt).map(cap1).join('; ') + '. ' : ''}Other market moves: ${others.map(mvTxt).join('; ') || 'none over 2 points'}.`
    } };
}

function pickSpotlight(T, W7, Y1) {
  const rows = Object.values(T.rows).filter(r => r.chamber !== 'house' || r.poll);
  const base = W7 || Y1;
  if (base) {
    const cmp = compare(T, base);
    const f = cmp.flips.find(m => m.t.chamber !== 'house') || cmp.flips[0];
    if (f) return { row: f.t, why: `favorite flipped ${cmp.per.long}`, delta: f.delta, per: cmp.per, prev: f.y };
    const big = cmp.movers.filter(m => lead(m.t).v < 85).sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))[0];
    if (big && Math.abs(big.delta) >= 5) return { row: big.t, why: `biggest move ${cmp.per.long}`, delta: big.delta, per: cmp.per, prev: big.y };
  }
  const close = rows.filter(r => r.chamber === 'senate').sort((a, b) => Math.abs(sideV(a) - 50) - Math.abs(sideV(b) - 50))[0];
  return { row: close, why: 'closest Senate race in the markets', delta: null };
}
function themeSpotlight(T, sp, dateT) {
  const r = sp.row, L = lead(r), side = r.dem != null ? 'D' : 'I', sideName = side === 'D' ? 'Dem' : 'Ind';
  const pollLine = r.poll ? `${r.poll.m >= 0 ? (side === 'D' ? 'D' : 'I') : 'R'}+${Math.abs(r.poll.m).toFixed(1)}${r.poll.partisan ? ' (includes partisan polls)' : ''}` : 'no recent public polling';
  const deltaLine = sp.delta != null ? `${sp.per.short}: ${signed(sp.delta)} pts for ${side === 'D' ? 'the Democrat' : 'the independent'}` : '';
  const body = big => `
    <div class="head" style="margin-top:${big ? 70 : 40}px;font-size:${big ? 104 : 80}px">${esc(raceLabel(r))}</div>
    <div class="sub" style="font-size:${big ? 34 : 30}px">${esc(r.d || r.i)} (${side}) vs. ${esc(r.r)} (R)</div>
    <div style="display:flex;align-items:baseline;gap:22px;margin-top:${big ? 60 : 30}px"><span class="big" style="color:${pColor(L.p)}">${Math.round(L.v)}%</span><span class="tag" style="font-size:34px">${esc(last(L.name))} (${L.p}) · market chance</span></div>
    ${raceBar(r)}
    ${r.pollP != null ? `<div class="mono" style="margin-top:${big ? 60 : 34}px;color:var(--ink2)">Markets vs. polls — chance the ${sideName === 'Dem' ? 'Democrat' : 'independent'} wins</div>${dumbbell(sideV(r), r.pollP, false, sideName)}` : ''}
    <div class="kv"><span>Polling average</span><b>${esc(pollLine)}</b><span>Blended chance (${sideName})</span><b>${Math.round(r.blend)}%</b>${deltaLine ? `<span>Movement</span><b>${esc(deltaLine)}</b>` : ''}</div>`;
  return { title: `Race spotlight: ${raceLabel(r)}`,
    post: [`<div class="card sq">${header('Race spotlight', dateT)}${body(false)}${footer(esc(sp.why))}</div>`],
    story: `<div class="card st">${header('Race spotlight', dateT)}${body(true)}<div class="sub" style="margin-top:50px">${oddsNote(L.v)}</div>${footer('link in bio')}</div>`,
    caption: {
      linkedin: `Race spotlight: ${raceLabel(r)} — ${r.d || r.i} (${side}) vs. ${r.r} (R).\n\nPrediction markets give ${L.name} (${L.p}) a ${Math.round(L.v)}% chance. ${r.pollP != null ? `The polling average (${pollLine}) implies ${Math.round(r.pollP)}% for the ${sideName === 'Dem' ? 'Democrat' : 'independent'}; blended, ${Math.round(r.blend)}%.` : 'There is no recent public polling, so this one rests on the markets.'}${deltaLine ? `\n${deltaLine}.` : ''}\n\n${oddsNote(L.v)}\nconvergence-index.com`,
      instagram: `Race spotlight 🔎 ${raceLabel(r)}\n${last(L.name)} (${L.p}) ${Math.round(L.v)}% in the markets${r.pollP != null ? ` · polls imply ${Math.round(r.pollP)}% for the ${sideName === 'Dem' ? 'Democrat' : 'independent'}` : ''}\nLink in bio.`,
      x: `Race spotlight — ${raceLabel(r)}: markets give ${L.name} (${L.p}) ${Math.round(L.v)}%${r.pollP != null ? `; polls (${pollLine}) imply ${Math.round(r.pollP)}% for the ${sideName === 'Dem' ? 'Democrat' : 'independent'}` : ''}.\nconvergence-index.com`,
      alt: `Race spotlight, ${raceLabel(r)}: ${r.d || r.i} versus ${r.r}. Prediction markets give ${L.name} a ${Math.round(L.v)}% chance. ${r.pollP != null ? `Polling average ${pollLine}, implying ${Math.round(r.pollP)}% for the ${sideName === 'Dem' ? 'Democrat' : 'independent'}.` : ''}`
    } };
}

function pvmTake(cur) {
  if (!cur || !cur.senate) return '';
  const d = cur.senate.mkt - cur.senate.poll;
  if (Math.abs(d) < 3) return 'On the Senate, the two signals agree.';
  return `On the Senate, markets are ${Math.round(Math.abs(d))} points ${d > 0 ? 'more bullish on Democrats' : 'more bullish on Republicans'} than the polls.`;
}
function themePvm(T, dateT) {
  const gaps = Object.values(T.rows).filter(r => r.pollP != null && !r.poll.partisan && sideV(r) != null)
    .map(r => ({ r, gap: Math.abs(sideV(r) - r.pollP) })).sort((a, b) => b.gap - a.gap).slice(0, 4);
  const cur = T.cur || {};
  const row = g => `<div class="gr"><div class="t"><span class="nm">${esc(raceLabel(g.r))}</span><span class="gap">${Math.round(g.gap)} pt${Math.round(g.gap) === 1 ? '' : 's'} apart</span></div>${dumbbell(sideV(g.r), g.r.pollP, true)}</div>`;
  const chamberDb = (lab, c) => c ? `<div class="gr"><div class="t"><span class="nm">${lab} control</span><span class="gap">${Math.round(Math.abs(c.mkt - c.poll))} pt${Math.round(Math.abs(c.mkt - c.poll)) === 1 ? '' : 's'} apart</span></div>${dumbbell(c.mkt, c.poll, true)}</div>` : '';
  const posts = [
    `<div class="card sq">${header('Polls vs. markets · 1 / 3', dateT)}
      <div class="head" style="font-size:74px;margin-top:40px">Two signals. Do they agree?</div>
      <div class="sub">Chance Democrats win control — what prediction markets say vs. what the polling averages imply.</div>
      <div style="margin-top:26px">${chamberDb('Senate', cur.senate)}${chamberDb('House', cur.house)}</div>${legend}<div class="sub" style="margin-top:34px;font-size:30px">${esc(pvmTake(cur))}</div>${footer('swipe for the races →')}</div>`,
    `<div class="card sq">${header('Where they disagree · 2 / 3', dateT)}
      <div class="sub" style="margin-top:26px;font-size:27px">Largest gaps between markets and nonpartisan polling averages — chance the Democrat (or independent) wins.</div>
      <div style="margin-top:6px">${gaps.map(row).join('')}</div>${footer('swipe →')}</div>`,
    `<div class="card sq">${header('Why they differ · 3 / 3', dateT)}
      <div class="head" style="font-size:66px;margin-top:40px">When they split, watch closely.</div>
      <div class="sub" style="font-size:31px;line-height:1.45">Polls measure what voters say today. Markets price everything traders think matters — polls included, plus news, money and history. A big gap means one of them is about to be proven wrong.</div>
      <div class="sub" style="font-size:27px;margin-top:30px">Our blend: 40% polls, 60% markets. Move the slider on the site to weight them yourself.</div>${footer('prediction markets × polls')}</div>`];
  const story = `<div class="card st">${header('Polls vs. markets', dateT)}
    <div class="head" style="margin-top:70px">Where polls and markets split.</div>
    <div style="margin-top:40px">${chamberDb('Senate', cur.senate)}</div>
    <div style="margin-top:20px">${gaps.slice(0, 4).map(row).join('')}</div>${legend}${footer('link in bio')}</div>`;
  const gTxt = g => `${raceLabel(g.r)} (markets ${Math.round(sideV(g.r))}%, polls ${Math.round(g.r.pollP)}%)`;
  return { title: 'Polls vs. markets', post: posts, story,
    caption: {
      linkedin: `Polls vs. prediction markets: where do they disagree?\n\nSenate control: markets ${Math.round(cur.senate.mkt)}% Democratic, polling-implied ${Math.round(cur.senate.poll)}%. House: markets ${Math.round(cur.house.mkt)}%, polls ${Math.round(cur.house.poll)}%.\nBiggest race-level gaps (nonpartisan polling only): ${gaps.map(gTxt).join('; ')}.\n\nWhen the two signals split, one of them is about to be proven wrong. The Convergence Index blends both.\nconvergence-index.com`,
      instagram: `Polls vs. markets ⚖️\nSenate: markets ${Math.round(cur.senate.mkt)}% · polls ${Math.round(cur.senate.poll)}%\nBiggest split: ${gTxt(gaps[0])}\nSwipe for more. Link in bio.`,
      x: `Where polls and prediction markets disagree most: ${gaps.slice(0, 3).map(gTxt).join('; ')}.\nconvergence-index.com`,
      alt: `Polls versus prediction markets. Senate control: markets ${Math.round(cur.senate.mkt)} percent Democratic, polls ${Math.round(cur.senate.poll)} percent. Largest race gaps: ${gaps.map(gTxt).join('; ')}.`
    } };
}

function themePath(T, dateT) {
  const s = T.seat, tl = T.tally, sen = pct(T.senate), cur = T.cur || {};
  const dSeats = tl[0], rSeats = tl[1], F = chamberFavor(sen);
  const seatsViz = (dSeats && rSeats) ? `<div style="position:relative;margin-top:40px"><div style="display:grid;grid-template-columns:repeat(100,1fr);gap:2px;height:64px">${Array.from({ length: 100 }, (_, i) => `<i style="display:block;background:${i < dSeats ? DEM : REP}"></i>`).join('')}</div><div style="position:absolute;left:calc(51% - 1px);top:-12px;height:88px;width:3px;background:var(--ink)"></div><div class="mono" style="position:absolute;left:calc(51% + 12px);top:-44px;color:var(--ink)">51 for control</div><div class="mono" style="display:flex;justify-content:space-between;margin-top:22px"><span style="color:${DEM}">${dSeats} D</span><span style="color:${REP}">${rSeats} R</span></div></div>` : '';
  const kv = `<div class="kv">
      ${s ? `<span>Seat market: most likely Democratic seats</span><b>${esc(s.median)}</b><span>Seat market: chance of ${s.need}+ Democratic seats</span><b>${Math.round(s.majority)}%</b>` : ''}
      ${cur.senate ? `<span>Control markets (Kalshi & Polymarket)</span><b>${Math.round(cur.senate.mkt)}%</b><span>Polling-implied chance</span><b>${Math.round(cur.senate.poll)}%</b>` : ''}
      <span>Blended chance of control</span><b style="color:${pColor(F.p)}">${Math.round(F.v)}% ${partyWord(F.p)}</b></div>`;
  const head = dSeats ? `If every race goes to its market favorite: <b style="font-weight:500;color:${dSeats >= 51 ? DEM : REP}">${dSeats >= 51 ? 'Democrats' : 'Republicans'} ${Math.max(dSeats, rSeats)}</b>–${Math.min(dSeats, rSeats)}.` : 'The path to 51.';
  return { title: 'Senate path to 51',
    post: [`<div class="card sq">${header('Path to 51', dateT)}
      <div class="head" style="font-size:62px;margin-top:40px;margin-bottom:30px">${head}</div>${seatsViz}${kv}${T.pathTip ? `<div class="sub" style="font-size:27px;margin-top:26px">${esc(T.pathTip.replace(/^With every race going to its market favorite, [^.]+\. /, ''))}</div>` : ''}${footer('Senate control · play the path on the site')}</div>`],
    story: `<div class="card st">${header('Path to 51', dateT)}<div class="head" style="margin-top:70px;font-size:84px;margin-bottom:40px">${head}</div>${seatsViz}${kv}
      ${T.pathTip ? `<div class="sub" style="margin-top:50px">${esc(T.pathTip)}</div>` : ''}${footer('link in bio')}</div>`,
    caption: {
      linkedin: `The Senate path to 51.\n\nIf every 2026 race goes to its prediction-market favorite, the Senate would be ${dSeats >= 51 ? 'Democrats' : 'Republicans'} ${Math.max(dSeats, rSeats)}–${Math.min(dSeats, rSeats)}.${s ? ` The seat market's most likely outcome is ${s.median} Democratic seats, with a ${Math.round(s.majority)}% chance of ${s.need}+.` : ''} Blended with the polling, the chance of ${partyWord(F.p)} control is ${Math.round(F.v)}%.\n\nPlay with the path yourself — hand any state to the other party and watch the math change.\nconvergence-index.com`,
      instagram: `The path to 51 🏛️\nMarket favorites: ${dSeats >= 51 ? 'D' : 'R'} ${Math.max(dSeats, rSeats)}–${Math.min(dSeats, rSeats)}\nBlended: ${partyWord(F.p)} ${Math.round(F.v)}%\nTry the interactive map — link in bio.`,
      x: `Senate path to 51: market favorites → ${dSeats >= 51 ? 'D' : 'R'} ${Math.max(dSeats, rSeats)}–${Math.min(dSeats, rSeats)}. Blended chance of ${partyWord(F.p)} control: ${Math.round(F.v)}%.\nconvergence-index.com`,
      alt: `Senate path to 51. If each race goes to its market favorite: ${dSeats} Democratic and ${rSeats} Republican seats. Blended chance of ${partyWord(F.p)} control ${Math.round(F.v)} percent.`
    } };
}

// ---------------------------------------------------------------- render
async function render(browser, html, file) {
  const page = await browser.newPage({ viewport: { width: 1200, height: 2000 }, deviceScaleFactor: 1 });
  if (html.includes('card st')) {       // stories: center the body vertically and scale it up a touch
    const a = html.indexOf('The Convergence Index</span></div>') + 'The Convergence Index</span></div>'.length, b = html.lastIndexOf('<div class="foot">');
    if (a > 40 && b > a) html = html.slice(0, a) + `<div style="margin:auto 0;zoom:1.1">` + html.slice(a, b) + '</div>' + html.slice(b);
  }
  await page.setContent(`<!doctype html><html><head><meta charset="utf-8"><style>${CSS}</style></head><body>${html}</body></html>`);
  await page.evaluate(() => document.fonts.ready);
  await (await page.$('.card')).screenshot({ path: file });
  await page.close();
}
function socialKit(plan, files, captions) {
  const img = f => `data:image/png;base64,${fs.readFileSync(path.join(OUT, f)).toString('base64')}`;
  const sec = (t, fs_) => `<h2>${t}</h2><div class="grid">${fs_.map(f => `<figure><img src="${img(f)}" alt=""><figcaption>${f}</figcaption></figure>`).join('')}</div>`;
  const cap = (k, v) => `<div class="cap"><h3>${k}</h3><pre>${esc(v)}</pre></div>`;
  return `<title>Convergence Social Kit</title>
<style>:root{--paper:#fcfbf8;--card:#f4f2ec;--ink:#17171a;--ink2:#5d5b56;--ink3:#75726b;--hair:#e2ded6;--accent:#2c4a7a}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#131316;--card:#1c1c20;--ink:#ecebe6;--ink2:#a9a69f;--ink3:#8c8981;--hair:#34343a;--accent:#8fb0e3}}
:root[data-theme="dark"]{--paper:#131316;--card:#1c1c20;--ink:#ecebe6;--ink2:#a9a69f;--ink3:#8c8981;--hair:#34343a;--accent:#8fb0e3}
*{box-sizing:border-box}body{background:var(--paper);color:var(--ink);font:17px/1.5 Georgia,serif;margin:0}
.wrap{max-width:1040px;margin:0 auto;padding:32px 16px 64px}h1{font-weight:400;font-size:clamp(28px,5vw,42px);margin:0;border-top:3px solid var(--ink);padding-top:12px}
.lede{color:var(--ink2);font-style:italic}h2{font:500 12px ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase;color:var(--ink2);margin:36px 0 12px;padding-top:12px;border-top:1px solid var(--hair)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:20px}figure{margin:0}figure img{width:100%;border:1px solid var(--hair);display:block}
figcaption{font:12px ui-monospace,monospace;color:var(--ink3);margin-top:6px}.cap{background:var(--card);padding:14px 16px;border-left:3px solid var(--accent);margin-bottom:14px}
.cap h3{font:600 12px ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase;margin:0 0 8px}.cap pre{white-space:pre-wrap;font:16px/1.5 Georgia,serif;margin:0}
.hint{font:12px ui-monospace,monospace;color:var(--ink3)}</style>
<div class="wrap"><h1>Social kit — ${esc(plan.dateLabel)}</h1>
<p class="lede">${esc(plan.summary)}</p><p class="hint">To save an image: press and hold it (phone) or right-click → Save image (computer).</p>
${sec(files.post.length > 1 ? `Main post — carousel (${files.post.length} slides, in order)` : 'Main post — single image', files.post)}
${sec('Story', [files.story])}
<h2>Captions</h2>${cap('LinkedIn', captions.linkedin)}${cap('Instagram', captions.instagram)}${cap('X', captions.x)}${cap('Alt text', captions.alt)}
</div>`;
}

// ---------------------------------------------------------------- main
(async () => {
  const browser = await chromium.launch();
  const T = await readPage(browser, path.join(REPO, 'index.html'));
  const dow = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', weekday: 'short' }).format(new Date());
  const THEMES = { Mon: 'board', Tue: 'spotlight', Wed: 'pvm', Thu: 'path', Fri: 'week' };
  const theme = opt('theme') || THEMES[dow];
  if (!theme) { console.log(JSON.stringify({ skipped: `weekend (${dow}) — no graphics` })); await browser.close(); return; }

  const hist = (opt('yesterday') && opt('week')) ? [] : gitPages(REPO);
  const Y1 = opt('yesterday') ? await readPage(browser, opt('yesterday')) : await pickEarlier(browser, hist, T.asOf, 16, dow === 'Mon' ? 72 : 24);
  const W7 = opt('week') ? await readPage(browser, opt('week')) : await pickEarlier(browser, hist, T.asOf, 36, 168);
  const dateT = fmtDate(T.asOf);
  const cDay = Y1 ? compare(T, Y1) : null;
  const level = opt('news') || newsLevel(cDay);

  // theme content
  let themed;
  if (theme === 'board') {
    // the board = today's standing; on Mondays, pair it with what changed since Friday
    const bdir = path.join(OUT, '_board'); fs.mkdirSync(bdir, { recursive: true });
    const bg = [path.join(REPO, 'build_graphics.cjs'), path.join(REPO, 'tools', 'build_graphics.cjs')].find(f => fs.existsSync(f));
    cp.execFileSync(process.execPath, [bg, path.join(REPO, 'index.html'), bdir], { stdio: 'inherit', cwd: path.dirname(bg), env: process.env });
    const ch = cDay ? themeChanges(T, cDay, dateT) : null;
    themed = { title: 'The board', boardFiles: ['feed-square.png'], post: ch ? ch.post.slice(0, 2) : [], story: null, boardStory: 'story.png',
      caption: ch ? ch.caption : { linkedin: fs.readFileSync(path.join(bdir, 'captions.md'), 'utf8').split('## LinkedIn')[1]?.split('##')[0]?.trim() || '', instagram: '', x: '', alt: '' } };
    themed.bdir = bdir;
  } else if (theme === 'spotlight') themed = themeSpotlight(T, pickSpotlight(T, W7, Y1), dateT);
  else if (theme === 'pvm') themed = themePvm(T, dateT);
  else if (theme === 'path') themed = themePath(T, dateT);
  else if (theme === 'week') themed = W7 ? themeChanges(T, compare(T, W7), dateT, 'week') : themePath(T, dateT);

  // news weighting
  const changes = cDay ? themeChanges(T, cDay, dateT) : null;
  let main, story, caption, summary;
  if (level === 'big' && changes && theme === 'week') {
    main = { kind: 'week', html: themed.post }; story = { kind: 'changes', html: changes.story };
    caption = themed.caption; summary = `Week in review leads (it includes today's big moves); a "what changed" story covers ${cDay.per.long}.`;
  } else if (level === 'big' && changes && theme !== 'board') {
    main = { kind: 'changes', html: changes.post }; story = { kind: theme, html: themed.story };
    caption = changes.caption; summary = `Big news ${cDay.per.long} — leading with what changed; today's planned theme (${themed.title}) is the story.`;
  } else if (level === 'some' && changes && theme !== 'board' && theme !== 'week') {
    main = { kind: theme, html: themed.post }; story = { kind: 'changes', html: changes.story };
    caption = themed.caption; summary = `${themed.title} leads; a "what changed" story covers the moves ${cDay.per.long}.`;
  } else {
    main = { kind: theme, html: themed.post }; story = { kind: theme, html: themed.story };
    caption = themed.caption; summary = `${themed.title}${level === 'quiet' ? ' — a quiet day in the markets' : ''}.`;
  }

  // render
  const files = { post: [], story: 'story.png' };
  let n = 0;
  if (theme === 'board' && main.kind === 'board') {
    fs.copyFileSync(path.join(themed.bdir, 'feed-square.png'), path.join(OUT, `post-${++n}.png`)); files.post.push(`post-${n}.png`);
  }
  for (const h of main.html) { await render(browser, h, path.join(OUT, `post-${++n}.png`)); files.post.push(`post-${n}.png`); }
  if (story.html) await render(browser, story.html, path.join(OUT, 'story.png'));
  else fs.copyFileSync(path.join(themed.bdir, themed.boardStory), path.join(OUT, 'story.png'));
  await browser.close();

  const plan = { date: etDay(T.asOf), dateLabel: dateT, weekday: dow, theme, news: level, main: main.kind, story: story.kind, summary,
    compared: cDay ? { since: Y1.asOf, per: cDay.per.short, senate: [cDay.sY, cDay.sT], house: [cDay.hY, cDay.hT], flips: cDay.flips.map(m => raceLabel(m.t)), maxRace: +cDay.maxRace.toFixed(1) } : null,
    files };
  const md = `# ${dateT} — ${summary}\n\nMain post: ${files.post.length > 1 ? `carousel, post in order: ${files.post.join(', ')}` : files.post[0]}. Story: story.png.\n\n## LinkedIn\n${caption.linkedin}\n\n## Instagram\n${caption.instagram}\n.\n.\n#2026midterms #elections #politics #predictionmarkets #polling #data\n\n## X\n${caption.x}\n\n## Alt text\n${caption.alt}\n`;
  fs.writeFileSync(path.join(OUT, 'captions.md'), md);
  fs.writeFileSync(path.join(OUT, 'plan.json'), JSON.stringify(plan, null, 1));
  fs.writeFileSync(path.join(OUT, 'social-kit.html'), socialKit(plan, files, caption));
  if (themed.bdir) fs.rmSync(themed.bdir, { recursive: true, force: true });
  console.log(JSON.stringify(plan, null, 1));
})().catch(e => { console.error(e); process.exit(1); });
