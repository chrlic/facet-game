"""Generate SVG hex-diagram fragments for the Backbone guide, using the
exact same odd-r hex geometry as the live game (docs/backbone.html)."""
import sys
sys.path.insert(0, '/Users/mdivis/Documents/playground/games')
from backbone_engine import neighbors, in_board, jump_targets, hex_distance

S = 34  # hex size, print-friendly (bigger than the in-game 30px)
import math

def hex_center(x, y):
    w = math.sqrt(3) * S
    cx = w * (x + (0.5 if y % 2 else 0)) + w / 2
    cy = 1.5 * S * (8 - y) + S
    return cx, cy

def hex_points(cx, cy):
    pts = []
    for i in range(6):
        a = math.radians(60 * i - 30)
        pts.append(f"{cx+S*math.cos(a):.1f},{cy+S*math.sin(a):.1f}")
    return " ".join(pts)

P_COLOR = {0: "#1a7a52", 1: "#2560a8"}
P_FILL = {0: "#eafaf1", 1: "#eaf2fb"}

def diagram(cells, edges=None, pad=14):
    """cells: list of dicts with keys:
       x,y (hex coords, used only for geometry & neighbor calc — not
       necessarily real board position, just a small local patch),
       kind: None|'router'|'switch'|'ap'|'server'|'dc' (piece, or None=empty),
       owner: 0|1|None,
       city: bool, cityBy: [0,1] subset,
       fw: bool, disabled: bool, disconnected: bool,
       dcOnline: bool|None, serverActive: bool,
       label: str (small caption under the hex), startMark: 0|1
       edges: list of ((x1,y1),(x2,y2), 'link'|'jump') hex-coordinate pairs

    Text is drawn in a dedicated final pass so later-painted hex tiles from
    neighboring rows can never cover an earlier row's labels.
    """
    edges = edges or []
    centers = {(c['x'], c['y']): hex_center(c['x'], c['y']) for c in cells}
    xs = [c[0] for c in centers.values()]; ys = [c[1] for c in centers.values()]
    minx, maxx = min(xs) - S - pad, max(xs) + S + pad
    miny, maxy = min(ys) - S - pad, max(ys) + S + pad
    for c in cells:
        if c.get('label'):
            cx, cy = centers[(c['x'], c['y'])]
            n_lines = c['label'].count('\n') + 1
            maxy = max(maxy, cy + S + 16 + 12 * n_lines + 4)
            half_w = max(len(l) for l in c['label'].split('\n')) * 3.6
            minx, maxx = min(minx, cx - half_w), max(maxx, cx + half_w)
        if c.get('startMark') is not None:
            cx, cy = centers[(c['x'], c['y'])]
            miny = min(miny, cy - S - 16)
            half_w = len(f"START P{c['startMark']+1}") * 4.0
            minx, maxx = min(minx, cx - half_w), max(maxx, cx + half_w)
    w, h = maxx - minx, maxy - miny
    out = [f'<svg viewBox="{minx:.0f} {miny:.0f} {w:.0f} {h:.0f}" '
           f'width="{w:.0f}" height="{h:.0f}" xmlns="http://www.w3.org/2000/svg">']
    texts = []  # collected and emitted last, so nothing else can paint over them

    # pass 1: hex tiles
    for c in cells:
        cx, cy = centers[(c['x'], c['y'])]
        fill = "#fbf3de" if c.get('city') else "#f4f6fb"
        out.append(f'<polygon points="{hex_points(cx,cy)}" fill="{fill}" '
                   f'stroke="#c9cfdc" stroke-width="1.5"/>')
        if c.get('city'):
            texts.append(f'<text x="{cx:.0f}" y="{cy+5:.0f}" text-anchor="middle" '
                         f'font-size="14" fill="#a9821f">&#9679;C</text>')
            for o in c.get('cityBy', []):
                dx = -9 if o == 0 else 9
                out.append(f'<circle cx="{cx+dx:.0f}" cy="{cy-11:.0f}" r="3.2" fill="{P_COLOR[o]}"/>')
                texts.append(f'<text x="{cx+dx:.0f}" y="{cy+15:.0f}" text-anchor="middle" '
                             f'font-size="10" font-weight="900" fill="{P_COLOR[o]}">+1</text>')
        if c.get('startMark') is not None:
            o = c['startMark']
            texts.append(f'<text x="{cx:.0f}" y="{cy-S-4:.0f}" text-anchor="middle" '
                         f'font-size="9" font-weight="700" fill="{P_COLOR[o]}">START P{o+1}</text>')

    # pass 2: edges
    for (a, b, kind) in edges:
        x1, y1 = centers.get(a, hex_center(*a))
        x2, y2 = centers.get(b, hex_center(*b))
        if kind == 'jump':
            out.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
                       f'stroke="#7a8296" stroke-width="2" stroke-dasharray="3,4"/>')
        else:
            out.append(f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
                       f'stroke="#7a8296" stroke-width="2.6"/>')

    # pass 3: pieces
    for c in cells:
        cx, cy = centers[(c['x'], c['y'])]
        kind = c.get('kind')
        if kind:
            o = c.get('owner', 0)
            dash = '3,2' if c.get('fw') else ('2,2' if c.get('disconnected') else '')
            sw = 3.4 if c.get('fw') else (1.6 if not c.get('disconnected') else 1.3)
            op = 0.5 if c.get('disconnected') else 1
            out.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="17" fill="{P_FILL[o]}" '
                       f'stroke="{P_COLOR[o]}" stroke-width="{sw}" '
                       f'stroke-dasharray="{dash}" opacity="{op}"/>')
            out.append(f'<use href="#icon-{kind}" x="{cx-10:.0f}" y="{cy-10:.0f}" '
                       f'width="20" height="20" color="{P_COLOR[o]}" opacity="{op}"/>')
            if kind == 'dc':
                online = c.get('dcOnline')
                if online is True:
                    out.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="22" fill="none" '
                               f'stroke="#c9971f" stroke-width="2.4"/>')
                    texts.append(f'<text x="{cx+16:.0f}" y="{cy+18:.0f}" text-anchor="middle" '
                                 f'font-size="12" font-weight="900" fill="#c9971f">+1</text>')
                elif online is False:
                    out.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="22" fill="none" '
                               f'stroke="#9aa0ae" stroke-width="1.4" stroke-dasharray="3,3"/>')
            if kind == 'server' and c.get('serverActive'):
                texts.append(f'<text x="{cx+16:.0f}" y="{cy+18:.0f}" text-anchor="middle" '
                             f'font-size="12" font-weight="900" fill="#c9971f">+1</text>')
            if c.get('disabled'):
                texts.append(f'<text x="{cx+15:.0f}" y="{cy-13:.0f}" text-anchor="middle" '
                             f'font-size="15" font-weight="900" fill="#c0392b">&#10005;</text>')
        if c.get('label'):
            lines = c['label'].split('\n')
            for li, line in enumerate(lines):
                texts.append(f'<text x="{cx:.0f}" y="{cy+S+16+12*li:.0f}" text-anchor="middle" '
                             f'font-size="11" fill="#5a6072">{line}</text>')

    # pass 4: all text, guaranteed on top
    out.extend(texts)
    out.append('</svg>')
    return "\n".join(out)


if __name__ == '__main__':
    d = diagram([{'x': 4, 'y': 4, 'kind': 'router', 'owner': 0}])
    print(len(d), 'chars for a single-hex diagram')
