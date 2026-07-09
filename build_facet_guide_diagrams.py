import sys, json
sys.path.insert(0, '/Users/mdivis/Documents/playground/games')
sys.path.insert(0, '.')
from gen_facet_guide_diagrams import diagram
from facet_engine import (BOARDS, KING, DIAG, ORTH, KNIGHT, SLIDERS,
                           DECAY_MAP, MOMENTUM_GLYPHS, FOG_RADIUS, FOG_MONARCH_RADIUS)

D = {}


def patch(n, default='F'):
    """n x n square of terrain, all `default`, keyed by (x,y)."""
    return {(x, y): default for x in range(n) for y in range(n)}


def cells_from(terrain, pieces=None, targets=None, blocked=None, dims=None, labels=None):
    pieces = pieces or {}
    targets = targets or set()
    blocked = blocked or set()
    dims = dims or set()
    labels = labels or {}
    out = []
    for (x, y), g in terrain.items():
        c = {'x': x, 'y': y, 'terrain': g}
        if (x, y) in pieces:
            c['piece'] = pieces[(x, y)]
        if (x, y) in targets:
            c['target'] = True
        if (x, y) in blocked:
            c['blocked'] = True
        if (x, y) in dims:
            c['dim'] = True
        if (x, y) in labels:
            c['label'] = labels[(x, y)]
        out.append(c)
    return out


# 1. Board overview — full Classic 7x7, real terrain + starting pieces
rows = BOARDS['classic']['rows']
W, H = BOARDS['classic']['size']
terrain = {}
for i, row in enumerate(rows):
    y = H - 1 - i
    for x, ch in enumerate(row):
        terrain[(x, y)] = ch
pieces = {}
mid = W // 2
for x in range(W):
    pieces[(x, 0)] = {'owner': 0, 'icon': '♚' if x == mid else '•', 'monarch': x == mid}
for x in range(W):
    pieces[(x, H - 1)] = {'owner': 1, 'icon': '♚' if x == mid else '•', 'monarch': x == mid}
D['board_overview'] = diagram(cells_from(terrain, pieces))

# 2. Field — king-step, 8 directions
t = patch(5, 'F')
targets = {(2 + dx, 2 + dy) for dx, dy in KING}
D['terrain_field'] = diagram(cells_from(
    t, {(2, 2): {'owner': 0, 'icon': '•'}}, targets))

# 3. Tower — rook slide, blocked by an enemy 2 squares up (captures there, no further)
t = patch(5, 'F')
t[(2, 2)] = 'R'
targets = set()
blocked = set()
for dx, dy in ORTH:
    x, y = 2, 2
    while True:
        x, y = x + dx, y + dy
        if not (0 <= x < 5 and 0 <= y < 5):
            break
        if (dx, dy) == (0, 1) and (x, y) == (2, 3):
            targets.add((x, y))  # capture the blocker, then stop
            break
        targets.add((x, y))
pieces = {(2, 2): {'owner': 0, 'icon': '♜'}, (2, 3): {'owner': 1, 'icon': '•'}}
D['terrain_tower'] = diagram(cells_from(t, pieces, targets))

# 4. Spire — bishop slide, diagonals to patch edge
t = patch(5, 'F')
t[(2, 2)] = 'B'
targets = set()
for dx, dy in DIAG:
    x, y = 2, 2
    while True:
        x, y = x + dx, y + dy
        if not (0 <= x < 5 and 0 <= y < 5):
            break
        targets.add((x, y))
D['terrain_spire'] = diagram(cells_from(
    t, {(2, 2): {'owner': 0, 'icon': '♝'}}, targets))

# 5. Gate — knight leap, ignores an adjacent blocker
t = patch(5, 'F')
t[(2, 2)] = 'N'
targets = {(2 + dx, 2 + dy) for dx, dy in KNIGHT if 0 <= 2 + dx < 5 and 0 <= 2 + dy < 5}
pieces = {(2, 2): {'owner': 0, 'icon': '♞'}, (2, 3): {'owner': 1, 'icon': '•'}}
D['terrain_gate'] = diagram(cells_from(t, pieces, targets))

# 6. Throne — queen slide (king directions, full slide) to patch edge
t = patch(5, 'F')
t[(2, 2)] = 'T'
targets = set()
for dx, dy in KING:
    x, y = 2, 2
    while True:
        x, y = x + dx, y + dy
        if not (0 <= x < 5 and 0 <= y < 5):
            break
        targets.add((x, y))
D['terrain_throne'] = diagram(cells_from(
    t, {(2, 2): {'owner': 0, 'icon': '♛'}}, targets))

# 7. Monarch — always 1 step, even standing on a Throne
t = patch(5, 'F')
t[(2, 2)] = 'T'
targets = {(2 + dx, 2 + dy) for dx, dy in KING}
D['monarch_move'] = diagram(cells_from(
    t, {(2, 2): {'owner': 0, 'icon': '♚', 'monarch': True}}, targets))

# 8. Capture — before / after
t = patch(1, 'F')
t = {(x, 0): 'F' for x in range(3)}
before = cells_from(t,
    {(0, 0): {'owner': 0, 'icon': '♜'}, (2, 0): {'owner': 1, 'icon': '•'}},
    targets={(1, 0), (2, 0)})
D['capture_before'] = diagram(before)
after = cells_from(t, {(2, 0): {'owner': 0, 'icon': '♜'}},
    labels={(2, 0): "Ben's piece is\nremoved from play"})
D['capture_after'] = diagram(after)

# 9. Regicide
t = {(x, 0): 'F' for x in range(3)}
pieces = {(0, 0): {'owner': 0, 'icon': '♜'},
          (2, 0): {'owner': 1, 'icon': '♚', 'monarch': True}}
D['regicide'] = diagram(cells_from(t, pieces, targets={(1, 0), (2, 0)},
    labels={(2, 0): "captured — game over\nimmediately (Regicide)"}))

# 10. Coronation
t = {(0, 0): 'T', (2, 0): 'T', (1, 0): 'F'}
pieces = {(0, 0): {'owner': 0, 'icon': '♛'}, (2, 0): {'owner': 0, 'icon': '♜'}}
D['coronation'] = diagram(cells_from(t, pieces,
    labels={(0, 0): "held 3 of 3 rounds\n→ Coronation win"}))

# 11. Elimination
t = {(x, 0): 'F' for x in range(3)}
pieces = {(1, 0): {'owner': 1, 'icon': '♚', 'monarch': True}}
D['elimination'] = diagram(cells_from(t, pieces,
    labels={(1, 0): "no agents left —\nbare Monarch loses on the spot"}))

# 12. Decay — before / after
t = patch(1, 'F')
t = {(0, 0): 'R', (1, 0): 'F'}
D['decay_before'] = diagram(cells_from(t, {(0, 0): {'owner': 0, 'icon': '♜'}},
    targets={(1, 0)}, labels={(0, 0): "Tower"}))
t2 = {(0, 0): DECAY_MAP['R'], (1, 0): 'F'}
D['decay_after'] = diagram(cells_from(t2, {(1, 0): {'owner': 0, 'icon': '♝'}},
    labels={(0, 0): "degraded to Spire\n(the tile the stone left)"}))

# 13. Fog — sighted radius (regular piece, r=2) with a ghost outside it
t = patch(7, 'F')
pieces = {(3, 3): {'owner': 0, 'icon': '•'},
          (6, 6): {'owner': 1, 'icon': '?', 'ghost': True}}
dims = {(x, y) for x in range(7) for y in range(7)
        if abs(x - 3) + abs(y - 3) > FOG_RADIUS}
D['fog_vision'] = diagram(cells_from(t, pieces, dims=dims,
    labels={(6, 6): "ghost — last seen here,\nmay have moved"}),
    ring=(3, 3, FOG_RADIUS))

# 14. Fog — monarch sees further (r=3)
t = patch(7, 'F')
pieces = {(3, 3): {'owner': 0, 'icon': '♚', 'monarch': True}}
dims = {(x, y) for x in range(7) for y in range(7)
        if abs(x - 3) + abs(y - 3) > FOG_MONARCH_RADIUS}
D['fog_monarch'] = diagram(cells_from(t, pieces, dims=dims),
    ring=(3, 3, FOG_MONARCH_RADIUS))

# 15. Fog — the bump: an unseen enemy cuts a blind slide short
t = {(x, 0): 'F' for x in range(5)}
pieces = {(0, 0): {'owner': 0, 'icon': '♜'},
          (2, 0): {'owner': 1, 'icon': '•', 'ghost': True}}
D['fog_bump'] = diagram(cells_from(t, pieces,
    targets={(2, 0)}, blocked={(4, 0)},
    labels={(2, 0): "BUMP — hidden,\ncaptured here",
            (4, 0): "intended target,\nnever reached"}))

# 16. Momentum — before / after
t = {(0, 0): 'T', (1, 0): 'F'}
D['momentum_before'] = diagram(cells_from(t, {(0, 0): {'owner': 0, 'icon': '♛'}},
    targets={(1, 0)}, labels={(0, 0): "Throne"}))
t2 = {(0, 0): 'T', (1, 0): 'F'}
D['momentum_after'] = diagram(cells_from(t2,
    {(1, 0): {'owner': 0, 'icon': '•', 'momentum': '♛'}},
    labels={(1, 0): "on a Field tile now, but still\nqueen-slides for 1 more move"}))

with open('facet_diagrams.json', 'w') as f:
    json.dump(D, f)
print('generated', len(D), 'diagrams:', list(D.keys()))
for k, v in D.items():
    print(f'  {k}: {len(v)} chars')
