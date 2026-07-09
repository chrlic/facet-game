import json
D = json.load(open('diagrams.json'))

ICON_DEFS = '''
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <defs>
    <symbol id="icon-router" viewBox="0 0 24 24">
      <g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="7.5"/>
        <path d="M12 4.2 L14.8 6.3 L12.5 8.1"/>
        <path d="M12 19.8 L9.2 17.7 L11.5 15.9"/>
      </g>
    </symbol>
    <symbol id="icon-switch" viewBox="0 0 24 24">
      <g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="6.5" width="18" height="11" rx="1.4"/>
        <path d="M6 10 H16.5"/>
        <path d="M13.8 7.8 L16.5 10 L13.8 12.2"/>
        <path d="M18 14 H7.5"/>
        <path d="M10.2 11.8 L7.5 14 L10.2 16.2"/>
      </g>
    </symbol>
    <symbol id="icon-ap" viewBox="0 0 24 24">
      <g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
        <rect x="9" y="16.5" width="6" height="3.4" rx="1" fill="currentColor" stroke="none"/>
        <path d="M8.4 14.6a5.2 5.2 0 0 1 7.2 0"/>
        <path d="M5.6 11.4a9.4 9.4 0 0 1 12.8 0"/>
      </g>
    </symbol>
    <symbol id="icon-firewall" viewBox="0 0 24 24">
      <g fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round">
        <rect x="2.5" y="4.5" width="19" height="15" rx="1.2"/>
        <path d="M2.5 9.5h19M2.5 14.5h19M8.5 4.5v5M14.8 4.5v5M5.7 9.5v5M11.8 9.5v5M17.8 9.5v5M8.5 14.5v5M14.8 14.5v5"/>
      </g>
    </symbol>
    <symbol id="icon-server" viewBox="0 0 24 24">
      <g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round">
        <rect x="4" y="4" width="16" height="6.6" rx="1.1"/>
        <rect x="4" y="13.4" width="16" height="6.6" rx="1.1"/>
        <circle cx="7.1" cy="7.3" r=".9" fill="currentColor" stroke="none"/>
        <circle cx="9.6" cy="7.3" r=".9" fill="currentColor" stroke="none"/>
        <path d="M13.2 7.3h4.3"/>
        <circle cx="7.1" cy="16.7" r=".9" fill="currentColor" stroke="none"/>
        <circle cx="9.6" cy="16.7" r=".9" fill="currentColor" stroke="none"/>
        <path d="M13.2 16.7h4.3"/>
      </g>
    </symbol>
    <symbol id="icon-dc" viewBox="0 0 24 24">
      <g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round">
        <rect x="3.2" y="10" width="4.6" height="10" rx="1"/>
        <rect x="9.7" y="5" width="4.6" height="15" rx="1"/>
        <rect x="16.2" y="10" width="4.6" height="10" rx="1"/>
        <path d="M2.5 20.5h19"/>
      </g>
    </symbol>
  </defs>
</svg>
'''

def icon(kind, color="#2a2f3a", size=15):
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" '
           f'style="vertical-align:-3px;color:{color}"><use href="#icon-{kind}"/></svg>')

def fig(key, caption, width="46%"):
    return f'''<figure style="display:inline-block;width:{width};vertical-align:top;margin:8px 1%;text-align:center;break-inside:avoid;page-break-inside:avoid">
      <div style="border:1px solid #dfe3ea;border-radius:10px;padding:10px;background:#fff">{D[key]}</div>
      <figcaption style="font-size:11.5px;color:#5a6072;margin-top:5px;line-height:1.4">{caption}</figcaption>
    </figure>'''

PIECES = [
    ("router", "Router", "2 BW", "The backbone. Extends your network into a new hex and claims it as territory. Datacenters need 2 adjacent Routers to come online."),
    ("switch", "Switch", "1 BW", "Cheap glue. May only be placed adjacent to 2+ of your own pieces — it fills gaps, it never expands the frontier."),
    ("ap", "Wireless AP", "3 BW", "Jumps your connection over exactly 1 hex — empty or enemy-occupied. The jumped hex is not your territory; the AP's own hex is."),
    ("firewall", "Firewall", "2 BW", "Placed on top of one of your pieces. Blocks the next Hack against that piece, then is discarded and returns to your supply."),
    ("server", "Server", "3 BW", "Serves 1 adjacent City (your choice, fixed at build time). Also satisfies the Server requirement for Datacenters in your network."),
    ("dc", "Datacenter", "6 BW", "Your engine of victory. Online — and worth 1 AI token — while adjacent to 2+ of your Routers and connected to 1+ of your Servers."),
]

html = f'''<!doctype html>
<html><head><meta charset="utf-8">
<title>BACKBONE — Player's Guide</title>
{ICON_DEFS}
<style>
  @page {{ size: A4; margin: 20mm 16mm; }}
  *{{box-sizing:border-box}}
  body{{font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;color:#20242e;
       line-height:1.55;font-size:13.5px;max-width:760px;margin:0 auto}}
  h1{{font-size:30px;letter-spacing:3px;margin:0 0 2px;font-weight:800}}
  h2{{font-size:19px;margin:30px 0 10px;padding-bottom:6px;border-bottom:2px solid #20242e;
     page-break-after:avoid}}
  h3{{font-size:15px;margin:16px 0 6px;page-break-after:avoid}}
  .tag{{color:#5a6072;font-size:13px;margin:0 0 18px}}
  .cover{{text-align:center;padding:70px 0 40px;page-break-after:always}}
  .cover .tag{{font-size:15px;margin-top:6px}}
  .cover .ver{{margin-top:60px;font-size:12px;color:#8a90a0}}
  table{{border-collapse:collapse;width:100%;margin:10px 0 16px;font-size:12.5px}}
  th,td{{border:1px solid #dfe3ea;padding:6px 9px;text-align:left;vertical-align:top}}
  th{{background:#f4f6fb;font-weight:700}}
  .cost{{color:#8a6d1f;font-weight:700;white-space:nowrap}}
  .callout{{background:#f4f6fb;border-left:4px solid #2560a8;padding:10px 14px;
           border-radius:0 8px 8px 0;margin:14px 0;font-size:12.5px}}
  .callout.warn{{border-color:#c0392b;background:#fbf1ef}}
  .callout b{{color:#20242e}}
  .figrow{{margin:10px 0}}
  .p1{{color:#1a7a52;font-weight:700}} .p2{{color:#2560a8;font-weight:700}}
  .stepbox{{display:flex;gap:8px;margin:14px 0;flex-wrap:wrap;break-inside:avoid;page-break-inside:avoid}}
  .step{{flex:1;min-width:130px;background:#f4f6fb;border-radius:10px;padding:10px 12px;
        font-size:12px;break-inside:avoid;page-break-inside:avoid}}
  table{{break-inside:avoid;page-break-inside:avoid}}
  .quickref{{break-inside:avoid;page-break-inside:avoid}}
  .callout{{break-inside:avoid;page-break-inside:avoid}}
  .step b{{display:block;font-size:12.5px;margin-bottom:3px}}
  .quickref{{background:#20242e;color:#eef1f7;padding:18px 20px;border-radius:12px;margin-top:20px}}
  .quickref h2{{color:#fff;border-color:#4a5066}}
  .quickref table{{font-size:12px}}
  .quickref th,.quickref td{{border-color:#3a4055;color:#eef1f7}}
  .quickref th{{background:#2a2f42}}
  footer{{margin-top:24px;font-size:10.5px;color:#9aa0ae;text-align:center}}
</style>
</head>
<body>

<div class="cover">
  <h1>BACKBONE</h1>
  <div class="tag">A network-building strategy game for 2 players<br>Ages 10+ &middot; roughly 30 minutes &middot; hex board</div>
  <div style="margin-top:50px">
    {D['board_overview']}
  </div>
  <div class="ver">Player's Guide &middot; Ruleset v1.1 &middot; symmetric board, 10 AI tokens to win</div>
</div>

<h2>Objective</h2>
<p>You are a rival network operator. Expand your infrastructure across the hex map, bring
<b>Datacenters</b> online, and connect <b>Cities</b> to your network. The first player to reach
<b>10 AI tokens</b> at the end of their turn triggers the endgame — see
<i>Winning the Game</i> below.</p>

<h2>The Board</h2>
<p>A 9&times;9 hex grid. Two corners are <b>start hexes</b> — yours already holds a Router and a Server.
Seven <b>City</b> hexes (⬢) are neutral, never move, and are shared ground: both players may connect
to the same City at once. The city layout is a true 180&deg; rotation of the grid, so both starting
corners are exactly the same distance from the nearest, second-nearest, and every other City —
nobody has a geometric head start.</p>

<h3>Adjacency</h3>
<div class="figrow">
  {fig('adjacency', 'Adjacent means the six hexes touching a hex — the highlighted hex and its full ring of neighbors.', '44%')}
  {fig('ap_jump', 'A Wireless AP also counts as adjacent to whatever sits exactly 1 hex beyond it in a straight line. The jumped hex itself is never claimed as territory.', '50%')}
</div>

<h2>Setup</h2>
<div class="stepbox">
  <div class="step"><b>1. Starting pieces</b>Each player begins with 1 Router and 1 Server on their start corner and the hex next to it.</div>
  <div class="step"><b>2. Bandwidth</b>Player 1 takes 3 BW. Player 2 takes 5 BW — the extra 2 offsets moving second.</div>
  <div class="step"><b>3. First move</b>Player 1 begins.</div>
</div>
<div class="callout">Bandwidth (BW) is the game's only currency — spent to Build, and to Hack.
Income (below) adds more of it every turn, up to a hand limit of 10.</div>

<h2>Turn Structure</h2>
<div class="stepbox">
  <div class="step"><b>1. Income</b>+3 BW, plus +1 BW per City you're currently connected to. Capped at 10 BW.</div>
  <div class="step"><b>2. Actions</b>Take any <b>2</b> actions: Build, Hack, or Reroute — the same action twice is fine.</div>
  <div class="step"><b>3. Recover</b>Remove Disabled markers from pieces that were hacked on the opponent's last turn.</div>
  <div class="step"><b>4. Score</b>Count your AI tokens. Reaching the target here can end the game — see below.</div>
</div>

<h2>The Three Actions</h2>

<h3>Build</h3>
<p>Pay the piece's cost and place it from your supply on an empty, non-City hex adjacent to your
network. New pieces must keep your network connected. (Firewalls are the exception — they're
placed on top of a piece you already own, not on an empty hex.)</p>
<div class="figrow">
  {fig('router_before', 'Before: two Routers form the frontier.', '30%')}
  {fig('router_after', 'After: a new Router extends the network one hex further — the new hex becomes territory.', '30%')}
  {fig('switch_valid', 'A Switch needs 2+ adjacent friendly pieces to be legal — it fills a gap...', '35%')}
</div>
<div class="figrow">
  {fig('switch_invalid', 'One adjacent piece is not enough. Switches consolidate; they do not expand the frontier on their own.', '46%')}
  {fig('server_city', 'A Server built adjacent to a City connects it — the City shows the connecting player color and starts contributing +1 AI token.', '46%')}
</div>

<h3>Hack</h3>
<p>Pay the Hack cost and choose an enemy piece adjacent to your network. If it carries a Firewall,
the Firewall is discarded (and returned to its owner's supply) and the piece is safe. Otherwise a
Disabled marker goes on it: until it recovers at the end of the victim's next turn, it does not
connect, serve, or score — <b>and any of the victim's pieces that were only reachable through it
fall out of the network too.</b> Hacks never destroy pieces or remove territory outright.</p>
<div class="figrow">
  {fig('hack_before', 'Before: a Router is the sole bridge connecting a Datacenter to the rest of the network.', '46%')}
  {fig('hack_after', 'After a Hack: the bridge Router is disabled, and the Datacenter it was carrying falls out of the network — no longer online, no longer scoring.', '46%')}
</div>
<div class="figrow">
  {fig('firewall', 'A Firewalled piece absorbs the next Hack instead of being disabled — the Firewall is spent in the process.', '38%')}
</div>
<div class="callout warn"><b>Defend what matters.</b> The single piece holding two halves of your
network together, or the Router propping up a Datacenter, is worth a Firewall far more than a
piece on the edge of your territory.</div>

<h3>Reroute</h3>
<p>Move one of your Switches or Wireless APs to a different legal hex, free of charge. Your
network must remain fully connected — at least as large as it was — after the move.</p>

<h2>Infrastructure Pieces</h2>
<table>
<tr><th>Piece</th><th>Cost</th><th>What it does</th></tr>
{''.join(f'<tr><td>{icon(k)} {name}</td><td class="cost">{cost}</td><td>{desc}</td></tr>' for k,name,cost,desc in PIECES)}
</table>

<h2>Scoring</h2>
<p>Checked at the end of every turn:</p>
<table>
<tr><th>Source</th><th>AI tokens</th></tr>
<tr><td>Each of your <b>online</b> Datacenter</td><td>1</td></tr>
<tr><td>Each City connected to your network</td><td>1</td></tr>
<tr><td>Two or more of your Datacenters linked through your network (once, as a bonus)</td><td>2</td></tr>
</table>
<div class="figrow">
  {fig('dc_online', 'Online: 2 adjacent Routers, and a Server somewhere in the same network. Scores +1 AI token — shown by the gold ring.', '48%')}
  {fig('dc_offline', 'Offline: only 1 adjacent Router so far. Built, but not yet earning anything — the dashed ring marks it.', '44%')}
</div>
<div class="figrow">
  {fig('dc_link', 'Two online Datacenters sharing one network trigger the one-time +2 link bonus — on top of the +1 each already earns for being online.', '70%')}
</div>
<div class="callout">A Datacenter that isn't online yet is an investment, not points — it takes a
turn or two of Router support to start paying off. Losing your only networked Server takes every
Datacenter offline at once, not just the City connections — that's usually the more dangerous hack.</div>

<h2>Winning the Game</h2>
<p>The moment you end a turn with <b>10 AI tokens or more</b>, your opponent gets exactly <b>one more full
turn</b> before the game is scored — a fair chance to catch up or overtake, since by the numbers
alone the player who reaches the target first would otherwise win almost automatically.
Afterward: whoever holds more AI tokens wins; a tie goes to whoever has more connected Cities; still tied is a draw.
(If <i>you</i> are the second player to reach the target on that closing turn, the game ends
immediately — both sides have already had the same number of turns, so no extra turn is needed.)</p>
<p>If both players are stuck with no productive action for a full round (four consecutive Passes),
the game ends the same way: most AI tokens, then more connected Cities, then a draw.</p>

<h2>Strategy Tips</h2>
<ul>
<li>Routers grab ground fast but stretch you thin — a long, unprotected spine is easy to Hack at the joints. Switches and Wireless APs make a denser, harder-to-cut core, at the cost of territory.</li>
<li>Firewall the pieces whose loss hurts most: the Server feeding a Datacenter, or the single link holding two halves of your network together — not whatever's simply nearest the front line.</li>
<li>An unbuilt Datacenter is not a Datacenter. Don't celebrate placing one until it actually has 2 Routers and a networked Server — check the ring.</li>
<li>The two-Datacenter link bonus (+2) is often the sprint that actually ends the game — it's worth planning your network's shape around getting two Datacenters into the same component, not just building them wherever there's room.</li>
<li>Hacking is limited to once per turn at 1 BW — cheap, but not free. A well-timed single Hack that severs a bridge is worth far more than denying one piece's income.</li>
</ul>

<div class="quickref">
  <h2 style="margin-top:0">Quick Reference</h2>
  <table>
    <tr><th>Piece</th><th>Cost</th><th>Piece</th><th>Cost</th></tr>
    <tr><td>{icon('router','#eef1f7')} Router</td><td>2 BW</td>
        <td>{icon('firewall','#eef1f7')} Firewall</td><td>2 BW</td></tr>
    <tr><td>{icon('switch','#eef1f7')} Switch</td><td>1 BW</td>
        <td>{icon('server','#eef1f7')} Server</td><td>3 BW</td></tr>
    <tr><td>{icon('ap','#eef1f7')} Wireless AP</td><td>3 BW</td>
        <td>{icon('dc','#eef1f7')} Datacenter</td><td>6 BW</td></tr>
  </table>
  <table>
    <tr><th>Rule</th><th>Value</th></tr>
    <tr><td>AI tokens to win</td><td>10 (triggers opponent's final turn)</td></tr>
    <tr><td>Income</td><td>+3 BW, +1 per connected City, cap 10</td></tr>
    <tr><td>Hack cost</td><td>1 BW, at most once per turn</td></tr>
    <tr><td>Datacenter online</td><td>2 adjacent Routers + 1 networked Server</td></tr>
    <tr><td>Datacenter link bonus</td><td>+2, once, for 2+ online Datacenters in one network</td></tr>
    <tr><td>Stuck game</td><td>4 consecutive Passes &rarr; most AI tokens, then more Cities, then draw</td></tr>
  </table>
</div>

<footer>BACKBONE Player's Guide &middot; generated from the live ruleset (backbone_engine.py) &middot; diagrams drawn with the game's own hex geometry</footer>

</body></html>
'''

open('BACKBONE_GUIDE.html', 'w').write(html)
print(f'wrote BACKBONE_GUIDE.html ({len(html)} chars)')
