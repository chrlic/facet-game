"""Generate SVG square-grid diagram fragments for the FACET guide, using the
exact same colors/glyphs as the live game (docs/index.html) and the real
movement/terrain constants from facet_engine.py."""
import sys
sys.path.insert(0, '/Users/mdivis/Documents/playground/games')

S = 40      # cell size, print-friendly
GAP = 3

TCOLOR = {'F': '#2a3147', 'R': '#2d5fa6', 'B': '#2f8f5b', 'N': '#c4772a', 'T': '#caa12e'}
TGLYPH = {'F': '', 'R': '♜', 'B': '♝', 'N': '♞', 'T': '♛'}  # rook/bishop/knight/queen outline
P_FILL = {0: '#f4f6fb', 1: '#2a304a'}
P_RING = {0: '#10131c', 1: '#c0caee'}
P_TEXT = {0: '#10131c', 1: '#f0f4ff'}
HL = '#1a7a52'   # legal-target ring (print-friendly green, darker than the on-screen neon)
SEL = '#c9971f'  # gold accent for callouts (momentum / coronation timer / capture flash)


def cell_xy(x, y, maxy):
    """(x,y) grid coords, y=0 at the bottom (matches facet_engine's P0 back
    row = lowest y) -> top-left pixel coords for this cell's box."""
    px = x * (S + GAP)
    py = (maxy - y) * (S + GAP)
    return px, py


def diagram(cells, pad=16, ring=None):
    """cells: list of dicts with keys:
       x, y: grid coords
       terrain: 'F'|'R'|'B'|'N'|'T'
       piece: None or dict(owner=0|1, icon=str, monarch=bool, ghost=bool,
              momentum=str-or-None, dim=bool)
       target: bool  -- highlighted as a legal move destination
       blocked: bool -- marked as an illegal/blocked destination (dashed red)
       dim: bool     -- fogged-out cell (whole square faded)
       label: str    -- caption under the cell (may contain \\n)
    ring: optional (cx, cy, radius) in GRID units -> draws a Manhattan-distance
       sight-radius outline (diamond) centered on that cell, radius in steps.

    Text/badges are collected and emitted in a dedicated final pass so no
    later-painted cell can ever cover an earlier one's caption.
    """
    xs = [c['x'] for c in cells]
    ys = [c['y'] for c in cells]
    maxy = max(ys)
    boxes = {(c['x'], c['y']): cell_xy(c['x'], c['y'], maxy) for c in cells}
    minx = min(px for px, py in boxes.values()) - pad
    miny = min(py for px, py in boxes.values()) - pad
    maxx = max(px for px, py in boxes.values()) + S + pad
    maxpy = max(py for px, py in boxes.values()) + S + pad
    for c in cells:
        if c.get('label'):
            px, py = boxes[(c['x'], c['y'])]
            n_lines = c['label'].count('\n') + 1
            maxpy = max(maxpy, py + S + 14 + 11 * n_lines + 4)
            half_w = max(len(l) for l in c['label'].split('\n')) * 3.3
            cx = px + S / 2
            minx, maxx = min(minx, cx - half_w), max(maxx, cx + half_w)
    if ring:
        rcx, rcy, rr = ring
        rpx, rpy = cell_xy(rcx, rcy, maxy)
        ccx, ccy = rpx + S / 2, rpy + S / 2
        span = rr * (S + GAP) + S / 2
        minx, maxx = min(minx, ccx - span - pad), max(maxx, ccx + span + pad)
        miny, maxpy = min(miny, ccy - span - pad), max(maxpy, ccy + span + pad)

    w, h = maxx - minx, maxpy - miny
    out = [f'<svg viewBox="{minx:.0f} {miny:.0f} {w:.0f} {h:.0f}" '
           f'width="{w:.0f}" height="{h:.0f}" xmlns="http://www.w3.org/2000/svg">']
    texts = []

    # pass 1: terrain squares
    for c in cells:
        px, py = boxes[(c['x'], c['y'])]
        fill = TCOLOR[c['terrain']]
        op = 0.3 if c.get('dim') else 1
        out.append(f'<rect x="{px:.0f}" y="{py:.0f}" width="{S}" height="{S}" rx="6" '
                    f'fill="{fill}" opacity="{op}"/>')
        g = TGLYPH[c['terrain']]
        if g:
            out.append(f'<text x="{px+S-7:.0f}" y="{py+15:.0f}" text-anchor="end" '
                        f'font-size="15" fill="#ffffff55" opacity="{op}">{g}</text>')
        if c.get('target'):
            out.append(f'<rect x="{px+2.5:.0f}" y="{py+2.5:.0f}" width="{S-5}" height="{S-5}" rx="4.5" '
                        f'fill="none" stroke="{HL}" stroke-width="3"/>')
        if c.get('blocked'):
            out.append(f'<rect x="{px+2.5:.0f}" y="{py+2.5:.0f}" width="{S-5}" height="{S-5}" rx="4.5" '
                        f'fill="none" stroke="#c0392b" stroke-width="2.4" stroke-dasharray="4,3"/>')

    # pass 2: pieces
    for c in cells:
        px, py = boxes[(c['x'], c['y'])]
        cx, cy = px + S / 2, py + S / 2
        p = c.get('piece')
        if p:
            o = p.get('owner', 0)
            op = 0.5 if p.get('ghost') or p.get('dim') else 1
            r = 15.5
            out.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r}" fill="{P_FILL[o]}" '
                        f'stroke="{P_RING[o]}" stroke-width="2" opacity="{op}"/>')
            if p.get('monarch'):
                out.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r+3.2:.0f}" fill="none" '
                            f'stroke="{SEL}" stroke-width="2"/>')
            icon = p.get('icon', '')
            texts.append(f'<text x="{cx:.0f}" y="{cy+6:.0f}" text-anchor="middle" '
                          f'font-size="18" fill="{P_TEXT[o]}" opacity="{op}">{icon}</text>')
            if p.get('momentum'):
                bx, by = cx + r - 3, cy - r + 3
                out.append(f'<circle cx="{bx:.0f}" cy="{by:.0f}" r="8" fill="#0c1020" '
                            f'stroke="{SEL}" stroke-width="1.3"/>')
                texts.append(f'<text x="{bx:.0f}" y="{by+3.5:.0f}" text-anchor="middle" '
                              f'font-size="9" fill="{SEL}">{p["momentum"]}</text>')
        if c.get('label'):
            lines = c['label'].split('\n')
            for li, line in enumerate(lines):
                texts.append(f'<text x="{cx:.0f}" y="{py+S+14+11*li:.0f}" text-anchor="middle" '
                              f'font-size="10.5" fill="#5a6072">{line}</text>')

    # pass 2b: sight-radius ring
    if ring:
        rcx, rcy, rr = ring
        rpx, rpy = cell_xy(rcx, rcy, maxy)
        ccx, ccy = rpx + S / 2, rpy + S / 2
        step = S + GAP
        pts = [
            (ccx, ccy - rr * step - S / 2 - 4),
            (ccx + rr * step + S / 2 + 4, ccy),
            (ccx, ccy + rr * step + S / 2 + 4),
            (ccx - rr * step - S / 2 - 4, ccy),
        ]
        pts_s = " ".join(f"{x:.0f},{y:.0f}" for x, y in pts)
        out.append(f'<polygon points="{pts_s}" fill="{HL}22" stroke="{HL}" '
                    f'stroke-width="2" stroke-dasharray="5,4"/>')

    out.extend(texts)
    out.append('</svg>')
    return "\n".join(out)


if __name__ == '__main__':
    d = diagram([{'x': 0, 'y': 0, 'terrain': 'F',
                  'piece': {'owner': 0, 'icon': '•'}}])
    print(len(d), 'chars for a single-cell diagram')
