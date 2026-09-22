#!/usr/bin/env node
/* Build the daily Convergence Index social graphics.
 *
 *   node tools/build_graphics.cjs <page.html> <outDir>
 *
 * <page.html> is the Convergence Index page (the claude.ai artifact read, or the site's index.html).
 * The script loads that page in headless Chromium so the page's OWN javascript computes the numbers,
 * then reads the rendered figures from the DOM — so the graphics always match the live site exactly.
 *
 * Framing is deliberately non-partisan: each chamber shows the CURRENTLY FAVORED party and its
 * control probability, so the graphics read the same whichever party leads (and flip automatically
 * if a lead changes). Nothing hard-codes one party.
 *
 * Outputs into <outDir>: feed-square.png (1080x1080), watch-square.png (1080x1080),
 * story.png (1080x1920), and captions.md.
 * Fonts are bundled in tools/fonts/ so the script is self-contained from a fresh clone.
 */
const fs = require('fs');
const path = require('path');

let chromium;
try { chromium = require('playwright').chromium; }
catch (e) { console.error('playwright is not installed. Run: npm install playwright'); process.exit(2); }

const IN = process.argv[2], OUT = process.argv[3];
if (!IN || !OUT) { console.error('usage: node build_graphics.cjs <page.html> <outDir>'); process.exit(2); }
fs.mkdirSync(OUT, { recursive: true });

const F = path.join(__dirname, 'fonts');
const b64 = f => fs.readFileSync(path.join(F, f)).toString('base64');
const FONTS = `
@font-face{font-family:'Newsreader';src:url(data:font/woff2;base64,${b64('newsreader.woff2')});font-weight:200 800;font-style:normal}
@font-face{font-family:'Newsreader';src:url(data:font/woff2;base64,${b64('newsreader-italic.woff2')});font-weight:200 800;font-style:italic}
@font-face{font-family:'IBM Plex Mono';src:url(data:font/woff2;base64,${b64('plex-400.woff2')});font-weight:400}
@font-face{font-family:'IBM Plex Mono';src:url(data:font/woff2;base64,${b64('plex-500.woff2')});font-weight:500}
@font-face{font-family:'IBM Plex Mono';src:url(data:font/woff2;base64,${b64('plex-600.woff2')});font-weight:600}`;

const LOGO = '<svg viewBox="0 0 120 60"><path d="M6 12 C40 12,44 28,60 30" fill="none" stroke="#2c4a7a" stroke-width="5" stroke-linecap="round"/><path d="M6 48 C40 48,44 32,60 30" fill="none" stroke="#17171a" stroke-width="5" stroke-linecap="round"/><circle cx="62" cy="30" r="8" fill="#2c4a7a"/></svg>';
const esc = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

// ---- non-partisan framing helpers ----
const DEM = '#2c4a7a', REP = '#9b3a2e', GOLD = '#9a7016';
// given the Democratic win probability, describe the race by whoever is favored
function favor(dem) {
  const isD = dem >= 50;
  const chance = Math.round(isD ? dem : 100 - dem);
  const party = isD ? 'Democratic' : 'Republican';
  const lean = chance >= 90 ? 'Solid' : chance >= 75 ? 'Likely' : chance >= 60 ? 'Lean' : 'Toss-up';
  const rate = lean === 'Toss-up' ? 'Toss-up' : `${lean} ${party}`;
  const color = (dem > 45 && dem < 55) ? GOLD : (isD ? DEM : REP);
  const cls = (dem > 45 && dem < 55) ? 'toss' : (isD ? 'dem' : 'rep');
  return { isD, chance, party, rate, color, cls };
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, deviceScaleFactor: 1 });
  page.on('pageerror', e => console.error('page error:', e.message));
  await page.route(/fonts\.googleapis|fonts\.gstatic/, r => r.abort());
  await page.goto('file://' + path.resolve(IN));
  await page.addStyleTag({ content: FONTS });
  await page.waitForFunction(() => {
    const h = document.getElementById('houseBlendValue');
    return h && /\d/.test(h.textContent);
  }, { timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(400);

  const data = await page.evaluate(() => {
    const t = id => (document.getElementById(id)?.textContent || '').trim();
    const num = s => { const m = String(s).match(/\d+(\.\d+)?/); return m ? parseFloat(m[0]) : null; };
    const asOf = (typeof DATA !== 'undefined' && DATA.asOf) ? DATA.asOf : null;
    const gaps = [...document.querySelectorAll('#houseGaps .gap-row, #senateGaps .gap-row, #govGaps .gap-row')].map(r => ({
      name: (r.querySelector('.g-name')?.textContent || '').trim(),
      txt: (r.querySelector('.g-txt')?.textContent || '').trim().replace(/[ \t]*[Pᴾ]$/, ''),
      gap: parseFloat((r.querySelector('.g-gap')?.textContent || '0').replace(/[^\d.]/g, '')) || 0,
      chamber: r.closest('#houseGaps') ? 'House' : r.closest('#senateGaps') ? 'Senate' : 'Governor'
    })).sort((a, b) => b.gap - a.gap);
    return { asOf, house: num(t('houseBlendValue')), senate: num(t('senateBlendValue')), govHeadline: t('govHeadline'), top: gaps[0] || null };
  });

  const d = data.asOf ? new Date(data.asOf) : new Date();
  const dateLabel = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', month: 'long', day: 'numeric', year: 'numeric' }).format(d);
  const DATE_ISO = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York' }).format(d);
  const shortDate = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', month: 'short', day: 'numeric' }).format(d).toUpperCase();

  const H = data.house ?? 0, S = data.senate ?? 0;
  const house = favor(H), senate = favor(S);

  // governors: parse "<Party> ... N of M" from the site's own headline (neutral either way)
  const gm = (data.govHeadline || '').match(/(Democrats|Republicans)\s+in\s+(\d+)\s+of\s+(\d+)/i);
  const govParty = gm ? (gm[1] === 'Democrats' ? 'Democratic' : 'Republican') : '';
  const govColor = gm ? (gm[1] === 'Democrats' ? DEM : REP) : DEM;
  const govCls = gm ? (gm[1] === 'Democrats' ? 'dem' : 'rep') : 'dem';
  const govNum = gm ? `${gm[2]} of ${gm[3]}` : '—';
  const govRate = gm ? `${govParty} lead` : '';

  const CSS = `
    *{margin:0;padding:0;box-sizing:border-box}
    :root{--paper:#fcfbf8;--ink:#17171a;--ink2:#5d5b56;--ink3:#8f8c85;--hair:#e2ded6;--dem:${DEM};--rep:${REP};--gold:${GOLD};
      --poll:#6b5b95;--mkt:#2f6f73;--serif:'Newsreader',Georgia,serif;--mono:'IBM Plex Mono',monospace}
    body{background:#333}
    .card{background:var(--paper);color:var(--ink);position:relative;overflow:hidden;display:flex;flex-direction:column}
    .sq{width:1080px;height:1080px;padding:84px 84px 76px}
    .st{width:1080px;height:1920px;padding:150px 96px 130px}
    .top{border:none;border-top:4px solid var(--ink)}
    .kick{font-family:var(--mono);font-size:23px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink2);font-weight:500;margin-top:20px;display:flex;justify-content:space-between}
    .brand{display:flex;align-items:center;gap:15px;margin-top:20px}
    .brand svg{width:54px;height:auto;flex:none}
    .brand .nm{font-family:var(--serif);font-size:33px;letter-spacing:.005em}
    .dem{color:var(--dem)}.rep{color:var(--rep)}.toss{color:var(--gold)}
    .foot{margin-top:auto;padding-top:26px;border-top:1px solid var(--hair);display:flex;justify-content:space-between;align-items:baseline;font-family:var(--mono);font-size:22px;color:var(--ink3);letter-spacing:.02em}
    .foot b{color:var(--ink);font-weight:600}
    .tag{font-family:var(--serif);font-style:italic;color:var(--ink2)}
    .rows{margin-top:20px}
    .row{padding:32px 0 34px;border-bottom:1px solid var(--hair);display:grid;grid-template-columns:1fr auto;align-items:center;column-gap:24px}
    .row:last-child{border-bottom:none}
    .row .lab{grid-column:1;grid-row:1;font-family:var(--mono);font-size:23px;text-transform:uppercase;letter-spacing:.08em;color:var(--ink2)}
    .row .rate{grid-column:2;grid-row:1;font-family:var(--mono);font-size:23px;font-weight:500;letter-spacing:.04em;color:var(--ink);display:flex;align-items:center;gap:10px;white-space:nowrap}
    .row .rate .dot{width:12px;height:12px;border-radius:50%}
    .row .val{grid-column:1 / -1;grid-row:2;font-family:var(--serif);font-weight:300;font-size:120px;line-height:1;letter-spacing:-.03em;margin-top:26px}
    .row .val.small{font-size:96px}
    .row .val .u{font-size:.42em;color:var(--ink2);font-style:italic;margin-left:12px;letter-spacing:0}
    .wwrap{margin-top:auto;margin-bottom:auto;padding:20px 0}
    .wk{font-family:var(--mono);font-size:24px;letter-spacing:.12em;text-transform:uppercase;color:var(--gold);font-weight:500}
    .wname{font-family:var(--serif);font-size:150px;font-weight:400;letter-spacing:-.02em;line-height:1;margin:14px 0 6px}
    .wch{font-family:var(--mono);font-size:24px;color:var(--ink2);text-transform:uppercase;letter-spacing:.06em}
    .dumb{position:relative;height:96px;margin:64px 0 8px}
    .dumb .axis{position:absolute;top:-40px;left:0;right:0;font-family:var(--mono);font-size:21px;color:var(--ink2);text-transform:uppercase;letter-spacing:.05em}
    .dumb .track{position:absolute;left:0;right:0;top:34px;height:2px;background:var(--hair)}
    .dumb .seg{position:absolute;top:33px;height:4px;background:color-mix(in srgb,var(--gold) 55%,transparent)}
    .dumb .pt{position:absolute;top:26px;width:18px;height:18px;border-radius:50%;transform:translateX(-50%);box-shadow:0 0 0 4px var(--paper)}
    .dumb .pt.p{background:var(--poll)} .dumb .pt.m{background:var(--mkt)}
    .dumb .cap{position:absolute;top:54px;transform:translateX(-50%);font-family:var(--mono);font-size:22px;white-space:nowrap}
    .dumb .cap.p{color:var(--poll)} .dumb .cap.m{color:var(--mkt)}
    .dumb .end{position:absolute;top:-4px;font-family:var(--mono);font-size:19px;color:var(--ink3)}
    .wsum{font-family:var(--serif);font-size:42px;color:var(--ink);margin-top:26px;line-height:1.25}
    .wsum b{color:var(--gold);font-weight:500}
    .st .brand .nm{font-size:38px}
    .st .srows{margin-top:64px}
    .st .srow{padding:52px 0;border-bottom:1px solid var(--hair)}
    .st .srow:last-child{border-bottom:none}
    .st .slab{font-family:var(--mono);font-size:27px;text-transform:uppercase;letter-spacing:.08em;color:var(--ink2);display:flex;justify-content:space-between;align-items:baseline}
    .st .slab .r{color:var(--ink);font-weight:500;display:flex;align-items:center;gap:10px}
    .st .slab .r .dot{width:13px;height:13px;border-radius:50%}
    .st .sval{font-family:var(--serif);font-weight:300;font-size:172px;line-height:1;letter-spacing:-.04em;margin-top:40px}
    .st .sval.small{font-size:120px;margin-top:44px}
    .st .sval .u{font-size:.34em;color:var(--ink2);font-style:italic;margin-left:14px;letter-spacing:0}
  `;

  const chamberRow = (lab, f) => `<div class="row"><span class="lab">${lab}</span>
    <span class="rate"><span class="dot" style="background:${f.color}"></span>${esc(f.rate)}</span>
    <div class="val ${f.cls}">${f.chance}%<span class="u">${f.party}</span></div></div>`;

  const feed = `<div class="card sq"><hr class="top">
    <div class="kick"><span>2026 U.S. Midterms</span><span>${esc(shortDate)}</span></div>
    <div class="brand">${LOGO}<span class="nm">The Convergence Index</span></div>
    <div class="rows">
      ${chamberRow('U.S. House — control', house)}
      ${chamberRow('U.S. Senate — control', senate)}
      <div class="row"><span class="lab">Governor races</span>
        <span class="rate"><span class="dot" style="background:${govColor}"></span>${esc(govRate)}</span>
        <div class="val small ${govCls}">${esc(govNum)}<span class="u">${esc(govParty)}</span></div></div>
    </div>
    <div class="foot"><span class="tag">markets × polls, blended</span><span><b>convergence-index.com</b></span></div></div>`;

  // watch card — reference the market favorite for that seat, so the axis is neutral either way
  const top = data.top;
  const pm = top && top.txt.match(/market\s+(\d+)%/i), pp = top && top.txt.match(/polls?\s+(\d+)%/i);
  const mktD = pm ? +pm[1] : null, polD = pp ? +pp[1] : null;
  let dumb = '';
  if (top && mktD != null && polD != null) {
    const refIsD = mktD >= 50;                 // reference party = whoever the market favors here
    const refParty = refIsD ? 'Democrat' : 'Republican';
    const mkt = refIsD ? mktD : 100 - mktD, pol = refIsD ? polD : 100 - polD;
    const lo = Math.min(mkt, pol), hi = Math.max(mkt, pol);
    dumb = `<div class="dumb"><div class="axis">Chance the ${refParty} wins this seat</div><div class="track"></div>
      <span class="end" style="left:0">0%</span><span class="end" style="right:0">100%</span>
      <span class="seg" style="left:${lo}%;width:${hi - lo}%"></span>
      <span class="pt p" style="left:${pol}%"></span><span class="pt m" style="left:${mkt}%"></span>
      <span class="cap p" style="left:${pol}%">Polls ${pol}%</span>
      <span class="cap m" style="left:${mkt}%;top:78px">Market ${mkt}%</span></div>`;
  }
  const watch = `<div class="card sq"><hr class="top">
    <div class="kick"><span>Where polls &amp; markets disagree</span><span>${esc(shortDate)}</span></div>
    <div class="wwrap">
      ${top ? `<div class="wk">Today's biggest split</div>
      <div class="wname">${esc(top.name)}</div><div class="wch">${esc(top.chamber)} race</div>
      ${dumb}
      <div class="wsum">The two signals sit <b>${top.gap} points</b> apart.</div>` :
      `<div class="wname">In sync</div><div class="wsum">Polls and markets broadly agree today.</div>`}
    </div>
    <div class="foot"><span class="tag">see every race</span><span><b>convergence-index.com</b></span></div></div>`;

  const storyRow = (lab, f) => `<div class="srow"><div class="slab"><span>${lab}</span>
    <span class="r"><span class="dot" style="background:${f.color}"></span>${esc(f.rate)}</span></div>
    <div class="sval ${f.cls}">${f.chance}%<span class="u">${f.party}</span></div></div>`;
  const story = `<div class="card st"><hr class="top">
    <div class="kick"><span>2026 Midterms · ${esc(shortDate)}</span><span></span></div>
    <div class="brand">${LOGO}<span class="nm">The Convergence Index</span></div>
    <div class="srows">
      ${storyRow('U.S. House — control', house)}
      ${storyRow('U.S. Senate — control', senate)}
      <div class="srow"><div class="slab"><span>Governor races</span>
        <span class="r"><span class="dot" style="background:${govColor}"></span>${esc(govRate)}</span></div>
        <div class="sval small ${govCls}">${esc(govNum)}<span class="u">${esc(govParty)}</span></div></div>
    </div>
    <div class="foot" style="font-size:28px"><span class="tag">markets × polls</span><span><b>convergence-index.com</b></span></div></div>`;

  const shell = body => `<!doctype html><html><head><meta charset="utf-8"><style>${FONTS}${CSS}</style></head><body>${body}</body></html>`;
  async function shoot(html, file) {
    const pg = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
    await pg.setContent(html, { waitUntil: 'load' });
    await pg.evaluate(() => document.fonts.ready);
    await pg.waitForTimeout(200);
    await (await pg.$('.card')).screenshot({ path: path.join(OUT, file) });
    await pg.close();
  }
  await shoot(shell(feed), 'feed-square.png');
  await shoot(shell(watch), 'watch-square.png');
  await shoot(shell(story), 'story.png');

  // captions — neutral, favored-party framing that flips automatically
  const govCap = gm ? `${gm[1]} lead ${gm[2]} of ${gm[3]} competitive governor races` : 'governor races in play';
  const splitLine = top ? `Today's widest poll–market split: ${top.name} (${top.chamber}), ${top.gap} points apart.` : '';
  const captions = `# Convergence Index — captions for ${dateLabel}

Figures as of ${dateLabel} ET. Neutral framing: each line names whichever party is favored, so nothing needs rewriting if a lead changes. Post feed-square.png on Twitter / LinkedIn / Instagram feed; use story.png for Stories; watch-square.png is an optional second slide.

## Twitter / X
Where the 2026 midterms stand today — prediction markets and polling, blended:

U.S. House — ${house.party} ${house.chance}% (${house.rate})
U.S. Senate — ${senate.party} ${senate.chance}% (${senate.rate})
Governors — ${govCap}

Full board, every figure sourced 👇
convergence-index.com

## LinkedIn
Today's read on the 2026 midterms from The Convergence Index, which blends prediction-market prices with the major polling averages into one control probability per chamber.

House: ${house.party} favored, ${house.chance}%. Senate: ${senate.party} favored, ${senate.chance}%. Governors: ${govCap}.

${splitLine} Move the slider to weight polls or markets yourself, and see where the two disagree.

convergence-index.com

## Instagram
Where the 2026 midterms stand today 🗳️
House: ${house.party} ${house.chance}% · Senate: ${senate.party} ${senate.chance}% · ${gm ? 'Governors: ' + govParty + ' lead in ' + gm[2] + ' of ' + gm[3] : 'Governors in play'}.
Prediction markets × polling, blended and updated daily. Link in bio.
.
.
#2026midterms #elections #politics #predictionmarkets #polling #data #ushouse #ussenate

## Alt text (paste into each platform's alt/description field)
The Convergence Index: control of the 2026 U.S. House leans ${house.party} (${house.chance}%) and the Senate ${senate.party} (${senate.chance}%); ${govCap}. ${splitLine}
`;
  fs.writeFileSync(path.join(OUT, 'captions.md'), captions);

  // ---- Social kit page (published as a claude.ai artifact; images embedded so no uploads are needed) ----
  const img64 = f => fs.readFileSync(path.join(OUT, f)).toString('base64');
  const sections = captions.split(/\n## /).slice(1).map(s => { const i = s.indexOf('\n'); return { h: s.slice(0, i).trim(), body: s.slice(i + 1).trim() }; });
  const graphics = [
    { file: 'feed-square.png', name: `${DATE_ISO} — feed.png`, label: 'Feed post', use: 'Twitter / X, LinkedIn, Instagram feed · 1080 × 1080', cls: 'sqimg' },
    { file: 'story.png', name: `${DATE_ISO} — story.png`, label: 'Story', use: 'Instagram and Facebook Stories · 1080 × 1920', cls: 'stimg' },
    { file: 'watch-square.png', name: `${DATE_ISO} — watch.png`, label: 'Race to watch', use: 'Optional second slide or standalone post · 1080 × 1080', cls: 'sqimg' }
  ];
  const kit = `<title>Convergence Social Kit</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300..600;1,6..72,300..500&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>
:root{--paper:#fcfbf8;--card:#f4f2ec;--ink:#17171a;--ink2:#5d5b56;--ink3:#75726b;--hair:#e2ded6;--accent:#2c4a7a;--ok:#2f6f73;
  --serif:'Newsreader',Georgia,'Times New Roman',serif;--mono:'IBM Plex Mono',ui-monospace,Menlo,monospace;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#131316;--card:#1c1c20;--ink:#ecebe6;--ink2:#a9a69f;--ink3:#8c8981;--hair:#34343a;--accent:#8fb0e3;--ok:#7cc0c4;color-scheme:dark}}
:root[data-theme="dark"]{--paper:#131316;--card:#1c1c20;--ink:#ecebe6;--ink2:#a9a69f;--ink3:#8c8981;--hair:#34343a;--accent:#8fb0e3;--ok:#7cc0c4;color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--paper);color:var(--ink);font-family:var(--serif);font-size:17px;line-height:1.5;margin:0}
.wrap{max-width:1040px;margin:0 auto;padding-inline:20px;padding-block:32px 64px}
header{border-top:3px solid var(--ink);padding-top:14px;display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:6px 20px}
h1{font-weight:400;font-size:clamp(30px,5vw,44px);letter-spacing:-.015em;margin:0;line-height:1.1}
.date{font-family:var(--mono);font-size:13px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink2)}
.lede{color:var(--ink2);font-style:italic;margin:10px 0 0;max-width:62ch}
h2{font-family:var(--mono);font-size:12px;font-weight:500;letter-spacing:.12em;text-transform:uppercase;color:var(--ink2);margin:40px 0 14px;padding-top:12px;border-top:1px solid var(--hair)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:24px;align-items:start}
figure{margin:0;display:flex;flex-direction:column;gap:10px}
figure img{width:100%;height:auto;display:block;border:1px solid var(--hair);background:#fcfbf8}
.stimg{max-width:72%}
figcaption{display:flex;flex-direction:column;gap:2px}
.gl{font-size:19px}
.gu{font-family:var(--mono);font-size:12px;color:var(--ink3)}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
button{font-family:var(--mono);font-size:12px;letter-spacing:.06em;text-transform:uppercase;border:1px solid var(--ink2);background:transparent;color:var(--ink);padding:9px 14px;cursor:pointer;min-height:40px}
button:hover{border-color:var(--ink);background:var(--card)}
button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.msg{font-family:var(--mono);font-size:12px;color:var(--ok)}
.hint{font-family:var(--mono);font-size:12px;color:var(--ink3)}
.caps{display:grid;gap:18px}
.cap{background:var(--card);padding:16px 18px;border-left:3px solid var(--accent)}
.cap h3{font-family:var(--mono);font-size:12px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;margin:0 0 8px;color:var(--ink)}
.cap pre{white-space:pre-wrap;word-wrap:break-word;font-family:var(--serif);font-size:16px;margin:0 0 12px;color:var(--ink)}
footer{margin-top:40px;font-family:var(--mono);font-size:12px;color:var(--ink3)}
footer a{color:var(--accent)}
@media (max-width:600px){.stimg{max-width:100%}}
</style>
<div class="wrap">
  <header><h1>Social kit</h1><span class="date">${esc(dateLabel)}</span></header>
  <p class="lede">Today's graphics and captions from The Convergence Index, rebuilt every morning after the data update. Figures as of ${esc(dateLabel)}.</p>
  <h2>Graphics</h2>
  <div class="grid">
  ${graphics.map((g, i) => `<figure>
      <img class="${g.cls}" src="data:image/png;base64,${img64(g.file)}" alt="${esc(g.label)} graphic for ${esc(dateLabel)}" id="img${i}">
      <figcaption><span class="gl">${esc(g.label)}</span><span class="gu">${esc(g.use)}</span></figcaption>
      <div class="row"><button type="button" class="save" data-i="${i}" data-name="${esc(g.name)}" hidden>Save image</button><span class="msg" id="m${i}" role="status"></span></div>
    </figure>`).join('\n  ')}
  </div>
  <p class="hint">On a phone you can also press and hold an image to save it.</p>
  <h2>Captions</h2>
  <div class="caps">
  ${sections.map((s, i) => `<div class="cap"><h3>${esc(s.h)}</h3><pre id="c${i}">${esc(s.body)}</pre>
      <div class="row"><button type="button" class="copy" data-i="${i}">Copy</button><span class="msg" id="cm${i}" role="status"></span></div></div>`).join('\n  ')}
  </div>
  <footer>Captions are also saved each morning to Google Drive → “Convergence Index — Social”. Live site: <a href="https://convergence-index.com" target="_blank" rel="noopener">convergence-index.com</a></footer>
</div>
<script>
(function(){
  var dl=null;
  function flash(id,t){var e=document.getElementById(id);if(!e)return;e.textContent=t;setTimeout(function(){e.textContent='';},3500);}
  function toBlob(src){var b=atob(src.split(',')[1]),a=new Uint8Array(b.length);for(var i=0;i<b.length;i++)a[i]=b.charCodeAt(i);return new Blob([a],{type:'image/png'});}
  var p=(window.claude&&window.claude.use)?window.claude.use('downloads'):Promise.resolve(null);
  Promise.resolve(p).then(function(d){dl=d;if(d)document.querySelectorAll('.save').forEach(function(b){b.hidden=false;});}).catch(function(){});
  document.addEventListener('click',function(e){
    var s=e.target.closest('.save');
    if(s&&dl){var i=s.dataset.i;dl.save({filename:s.dataset.name,data:toBlob(document.getElementById('img'+i).src)}).then(function(){flash('m'+i,'Saved');},function(err){flash('m'+i,err&&err.code==='declined'?'Not saved':'Could not save — press and hold the image instead');});return;}
    var c=e.target.closest('.copy');
    if(c){var j=c.dataset.i,t=document.getElementById('c'+j).textContent;
      var done=function(){flash('cm'+j,'Copied');};
      if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(done,function(){sel(j);});}else sel(j);
    }
  });
  function sel(j){var r=document.createRange();r.selectNodeContents(document.getElementById('c'+j));var s=window.getSelection();s.removeAllRanges();s.addRange(r);flash('cm'+j,'Selected — copy it from the menu');}
})();
</script>
`;
  fs.writeFileSync(path.join(OUT, 'social-kit.html'), kit);
  console.log(JSON.stringify({ house: `${house.party} ${house.chance}`, senate: `${senate.party} ${senate.chance}`, gov: `${govNum} ${govParty}`, top: top && top.name + ' ' + top.gap, asOf: data.asOf, files: fs.readdirSync(OUT) }, null, 1));
  await browser.close();
})();
