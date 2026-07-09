import json
D = json.load(open('facet_diagrams.json'))

TCOLOR = {'F': '#2a3147', 'R': '#2d5fa6', 'B': '#2f8f5b', 'N': '#c4772a', 'T': '#caa12e'}
TGLYPH = {'F': '&#8226;', 'R': '&#9820;', 'B': '&#9821;', 'N': '&#9822;', 'T': '&#9819;'}


def swatch(g, size=15):
    return (f'<span style="display:inline-flex;align-items:center;justify-content:center;'
            f'width:{size}px;height:{size}px;border-radius:4px;background:{TCOLOR[g]};'
            f'color:#fff;font-size:{size-4}px;vertical-align:-3px;margin-right:2px">{TGLYPH[g]}</span>')


def fig(key, caption, width="46%"):
    return f'''<figure style="display:inline-block;width:{width};vertical-align:top;margin:8px 1%;text-align:center;break-inside:avoid;page-break-inside:avoid">
      <div style="border:1px solid #dfe3ea;border-radius:10px;padding:10px;background:#fff">{D[key]}</div>
      <figcaption style="font-size:11.5px;color:#5a6072;margin-top:5px;line-height:1.4">{caption}</figcaption>
    </figure>'''


TERRAIN = [
    ('F', 'Field', 'Step 1 square in any direction (like a king).'),
    ('R', 'Tower', 'Slide horizontally or vertically, any distance (like a rook).'),
    ('B', 'Spire', 'Slide diagonally, any distance (like a bishop).'),
    ('N', 'Gate', 'Leap in an L-shape, ignoring anything in between (like a knight).'),
    ('T', 'Throne', 'Slide in all 8 directions, any distance (like a queen) — also a win objective.'),
]

html = f'''<!doctype html>
<html><head><meta charset="utf-8">
<title>FACET — Player's Guide</title>
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
  <h1>FACET</h1>
  <div class="tag">A chess-inspired strategy game for 2 players<br>Ages 10+ &middot; 15&ndash;30 minutes &middot; square board</div>
  <div style="margin-top:50px">
    {D['board_overview']}
  </div>
  <div class="ver">Player's Guide &middot; Classic 7&times;7 board shown &middot; 10 boards, 3 optional modes</div>
</div>

<h2>Objective</h2>
<p>Every stone is identical — what it can do is granted entirely by the <b>terrain tile</b> it stands
on. Move your stones across the board, using the tiles beneath them, until you either capture the
enemy <b>Monarch</b>, hold both <b>Thrones</b> long enough to be crowned, or strip the enemy down to
a bare Monarch with nothing left to fight with.</p>

<h2>The Board</h2>
<p>A square grid (7&times;7, 8&times;8, or 9&times;9 depending on the board). Every board is
180&deg; rotationally symmetric with exactly two Throne tiles, so neither side starts with a
geometric advantage. Five terrain types are scattered across it:</p>
<table>
<tr><th>Tile</th><th>Name</th><th>Grants this move</th></tr>
{''.join(f'<tr><td>{swatch(g)} {name}</td><td>{desc}</td></tr>' for g, name, desc in TERRAIN[:4])}
<tr><td>{swatch('T')} Throne</td><td>{TERRAIN[4][2]}</td></tr>
</table>
<div class="callout">A stone's move is <b>not fixed</b> — it's whatever the tile underneath currently
grants. Slide a piece from a Tower onto a Gate and its next move is a knight-leap, not a rook-slide.
The board itself is the most important piece.</div>

<h2>Terrain &amp; Movement</h2>
<p>Sliders (Tower, Spire, Throne) travel any distance in their directions until blocked by a piece —
landing on an enemy captures it, landing on your own is illegal, and you stop right there either way.
The Gate leaps in an L exactly like a knight and never cares what's in between.</p>
<div class="figrow">
  {fig('terrain_field', 'Field: 1 step, any of the 8 directions.', '30%')}
  {fig('terrain_tower', 'Tower: slides orthogonally — an enemy in the way is captured, and the slide stops there.', '30%')}
  {fig('terrain_spire', 'Spire: slides diagonally, same blocking rule.', '30%')}
</div>
<div class="figrow">
  {fig('terrain_gate', 'Gate: leaps in an L — the piece one square away is completely irrelevant, the leap ignores it.', '30%')}
  {fig('terrain_throne', 'Throne: slides in all 8 directions — a Tower and a Spire\'s movement combined.', '30%')}
  {fig('monarch_move', 'The Monarch is the one exception: always exactly 1 step, no matter which tile it stands on — even a Throne.', '30%')}
</div>

<h2>Capture</h2>
<p>Land on a square occupied by an enemy stone to capture it — it's removed from the game
immediately. You may never land on your own stone. Sliders stop the instant they capture; they
can't continue past it in the same move.</p>
<div class="figrow">
  {fig('capture_before', "Ana's Tower can slide onto either empty square, or capture Ben's stone two squares away.", '30%')}
  {fig('capture_after', 'Landing on it removes it from play — Ana\'s piece now stands on that square.', '30%')}
</div>

<h2>Winning the Game</h2>
<p>Three ways to win — no draw-by-points here, every decisive game ends in exactly one of these:</p>
<div class="figrow">
  {fig('regicide', '<b>Regicide</b> — capture the enemy Monarch. Game over immediately, no matter the material on the board.', '30%')}
  {fig('coronation', '<b>Coronation</b> — hold every Throne tile for a full round (3 plies). The opponent always gets one turn to contest it first before it counts.', '30%')}
  {fig('elimination', '<b>Elimination</b> — the enemy is reduced to a bare Monarch with no other stones left. Even undefeated, a lone Monarch immediately loses.', '30%')}
</div>
<div class="callout">If the player to move has no legal move at all, the game is a <b>draw</b>. Either
side may also offer a draw at any time; the opponent can accept or decline.</div>

<h2>Optional Modes</h2>
<p>Selected before the game starts; the board list only offers layouts that were simulation-tested
for whichever mode is active.</p>

<h3>Terrain Decay</h3>
<p>Every time a stone <i>leaves</i> a special tile, that tile degrades one tier — permanently, for
both players. Thrones never decay. Movement power becomes a resource you spend, not a fixture of
the map.</p>
<div class="figrow">
  {fig('decay_before', 'A Tower, about to be vacated.', '22%')}
  {fig('decay_after', 'Tower &rarr; Spire &rarr; Gate &rarr; Field — one tier per departure. The next stone to land here inherits whatever tier is left.', '40%')}
</div>

<h3>Fog of War</h3>
<p>Each side sees only a radius around their own stones — Manhattan distance 2 for ordinary stones,
3 around the Monarch. Thrones are always visible to both sides regardless of distance. Enemy stones
you've spotted linger as faded <b>ghosts</b> at their last-known square after they leave your sight —
useful memory, but they may not still be there.</p>
<div class="figrow">
  {fig('fog_vision', "An ordinary stone's sight (radius 2). The enemy stone outside it is remembered as a ghost, not seen live.", '46%')}
  {fig('fog_monarch', "The Monarch sees further — radius 3 — reflecting the extra danger it's in.", '46%')}
</div>
<p>Because a slider's path can cross a square you can't currently see, moves are planned on your own
fog view — if that path actually crosses a hidden enemy, the slide <b>bumps</b>: it stops at the
first hidden piece it meets and captures it there, instead of reaching wherever you intended.</p>
<div class="figrow">
  {fig('fog_bump', "You slide intending (0,0)&rarr;(4,0). An enemy you couldn't see was waiting at (2,0) — the slide stops and captures it there instead.", '46%')}
</div>
<div class="callout">The AI plays fog games under the exact same blindfold — it never peeks at the
full board, and keeps the same kind of short-term memory of recent sightings a human player would.</div>

<h3>Momentum</h3>
<p>A stone that leaves a special tile keeps that tile's rank for <b>one more move</b>, layered on top
of whatever its new tile grants. The retained rank is public information (shown as a badge on the
stone) and expires the move after next. Leaving a Throne this way keeps the queen-slide alive for one
extra move — throne raids get a real exit, instead of being stranded the instant they retreat.</p>
<div class="figrow">
  {fig('momentum_before', 'A Queen-mover on the Throne...', '22%')}
  {fig('momentum_after', '...slides off to a Field tile. It only steps 1 square from here on its OWN tile grant, but the retained badge means this next move can still be a full queen-slide.', '40%')}
</div>
<div class="callout warn">Momentum is mutually exclusive with Decay and Fog — pick at most one mode
per game.</div>

<h2>Side Choice &amp; Difficulty</h2>
<p>White moves first — a measurable advantage — so before each game you choose to play White,
Black, or Random; your own stones always render at the bottom of the screen regardless. Against the
AI, pick Easy, Normal, or Hard: deeper difficulties search further ahead and take longer to move,
including proposing and evaluating their own draw offers based on the position.</p>

<h2>Strategy Tips</h2>
<ul>
<li>Watch the tile, not the piece — the same stone is a lumbering Field-walker one move and a
rook on the next, purely because of where it's standing.</li>
<li>The Gate ignores everything in its path. In cramped, piece-dense positions it's often your only
stone that can actually reach a square this turn.</li>
<li>Never let your Monarch's safety depend on "the enemy probably won't find a way in" — Regicide
ends the game outright, no matter how far ahead you are on material.</li>
<li>Coronation gives the opponent exactly one turn to contest a Throne you're about to lock down —
that turn is your last chance to break the hold, not a moment to waste elsewhere.</li>
<li>Running an enemy down to their last non-Monarch piece is just as final as capturing their King —
count remaining agents, not just position.</li>
<li>In Fog games, a ghost marker is memory, not certainty — don't slide a valuable piece through a
square you merely <i>remember</i> being empty.</li>
</ul>

<div class="quickref">
  <h2 style="margin-top:0">Quick Reference</h2>
  <table>
    <tr><th>Tile</th><th>Grants</th><th>Tile</th><th>Grants</th></tr>
    <tr><td>{swatch('F')} Field</td><td>step 1</td>
        <td>{swatch('N')} Gate</td><td>knight leap</td></tr>
    <tr><td>{swatch('R')} Tower</td><td>rook slide</td>
        <td>{swatch('T')} Throne</td><td>queen slide</td></tr>
    <tr><td>{swatch('B')} Spire</td><td>bishop slide</td><td></td><td></td></tr>
  </table>
  <table>
    <tr><th>Rule</th><th>Value</th></tr>
    <tr><td>Win conditions</td><td>Regicide, Coronation (hold all Thrones 3 plies), Elimination (bare Monarch)</td></tr>
    <tr><td>Monarch move</td><td>always 1 step, ignores terrain</td></tr>
    <tr><td>No legal move</td><td>draw (or by mutual agreement any time)</td></tr>
    <tr><td>Decay chain</td><td>Tower &rarr; Spire &rarr; Gate &rarr; Field (Thrones never decay)</td></tr>
    <tr><td>Fog sight radius</td><td>2 (ordinary), 3 (Monarch); Thrones always visible</td></tr>
    <tr><td>Momentum</td><td>retained rank lasts 1 extra move; not combinable with Decay/Fog</td></tr>
  </table>
</div>

<footer>FACET Player's Guide &middot; generated from the live ruleset (facet_engine.py) &middot; diagrams drawn with the game's own board geometry and colors</footer>

</body></html>
'''

open('FACET_GUIDE.html', 'w').write(html)
print(f'wrote FACET_GUIDE.html ({len(html)} chars)')
