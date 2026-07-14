"""Generate the illustrated HYPERSCALE player's guide (HTML -> print to PDF with
Chrome). Hex diagrams are drawn here in SVG using the same board geometry, pieces
and colours as the live game (docs/hyperscale.html / hyperscale_engine.js), in a
print-friendly light palette."""
import math

# ---- print-friendly palette (darker than the on-screen neon) ----
INK = '#20242e'
P0 = '#1a7a52'; P0F = '#e7f4ed'      # you (green)
P1 = '#2560a8'; P1F = '#e9f0fb'      # AI (blue)
PWR = '#b5651d'; PWRF = '#f0d8bd'    # power / stations (orange)
HEXF = '#f6f8fc'; HEXS = '#ccd3e1'   # empty hex
GRID = '#e3e8f1'

S = 26          # hex "radius"
W = math.sqrt(3) * S


def hexpoly(cx, cy):
    pts = []
    for i in range(6):
        a = math.pi / 180 * (60 * i - 30)
        pts.append(f'{cx + S * math.cos(a):.1f},{cy + S * math.sin(a):.1f}')
    return ' '.join(pts)


def center(x, y, ox, oy):
    """odd-r offset, y increasing UPWARD (row 0 bottom), matching the game."""
    cx = ox + W * (x + 0.5 * (y & 1)) + W / 2
    cy = oy - 1.5 * S * y
    return cx, cy


def board(cells, links=None, roads=None, w=None, h=None, pad=18):
    """cells: dict (x,y) -> dict(kind, owner, label, cap, faint).
       kind: 'hex'|'station'|'hq'|'dc'|'pl'(power-line piece)|'road'.
       links: list of ((x1,y1),(x2,y2)) dashed orange power connections.
       roads: list of ((x1,y1),(x2,y2)) solid owner-coloured road links."""
    xs = [x for x, y in cells]; ys = [y for x, y in cells]
    maxy = max(ys)
    ox = pad - min(W * (x + 0.5 * (y & 1)) for x, y in cells)
    oy = pad + 1.5 * S * maxy + S
    cen = {k: center(k[0], k[1], ox, oy) for k in cells}
    width = max(cx for cx, cy in cen.values()) + W / 2 + pad
    height = max(cy for cx, cy in cen.values()) + S + pad
    out = [f'<svg viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}" xmlns="http://www.w3.org/2000/svg">']
    # base hexes first
    for (x, y), c in cells.items():
        cx, cy = cen[(x, y)]
        op = '0.4' if c.get('faint') else '1'
        fill = HEXF
        if c['kind'] == 'hq':
            fill = P0F if c.get('owner') == 0 else P1F
        out.append(f'<polygon points="{hexpoly(cx, cy)}" fill="{fill}" stroke="{HEXS}" stroke-width="1.2" opacity="{op}"/>')
    # road links (solid, owner colour)
    for (a, b) in (roads or []):
        if a in cen and b in cen:
            (x1, y1), (x2, y2) = cen[a], cen[b]
            col = P0 if cells.get(a, {}).get('owner', 0) == 0 else P1
            out.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="{col}" stroke-width="3" stroke-opacity="0.5"/>')
    # power links (dashed orange)
    for (a, b) in (links or []):
        if a in cen and b in cen:
            (x1, y1), (x2, y2) = cen[a], cen[b]
            out.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="{PWR}" stroke-width="2.2" stroke-dasharray="4,3" stroke-opacity="0.85"/>')
    # piece glyphs on top
    for (x, y), c in cells.items():
        cx, cy = cen[(x, y)]
        k = c['kind']
        if k == 'station':
            out.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="13" fill="{PWR}" stroke="#7a3f10" stroke-width="1.5"/>')
            out.append(f'<text x="{cx:.0f}" y="{cy+4:.0f}" text-anchor="middle" font-size="13" font-weight="800" fill="#fff">{c["cap"]}</text>')
        elif k == 'hq':
            col = P0 if c.get('owner') == 0 else P1
            out.append(f'<text x="{cx:.0f}" y="{cy+4:.0f}" text-anchor="middle" font-size="12" font-weight="800" fill="{col}">HQ</text>')
        elif k == 'dc':
            col = P0 if c.get('owner') == 0 else P1
            out.append(f'<rect x="{cx-13:.0f}" y="{cy-13:.0f}" width="26" height="26" rx="5" fill="#fff" stroke="{col}" stroke-width="2.4"/>')
            out.append(f'<text x="{cx:.0f}" y="{cy+4:.0f}" text-anchor="middle" font-size="12" font-weight="800" fill="{col}">{c.get("label","")}</text>')
        elif k == 'pl':
            col = P0 if c.get('owner') == 0 else P1
            out.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="5" fill="{PWR}" stroke="{col}" stroke-width="1.5"/>')
        elif k == 'road':
            col = P0 if c.get('owner') == 0 else P1
            out.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="5" fill="{col}"/>')
        if c.get('sab'):   # sabotage target: red dashed hex + cross
            out.append(f'<polygon points="{hexpoly(cx, cy)}" fill="#c0392b" fill-opacity="0.12" stroke="#c0392b" stroke-width="2.2" stroke-dasharray="4,3"/>')
            out.append(f'<text x="{cx:.0f}" y="{cy+5:.0f}" text-anchor="middle" font-size="15" font-weight="800" fill="#c0392b">&#10005;</text>')
        if c.get('note'):
            out.append(f'<text x="{cx:.0f}" y="{cy-17:.0f}" text-anchor="middle" font-size="9" fill="#7a8194">{c["note"]}</text>')
    out.append('</svg>')
    return ''.join(out)


def H(*rows):
    return {k: v for d in rows for k, v in d.items()}


STATIONS = {(4, 3): 5, (4, 4): 6, (4, 5): 5, (2, 2): 2, (6, 6): 2}

# ---- diagram: full board overview ----
cells = {}
for y in range(9):
    for x in range(9):
        cells[(x, y)] = {'kind': 'hex'}
cells[(0, 0)] = {'kind': 'hq', 'owner': 0}
cells[(8, 8)] = {'kind': 'hq', 'owner': 1}
for (x, y), cap in STATIONS.items():
    cells[(x, y)] = {'kind': 'station', 'cap': cap}
DIA_BOARD = board(cells, pad=14)

# ---- diagram: powered by adjacency ----
c = {(x, y): {'kind': 'hex', 'faint': True} for x in range(3, 7) for y in range(2, 6)}
c[(4, 4)] = {'kind': 'station', 'cap': 6}
c[(5, 4)] = {'kind': 'dc', 'owner': 0, 'label': '4', 'note': 'next to station'}
DIA_ADJ = board(c, links=[((5, 4), (4, 4))])

# ---- diagram: powered by a power line ----
c = {(x, y): {'kind': 'hex', 'faint': True} for x in range(1, 6) for y in range(2, 6)}
c[(4, 4)] = {'kind': 'station', 'cap': 6}
c[(1, 3)] = {'kind': 'dc', 'owner': 0, 'label': '4', 'note': 'far from power'}
c[(2, 3)] = {'kind': 'pl', 'owner': 0}
c[(3, 3)] = {'kind': 'pl', 'owner': 0}
DIA_LINE = board(c, links=[((1, 3), (2, 3)), ((2, 3), (3, 3)), ((3, 3), (4, 4))])

# ---- diagram: road to HQ (manning) ----
c = {(x, y): {'kind': 'hex', 'faint': True} for x in range(0, 5) for y in range(0, 4)}
c[(0, 0)] = {'kind': 'hq', 'owner': 0}
c[(1, 0)] = {'kind': 'road', 'owner': 0}
c[(2, 1)] = {'kind': 'road', 'owner': 0}
c[(3, 2)] = {'kind': 'dc', 'owner': 0, 'label': '4', 'note': '3 hops from HQ'}
c[(4, 2)] = {'kind': 'station', 'cap': 5}
DIA_ROAD = board(c, roads=[((0, 0), (1, 0)), ((1, 0), (2, 1)), ((2, 1), (3, 2))], links=[((3, 2), (4, 2))])

# ---- diagram: sabotage a chokepoint ----
c = {(x, y): {'kind': 'hex', 'faint': True} for x in range(2, 8) for y in range(2, 6)}
c[(7, 5)] = {'kind': 'hq', 'owner': 1}
c[(6, 4)] = {'kind': 'road', 'owner': 1}
c[(5, 4)] = {'kind': 'road', 'owner': 1, 'sab': True, 'note': 'you demolish this'}
c[(4, 4)] = {'kind': 'dc', 'owner': 1, 'label': '4'}
c[(4, 5)] = {'kind': 'dc', 'owner': 1, 'label': '3'}
c[(4, 3)] = {'kind': 'road', 'owner': 0, 'note': 'your piece, adjacent'}
DIA_SAB = board(c, roads=[((7, 5), (6, 4)), ((6, 4), (5, 4)), ((5, 4), (4, 4)), ((4, 4), (4, 5))])

# ---- diagram: contested centre ----
c = {(x, y): {'kind': 'hex', 'faint': True} for x in range(2, 7) for y in range(2, 6)}
for (x, y), cap in [((4, 3), 5), ((4, 4), 6), ((4, 5), 5)]:
    c[(x, y)] = {'kind': 'station', 'cap': cap}
c[(3, 3)] = {'kind': 'dc', 'owner': 0, 'label': '4'}
c[(5, 4)] = {'kind': 'dc', 'owner': 1, 'label': '4'}
DIA_CENTRE = board(c, links=[((3, 3), (4, 3)), ((3, 3), (4, 4)), ((5, 4), (4, 4)), ((5, 4), (4, 5)), ((5, 4), (4, 3))])


def fig(svg, cap, width='46%'):
    return (f'<figure style="display:inline-block;width:{width};vertical-align:top;margin:8px 1%;'
            f'text-align:center;break-inside:avoid;page-break-inside:avoid">'
            f'<div style="border:1px solid #dfe3ea;border-radius:10px;padding:10px;background:#fff">{svg}</div>'
            f'<figcaption style="font-size:11.5px;color:#5a6072;margin-top:5px;line-height:1.4">{cap}</figcaption></figure>')


html = f'''<!doctype html>
<html><head><meta charset="utf-8">
<title>HYPERSCALE — Player's Guide</title>
<style>
  @page {{ size: A4; margin: 20mm 16mm; }}
  *{{box-sizing:border-box}}
  body{{font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;color:{INK};
       line-height:1.55;font-size:13.5px;max-width:760px;margin:0 auto}}
  h1{{font-size:32px;letter-spacing:4px;margin:0 0 2px;font-weight:800}}
  h2{{font-size:19px;margin:28px 0 10px;padding-bottom:6px;border-bottom:2px solid {INK};page-break-after:avoid}}
  h3{{font-size:15px;margin:16px 0 6px;page-break-after:avoid}}
  p{{margin:8px 0}}
  .tag{{color:#5a6072;font-size:13px;margin:0 0 18px}}
  .cover{{text-align:center;padding:60px 0 30px;page-break-after:always}}
  .cover .tag{{font-size:15px;margin-top:6px}}
  .cover .ver{{margin-top:40px;font-size:12px;color:#8a90a0}}
  table{{border-collapse:collapse;width:100%;margin:10px 0 16px;font-size:12.5px;break-inside:avoid;page-break-inside:avoid}}
  th,td{{border:1px solid #dfe3ea;padding:6px 9px;text-align:left;vertical-align:top}}
  th{{background:#f4f6fb;font-weight:700}}
  .callout{{background:#f4f6fb;border-left:4px solid {P0};padding:10px 14px;border-radius:0 8px 8px 0;margin:14px 0;font-size:12.5px;break-inside:avoid;page-break-inside:avoid}}
  .callout.warn{{border-color:#c0392b;background:#fbf1ef}}
  .callout b{{color:{INK}}}
  .figrow{{margin:10px 0}}
  .you{{color:{P0};font-weight:700}} .ai{{color:{P1};font-weight:700}} .pw{{color:{PWR};font-weight:700}}
  .stepbox{{display:flex;gap:8px;margin:14px 0;flex-wrap:wrap;break-inside:avoid;page-break-inside:avoid}}
  .step{{flex:1;min-width:150px;background:#f4f6fb;border-radius:10px;padding:10px 12px;font-size:12px}}
  .step b{{display:block;font-size:12.5px;margin-bottom:3px}}
  ul{{margin:8px 0 8px 0;padding-left:20px}} li{{margin:5px 0}}
  .quickref{{background:{INK};color:#eef1f7;padding:18px 20px;border-radius:12px;margin-top:22px;break-inside:avoid;page-break-inside:avoid}}
  .quickref h2{{color:#fff;border-color:#4a5066;margin-top:0}}
  .quickref table{{font-size:12px}}
  .quickref th,.quickref td{{border-color:#3a4055;color:#eef1f7}}
  .quickref th{{background:#2a2f42}}
  footer{{margin-top:24px;font-size:10.5px;color:#9aa0ae;text-align:center}}
</style>
</head>
<body>

<div class="cover">
  <h1>HYPERSCALE</h1>
  <div class="tag">Build an AI-datacenter empire &mdash; 1 player vs. the computer<br>
     Ages 12+ &middot; ~10&ndash;15 minutes &middot; hex board</div>
  <div style="margin-top:36px">{DIA_BOARD}</div>
  <div class="ver">Player's Guide &middot; 9&times;9 hex board &middot; two HQs, five power stations</div>
</div>

<h2>The Idea</h2>
<p>You and the computer each run a datacenter company from a corner <b>HQ</b>. Over <b>24 days</b> you
claim ground, wire datacenters to shared <b>power stations</b>, staff and equip them, and sell their
output as <b>AI tokens</b>. Power is scarce and fixed to the map, so most of the game is a fight over
the same few stations. <b>Whoever has produced the most AI tokens after day 24 wins.</b></p>

<h2>The Board</h2>
<p>A 9&times;9 hex grid. Your <span class="you">HQ</span> sits in one corner, the
<span class="ai">AI's HQ</span> in the opposite one. Five <span class="pw">power stations</span> are
fixed on the map, each with a capacity (the number on it = how many servers it can power):</p>
<table>
<tr><th>Stations</th><th>Where</th><th>Capacity</th></tr>
<tr><td><span class="pw">Central corridor</span> (3 stations)</td><td>middle of the board</td><td>5 + 6 + 5 = <b>16</b> power</td></tr>
<tr><td>Two <span class="pw">home stations</span></td><td>one near each HQ</td><td>2 each</td></tr>
</table>
<div class="callout">There are only <b>20 power</b> on the whole board and no way to make more. The
big central corridor is the prize &mdash; sitting in your corner only ever powers ~2 servers, so the
game is decided in the middle.</div>

<h2>A Day = 3 Actions</h2>
<p>You and the AI alternate days. On your day you take up to <b>3 actions</b>, then end the day. At
the start of every day your powered servers produce tokens and pay their running costs automatically.
Each action is one of:</p>
<div class="stepbox">
  <div class="step"><b>Build a piece</b>Road, power line, or datacenter on an empty hex.</div>
  <div class="step"><b>Add a server</b>Equip one of your datacenters with a server (buys parts from the market).</div>
  <div class="step"><b>Prestock a part</b>Buy GPU / HBM / CPU from the market to hold for later.</div>
  <div class="step"><b>Sabotage</b>Demolish an adjacent enemy road or power line (once per day). See below.</div>
</div>

<h2>What You Build</h2>
<table>
<tr><th>Piece</th><th>Cost</th><th>What it does</th></tr>
<tr><td><b>Road</b></td><td>$1</td><td>Connects a datacenter back to your HQ so it can be <b>staffed</b>. Chains hex to hex.</td></tr>
<tr><td><b>Power line</b></td><td>$2</td><td>Extends power from a station to a datacenter that isn't next to one. Chains hex to hex.</td></tr>
<tr><td><b>Datacenter</b></td><td>$4</td><td>Holds up to <b>4 servers</b>. Earns only when it's both road-connected and powered.</td></tr>
</table>
<div class="callout">Every piece <b>occupies its hex</b> and blocks the opponent from routing through
it &mdash; walling off the enemy's path is a real tactic.</div>

<h2>Powering a Datacenter</h2>
<p>A datacenter draws power if it is <b>next to a station</b>, or if a chain of your <b>power-line
pieces</b> connects it to one. It draws from every station its network touches (multi-source), so
wiring to several stations makes it resilient if the opponent hogs one.</p>
<div class="figrow">
  {fig(DIA_ADJ, 'Built <b>next to a station</b> &mdash; powered for free (dashed line = the power link).', '46%')}
  {fig(DIA_LINE, 'Built far away &mdash; a chain of <span class="pw">power-line pieces</span> ($2 each) carries power out to it.', '46%')}
</div>
<div class="callout warn">A datacenter needs <b>both</b> a road to HQ <i>and</i> power to earn. A road
with no power = <i>unpowered</i>; power with no road = <i>no staff</i>. Neither produces a thing.</div>

<h2>Servers &amp; the Market</h2>
<p>Output comes from <b>servers</b>. One server = <b>2 GPU + 1 HBM + 1 CPU</b>, bought from a single
shared, finite market. Prices <b>rise as the reserve depletes</b>, so the parts get more expensive the
more everyone buys &mdash; and GPU (the scarcest) can run out entirely. A datacenter holds at most
<b>4 servers</b>, so you can't win by scaling one giant site; you must spread across the contested
stations.</p>
<div class="callout">You can <b>prestock</b> parts to hold for later. Use it to <i>hedge</i> a coming
price rise or to <i>deny</i> the scarce GPU to the AI &mdash; but parts you buy and never install are
wasted money. Buying just-in-time is usually cheaper.</div>

<h2>Running Costs: Power &amp; Staff</h2>
<p>Each powered server earns revenue every day but also costs money to run:</p>
<ul>
<li><b>Power</b> &mdash; a flat cost per powered server.</li>
<li><b>Staffing (manning)</b> &mdash; grows with the <b>road distance</b> from the datacenter back to
your HQ. A site far from home costs more to keep running.</li>
</ul>
<div class="figrow">
  {fig(DIA_ROAD, 'A datacenter 3 road-hops from HQ. The further the road path, the higher its daily staffing cost &mdash; and blocking the enemy into detours raises <i>theirs</i>.', '52%')}
</div>

<h2>The Fight for the Centre</h2>
<p>Both players draw from the same central stations, so their capacity is <b>shared and contested</b>.
When servers compete for a station, the bigger datacenters get powered first; the rest sit <b>dark</b>
(built, but producing nothing). Installing more servers than you can actually power is wasted money.</p>
<div class="figrow">
  {fig(DIA_CENTRE, 'Both of you wire into the central corridor. The 16 central power is split between you &mdash; grab your share early.', '52%')}
</div>

<h2>Sabotage</h2>
<p>Once per day you may spend an action and <b>$3</b> to <b>demolish an enemy road or power-line
piece</b> &mdash; but only one that sits <b>next to a piece of yours</b>, so you have to push into
their space first. You can't destroy a datacenter itself; you cut the <b>connective tissue</b> that
keeps it running.</p>
<div class="figrow">
  {fig(DIA_SAB, 'Their two datacenters hang off one road. Get a piece next to the <span style="color:#c0392b">choke point</span> and demolish it &mdash; both sites lose their link to HQ and go dark until rebuilt.', '52%')}
</div>
<div class="callout">Cutting a <b>choke point</b> &mdash; a single road or power line that several datacenters
depend on &mdash; hits hardest. Defend by building <b>redundant routes</b> so no one piece is critical,
and rebuild a cut link promptly (it's cheap). It's a tempo weapon, not a knockout: limited to once a
day, and the victim repairs for a dollar or two.</div>

<h2>Winning</h2>
<p>Score is <b>cumulative</b>: every day, each powered server adds one AI token to your total. After
<b>day 24</b>, the higher total wins. Because it's cumulative, <b>timing is everything</b> &mdash; a
server switched on early earns for ~20 days; the same server built on the last day earns once.</p>

<h2>Strategy Tips</h2>
<ul>
<li><b>Get online fast and stay full.</b> Fill a datacenter to 4 powered servers before starting the
next one &mdash; early tokens compound, late ones barely count.</li>
<li><b>Contest the centre.</b> Turtling on your 2-power home station caps you at a trivial score. Race
a road to the central corridor and claim your share of the 16.</li>
<li><b>Don't build dark servers.</b> If a station is full, extra servers there produce nothing. Wire to
another open station instead.</li>
<li><b>Buy parts just-in-time.</b> Prices climb as the market drains and leftover stock is dead money.
Prestock only to hedge a spike or to starve the AI of GPU.</li>
<li><b>Mind the manning bill.</b> A far-flung site earns the same tokens but costs more to staff &mdash;
and you can raise the enemy's costs by walling their roads into detours.</li>
<li><b>Wire to more than one station</b> so a contested pool going full doesn't strand your servers.</li>
<li><b>Sabotage choke points, not leaves.</b> Cutting the one road that carries a cluster of the enemy's
sites is worth an action; snipping a dead-end road that carries nothing is not. And keep your own
critical links backed up with a spare route.</li>
</ul>

<div class="quickref">
  <h2>Quick Reference</h2>
  <table>
    <tr><th>Build</th><th>Cost</th><th>Build</th><th>Cost</th></tr>
    <tr><td>Road</td><td>$1</td><td>Datacenter</td><td>$4 (max 4 servers)</td></tr>
    <tr><td>Power line</td><td>$2</td><td>Server</td><td>2 GPU + 1 HBM + 1 CPU (market price)</td></tr>
  </table>
  <table>
    <tr><th>Rule</th><th>Value</th></tr>
    <tr><td>Length of game</td><td>24 days, 3 actions per day</td></tr>
    <tr><td>Total power on the board</td><td>20 (central 16, two homes 2 each)</td></tr>
    <tr><td>A datacenter earns when</td><td>road-connected to HQ <b>and</b> powered (adjacent or wired to a station)</td></tr>
    <tr><td>Server output</td><td>1 AI token per powered server per day (score = cumulative)</td></tr>
    <tr><td>Daily cost per server</td><td>power (flat) + staffing (grows with road distance from HQ)</td></tr>
    <tr><td>Market</td><td>shared &amp; finite; prices rise as it depletes; GPU is scarcest</td></tr>
    <tr><td>Sabotage</td><td>$3, once/day; demolish an enemy road/power line next to your piece; cuts their downstream sites offline</td></tr>
    <tr><td>Win</td><td>most cumulative AI tokens after day 24</td></tr>
  </table>
</div>

<footer>HYPERSCALE Player's Guide &middot; generated from the live ruleset (hyperscale_engine.js) &middot; diagrams drawn with the game's own hex geometry and colours</footer>

</body></html>'''

open('HYPERSCALE_GUIDE.html', 'w').write(html)
print(f'wrote HYPERSCALE_GUIDE.html ({len(html)} chars)')
