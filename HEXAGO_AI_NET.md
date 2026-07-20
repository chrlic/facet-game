# HEXA-GO — Neural AI (Tier 2) scope

A small **policy + value network trained by self-play** (AlphaZero-lite) to replace random rollouts
as the position evaluator, run in-browser (JS) and on the server (numpy), with **PUCT** search on top.
This is the path to genuine Go strength; the current engines (flat-MC + RAVE offline, greedy online)
are casual by design.

## 1. Goal & success criteria
- **Primary:** an AI that clearly beats the current MC engine — target **≥ 70%** vs `aiMove` (RAVE-flat)
  at equal wall-clock, on the online board (`tri`/medium, 127 points).
- **Online == offline strength:** the same net powers both the JS client and the Python server, so the
  server AI stops being the weaker greedy policy.
- **Constraints kept:** no build step, no CDN/external libs (offline PWA + strict CSP) → inference is
  hand-written JS + numpy; weights ship as a self-contained JSON asset. JS/Python inference must match.

## 2. Why a net (bottleneck diagnosis)
This session's A/B experiments already localise the problem:
- RAVE beat flat-MC **14/14** → sample-efficiency matters.
- PUCT lost **1/14** → deeper tree search does *not* help here, because **the leaf evaluation (a random
  rollout) is too noisy**. PUCT only pays off with crisp leaf evals (a value net) or 10⁴+ sims.
- Shape patterns were a **wash**; territory sense fixed *visible* blunders but not raw strength.

⇒ The lever is **evaluation quality**, not the search algorithm. A learned value replaces the noisy
rollout; a learned policy replaces the hand-tuned priors. Then PUCT finally wins.

## 3. Architecture — a tiny graph net (GNN)
The boards are **graphs**, not grids (triangular deg-6 / elongated deg-5 lattices, sizes s/m/l), so a
standard CNN doesn't apply. A message-passing GNN with **shared weights** is the natural fit: one net
generalises across board type *and* size via the adjacency, and it's simple to hand-write in JS/numpy.

**Input** — per node `v`, from the side-to-move's perspective (so the net is colour-symmetric):
`[is_empty, is_mine, is_theirs, my_group_libs∈{1,2,3+} (3 planes), ko_here, line=min(BD,4)/4]` ≈ 8–10
features. (Reuse `BD` boundary-distance + `group()` liberties already in `hexago_engine`.)

**Body** — K≈4 graph-conv layers, hidden dim H≈48:
`h_v ← ReLU(W_self·h_v + W_nb·mean_{u∈adj(v)} h_u + b)` (mean-aggregation = size-robust).

**Heads:**
- **Policy:** per-node linear → move logit; a separate `pass` logit from mean-pooled features; softmax
  over legal moves only.
- **Value:** mean-pool → 1-hidden-layer MLP → `tanh` → v ∈ [−1,1] (win prob for side-to-move).

**Size:** ~4·(2·H·H) + input/heads ≈ **30–45k params** → JSON weights a few hundred KB (quantise to
int8 if needed). **Inference cost** on 127 nodes: ~4 layers × (127·H·H) ≈ ~5M mults ⇒ **< 5 ms** in JS,
similar in numpy — cheap enough to call at every PUCT node.

## 4. Inference (client + server, parity)
- `docs/hexago_net.js` — load `hexago-weights.json`; `netEval(state) → {policy: Float32[NP], pass, value}`.
  Pure loops over `ADJ`; no libs. Cached in `hxg-sw.js`.
- `hexago_net.py` — numpy forward pass, **same weights file**.
- **Parity test:** identical outputs (±1e-5) on a fixed set of positions, JS vs Python, before shipping.

## 5. Training pipeline
Run offline (Node or Python) on the maintainer's machine; ship only the resulting weights JSON.

**Phase A — bootstrap by imitation (cheap, ships first).** Generate N positions from self-play of the
*current* MC AI; label each with (a) the MC visit distribution as policy target π, (b) `scoreArea`
outcome z. Train the net to match (cross-entropy on π + MSE on z). Result: a net ≈ MC-AI strength but
**evaluated in <5 ms** — immediately usable as fast PUCT priors + value. No RL loop needed for this
step. *This alone is a meaningful, low-risk win and de-risks Phase B.*

**Phase B — self-play RL (the strength jump).** AlphaZero loop:
1. **Self-play:** each move = PUCT (≈100–300 sims) guided by the current net (priors = policy head,
   leaf value = value head, **no rollouts**). Record (state, π=visit counts, z=result).
2. **Train:** loss = CE(policy, π) + MSE(value, z) + small L2. Small net → training is fast; **self-play
   generation dominates** (parallelise across CPU cores).
3. **Gate:** new net replaces old only if it beats it **> 55%** over a match. Iterate.

**Compute reality (CPU-only):** self-play at ~100–300 sims/move on 127 nodes is the cost driver — plan
a **curriculum**: start on `tri`/small (91 nodes) to iterate fast, then transfer/fine-tune to medium.
Bootstrapping from the MC AI (Phase A) cuts the cold-start cost sharply. Expect several iterations of
"a few hundred self-play games → retrain → gate" per strength step.

## 6. Search integration (PUCT + net)
Revive the PUCT tree (removed this session) but evaluate leaves with the **net value** instead of a
rollout, and seed priors from the **net policy**:
`U = Q + c_puct · P_net · √N_parent / (1+n)`, leaf `V = netValue(leaf)`.
- Client: `aiMove` → net-PUCT off-thread in the worker.
- Server: net-PUCT with a small sim count — net inference is cheap in numpy, so this is **fast enough
  in Python** (unlike MC rollouts), finally giving the online AI real strength.

## 7. Milestones
1. **Net + inference (untrained):** `hexago_net.js` + `hexago_net.py`, parity + speed verified. (~1d)
2. **Data pipeline:** MC-labelled position generator + on-disk format. (~0.5d)
3. **Phase A imitation:** train → net matches MC AI; ship as fast priors/value. (~1d + train time)
4. **Net-PUCT integration** (client + server) + A/B vs MC AI. (~1d)
5. **Phase B self-play RL** + gating; iterate to the ≥70% target. (~2–4d impl + background compute)
6. **Deploy:** weights JSON, SW cache bump, both engines, memory + doc update.

## 8. Effort & compute
- Implementation: **~1–1.5 weeks**. Phase A + net-PUCT (a usable, stronger AI) reachable in **~3 days**.
- Compute: Phase A modest; **Phase B is the variable** — depends on CPU budget and target strength.

## 9. Risks & mitigations
| Risk | Mitigation |
|---|---|
| CPU self-play cost (biggest) | small net + low sims + `tri/small` curriculum + MC bootstrap + parallel self-play; cap iterations |
| Non-standard lattice — no pretrained nets/data | self-play generates all data (already the plan); GNN shares weights across board types/sizes |
| JS↔Python inference divergence | fixed-position parity test in CI-style check before ship |
| No build step / CSP (offline PWA) | hand-written GNN, weights as inline-able JSON; no TF.js/ONNX/CDN |
| Weights bloat the PWA | keep net ~40k params; int8-quantise; lazy-load (offline MC stays the fallback) |
| Overfit to `tri/medium` only | train across boards/sizes; mean-aggregation keeps it size-robust |
| Regression risk | net path behind a flag; MC engine stays as fallback + gating before default |

## 10. Open decisions (need your call)
1. **Scope:** Phase A only (imitation → fast, moderate gain) **or** Phase A+B (self-play → genuine
   strength, more compute)?
2. **Compute budget** for Phase B (hours? overnight? days? cores available?) — sets the strength target.
3. **Board coverage:** just the online `tri/medium`, or all boards/sizes?
4. **Inference:** confirm hand-written GNN (offline-safe, recommended) vs allowing a library.

## Recommendation
Ship **Phase A + net-PUCT** first (a real, low-risk improvement in ~3 days, no training loop), then
greenlight **Phase B** self-play as a compute-bounded follow-up to reach genuinely strong play — and,
because the same weights run server-side, it closes the online/offline strength gap at the same time.
