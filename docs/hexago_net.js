// HEXA-GO neural evaluator — a tiny message-passing graph net (policy + value) over the board
// adjacency. Same weights run here (browser/Node) and in hexago_net.py (server, pure Python). It is
// the learned replacement for random rollouts: forward(state) -> {policy per point, passLogit, value}.
// Architecture (all shared weights, so ONE net works on any lattice type/size via ADJ):
//   h = ReLU(inW·feat + inB)                         input projection  F -> H
//   repeat K:  h = ReLU(selfW·h + nbW·mean_nb(h) + b)   graph conv       H -> H
//   policyLogit[v] = h[v]·polW + polB   (per node)
//   passLogit      = pooled·passW + passB   (pooled = mean_v h[v])
//   value          = tanh( ReLU(pooled·valW1 + valB1)·valW2 + valB2 )   in [-1,1], side-to-move POV
// Features per node (side-to-move POV): [is_mine, is_theirs, is_empty, line=min(BD,4)/4, is_ko].
(function (root, factory) {
  var mod = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = mod;
  root.HEXANET = mod;
})(typeof self !== "undefined" ? self : this, function () {
  var W = null;                 // loaded weights
  function setWeights(w) { W = w; }
  function loaded() { return !!W; }

  function relu(x) { return x < 0 ? 0 : x; }
  // y[r] = sum_c M[r*cols+c]*x[c] + (bias? b[r]:0)   (M is rows×cols row-major)
  function matvec(M, x, rows, cols, b, out) {
    for (var r = 0; r < rows; r++) {
      var s = b ? b[r] : 0, o = r * cols;
      for (var c = 0; c < cols; c++) s += M[o + c] * x[c];
      out[r] = s;
    }
    return out;
  }

  // atari mask: 1 where the stone belongs to a group with exactly one liberty (parity with train.js / .py)
  function atariMask(col, adj, NP) {
    var mask = new Int8Array(NP), seen = new Int8Array(NP), i;
    for (i = 0; i < NP; i++) {
      if (col[i] === 0 || seen[i]) continue;
      var c = col[i], stack = [i], grp = [], libs = {}, nlib = 0; seen[i] = 1;
      while (stack.length) {
        var v = stack.pop(); grp.push(v); var ns = adj[v];
        for (var j = 0; j < ns.length; j++) { var u = ns[j];
          if (col[u] === 0) { if (!libs[u]) { libs[u] = 1; nlib++; } }
          else if (col[u] === c && !seen[u]) { seen[u] = 1; stack.push(u); } }
      }
      if (nlib === 1) for (var g = 0; g < grp.length; g++) mask[grp[g]] = 1;
    }
    return mask;
  }
  // features: Float32Array[NP*F], side-to-move perspective. F=7:
  // [is_mine, is_theirs, is_empty, line, is_ko, mine_atari, theirs_atari]
  function features(state, adj, bd, NP) {
    var F = W.F, me = state.turn, opp = 3 - me, col = state.color, feat = new Float32Array(NP * F), v;
    var atari = atariMask(col, adj, NP);
    for (v = 0; v < NP; v++) {
      var b = v * F, c = col[v];
      feat[b] = c === me ? 1 : 0;
      feat[b + 1] = c === opp ? 1 : 0;
      feat[b + 2] = c === 0 ? 1 : 0;
      feat[b + 3] = Math.min(bd[v], 4) / 4;
      feat[b + 4] = v === state.ko ? 1 : 0;
      feat[b + 5] = (c === me && atari[v]) ? 1 : 0;
      feat[b + 6] = (c === opp && atari[v]) ? 1 : 0;
    }
    return feat;
  }

  // forward pass; board = {adj, size, bd} from HEXAGO.board(). Returns {policy:Float32[NP], passLogit, value, h}
  function forward(state, board) {
    var adj = board.adj, NP = board.size, bd = board.bd;
    var F = W.F, H = W.H, K = W.K, Hv = W.Hv, v, k, i;
    var feat = features(state, adj, bd, NP);
    // input projection -> h (NP×H)
    var h = new Float32Array(NP * H), tmp = new Float32Array(F);
    for (v = 0; v < NP; v++) {
      var fb = v * F; for (i = 0; i < F; i++) tmp[i] = feat[fb + i];
      var row = new Float32Array(H); matvec(W.inW, tmp, H, F, W.inB, row);
      for (i = 0; i < H; i++) h[v * H + i] = relu(row[i]);
    }
    // K graph-conv layers
    var agg = new Float32Array(H), hv = new Float32Array(H), self = new Float32Array(H), nb = new Float32Array(H);
    for (k = 0; k < K; k++) {
      var L = W.layers[k], nh = new Float32Array(NP * H);
      for (v = 0; v < NP; v++) {
        var ns = adj[v], nn = ns.length;
        for (i = 0; i < H; i++) agg[i] = 0;
        for (var j = 0; j < nn; j++) { var ub = ns[j] * H; for (i = 0; i < H; i++) agg[i] += h[ub + i]; }
        if (nn) for (i = 0; i < H; i++) agg[i] /= nn;
        var vb = v * H; for (i = 0; i < H; i++) hv[i] = h[vb + i];
        matvec(L.selfW, hv, H, H, null, self);
        matvec(L.nbW, agg, H, H, null, nb);
        for (i = 0; i < H; i++) nh[vb + i] = relu(self[i] + nb[i] + L.b[i]);
      }
      h = nh;
    }
    // pooled = mean over nodes
    var pooled = new Float32Array(H);
    for (v = 0; v < NP; v++) { var pb = v * H; for (i = 0; i < H; i++) pooled[i] += h[pb + i]; }
    for (i = 0; i < H; i++) pooled[i] /= NP;
    // policy logits (per node) + pass
    var policy = new Float32Array(NP);
    for (v = 0; v < NP; v++) { var s = W.polB, hb = v * H; for (i = 0; i < H; i++) s += h[hb + i] * W.polW[i]; policy[v] = s; }
    var passLogit = W.passB; for (i = 0; i < H; i++) passLogit += pooled[i] * W.passW[i];
    // value head
    var vh = new Float32Array(Hv); matvec(W.valW1, pooled, Hv, H, W.valB1, vh);
    for (i = 0; i < Hv; i++) vh[i] = relu(vh[i]);
    var vo = W.valB2; for (i = 0; i < Hv; i++) vo += vh[i] * W.valW2[i];
    var value = Math.tanh(vo);
    return { policy: policy, passLogit: passLogit, value: value, h: h, pooled: pooled };
  }

  // softmax over legal empty points (+ pass), returns {probs:{id:p}, passP}
  function policyProbs(state, board) {
    var out = forward(state, board), NP = board.size, col = state.color, v;
    var ids = [], logits = [], max = out.passLogit;
    for (v = 0; v < NP; v++) if (col[v] === 0) { ids.push(v); logits.push(out.policy[v]); if (out.policy[v] > max) max = out.policy[v]; }
    var Z = 0, probs = {}, e;
    for (var i = 0; i < ids.length; i++) { e = Math.exp(logits[i] - max); probs[ids[i]] = e; Z += e; }
    var passP = Math.exp(out.passLogit - max); Z += passP;
    for (var id in probs) probs[id] /= Z; passP /= Z;
    return { probs: probs, passP: passP, value: out.value };
  }

  // random-init weights (Xavier-ish) for a fresh net / testing
  function randomWeights(F, H, K, Hv) {
    F = F || 7; H = H || 32; K = K || 3; Hv = Hv || 16;
    function rnd(n, fan) { var a = new Float32Array(n), s = Math.sqrt(2 / fan); for (var i = 0; i < n; i++) a[i] = (Math.random() * 2 - 1) * s; return Array.from(a); }
    function zeros(n) { return Array.from(new Float32Array(n)); }
    var layers = []; for (var k = 0; k < K; k++) layers.push({ selfW: rnd(H * H, H), nbW: rnd(H * H, H), b: zeros(H) });
    return {
      F: F, H: H, K: K, Hv: Hv,
      inW: rnd(H * F, F), inB: zeros(H), layers: layers,
      polW: rnd(H, H), polB: 0, passW: rnd(H, H), passB: 0,
      valW1: rnd(Hv * H, H), valB1: zeros(Hv), valW2: rnd(Hv, Hv), valB2: 0
    };
  }

  // ---- net-guided PUCT: priors from the policy head, leaf value from the value head (no rollouts) ----
  function engine() {
    if (typeof HEXAGO !== "undefined") return HEXAGO;
    if (typeof require !== "undefined") return require("./hexago_engine.js");
    return null;
  }
  // build a node: run the net once, keep top-K legal moves as edges (priors P), store win-prob q
  function makeNode(GO, state, board, K) {
    var out = forward(state, board), NP = board.size, col = state.color, me = state.turn, v;
    var q = (out.value + 1) / 2;                              // win prob for side-to-move, in [0,1]
    // territory sense: don't fill your own settled area or invade a small sealed enemy pocket (matches
    // the MC engine's policy) — keeps play sensible AND lets games END promptly instead of dragging on.
    var enc = GO.enclosure ? GO.enclosure(col) : null;
    // legal empties, softmax the policy logits over them, keep the top-K by prior
    var ids = [], mx = -1e18;
    for (v = 0; v < NP; v++) {
      if (col[v] !== 0 || !GO.isLegal(state, v)) continue;
      if (enc) { var ro = enc.owner[v], rs = enc.size[v]; if (ro === me || (ro === 3 - me && rs <= 12)) continue; }
      ids.push(v); if (out.policy[v] > mx) mx = out.policy[v];
    }
    var arr = [], Z = 0, i;
    for (i = 0; i < ids.length; i++) { var e = Math.exp(out.policy[ids[i]] - mx); arr.push({ id: ids[i], p: e }); Z += e; }
    for (i = 0; i < arr.length; i++) arr[i].p /= Z;
    arr.sort(function (a, b) { return b.p - a.p; });
    if (arr.length > K) arr = arr.slice(0, K);
    var edges = [];
    for (i = 0; i < arr.length; i++) edges.push({ id: arr[i].id, P: arr[i].p, N: 0, W: 0, aN: 0, aW: 0, child: null });
    return { state: state, edges: edges, q: q, mover: me, N: 0 };
  }
  var RAVE_BIAS = 2.5e-3;
  // ONE tree-RAVE simulation: descend by PUCT+AMAF, expand a leaf, evaluate by a heavy rollout, then
  // backprop real stats AND all-moves-as-first (RAVE) stats up the path. Net priors + RAVE + rollout
  // value together make the search as sample-efficient as MC-RAVE, plus tree depth + learned priors.
  function simulateRave(GO, root, board, Cpuct, K) {
    var path = [], node = root, i;
    while (true) {
      node.N++;
      if (node.edges.length === 0) break;                      // terminal-ish leaf
      var sqrtN = Math.sqrt(node.N), bi = 0, bestU = -1e18;
      for (i = 0; i < node.edges.length; i++) {
        var ed = node.edges[i];
        var qn = ed.N > 0 ? ed.W / ed.N : node.q;              // FPU = parent net value
        var beta = ed.aN > 0 ? ed.aN / (ed.aN + ed.N + ed.aN * ed.N * RAVE_BIAS) : 0;
        var qr = (1 - beta) * qn + beta * (ed.aN > 0 ? ed.aW / ed.aN : qn);
        var u = qr + Cpuct * ed.P * sqrtN / (1 + ed.N);
        if (u > bestU) { bestU = u; bi = i; }
      }
      path.push({ node: node, ei: bi });
      var e = node.edges[bi];
      if (e.child === null) { e.child = makeNode(GO, GO.play(node.state, e.id), board, K); node = e.child; node.N++; break; }
      node = e.child;
    }
    var rr = GO.rolloutFirst(node.state), first = rr.first;
    var w = rr.winner === "draw" ? 0 : (rr.winner === "black" ? 1 : 2);
    for (i = 0; i < path.length; i++) { var pn = path[i].node, mv = pn.edges[path[i].ei].id; if (first[mv] === 0) first[mv] = pn.mover; }
    for (i = 0; i < path.length; i++) {
      var n2 = path[i].node, C = n2.mover, ce = n2.edges[path[i].ei];
      var res = w === 0 ? 0.5 : (w === C ? 1 : 0);
      ce.N++; ce.W += res;
      for (var j = 0; j < n2.edges.length; j++) { var e2 = n2.edges[j]; if (first[e2.id] === C) { e2.aN++; e2.aW += res; } }
    }
  }
  function netPuct(state, budgetMs, opts) {
    var GO = engine(), board = GO.board(), me = state.turn;
    var deadline = Date.now() + (budgetMs || 800), C = (opts && opts.c) || 1.4, K = (opts && opts.k) || 24;
    var root = makeNode(GO, state, board, K);
    if (root.edges.length === 0) return { pass: true };
    var sc0 = GO.score(state), myMargin = me === 1 ? sc0.margin : -sc0.margin;
    if (state.passes >= 1 && myMargin > 0) return { pass: true };   // both-pass endgame when ahead
    // root exploration noise for self-play (mix uniform into the priors) so games diversify
    if (opts && opts.noise) { var eps = opts.noise, n = root.edges.length; for (var e3 = 0; e3 < n; e3++) root.edges[e3].P = (1 - eps) * root.edges[e3].P + eps / n; }
    var fixed = opts && opts.sims, sims = 0;
    while ((fixed ? sims < fixed : Date.now() < deadline) && sims < 100000) { simulateRave(GO, root, board, C, K); sims++; }
    var best = root.edges[0];
    for (var i = 1; i < root.edges.length; i++) if (root.edges[i].N > best.N) best = root.edges[i];
    var dist = []; for (i = 0; i < root.edges.length; i++) dist.push([root.edges[i].id, root.edges[i].N]);
    return { pass: false, id: best.id, sims: sims, winrate: best.N ? best.W / best.N : root.q, value: root.q, dist: dist };
  }

  return { setWeights: setWeights, loaded: loaded, forward: forward, policyProbs: policyProbs,
           features: features, randomWeights: randomWeights, netPuct: netPuct };
});
