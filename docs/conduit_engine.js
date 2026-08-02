// CONDUIT — prototype engine (JS port of conduit_engine.py). Fiber flow game on a degree-6 hex-cell
// board. Real Dinic max-flow + min-cut drive scoring, the AI, and the UI's "danger line". Offline.
// Cells are keyed "q,r"; edges keyed "a|b" (endpoints sorted). Two players: 0 = you, 1 = AI.
(function (root, factory) {
  var mod = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = mod;
  root.CONDUIT = mod;
})(typeof self !== "undefined" ? self : this, function () {
  var DIRS = [[1, 0], [1, -1], [0, -1], [-1, 0], [-1, 1], [0, 1]];
  var COST = { build: 3, upgrade: 2, interdict: 3 };
  var MAXCAP = 3, TICKS = 20;

  function ck(q, r) { return q + "," + r; }
  function edge(a, b) { return a < b ? a + "|" + b : b + "|" + a; }
  function ends(e) { return e.split("|"); }

  function genBoard(R) {
    var cells = [], set = {};
    for (var q = -R; q <= R; q++) for (var r = -R; r <= R; r++)
      if (Math.abs(q + r) <= R) { var k = ck(q, r); cells.push(k); set[k] = true; }
    var adj = {};
    cells.forEach(function (k) {
      var p = k.split(",").map(Number), out = [];
      DIRS.forEach(function (d) { var nk = ck(p[0] + d[0], p[1] + d[1]); if (set[nk]) out.push(nk); });
      adj[k] = out;
    });
    return { cells: cells, set: set, adj: adj };
  }

  // symmetric fiber scenario: opposite-corner PoPs, exchanges in 180deg pairs + a fat centre
  function makeScenario(R) {
    R = R || 3;
    var b = genBoard(R);
    var srcA = ck(-R, R), srcB = ck(R, -R);   // player 0 (you) in the BOTTOM-LEFT, matching the other games
    var raw = [[[0, 0], 4, 3], [[R - 1, -1], 3, 3], [[1, R - 2], 2, 4]];
    var sinks = [];
    raw.forEach(function (s, i) {
      var c = s[0];
      function push(cell) { var k = ck(cell[0], cell[1]); if (b.set[k]) sinks.push({ cell: k, dem: s[1], price: s[2] }); }
      push(c);
      if (i > 0) push([-c[0], -c[1]]);   // its 180deg mirror
    });
    return { cells: b.cells, adj: b.adj, set: b.set, src: [srcA, srcB], sinks: sinks, R: R };
  }

  // ---------------- Dinic max-flow ----------------
  function Dinic(n) { this.n = n; this.g = []; for (var i = 0; i < n; i++) this.g.push([]); }
  Dinic.prototype.add = function (u, v, c) {
    this.g[u].push([v, c, this.g[v].length]);
    this.g[v].push([u, 0, this.g[u].length - 1]);
  };
  Dinic.prototype.bfs = function (s, t) {
    this.lv = new Int32Array(this.n).fill(-1); this.lv[s] = 0; var q = [s], h = 0;
    while (h < q.length) { var u = q[h++]; for (var i = 0; i < this.g[u].length; i++) { var e = this.g[u][i]; if (e[1] > 0 && this.lv[e[0]] < 0) { this.lv[e[0]] = this.lv[u] + 1; q.push(e[0]); } } }
    return this.lv[t] >= 0;
  };
  Dinic.prototype.dfs = function (u, t, f) {
    if (u === t) return f;
    for (; this.it[u] < this.g[u].length; this.it[u]++) {
      var e = this.g[u][this.it[u]];
      if (e[1] > 0 && this.lv[e[0]] === this.lv[u] + 1) {
        var d = this.dfs(e[0], t, Math.min(f, e[1]));
        if (d > 0) { e[1] -= d; this.g[e[0]][e[2]][1] += d; return d; }
      }
    }
    return 0;
  };
  Dinic.prototype.maxflow = function (s, t) {
    var flow = 0;
    while (this.bfs(s, t)) { this.it = new Int32Array(this.n); var f; while ((f = this.dfs(s, t, 1e9)) > 0) flow += f; }
    return flow;
  };
  Dinic.prototype.reachable = function (s) {   // residual-reachable from s => source side of a min-cut
    var seen = new Uint8Array(this.n); seen[s] = 1; var q = [s], h = 0;
    while (h < q.length) { var u = q[h++]; for (var i = 0; i < this.g[u].length; i++) { var e = this.g[u][i]; if (e[1] > 0 && !seen[e[0]]) { seen[e[0]] = 1; q.push(e[0]); } } }
    return seen;
  };

  function idxMap(cells) { var m = {}; for (var i = 0; i < cells.length; i++) m[cells[i]] = i; return m; }

  function buildGraph(links, cells, extra) {
    var idx = idxMap(cells), d = new Dinic(cells.length + (extra || 0));
    for (var e in links) { var c = links[e]; if (c <= 0) continue; var uv = ends(e); d.add(idx[uv[0]], idx[uv[1]], c); d.add(idx[uv[1]], idx[uv[0]], c); }
    return { d: d, idx: idx };
  }

  function flowToOne(links, source, sink, cells) {
    if (source === sink) return 0;
    var g = buildGraph(links, cells, 0);
    return g.d.maxflow(g.idx[source], g.idx[sink]);
  }

  // max-flow to a super-sink, each exchange feeding it at its contended share; returns {thr, cut:[edges]}
  function delivered(links, source, sinkCaps, cells) {
    var g = buildGraph(links, cells, 1), T = cells.length, any = false;
    for (var s in sinkCaps) { if (sinkCaps[s] > 0) { g.d.add(g.idx[s], T, sinkCaps[s]); any = true; } }
    if (!(source in g.idx) || !any) return { thr: 0, cut: [] };
    var thr = g.d.maxflow(g.idx[source], T);
    // min-cut: edges from residual-reachable set to the rest that are real (non-super-sink) links
    var seen = g.d.reachable(g.idx[source]), cut = [], inv = cells;
    for (var e in links) { var uv = ends(e); var a = g.idx[uv[0]], b = g.idx[uv[1]]; if (links[e] > 0 && seen[a] !== seen[b]) cut.push(e); }
    return { thr: thr, cut: cut };
  }

  // network capacity: how much p COULD deliver if they won every exchange's full demand. Capped by both
  // the board's demand and p's own min-cut — so it's the right "robustness" target for the AI to invest
  // surplus credit into (a fatter, cut-resilient net) instead of hoarding, and it drives upgrades.
  function netCapacity(state, p) {
    var full = {}; state.sc.sinks.forEach(function (sk) { full[sk.cell] = sk.dem; });
    return delivered(effLinks(state, p), state.sc.src[p], full, state.sc.cells).thr;
  }

  // DANGER SET: every one of p's links where a single enemy Cut (a -1 throttle, exactly the in-game
  // interdiction) would actually reduce p's DELIVERED throughput — computed by applying that throttle and
  // re-resolving the full game (so contention shifts are included), then comparing. On a uniform 1-wide
  // path that's the WHOLE path (all equally critical — no arbitrary "first link"); once a parallel route
  // carries the load, a cut that costs nothing drops off the set. This is what the UI's red line shows.
  function dangerLinks(state, p) {
    var base = resolve(state).thr[p];
    if (base <= 0) return [];
    var out = [], L = state.links[p];
    for (var e in L) {
      var key = p + "@" + e, had = key in state.throttle;
      if (!had) state.throttle[key] = 3;                 // simulate the Cut (-1 capacity on p's link e)
      var t = resolve(state).thr[p];
      if (!had) delete state.throttle[key];
      if (t < base) out.push(e);
    }
    return out;
  }

  // effective links = a player's links with active interdiction throttles applied
  function effLinks(state, p) {
    var out = {}, L = state.links[p];
    for (var e in L) out[e] = L[e];
    for (var key in state.throttle) { var parts = key.split("@"); if (+parts[0] === p && out[parts[1]] != null) out[parts[1]] = Math.max(0, out[parts[1]] - 1); }
    return out;
  }

  // resolve one tick: contention split by reach, then delivered max-flow per player. Returns throughput,
  // per-exchange split, and each player's min-cut edge set (for the UI danger line).
  function resolve(state) {
    var sc = state.sc, cells = sc.cells, eff = [effLinks(state, 0), effLinks(state, 1)];
    var reach = [{}, {}], caps = [{}, {}], split = {};
    sc.sinks.forEach(function (sk) {
      var a = flowToOne(eff[0], sc.src[0], sk.cell, cells), b = flowToOne(eff[1], sc.src[1], sk.cell, cells);
      reach[0][sk.cell] = a; reach[1][sk.cell] = b;
      var tot = a + b, ca = 0, cb = 0;
      if (tot > 0) { ca = Math.floor(sk.dem * a / tot); cb = Math.floor(sk.dem * b / tot); var rem = sk.dem - ca - cb; if (rem) { if (a >= b) ca += rem; else cb += rem; } }
      caps[0][sk.cell] = ca; caps[1][sk.cell] = cb; split[sk.cell] = [ca, cb];
    });
    var d0 = delivered(eff[0], sc.src[0], caps[0], cells), d1 = delivered(eff[1], sc.src[1], caps[1], cells);
    return { thr: [d0.thr, d1.thr], split: split, cut: [d0.cut, d1.cut] };
  }

  // ---------------- game state ----------------
  function newGame(R) {
    var sc = makeScenario(R || 3);
    return { sc: sc, links: [{}, {}], credit: [12, 12], revenue: [0, 0], throttle: {}, tick: 0, ticks: TICKS };
  }

  function touch(state, p) { var s = {}; s[state.sc.src[p]] = 1; for (var e in state.links[p]) { var uv = ends(e); s[uv[0]] = 1; s[uv[1]] = 1; } return s; }

  function legalBuilds(state, p) {
    var t = touch(state, p), occ = {}, e; for (e in state.links[0]) occ[e] = 1; for (e in state.links[1]) occ[e] = 1;
    var out = {}, adj = state.sc.adj;
    for (var c in t) adj[c].forEach(function (nb) { var e2 = edge(c, nb); if (!occ[e2]) out[e2] = 1; });
    return Object.keys(out);
  }
  function legalUpgrades(state, p) { var out = []; for (var e in state.links[p]) if (state.links[p][e] < MAXCAP) out.push(e); return out; }
  function legalInterdicts(state, p) {
    var opp = 1 - p, t = touch(state, p), out = [];
    for (var e in state.links[opp]) { var uv = ends(e); if (state.links[opp][e] > 0 && (t[uv[0]] || t[uv[1]]) && !(opp + "@" + e in state.throttle)) out.push(e); }
    return out;
  }

  function canAfford(state, p, kind) { return state.credit[p] >= COST[kind]; }

  function apply(state, p, kind, e) {
    if (state.credit[p] < COST[kind]) return false;
    if (kind === "build") { if (state.links[0][e] || state.links[1][e]) return false; state.links[p][e] = 1; }
    else if (kind === "upgrade") { if (!state.links[p][e] || state.links[p][e] >= MAXCAP) return false; state.links[p][e] += 1; }
    else if (kind === "interdict") { state.throttle[(1 - p) + "@" + e] = 3; }
    else return false;
    state.credit[p] -= COST[kind];
    return true;
  }

  function tickIncome(state, thr) {
    for (var p = 0; p < 2; p++) { state.revenue[p] += thr[p]; state.credit[p] += 4 + thr[p]; }
    for (var k in state.throttle) { state.throttle[k] -= 1; if (state.throttle[k] <= 0) delete state.throttle[k]; }
  }

  // ---------------- max-flow AI (greedy 1-ply + path shaping) ----------------
  function reachPotential(state, p) {
    var t = touch(state, p), opp = state.links[1 - p], adj = state.sc.adj, dist = {}, q = [], h = 0;
    for (var c in t) { dist[c] = 0; q.push(c); }
    while (h < q.length) { var u = q[h++]; adj[u].forEach(function (nb) { if (opp[edge(u, nb)]) return; if (dist[nb] == null) { dist[nb] = dist[u] + 1; q.push(nb); } }); }
    var pot = 0; state.sc.sinks.forEach(function (sk) { pot -= (dist[sk.cell] != null ? dist[sk.cell] : 12); });
    return pot;
  }

  function snapshot(state) { return { l0: Object.assign({}, state.links[0]), l1: Object.assign({}, state.links[1]), thr: Object.assign({}, state.throttle), cr: state.credit.slice() }; }
  function restore(state, s) { state.links[0] = s.l0; state.links[1] = s.l1; state.throttle = s.thr; state.credit = s.cr; }

  function aiTurn(state, p) {
    var budget = 3, SHAPE = 0.2, ROBUST = 0.12;   // ROBUST: value network capacity so surplus credit buys
    while (budget > 0 && state.credit[p] >= 2) {   // a fatter, cut-resilient net (drives upgrades) not hoarding
      var base = resolve(state), b0 = (base.thr[p] - base.thr[1 - p]) + SHAPE * reachPotential(state, p) + ROBUST * netCapacity(state, p);
      var cands = [];
      legalBuilds(state, p).forEach(function (e) { if (canAfford(state, p, "build")) cands.push(["build", e]); });
      legalUpgrades(state, p).forEach(function (e) { if (canAfford(state, p, "upgrade")) cands.push(["upgrade", e]); });
      legalInterdicts(state, p).forEach(function (e) { if (canAfford(state, p, "interdict")) cands.push(["interdict", e]); });
      if (!cands.length) break;
      // shuffle + cap candidate count so the JS turn stays snappy
      for (var i = cands.length - 1; i > 0; i--) { var j = (Math.random() * (i + 1)) | 0; var tmp = cands[i]; cands[i] = cands[j]; cands[j] = tmp; }
      if (cands.length > 44) cands = cands.slice(0, 44);
      var best = null, bestGain = 1e-9;
      for (var ci = 0; ci < cands.length; ci++) {
        var mv = cands[ci], s = snapshot(state);
        if (!apply(state, p, mv[0], mv[1])) { restore(state, s); continue; }
        var t = resolve(state), gain = (t.thr[p] - t.thr[1 - p]) + SHAPE * reachPotential(state, p) + ROBUST * netCapacity(state, p) - b0;
        if (mv[0] === "interdict") gain -= 0.25;
        restore(state, s);
        if (gain > bestGain) { bestGain = gain; best = mv; }
      }
      if (!best) {
        // greedy plateaued (widening a cut needs several upgrades, each flat on its own). If flush with
        // credit, invest it in robustness: upgrade a bottleneck (danger) link, else a flow-carrying link.
        if (state.credit[p] >= COST.upgrade + 2) {
          var dl = dangerLinks(state, p), up = null;
          for (var di = 0; di < dl.length; di++) if (state.links[p][dl[di]] < MAXCAP) { up = dl[di]; break; }
          if (!up) { var ups = legalUpgrades(state, p); if (ups.length) up = ups[(Math.random() * ups.length) | 0]; }
          if (up) { apply(state, p, "upgrade", up); budget--; continue; }
        }
        break;
      }
      apply(state, p, best[0], best[1]); budget--;
    }
  }

  return {
    makeScenario: makeScenario, newGame: newGame, resolve: resolve,
    legalBuilds: legalBuilds, legalUpgrades: legalUpgrades, legalInterdicts: legalInterdicts,
    canAfford: canAfford, apply: apply, tickIncome: tickIncome, aiTurn: aiTurn, dangerLinks: dangerLinks,
    ends: ends, edge: edge, COST: COST, MAXCAP: MAXCAP, TICKS: TICKS
  };
});
