// ============================================================================================
// TRAINER (teaching version) — trains the HEXA-GO graph net in plain JS with HAND-WRITTEN backprop.
// ============================================================================================
// If you want to understand how a neural net actually learns, this is the file: nothing is hidden in
// a framework. We implement the forward pass AND its gradients by hand, then prove the gradients are
// correct with a finite-difference check (`node net/train.js --gradcheck`). See net/README.md §6.
//
// WHAT "TRAINING" MEANS HERE:
//   For each recorded position we know two "right answers":
//     pi = the search's move-visit distribution   (a better policy than the raw net)
//     z  = who actually won the game (+1 / -1)     (the truth about the value)
//   We measure how wrong the net is with a LOSS, then nudge every weight a tiny step in the direction
//   that reduces the loss. That direction is the negative GRADIENT (dLoss/dWeight), and computing it
//   efficiently is exactly what BACKPROPAGATION does.
//     loss = cross_entropy(net_policy, pi)   +   (net_value - z)^2
//            \___ push probability onto the __/    \__ predict the outcome __/
//                 moves the search liked
//
// HOW BACKPROP WORKS (the whole idea in three lines):
//   1. Forward pass: run the net, but REMEMBER each layer's inputs/outputs ("activations").
//   2. Start from dLoss/dOutput at the very end (easy: it's the derivative of the loss).
//   3. Walk BACKWARD through the layers; each layer turns "gradient w.r.t. my output" into
//      "gradient w.r.t. my input" and "gradient w.r.t. my weights" (the chain rule). Accumulate the
//      weight-gradients; the input-gradient feeds the previous layer. That's it.
//
// The forward here MIRRORS docs/hexago_net.js exactly, so trained weights drop straight into the
// browser/server inference with no conversion. (train_mlx.py is the GPU version: same math, autodiff.)
const fs = require("fs");
const GO = require("../docs/hexago_engine.js");
const NET = require("../docs/hexago_net.js");

let BOARD_TYPE = "tri", BOARD_SIZE = "m";
GO.setBoard(BOARD_TYPE, BOARD_SIZE);
let board = GO.board(), NP = board.size, ADJ = board.adj, BD = board.bd;
const F = 7;
// Auxiliary-head loss weights (KataGo-style). These heads (ownership + final score) only SHAPE the
// shared trunk — kept well below the policy/value terms so they guide, not dominate, the learning.
const COWN = 0.15, CSC = 0.15;

function atariMask(col) {
  const mask = new Int8Array(NP), seen = new Int8Array(NP);
  for (let i = 0; i < NP; i++) {
    if (col[i] === 0 || seen[i]) continue;
    const c = col[i]; let stack = [i], grp = [], libs = {}, nlib = 0; seen[i] = 1;
    while (stack.length) { const v = stack.pop(); grp.push(v); const ns = ADJ[v];
      for (let j = 0; j < ns.length; j++) { const u = ns[j];
        if (col[u] === 0) { if (!libs[u]) { libs[u] = 1; nlib++; } }
        else if (col[u] === c && !seen[u]) { seen[u] = 1; stack.push(u); } } }
    if (nlib === 1) for (let g = 0; g < grp.length; g++) mask[grp[g]] = 1;
  }
  return mask;
}
function feats(color, turn, ko) {
  const me = turn, opp = 3 - me, f = new Float64Array(NP * F), atari = atariMask(color);
  for (let v = 0; v < NP; v++) {
    const b = v * F, c = color[v];
    f[b] = c === me ? 1 : 0; f[b + 1] = c === opp ? 1 : 0; f[b + 2] = c === 0 ? 1 : 0;
    f[b + 3] = Math.min(BD[v], 4) / 4; f[b + 4] = (v === ko) ? 1 : 0;
    f[b + 5] = (c === me && atari[v]) ? 1 : 0; f[b + 6] = (c === opp && atari[v]) ? 1 : 0;
  }
  return f;
}
// ---- modular ops: each has a FORWARD and a matching BACKWARD (the building blocks of backprop) ----
// Arrays are flat & row-major: a batch of N rows, each `dim` wide, is one Float64Array where element
// (row v, column i) lives at v*dim + i. (Flat arrays are just faster than arrays-of-arrays in JS.)

// LINEAR LAYER — a fully-connected layer applied to every one of N points that SHARE the weights W,b.
//   forward:  Y[v,o] = b[o] + Σ_i  W[o,i] * X[v,i]           (each output o is a weighted sum of inputs)
// W is [Out rows × In cols] row-major, so weight W[o,i] is at W[o*In + i].
function linFwd(X, W, b, N, In, Out) {
  const Y = new Float64Array(N * Out);
  for (let v = 0; v < N; v++) for (let o = 0; o < Out; o++) {
    let s = b ? b[o] : 0; const wo = o * In, xv = v * In;
    for (let i = 0; i < In; i++) s += W[wo + i] * X[xv + i];
    Y[v * Out + o] = s;
  }
  return Y;
}
// BACKWARD of the linear layer. Given dY = dLoss/dY (how the loss changes with each output), produce:
//   dX[v,i] += Σ_o W[o,i] * dY[v,o]     (send gradient to the inputs, for the previous layer)
//   dW[o,i] += Σ_v X[v,i] * dY[v,o]     (gradient for each weight = input that used it × its output's grad)
//   db[o]   += Σ_v dY[v,o]              (bias just added, so its gradient is the summed output grad)
// These three lines ARE the chain rule for `Y = W·X + b`. Every framework's Linear layer does exactly
// this under the hood. dW/db accumulate across the whole minibatch; dX flows to the earlier layers.
function linBwd(X, W, dY, N, In, Out, dX, dW, db) {
  for (let v = 0; v < N; v++) for (let o = 0; o < Out; o++) {
    const g = dY[v * Out + o]; if (db) db[o] += g; const wo = o * In, xv = v * In;
    for (let i = 0; i < In; i++) { dW[wo + i] += g * X[xv + i]; if (dX) dX[xv + i] += W[wo + i] * g; }
  }
}
// GRAPH MEAN — the ONE operation that makes this a graph net: each point's output is the AVERAGE of
// its neighbours' vectors. This is how information spreads across the board (do it K times and a point
// "sees" K steps away). Averaging (not summing) is why the same weights work on 5- and 6-neighbour
// boards.  forward:  A[v] = mean over u in neighbours(v) of H[u].
function gmeanFwd(H, N, dim) {
  const A = new Float64Array(N * dim);
  for (let v = 0; v < N; v++) { const ns = ADJ[v], nn = ns.length, av = v * dim;
    for (let j = 0; j < nn; j++) { const ub = ns[j] * dim; for (let i = 0; i < dim; i++) A[av + i] += H[ub + i]; }
    if (nn) for (let i = 0; i < dim; i++) A[av + i] /= nn; }
  return A;
}
// BACKWARD of the mean: v averaged its neighbours, so a gradient arriving at A[v] is split equally back
// to each of v's neighbours (each got weight 1/degree). Gradients accumulate: a point that is a
// neighbour of many points receives a contribution from each.
function gmeanBwd(dA, N, dim, dH) {
  for (let v = 0; v < N; v++) { const ns = ADJ[v], nn = ns.length, av = v * dim; if (!nn) continue;
    for (let j = 0; j < nn; j++) { const ub = ns[j] * dim; for (let i = 0; i < dim; i++) dH[ub + i] += dA[av + i] / nn; } }
}
// ReLU(x) = max(x,0): the non-linearity. Its backward is trivial (derivative is 1 where x>0, else 0),
// which we apply inline later by zeroing the gradient wherever the pre-activation was <= 0.
const relu = (X) => { const Y = new Float64Array(X.length); for (let i = 0; i < X.length; i++) Y[i] = X[i] > 0 ? X[i] : 0; return Y; };

function zerosLike(W) {
  const g = { inW: new Float64Array(W.inW.length), inB: new Float64Array(W.inB.length),
    layers: W.layers.map(L => ({ selfW: new Float64Array(L.selfW.length), nbW: new Float64Array(L.nbW.length), b: new Float64Array(L.b.length) })),
    polW: new Float64Array(W.polW.length), polB: 0, valW1: new Float64Array(W.valW1.length), valB1: new Float64Array(W.valB1.length),
    valW2: new Float64Array(W.valW2.length), valB2: 0,
    ownW: new Float64Array(W.ownW.length), ownB: 0,
    scoreW1: new Float64Array(W.scoreW1.length), scoreB1: new Float64Array(W.scoreB1.length),
    scoreW2: new Float64Array(W.scoreW2.length), scoreB2: 0 };
  return g;
}

// forward + backprop for ONE record; accumulates grads into `grad`; returns [loss, polLoss, valLoss]
function lossGrad(rec, W, grad, cval) {
  const H = W.H, K = W.K, Hv = W.Hv;
  const color = new Int8Array(NP); for (let i = 0; i < NP; i++) color[i] = rec.c.charCodeAt(i) - 48;
  const f = feats(color, rec.turn, rec.ko);
  // ---- forward with cache ----
  const h0pre = linFwd(f, W.inW, W.inB, NP, F, H), h0 = relu(h0pre);
  const hs = [h0], pres = [h0pre], aggs = [null];
  for (let k = 0; k < K; k++) {
    const L = W.layers[k], hp = hs[k];
    const A = gmeanFwd(hp, NP, H);
    const selfY = linFwd(hp, L.selfW, null, NP, H, H), nbY = linFwd(A, L.nbW, null, NP, H, H);
    const pre = new Float64Array(NP * H); for (let i = 0; i < NP * H; i++) pre[i] = selfY[i] + nbY[i] + L.b[i % H];
    hs.push(relu(pre)); pres.push(pre); aggs.push(A);
  }
  const hK = hs[K];
  const pooled = new Float64Array(H); for (let v = 0; v < NP; v++) for (let i = 0; i < H; i++) pooled[i] += hK[v * H + i];
  for (let i = 0; i < H; i++) pooled[i] /= NP;
  const polLogit = linFwd(hK, W.polW, [W.polB], NP, H, 1);              // [NP]
  const vpre = linFwd(pooled, W.valW1, W.valB1, 1, H, Hv), vhid = relu(vpre);
  const vopre = linFwd(vhid, W.valW2, [W.valB2], 1, Hv, 1)[0], val = Math.tanh(vopre);
  // AUX HEADS forward (only when the record carries their targets — old data trains policy+value only):
  //   ownership[v] = tanh(hK[v]·ownW + ownB)       per-point: +1 mine / -1 theirs / 0 neutral
  //   score        = pooled -> ReLU MLP -> LINEAR  the final margin (mover POV), normalised by NP
  const hasOwn = typeof rec.own === "string", hasSc = typeof rec.sm === "number";
  let ownPre = null, ownV = null, scPre = null, scHid = null, scPred = 0;
  if (hasOwn) {
    ownPre = linFwd(hK, W.ownW, [W.ownB], NP, H, 1);                    // [NP] per-node logit
    ownV = new Float64Array(NP); for (let v = 0; v < NP; v++) ownV[v] = Math.tanh(ownPre[v]);
  }
  if (hasSc) {
    scPre = linFwd(pooled, W.scoreW1, W.scoreB1, 1, H, Hv); scHid = relu(scPre);
    scPred = linFwd(scHid, W.scoreW2, [W.scoreB2], 1, Hv, 1)[0];        // LINEAR (a regression, no tanh)
  }
  // ---- POLICY LOSS: cross-entropy between the net's move probabilities and the search target pi ----
  // SOFTMAX turns the raw per-point scores (polLogit) into a probability distribution over LEGAL moves.
  // (We subtract the max first — "max-trick" — purely for numerical safety so exp() doesn't overflow.)
  const legal = []; for (let v = 0; v < NP; v++) if (color[v] === 0) legal.push(v);
  let mx = -1e18; for (const v of legal) if (polLogit[v] > mx) mx = polLogit[v];
  let Z = 0; const p = {}; for (const v of legal) { const e = Math.exp(polLogit[v] - mx); p[v] = e; Z += e; }
  for (const v of legal) p[v] /= Z;                                     // p = net's move probabilities
  // The TARGET is the search's visit counts, normalised. We "sharpen" (raise to a power) first because
  // a low-simulation search spreads visits thinly; squaring concentrates the target on the best moves.
  const SHARP = 2.0, raw = {}; for (const [id, n] of rec.pi) raw[id] = (raw[id] || 0) + n;
  let tot = 0; const tgt = {};
  for (const id in raw) { const w = Math.pow(raw[id], SHARP); tgt[id] = w; tot += w; }
  for (const id in tgt) tgt[id] /= tot;
  // Cross-entropy H(tgt, p) = -Σ tgt·log(p): small when p puts its mass where tgt does.
  let polLoss = 0; for (const v of legal) { const t = tgt[v] || 0; if (t > 0) polLoss -= t * Math.log(p[v] + 1e-12); }
  // VALUE LOSS: squared error between the net's win-estimate and the actual game outcome z.
  const valLoss = (val - rec.z) * (val - rec.z);
  // AUX LOSSES (mean-squared error). ownership: average over points of (predicted - final owner)^2.
  // score: (predicted - final margin)^2. Both push the trunk to model the whole board's territory.
  let ownLoss = 0, scoreLoss = 0, ownTgt = null;
  if (hasOwn) {
    ownTgt = new Float64Array(NP);
    for (let v = 0; v < NP; v++) { const t = rec.own.charCodeAt(v) - 48; const tv = t === 1 ? 1 : t === 2 ? -1 : 0; ownTgt[v] = tv; const d = ownV[v] - tv; ownLoss += d * d; }
    ownLoss /= NP;
  }
  if (hasSc) scoreLoss = (scPred - rec.sm) * (scPred - rec.sm);
  // ================================ BACKWARD PASS (compute all gradients) =========================
  // Beautiful fact: the gradient of softmax-cross-entropy w.r.t. the raw scores is just (p - target).
  // So the policy head's output-gradient is simply "predicted minus wanted" for every legal move.
  const dPol = new Float64Array(NP);                                    // dLoss/dpolLogit
  for (const v of legal) dPol[v] = p[v] - (tgt[v] || 0);
  // VALUE head backward. Loss = (val - z)^2, and val = tanh(vopre), so by the chain rule:
  //   dLoss/dvopre = 2(val - z) · tanh'(vopre),  and tanh'(x) = 1 - tanh(x)^2 = 1 - val^2.
  const dval = 2 * cval * (val - rec.z), dvopre = dval * (1 - val * val);
  const dvhid = new Float64Array(Hv);
  // walk the gradient back through the two value linear layers. (The little {get/set 0} object is just
  // a 1-element "array" that routes the bias gradient into the scalar grad.valB2 — a JS shortcut.)
  linBwd(vhid, W.valW2, [dvopre], 1, Hv, 1, dvhid, grad.valW2, { get 0() { return 0; }, set 0(x) { grad.valB2 += x; } });
  for (let i = 0; i < Hv; i++) if (vpre[i] <= 0) dvhid[i] = 0;          // ReLU backward: kill grad where pre<=0
  const dpooled = new Float64Array(H);
  linBwd(pooled, W.valW1, dvhid, 1, H, Hv, dpooled, grad.valW1, grad.valB1);
  // SCORE head backward — same shape as the value head but LINEAR (no tanh), so dLoss/dscPred = 2·CSC·(pred-target).
  // Its gradient accumulates into the SAME dpooled (both heads read the pooled trunk vector).
  if (hasSc) {
    const dscPred = 2 * CSC * (scPred - rec.sm), dscHid = new Float64Array(Hv);
    linBwd(scHid, W.scoreW2, [dscPred], 1, Hv, 1, dscHid, grad.scoreW2, { get 0() { return 0; }, set 0(x) { grad.scoreB2 += x; } });
    for (let i = 0; i < Hv; i++) if (scPre[i] <= 0) dscHid[i] = 0;                 // ReLU backward
    linBwd(pooled, W.scoreW1, dscHid, 1, H, Hv, dpooled, grad.scoreW1, grad.scoreB1);
  }
  // POLICY head backward: turn dPol (per point) into a gradient on the final node features hK.
  const dhK = new Float64Array(NP * H);
  const polBbox = { get 0() { return 0; }, set 0(x) { grad.polB += x; } };
  linBwd(hK, W.polW, dPol, NP, H, 1, dhK, grad.polW, polBbox);
  // OWNERSHIP head backward — per node, through tanh: dLoss/downPre[v] = 2·(COWN/NP)·(pred-target)·(1-pred²).
  // Accumulates into the SAME dhK as the policy head (both read the per-node final features hK).
  if (hasOwn) {
    const dOwnPre = new Float64Array(NP);
    for (let v = 0; v < NP; v++) dOwnPre[v] = (2 * COWN / NP) * (ownV[v] - ownTgt[v]) * (1 - ownV[v] * ownV[v]);
    linBwd(hK, W.ownW, dOwnPre, NP, H, 1, dhK, grad.ownW, { get 0() { return 0; }, set 0(x) { grad.ownB += x; } });
  }
  // POOLING backward: `pooled` was the average of hK over all points, so its gradient spreads back
  // equally (÷NP) to every point. Both heads' gradients now live in dhK — sum them and flow onward.
  for (let v = 0; v < NP; v++) for (let i = 0; i < H; i++) dhK[v * H + i] += dpooled[i] / NP;
  // CONV LAYERS backward — walk from the last message-passing layer to the first, reversing each step.
  let dh = dhK;
  for (let k = K - 1; k >= 0; k--) {
    const L = W.layers[k], gL = grad.layers[k], pre = pres[k + 1], hp = hs[k], A = aggs[k + 1];
    const dpre = new Float64Array(NP * H);
    for (let i = 0; i < NP * H; i++) dpre[i] = pre[i] > 0 ? dh[i] : 0;
    for (let v = 0; v < NP; v++) for (let i = 0; i < H; i++) gL.b[i] += dpre[v * H + i];   // bias grad
    const dhp = new Float64Array(NP * H), dA = new Float64Array(NP * H);
    linBwd(hp, L.selfW, dpre, NP, H, H, dhp, gL.selfW, null);
    linBwd(A, L.nbW, dpre, NP, H, H, dA, gL.nbW, null);
    gmeanBwd(dA, NP, H, dhp);
    dh = dhp;
  }
  // input proj backward
  const dh0pre = new Float64Array(NP * H);
  for (let i = 0; i < NP * H; i++) dh0pre[i] = h0pre[i] > 0 ? dh[i] : 0;
  linBwd(f, W.inW, dh0pre, NP, F, H, null, grad.inW, grad.inB);
  return [polLoss + cval * valLoss + COWN * ownLoss + CSC * scoreLoss, polLoss, valLoss, ownLoss, scoreLoss];
}

// ---- gradient check ----
function gradCheck() {
  GO.setBoard("tri", "s"); board = GO.board(); NP = board.size; ADJ = board.adj; BD = board.bd;
  const W = NET.randomWeights(F, 4, 2, 3);
  // bias the value & score hidden layers positive so their ReLU units fire — otherwise the tiny random
  // net leaves them dead and the head gradients are trivially 0 (a check that passes but proves nothing).
  for (let i = 0; i < W.valB1.length; i++) W.valB1[i] = 0.5;
  for (let i = 0; i < W.scoreB1.length; i++) W.scoreB1[i] = 0.5;
  // one synthetic record
  let s = GO.initial(); for (const m of [10, 12, 20]) s = GO.play(s, m);
  // synthetic own/sm targets so the aux heads are exercised by the gradient check too
  let own = ""; for (let i = 0; i < NP; i++) own += String(i % 3);
  const rec = { c: Array.from(s.color).join(""), turn: s.turn, ko: s.ko,
    pi: [[15, 30], [22, 10], [8, 5]], z: 1, own: own, sm: 0.3 };
  const grad = zerosLike(W); lossGrad(rec, W, grad, 1.0);
  const eps = 1e-4;
  // for the head weights, check the index with the LARGEST gradient so we land on a live (non-dead-ReLU)
  // path — otherwise a tiny random net can zero a channel and the check passes without proving anything.
  const argmaxAbs = (a) => { let bi = 0, bv = -1; for (let i = 0; i < a.length; i++) { const x = Math.abs(a[i]); if (x > bv) { bv = x; bi = i; } } return bi; };
  const targets = [["inW", 3], ["polW", 1], ["inB", 0],
    ["valW1", argmaxAbs(grad.valW1)], ["valW2", argmaxAbs(grad.valW2)],
    ["ownW", argmaxAbs(grad.ownW)], ["scoreW1", argmaxAbs(grad.scoreW1)], ["scoreW2", argmaxAbs(grad.scoreW2)]];
  let maxErr = 0;
  const loss = (Wp) => lossGrad(rec, Wp, zerosLike(Wp), 1.0)[0];
  for (const [key, idx] of targets) {
    const orig = W[key][idx];
    W[key][idx] = orig + eps; const lp = loss(W);
    W[key][idx] = orig - eps; const lm = loss(W);
    W[key][idx] = orig;
    const num = (lp - lm) / (2 * eps), ana = grad[key][idx], err = Math.abs(num - ana) / (Math.abs(num) + Math.abs(ana) + 1e-9);
    maxErr = Math.max(maxErr, err);
    console.log(`  ${key}[${idx}]  analytic ${ana.toFixed(6)}  numeric ${num.toFixed(6)}  relerr ${err.toExponential(2)}`);
  }
  // check a layer weight
  const orig = W.layers[0].selfW[5];
  W.layers[0].selfW[5] = orig + eps; const lp = loss(W); W.layers[0].selfW[5] = orig - eps; const lm = loss(W); W.layers[0].selfW[5] = orig;
  const num = (lp - lm) / (2 * eps), ana = zerosLike(W).layers[0].selfW[5]; // recompute grad
  const g2 = zerosLike(W); lossGrad(rec, W, g2, 1.0);
  const err = Math.abs(num - g2.layers[0].selfW[5]) / (Math.abs(num) + Math.abs(g2.layers[0].selfW[5]) + 1e-9);
  console.log(`  layers[0].selfW[5]  analytic ${g2.layers[0].selfW[5].toFixed(6)}  numeric ${num.toFixed(6)}  relerr ${err.toExponential(2)}`);
  maxErr = Math.max(maxErr, err);
  console.log(maxErr < 1e-3 ? "GRADCHECK PASS ✓" : "GRADCHECK FAIL ✗ maxErr=" + maxErr);
}

// ---- training loop (SGD + momentum) ----
function applyGrad(W, grad, V, lr, mu, n) {
  const step = (w, g, vv) => { for (let i = 0; i < w.length; i++) { vv[i] = mu * vv[i] + g[i] / n; w[i] -= lr * vv[i]; } };
  step(W.inW, grad.inW, V.inW); step(W.inB, grad.inB, V.inB);
  for (let k = 0; k < W.K; k++) { step(W.layers[k].selfW, grad.layers[k].selfW, V.layers[k].selfW); step(W.layers[k].nbW, grad.layers[k].nbW, V.layers[k].nbW); step(W.layers[k].b, grad.layers[k].b, V.layers[k].b); }
  step(W.polW, grad.polW, V.polW); V.polB = mu * V.polB + grad.polB / n; W.polB -= lr * V.polB;
  step(W.valW1, grad.valW1, V.valW1); step(W.valB1, grad.valB1, V.valB1); step(W.valW2, grad.valW2, V.valW2); V.valB2 = mu * V.valB2 + grad.valB2 / n; W.valB2 -= lr * V.valB2;
  step(W.ownW, grad.ownW, V.ownW); V.ownB = mu * V.ownB + grad.ownB / n; W.ownB -= lr * V.ownB;
  step(W.scoreW1, grad.scoreW1, V.scoreW1); step(W.scoreB1, grad.scoreB1, V.scoreB1); step(W.scoreW2, grad.scoreW2, V.scoreW2); V.scoreB2 = mu * V.scoreB2 + grad.scoreB2 / n; W.scoreB2 -= lr * V.scoreB2;
}

function train() {
  const dataFile = process.argv[3] || "net/data.jsonl";
  const outFile = process.argv[4] || "docs/hexago-weights.json";
  const epochs = +(process.argv[5] || 8), H = +(process.argv[6] || 32), K = +(process.argv[7] || 3), Hv = 16;
  const lr = +(process.argv[8] || 0.05), cval = 1.0, batch = 32;
  const warm = process.argv[9];    // optional warm-start weights (Phase-B RL iterations)
  const data = fs.readFileSync(dataFile, "utf8").trim().split("\n").map(JSON.parse);
  let W;
  if (warm && fs.existsSync(warm)) { W = JSON.parse(fs.readFileSync(warm, "utf8")); console.log(`warm-start from ${warm} (H${W.H} K${W.K})`); }
  else W = NET.randomWeights(F, H, K, Hv);
  if (!W.ownW) {   // warm-starting from a net without aux heads: initialise them fresh (identity-neutral start)
    const r = NET.randomWeights(W.F, W.H, W.K, W.Hv);
    W.ownW = r.ownW; W.ownB = r.ownB; W.scoreW1 = r.scoreW1; W.scoreB1 = r.scoreB1; W.scoreW2 = r.scoreW2; W.scoreB2 = r.scoreB2;
    console.log("  (added ownership + score heads to warm-start net)");
  }
  console.log(`data ${data.length} positions | net H${W.H} K${W.K} | epochs ${epochs} lr ${lr}`);
  const V = zerosLike(W), mu = 0.9;
  for (let ep = 0; ep < epochs; ep++) {
    for (let i = data.length - 1; i > 0; i--) { const j = (Math.random() * (i + 1)) | 0; const t = data[i]; data[i] = data[j]; data[j] = t; }
    const elr = lr * (1 - 0.5 * ep / epochs);   // gentle lr decay
    let L = 0, PL = 0, VL = 0, OL = 0, SL = 0, cnt = 0;
    for (let b = 0; b < data.length; b += batch) {
      const grad = zerosLike(W); let n = 0;
      for (let i = b; i < Math.min(b + batch, data.length); i++) { const [l, pl, vl, ol, sl] = lossGrad(data[i], W, grad, cval); L += l; PL += pl; VL += vl; OL += ol; SL += sl; n++; cnt++; }
      applyGrad(W, grad, V, elr, mu, n);
    }
    console.log(`epoch ${ep + 1}/${epochs}  loss ${(L / cnt).toFixed(4)}  pol ${(PL / cnt).toFixed(4)}  val ${(VL / cnt).toFixed(4)}  own ${(OL / cnt).toFixed(4)}  score ${(SL / cnt).toFixed(4)}`);
  }
  // serialize (plain arrays); use the net's OWN dims (warm-start may differ from argv)
  const outW = { F: W.F, H: W.H, K: W.K, Hv: W.Hv, inW: Array.from(W.inW), inB: Array.from(W.inB),
    layers: W.layers.map(L => ({ selfW: Array.from(L.selfW), nbW: Array.from(L.nbW), b: Array.from(L.b) })),
    polW: Array.from(W.polW), polB: W.polB, passW: Array.from(W.passW), passB: W.passB,
    valW1: Array.from(W.valW1), valB1: Array.from(W.valB1), valW2: Array.from(W.valW2), valB2: W.valB2,
    ownW: Array.from(W.ownW), ownB: W.ownB,
    scoreW1: Array.from(W.scoreW1), scoreB1: Array.from(W.scoreB1), scoreW2: Array.from(W.scoreW2), scoreB2: W.scoreB2,
    board: BOARD_TYPE + "/" + BOARD_SIZE };
  fs.writeFileSync(outFile, JSON.stringify(outW));
  console.log(`saved -> ${outFile} (${(JSON.stringify(outW).length / 1024).toFixed(0)} KB)`);
}

if (process.argv[2] === "--gradcheck") gradCheck();
else train();
