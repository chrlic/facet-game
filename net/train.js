// Phase-A imitation trainer for the HEXA-GO graph net (pure JS, manual backprop).
// Loss = policy cross-entropy (target = MC visit distribution) + c_val * value MSE (target = outcome).
// The forward here MIRRORS docs/hexago_net.js exactly so trained weights drop straight into inference.
// Verified by finite-difference gradient checking (node net/train.js --gradcheck).
const fs = require("fs");
const GO = require("../docs/hexago_engine.js");
const NET = require("../docs/hexago_net.js");

let BOARD_TYPE = "tri", BOARD_SIZE = "m";
GO.setBoard(BOARD_TYPE, BOARD_SIZE);
let board = GO.board(), NP = board.size, ADJ = board.adj, BD = board.bd;
const F = 7;

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
// ---- modular ops (forward + backward on flat row-major arrays) ----
function linFwd(X, W, b, N, In, Out) {
  const Y = new Float64Array(N * Out);
  for (let v = 0; v < N; v++) for (let o = 0; o < Out; o++) {
    let s = b ? b[o] : 0; const wo = o * In, xv = v * In;
    for (let i = 0; i < In; i++) s += W[wo + i] * X[xv + i];
    Y[v * Out + o] = s;
  }
  return Y;
}
function linBwd(X, W, dY, N, In, Out, dX, dW, db) {
  for (let v = 0; v < N; v++) for (let o = 0; o < Out; o++) {
    const g = dY[v * Out + o]; if (db) db[o] += g; const wo = o * In, xv = v * In;
    for (let i = 0; i < In; i++) { dW[wo + i] += g * X[xv + i]; if (dX) dX[xv + i] += W[wo + i] * g; }
  }
}
function gmeanFwd(H, N, dim) {
  const A = new Float64Array(N * dim);
  for (let v = 0; v < N; v++) { const ns = ADJ[v], nn = ns.length, av = v * dim;
    for (let j = 0; j < nn; j++) { const ub = ns[j] * dim; for (let i = 0; i < dim; i++) A[av + i] += H[ub + i]; }
    if (nn) for (let i = 0; i < dim; i++) A[av + i] /= nn; }
  return A;
}
function gmeanBwd(dA, N, dim, dH) {
  for (let v = 0; v < N; v++) { const ns = ADJ[v], nn = ns.length, av = v * dim; if (!nn) continue;
    for (let j = 0; j < nn; j++) { const ub = ns[j] * dim; for (let i = 0; i < dim; i++) dH[ub + i] += dA[av + i] / nn; } }
}
const relu = (X) => { const Y = new Float64Array(X.length); for (let i = 0; i < X.length; i++) Y[i] = X[i] > 0 ? X[i] : 0; return Y; };

function zerosLike(W) {
  const g = { inW: new Float64Array(W.inW.length), inB: new Float64Array(W.inB.length),
    layers: W.layers.map(L => ({ selfW: new Float64Array(L.selfW.length), nbW: new Float64Array(L.nbW.length), b: new Float64Array(L.b.length) })),
    polW: new Float64Array(W.polW.length), polB: 0, valW1: new Float64Array(W.valW1.length), valB1: new Float64Array(W.valB1.length),
    valW2: new Float64Array(W.valW2.length), valB2: 0 };
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
  // ---- policy loss over legal empties ----
  const legal = []; for (let v = 0; v < NP; v++) if (color[v] === 0) legal.push(v);
  let mx = -1e18; for (const v of legal) if (polLogit[v] > mx) mx = polLogit[v];
  let Z = 0; const p = {}; for (const v of legal) { const e = Math.exp(polLogit[v] - mx); p[v] = e; Z += e; }
  for (const v of legal) p[v] /= Z;
  // sharpen the (noisy, low-sim) MC visit target: tgt_i ∝ visits_i^SHARP, concentrating on top moves
  const SHARP = 2.0, raw = {}; for (const [id, n] of rec.pi) raw[id] = (raw[id] || 0) + n;
  let tot = 0; const tgt = {};
  for (const id in raw) { const w = Math.pow(raw[id], SHARP); tgt[id] = w; tot += w; }
  for (const id in tgt) tgt[id] /= tot;
  let polLoss = 0; for (const v of legal) { const t = tgt[v] || 0; if (t > 0) polLoss -= t * Math.log(p[v] + 1e-12); }
  const valLoss = (val - rec.z) * (val - rec.z);
  // ---- backward ----
  const dPol = new Float64Array(NP);                                    // grad wrt polLogit
  for (const v of legal) dPol[v] = p[v] - (tgt[v] || 0);
  // value
  const dval = 2 * cval * (val - rec.z), dvopre = dval * (1 - val * val);
  const dvhid = new Float64Array(Hv);
  linBwd(vhid, W.valW2, [dvopre], 1, Hv, 1, dvhid, grad.valW2, { get 0() { return 0; }, set 0(x) { grad.valB2 += x; } });
  for (let i = 0; i < Hv; i++) if (vpre[i] <= 0) dvhid[i] = 0;
  const dpooled = new Float64Array(H);
  linBwd(pooled, W.valW1, dvhid, 1, H, Hv, dpooled, grad.valW1, grad.valB1);
  // policy head: dY = dPol (Out=1)
  const dhK = new Float64Array(NP * H);
  const polBbox = { get 0() { return 0; }, set 0(x) { grad.polB += x; } };
  linBwd(hK, W.polW, dPol, NP, H, 1, dhK, grad.polW, polBbox);
  // pooling backward
  for (let v = 0; v < NP; v++) for (let i = 0; i < H; i++) dhK[v * H + i] += dpooled[i] / NP;
  // conv layers backward
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
  return [polLoss + cval * valLoss, polLoss, valLoss];
}

// ---- gradient check ----
function gradCheck() {
  GO.setBoard("tri", "s"); board = GO.board(); NP = board.size; ADJ = board.adj; BD = board.bd;
  const W = NET.randomWeights(F, 4, 2, 3);
  // one synthetic record
  let s = GO.initial(); for (const m of [10, 12, 20]) s = GO.play(s, m);
  const rec = { c: Array.from(s.color).join(""), turn: s.turn, ko: s.ko,
    pi: [[15, 30], [22, 10], [8, 5]], z: 1 };
  const grad = zerosLike(W); lossGrad(rec, W, grad, 1.0);
  const eps = 1e-4;
  const targets = [["inW", 3], ["polW", 1], ["valW1", 2], ["valW2", 0], ["inB", 0]];
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
}

function train() {
  const dataFile = process.argv[3] || "net/data.jsonl";
  const outFile = process.argv[4] || "docs/hexago-weights.json";
  const epochs = +(process.argv[5] || 8), H = +(process.argv[6] || 32), K = +(process.argv[7] || 3), Hv = 16;
  const lr = +(process.argv[8] || 0.05), cval = 1.0, batch = 32;
  const data = fs.readFileSync(dataFile, "utf8").trim().split("\n").map(JSON.parse);
  console.log(`data ${data.length} positions | net H${H} K${K} | epochs ${epochs} lr ${lr}`);
  const W = NET.randomWeights(F, H, K, Hv), V = zerosLike(W), mu = 0.9;
  for (let ep = 0; ep < epochs; ep++) {
    for (let i = data.length - 1; i > 0; i--) { const j = (Math.random() * (i + 1)) | 0; const t = data[i]; data[i] = data[j]; data[j] = t; }
    const elr = lr * (1 - 0.5 * ep / epochs);   // gentle lr decay
    let L = 0, PL = 0, VL = 0, cnt = 0;
    for (let b = 0; b < data.length; b += batch) {
      const grad = zerosLike(W); let n = 0;
      for (let i = b; i < Math.min(b + batch, data.length); i++) { const [l, pl, vl] = lossGrad(data[i], W, grad, cval); L += l; PL += pl; VL += vl; n++; cnt++; }
      applyGrad(W, grad, V, elr, mu, n);
    }
    console.log(`epoch ${ep + 1}/${epochs}  loss ${(L / cnt).toFixed(4)}  pol ${(PL / cnt).toFixed(4)}  val ${(VL / cnt).toFixed(4)}`);
  }
  // serialize (plain arrays)
  const outW = { F, H, K, Hv, inW: Array.from(W.inW), inB: Array.from(W.inB),
    layers: W.layers.map(L => ({ selfW: Array.from(L.selfW), nbW: Array.from(L.nbW), b: Array.from(L.b) })),
    polW: Array.from(W.polW), polB: W.polB, passW: Array.from(W.passW), passB: W.passB,
    valW1: Array.from(W.valW1), valB1: Array.from(W.valB1), valW2: Array.from(W.valW2), valB2: W.valB2,
    board: BOARD_TYPE + "/" + BOARD_SIZE };
  fs.writeFileSync(outFile, JSON.stringify(outW));
  console.log(`saved -> ${outFile} (${(JSON.stringify(outW).length / 1024).toFixed(0)} KB)`);
}

if (process.argv[2] === "--gradcheck") gradCheck();
else train();
