// HEXA-GO — a Go-like game on the OCTA board (same tiling as OCTA-CHESS).
//
// Stones are placed on the CELLS (octagons + diamonds), which connect through shared edges:
//   octagon–octagon (orthogonal, shared flat edge) and octagon–diamond (shared diagonal edge).
// Interior octagons therefore have up to 8 liberties and diamonds 4 — enough connectivity to
// build living groups (unlike the degree-3 vertex board, which was too sparse for Go).
// Scoring is by TERRITORY (Japanese): surrounded empty cells + prisoners captured + komi.
(function (global) {
  "use strict";

  // ---- board topologies --------------------------------------------------
  // Stones sit on the VERTICES of an equal-edge tiling; two points are adjacent (connected /
  // share a liberty) when they are exactly one edge apart. Choosing the tiling sets the degree:
  //   "tri"  = triangular tiling  -> 6 adjacencies (6 triangles meet at each vertex)
  //   "elong"= elongated triangular tiling (3.3.3.4.4) -> 5 adjacencies (rows of squares+triangles)
  // (The old octagon-cell board gave interior degree 8 — too connected; groups too hard to kill.)
  var H = Math.sqrt(3) / 2, VIEW = 800, PAD = 60;

  function triPoints(rad) {                              // hexagonal region of a triangular lattice
    var pts = [];
    for (var q = -rad; q <= rad; q++) for (var r = -rad; r <= rad; r++)
      if (Math.abs(q + r) <= rad) pts.push({ x: q + r / 2, y: r * H });
    return pts;
  }
  function elongPoints(cols, rows) {                     // elongated triangular tiling (deg 5)
    var pts = [], y = 0;
    for (var i = 0; i < rows; i++) {
      var off = (Math.floor(i / 2) % 2) * 0.5;
      for (var c = 0; c < cols; c++) pts.push({ x: c + off, y: y });
      y += (i % 2 === 0) ? 1 : H;                        // square strip then triangle strip
    }
    return pts;
  }
  function connectByDistance(pts, edge) {                // link points ~one edge apart
    var adj = pts.map(function () { return []; }), t2 = (edge * 1.08) * (edge * 1.08);
    for (var i = 0; i < pts.length; i++) for (var j = i + 1; j < pts.length; j++) {
      var dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y;
      if (dx * dx + dy * dy <= t2) { adj[i].push(j); adj[j].push(i); }
    }
    return adj;
  }
  function convexHull(pts) {
    var p = pts.map(function (q, i) { return [q.x, q.y, i]; }).sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    var cross = function (o, a, b) { return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]); };
    var lo = [], hi = [], k;
    for (k = 0; k < p.length; k++) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], p[k]) <= 0) lo.pop(); lo.push(p[k]); }
    for (k = p.length - 1; k >= 0; k--) { while (hi.length >= 2 && cross(hi[hi.length - 2], hi[hi.length - 1], p[k]) <= 0) hi.pop(); hi.push(p[k]); }
    lo.pop(); hi.pop();
    return lo.concat(hi).map(function (q) { return { x: q[0], y: q[1] }; });
  }
  var TRI_RAD = { s: 5, m: 6, l: 7 }, ELONG_N = { s: 10, m: 12, l: 14 }; // configurable board size
  function boundaryDist(adj) {                 // graph distance to the board edge = Go "line" - 1
    var n = adj.length, maxDeg = 0, i, bd = new Int16Array(n), q = [], head = 0;
    for (i = 0; i < n; i++) maxDeg = Math.max(maxDeg, adj[i].length);
    for (i = 0; i < n; i++) { if (adj[i].length < maxDeg) { bd[i] = 0; q.push(i); } else bd[i] = -1; }
    while (head < q.length) { var v = q[head++], ns = adj[v]; for (var k = 0; k < ns.length; k++) { var w = ns[k]; if (bd[w] === -1) { bd[w] = bd[v] + 1; q.push(w); } } }
    for (i = 0; i < n; i++) if (bd[i] === -1) bd[i] = 0;
    return { bd: bd, maxDeg: maxDeg };
  }
  function makeBoard(type, sz) {
    var raw = type === "elong" ? elongPoints(ELONG_N[sz], ELONG_N[sz] + 1) : triPoints(TRI_RAD[sz]);
    var minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9, i;
    for (i = 0; i < raw.length; i++) { minX = Math.min(minX, raw[i].x); minY = Math.min(minY, raw[i].y); maxX = Math.max(maxX, raw[i].x); maxY = Math.max(maxY, raw[i].y); }
    var uw = maxX - minX, uh = maxY - minY, scale = (VIEW - 2 * PAD) / Math.max(uw, uh);
    var w = uw * scale, h = uh * scale, ox = (VIEW - w) / 2, oy = (VIEW - h) / 2;
    var pts = raw.map(function (p) { return { x: (p.x - minX) * scale + ox, y: (p.y - minY) * scale + oy }; });
    var adj = connectByDistance(pts, scale), bi = boundaryDist(adj);
    return { type: type, points: pts, adj: adj, size: pts.length, hull: convexHull(pts), edgePx: scale, bd: bi.bd, maxDeg: bi.maxDeg };
  }

  var BOARDS = {};
  var CUR, ADJ, NP, PTS, BD;
  function setBoard(type, sz) {
    if (type !== "tri" && type !== "elong") type = "tri";
    if (!TRI_RAD[sz]) sz = "m";
    var key = type + sz;
    if (!BOARDS[key]) BOARDS[key] = makeBoard(type, sz);
    CUR = BOARDS[key]; ADJ = CUR.adj; NP = CUR.size; PTS = CUR.points; BD = CUR.bd;
    return CUR;
  }
  setBoard("tri", "m");
  var KOMI = 5.5;

  // ---- state (color: 0 empty, 1 black, 2 white; black first) -------------
  function initial() { return { color: new Int8Array(NP), turn: 1, ko: -1, passes: 0, caps: { 1: 0, 2: 0 }, moveNo: 0, last: -1 }; }
  function clone(s) { return { color: s.color.slice(), turn: s.turn, ko: s.ko, passes: s.passes, caps: { 1: s.caps[1], 2: s.caps[2] }, moveNo: s.moveNo, last: s.last }; }

  function group(color, id) {
    var c = color[id], stack = [id], seen = {}, stones = [], libs = {}; seen[id] = 1;
    while (stack.length) {
      var v = stack.pop(); stones.push(v); var ns = ADJ[v];
      for (var i = 0; i < ns.length; i++) { var w = ns[i];
        if (color[w] === 0) libs[w] = 1; else if (color[w] === c && !seen[w]) { seen[w] = 1; stack.push(w); } }
    }
    return { stones: stones, libs: Object.keys(libs).length };
  }

  function tryPlace(state, id) {
    if (id < 0 || id >= NP || state.color[id] !== 0 || id === state.ko) return null;
    var c = state.turn, opp = 3 - c, col = state.color.slice(); col[id] = c;
    var ns = ADJ[id], captured = 0, lastCap = -1, seen = {};
    for (var i = 0; i < ns.length; i++) { var w = ns[i];
      if (col[w] === opp && !seen[w]) { var g = group(col, w);
        if (g.libs === 0) { for (var j = 0; j < g.stones.length; j++) { col[g.stones[j]] = 0; seen[g.stones[j]] = 1; lastCap = g.stones[j]; } captured += g.stones.length; }
        else for (var j2 = 0; j2 < g.stones.length; j2++) seen[g.stones[j2]] = 1; } }
    if (captured === 0 && group(col, id).libs === 0) return null;   // suicide
    return { color: col, captured: captured, lastCap: lastCap };
  }
  function isLegal(state, id) { return tryPlace(state, id) !== null; }
  function legalMoves(state) { var out = []; for (var i = 0; i < NP; i++) if (state.color[i] === 0 && isLegal(state, i)) out.push(i); return out; }

  function play(state, id) {
    var r = tryPlace(state, id); if (!r) return state;
    var s = clone(state); s.color = r.color; s.caps[state.turn] += r.captured;
    var mine = group(s.color, id);
    s.ko = (r.captured === 1 && mine.stones.length === 1 && mine.libs === 1) ? r.lastCap : -1;
    s.turn = 3 - state.turn; s.passes = 0; s.moveNo++; s.last = id; return s;
  }
  function pass(state) { var s = clone(state); s.turn = 3 - state.turn; s.ko = -1; s.passes = state.passes + 1; s.moveNo++; s.last = -1; return s; }
  function ended(state) { return state.passes >= 2; }

  // ---- TERRITORY scoring: surrounded empty cells + prisoners + komi (not stones) ----
  function score(state) {
    var col = state.color, seen = new Int8Array(NP), terrB = 0, terrW = 0, i;
    for (i = 0; i < NP; i++) {
      if (col[i] !== 0 || seen[i]) continue;
      var stack = [i], region = [], border = 0; seen[i] = 1;
      while (stack.length) { var v = stack.pop(); region.push(v); var ns = ADJ[v];
        for (var k = 0; k < ns.length; k++) { var u = ns[k]; if (col[u] === 0) { if (!seen[u]) { seen[u] = 1; stack.push(u); } } else border |= col[u]; } }
      if (border === 1) terrB += region.length; else if (border === 2) terrW += region.length;
    }
    var black = terrB + state.caps[1], white = terrW + state.caps[2] + KOMI;
    return { black: black, white: white, terrB: terrB, terrW: terrW, capB: state.caps[1], capW: state.caps[2],
             komi: KOMI, margin: black - white, winner: black > white ? "black" : (white > black ? "white" : "draw") };
  }
  // Live estimate: like score() but only counts an empty region as territory if it is a genuinely
  // enclosed pocket (size <= cap). Early on, the whole open board is ONE region touching one colour,
  // which score() wrongly credits as huge territory — this only counts what's undeniably surrounded.
  function scoreLive(state) {
    var col = state.color, seen = new Int8Array(NP), terrB = 0, terrW = 0, i;
    var cap = Math.max(8, Math.round(NP * 0.16));
    for (i = 0; i < NP; i++) {
      if (col[i] !== 0 || seen[i]) continue;
      var stack = [i], region = [], border = 0; seen[i] = 1;
      while (stack.length) { var v = stack.pop(); region.push(v); var ns = ADJ[v];
        for (var k = 0; k < ns.length; k++) { var u = ns[k]; if (col[u] === 0) { if (!seen[u]) { seen[u] = 1; stack.push(u); } } else border |= col[u]; } }
      if (region.length <= cap) { if (border === 1) terrB += region.length; else if (border === 2) terrW += region.length; }
    }
    var black = terrB + state.caps[1], white = terrW + state.caps[2] + KOMI;
    return { black: black, white: white, terrB: terrB, terrW: terrW, capB: state.caps[1], capW: state.caps[2],
             komi: KOMI, margin: black - white, winner: black > white ? "black" : (white > black ? "white" : "draw") };
  }
  function status(state) { if (!ended(state)) return { over: false }; var sc = score(state); return { over: true, result: sc.winner, score: sc }; }

  // ---- helpers for the playout policy ----
  function isEye(color, id, c) { var ns = ADJ[id]; for (var i = 0; i < ns.length; i++) if (color[ns[i]] !== c) return false; return ns.length > 0; }
  function firstLiberty(col, id) {                       // one empty point adjacent to id's group
    var c = col[id], stack = [id], seen = {}; seen[id] = 1;
    while (stack.length) { var v = stack.pop(), ns = ADJ[v];
      for (var i = 0; i < ns.length; i++) { var w = ns[i]; if (col[w] === 0) return w; else if (col[w] === c && !seen[w]) { seen[w] = 1; stack.push(w); } } }
    return -1;
  }
  function shuffle(a) { for (var i = a.length - 1; i > 0; i--) { var j = (Math.random() * (i + 1)) | 0, t = a[i]; a[i] = a[j]; a[j] = t; } }
  // legal, non-eye, non-self-atari move (unless it captures); returns the tryPlace result or null
  function goodMove(st, id, me) {
    if (st.color[id] !== 0 || id === st.ko) return null;
    if (isEye(st.color, id, me)) return null;
    var r = tryPlace(st, id); if (!r) return null;
    if (r.captured === 0 && group(r.color, id).libs === 1) return null;
    return r;
  }
  function commit(st, id, r, me) {
    st.color = r.color; st.caps[me] += r.captured;
    var mg = group(st.color, id);
    st.ko = (r.captured === 1 && mg.stones.length === 1 && mg.libs === 1) ? r.lastCap : -1;
  }

  // Go move-policy: rates an empty point for `me` from real Go knowledge. Used to prune the root
  // to sensible moves and to seed priors — the search is too small to find good shape on its own.
  // "line value": 1st line (edge) is bad, 3rd/4th line is the ideal opening — weighted by how open
  // the board still is. Plus captures, atari, and staying near the action.
  var LINEVAL = [-0.95, -0.28, 0.42, 0.34, 0.16, 0.10];  // indexed by min(bd,5) = (Go line - 1)
  function policyScore(state, id, me, openness, r) {
    if (!r) r = tryPlace(state, id); if (!r) return -1e9;
    if (isEye(state.color, id, me)) return -1e9;
    if (r.captured === 0 && group(r.color, id).libs === 1) return -1e9;   // self-atari
    var h = r.captured * 0.6;
    var ns = ADJ[id], friend = 0, enemy = 0, atari = 0;
    for (var i = 0; i < ns.length; i++) { var w = ns[i];
      if (state.color[w] === me) friend++;
      else if (state.color[w] === 3 - me) { enemy++; var eg = group(r.color, w); if (eg.stones.length && eg.libs === 1) atari++; } }
    h += atari * 0.4;
    h += LINEVAL[Math.min(BD[id], 5)] * openness;          // opening: love the 3rd/4th line, avoid 1st
    h += 0.06 * Math.min(friend, 2) + 0.055 * Math.min(enemy, 2);  // stay where the play is
    if (friend >= 3) h -= 0.10;                             // discourage filling your own shape
    return h;
  }

  // A single "heavy" playout: near the opponent's last stone it prefers capturing an atari'd
  // group or saving its own, then plays locally, then globally at random. Much stronger estimates
  // than uniform-random playouts. Returns the terminal state (both sides passed / board full).
  // `first` (optional Int8Array): records, per point, the colour that FIRST plays there during the
  // playout — used by RAVE/AMAF to credit every move that appeared, not just the root move.
  function runPlayout(state, first) {
    var st = { color: state.color.slice(), turn: state.turn, ko: state.ko, passes: state.passes, caps: { 1: state.caps[1], 2: state.caps[2] } };
    var last = state.last, passes = state.passes, moves = 0, maxM = 3 * NP, order = null;
    while (passes < 2 && moves < maxM) {
      var me = st.turn, chosen = -1, cr = null, i, r;
      // 1. tactics next to the last move: capture an atari'd enemy / rescue an atari'd friend
      if (last >= 0) {
        var ns = ADJ[last], cand = [];
        for (i = 0; i < ns.length; i++) { var w = ns[i]; if (st.color[w] === 0) continue;
          var g = group(st.color, w);
          if (g.libs === 1) { var lp = firstLiberty(st.color, w); if (lp >= 0) { r = goodMove(st, lp, me); if (r) cand.push([lp, r]); } } }
        if (cand.length && Math.random() < 0.92) { var pk = cand[(Math.random() * cand.length) | 0]; chosen = pk[0]; cr = pk[1]; }
      }
      // 2. local: a random empty point next to the last move
      if (chosen < 0 && last >= 0 && Math.random() < 0.55) {
        var ln = ADJ[last].slice(); shuffle(ln);
        for (i = 0; i < ln.length; i++) { r = goodMove(st, ln[i], me); if (r) { chosen = ln[i]; cr = r; break; } }
      }
      // 3. global random (mostly skip the 1st line — edge moves are almost always bad)
      if (chosen < 0) {
        if (!order) { order = []; for (var q = 0; q < NP; q++) order.push(q); }
        shuffle(order);
        for (i = 0; i < order.length; i++) { var oi = order[i];
          if (BD[oi] === 0 && Math.random() < 0.8) continue;
          r = goodMove(st, oi, me); if (r) { chosen = oi; cr = r; break; } }
      }
      if (chosen < 0) { st.passes = ++passes; st.ko = -1; }
      else { commit(st, chosen, cr, me); passes = st.passes = 0; last = chosen;
             if (first && first[chosen] === 0) first[chosen] = me; }
      st.turn = 3 - me; moves++;
    }
    return st;
  }
  function playout(state) {
    var sc = score(runPlayout(state));
    return sc.winner === "draw" ? 0 : (sc.winner === "black" ? 1 : 2);
  }

  // area ownership at a (near-)terminal position: stone -> its colour; empty region -> the single
  // colour surrounding it, else 0 (dame). Returns Int8Array of 0/1/2 per point.
  function areaOwners(col) {
    var o = new Int8Array(NP), seen = new Int8Array(NP), i;
    for (i = 0; i < NP; i++) {
      if (col[i]) { o[i] = col[i]; continue; }
      if (seen[i]) continue;
      var stack = [i], region = [], border = 0; seen[i] = 1;
      while (stack.length) { var v = stack.pop(); region.push(v); var ns = ADJ[v];
        for (var k = 0; k < ns.length; k++) { var u = ns[k]; if (col[u] === 0) { if (!seen[u]) { seen[u] = 1; stack.push(u); } } else border |= col[u]; } }
      var owner = border === 1 ? 1 : border === 2 ? 2 : 0;
      for (var r = 0; r < region.length; r++) o[region[r]] = owner;
    }
    return o;
  }

  // Monte-Carlo TERRITORY scoring. Runs playouts, averages per-point area ownership, and only
  // credits a point a player owns in >= T of them ("doubtlessly owned"). Dead stones are captured
  // during the playouts, so they correctly become the surrounder's territory + a prisoner — no
  // explicit life-and-death needed. Score = owned empty territory + prisoners + komi (not stones).
  function scoreFinal(state, playouts) {
    playouts = playouts || 320;
    var base = clone(state); base.passes = 0; base.last = -1;   // reset so the board is played OUT
    var bc = new Float64Array(NP), wc = new Float64Array(NP), i, p;
    for (p = 0; p < playouts; p++) {
      var o = areaOwners(runPlayout(base).color);
      for (i = 0; i < NP; i++) { if (o[i] === 1) bc[i]++; else if (o[i] === 2) wc[i]++; }
    }
    var T = 0.6, terrB = 0, terrW = 0, prisB = 0, prisW = 0, own = new Int8Array(NP);
    for (i = 0; i < NP; i++) {
      var bf = bc[i] / playouts, wf = wc[i] / playouts;
      var oc = bf >= T ? 1 : wf >= T ? 2 : 0; own[i] = oc;
      if (oc === 0) continue;
      var cur = state.color[i];
      if (cur === 0) { if (oc === 1) terrB++; else terrW++; }
      else if (cur !== oc) { if (oc === 1) { terrB++; prisB++; } else { terrW++; prisW++; } } // dead stone
    }
    var capB = state.caps[1] + prisB, capW = state.caps[2] + prisW;
    var black = terrB + capB, white = terrW + capW + KOMI;
    return { black: black, white: white, terrB: terrB, terrW: terrW, capB: capB, capW: capW, komi: KOMI,
             own: own, margin: black - white, winner: black > white ? "black" : (white > black ? "white" : "draw") };
  }

  // ---- Monte-Carlo AI (flat UCB1 at the root) ----
  var MC_MS = 850;
  function aiMove(state, budgetMs, opts) {
    var raveOn = !(opts && opts.rave === false);   // toggle for A/B testing RAVE vs flat MC
    var me = state.turn, deadline = Date.now() + (budgetMs || MC_MS);
    // openness: fraction of the board still empty (line-value matters most in the opening)
    var empties = 0; for (var e = 0; e < NP; e++) if (state.color[e] === 0) empties++;
    var openness = empties / NP;
    // rate every legal move with the Go policy, then keep only the best handful to search
    var scored = [];
    for (var id = 0; id < NP; id++) {
      if (state.color[id] !== 0) continue;
      var r = tryPlace(state, id); if (!r) continue;
      var ps = policyScore(state, id, me, openness, r);
      if (ps > -1e8) scored.push({ id: id, ps: ps, child: null });
    }
    var sc0 = score(state), myMargin = me === 1 ? sc0.margin : -sc0.margin;
    if (scored.length === 0) return { pass: true };
    if (state.passes >= 1 && myMargin > 0) return { pass: true };
    scored.sort(function (a, b) { return b.ps - a.ps; });
    var K = Math.min(scored.length, Math.max(16, Math.round(NP * 0.28)));   // search only good moves
    var cands = scored.slice(0, K);
    // priors from the policy score; children precomputed
    // Root MC with RAVE (Rapid Action Value Estimation / AMAF): besides each candidate's real
    // MC stats, keep "all-moves-as-first" stats — every playout also updates every candidate whose
    // point was later played by us. Each playout thus refines ~all candidates, not just one, so the
    // ranking converges far faster on a small (browser) playout budget.
    var PRIOR = 4, C2 = 1.2, RAVE_BIAS = 2.5e-3;
    var C = cands.length, wins = new Float64Array(C), plays = new Float64Array(C), real = 0;
    var amWins = new Float64Array(C), amPlays = new Float64Array(C), first = new Int8Array(NP);
    for (var ci = 0; ci < C; ci++) {
      cands[ci].child = play(state, cands[ci].id);
      var h = 0.5 + cands[ci].ps; if (h > 0.9) h = 0.9; else if (h < 0.15) h = 0.15;
      plays[ci] = PRIOR; wins[ci] = h * PRIOR; amPlays[ci] = PRIOR; amWins[ci] = h * PRIOR;
    }
    var total = C * PRIOR;
    while (Date.now() < deadline) {
      var pick = 0, bestU = -1e18;
      for (var k = 0; k < C; k++) {
        var n = plays[k], an = amPlays[k];
        var beta = raveOn ? an / (an + n + an * n * RAVE_BIAS) : 0;   // AMAF early, real stats late
        var val = (1 - beta) * (wins[k] / n) + beta * (amWins[k] / an);
        var u = val + C2 * Math.sqrt(Math.log(total + 1) / n);
        if (u > bestU) { bestU = u; pick = k; }
      }
      first.fill(0);
      var sc = score(runPlayout(cands[pick].child, first));
      var w = sc.winner === "draw" ? 0 : (sc.winner === "black" ? 1 : 2);
      first[cands[pick].id] = me;                            // the root move counts for AMAF too
      var res = (w === me) ? 1 : (w === 0 ? 0.5 : 0);
      plays[pick]++; wins[pick] += res; total++; real++;
      for (var j = 0; j < C; j++) if (first[cands[j].id] === me) { amPlays[j]++; amWins[j] += res; }
      if (real > 40000) break;
    }
    var best = 0, bestN = -1;                                 // most-simulated move (robust choice)
    for (var k2 = 0; k2 < C; k2++) if (plays[k2] > bestN) { bestN = plays[k2]; best = k2; }
    return { pass: false, id: cands[best].id, sims: real, winrate: wins[best] / plays[best] };
  }

  var HEXAGO = {
    VIEW: VIEW, KOMI: KOMI,
    setBoard: setBoard,
    board: function () { return { type: CUR.type, points: PTS, adj: ADJ, size: NP, hull: CUR.hull, edgePx: CUR.edgePx, bd: BD }; },
    get points() { return PTS; }, get adj() { return ADJ; }, get size() { return NP; },
    initial: initial, clone: clone, isLegal: isLegal, legalMoves: legalMoves,
    play: play, pass: pass, ended: ended, score: score, scoreLive: scoreLive, scoreFinal: scoreFinal, status: status, group: group, aiMove: aiMove
  };
  if (typeof module !== "undefined" && module.exports) module.exports = HEXAGO;
  global.HEXAGO = HEXAGO;
})(typeof self !== "undefined" ? self : this);
