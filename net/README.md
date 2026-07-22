# HEXA-GO neural AI — how the training works (a guided tour)

This folder trains the Go-playing neural net used by HEXA-GO. It's a small, from-scratch
**AlphaZero-style** pipeline, written in plain JavaScript + Python (no PyTorch/TF at *runtime*), so
every piece is readable end to end. This document explains the ideas and points you at the exact
files/functions. Read it top to bottom; then read the code in the "Reading order" section.

> **The one-sentence summary:** a neural net *guesses* good moves and who's winning; a tree search
> *checks* those guesses by looking ahead; the net then *trains itself* to imitate the (smarter)
> search; repeat. Each turn of that loop makes both the net and the search a little stronger.

---

## 1. The three ingredients of AlphaZero

Every AlphaZero-like system has exactly three parts. Hold these in your head — everything else is detail.

1. **A network** `f(position) → (policy, value)`
   - **policy**: a probability over moves — "which moves look good here?"
   - **value**: a number in [−1, +1] — "who is winning, from the side-to-move's view?"
   - Ours is a **graph neural network** (§3). File: `docs/hexago_net.js` (JS) / `hexago_net.py` (Python).

2. **A search** that *uses* the net to look ahead: **MCTS with PUCT** (§4).
   - The net's policy tells the search where to look first; the net's value (or a random playout)
     tells it how good a leaf is. The search returns a *better* policy than the raw net — because it
     actually read a few moves ahead. File: `docs/hexago_net.js` → `netPuct`.

3. **Self-play + training** that closes the loop (§5, §6):
   - Let the net (wrapped in search) **play itself**. For every position, record what the *search*
     decided (its move-visit counts = an improved policy π) and, at game end, who won (z).
   - **Train** the net so its policy → π and its value → z. Now the raw net is a bit closer to the
     search's judgment, so next round's search (starting from a better net) is stronger still.
   - Files: `net/selfplay.js` (generate), `net/train.js` / `net/train_mlx.py` (train), `net/phasec.sh`
     (the loop).

That's it. The "magic" is that **search improves the policy for free** (looking ahead beats guessing),
and training distills that improvement back into the net, so the improvement compounds.

---

## 2. Why this project has two "phases"

Starting the loop from a *random* net is slow — early self-play is near-random, so the data is weak.
We bootstrapped instead:

- **Phase A — imitation** (`net/gen_data.js`): first generate data by watching the *old hand-written
  Monte-Carlo AI* play, and train the net to copy it. This gives a net that's ≈ as good as that AI but
  runs in <1 ms — a warm start. (It is *not* strong enough to beat the MC engine on its own; imitation
  can't exceed its teacher.)
- **Phase B / C — self-play RL** (`net/phaseb.sh`, `net/phasec.sh`): the real AlphaZero loop from §1,
  which *surpasses* the teacher because the search keeps finding better moves than the current net.

The big practical lesson we learned (see §7): **the search must be at least as strong as the thing you
want to beat**, or self-play just teaches the net to be mediocre. RAVE (§4) was what made our search
strong enough.

---

## 3. The network — a graph neural net (GNN)

**Why a GNN and not a CNN?** A Go board is usually a grid, so people use convolutional nets. But
HEXA-GO's boards are *graphs* — triangular (6 neighbours per point) and elongated (5 neighbours)
lattices, at several sizes. A CNN assumes a fixed grid; a GNN works on *any* graph. Better still, with
**shared weights** one net plays every board type and size — which is exactly how we later trained a
single net on all six boards at once.

**Architecture** (see `features()` and `forward()` in `docs/hexago_net.js`):

```
input:  per board-point, 7 numbers from the side-to-move's view:
        [is_mine, is_theirs, is_empty, line(edge-distance), is_ko, my_atari, their_atari]

body:   h = ReLU(W_in · features + b_in)                    # project 7 → H (e.g. 64) per point
        repeat K times:                                     # "message passing"
            neigh = average of h over each point's neighbours
            h     = ReLU(W_self · h + W_nb · neigh + b)      # mix a point with its neighbourhood

heads:  policy[point] = h[point] · W_pol + b_pol            # one score per point → softmax over legal
        value        = tanh( pooled(h) · W_val … )          # one number in [-1,1]
        ownership[pt]= tanh( h[point] · W_own + b_own )     # AUX: who ends up owning this point
        score        = pooled(h) · W_score …  (linear)      # AUX: final margin (mover POV)
```

**Auxiliary heads (ownership + score)** are the two extra outputs above. They are *not* used to pick
moves — the search only reads `policy` and `value`. Their job is to **shape the shared body** during
training. A small value head, learning only from a single win/lose bit per game, tends to understand
*local* fights (which it can see within the search horizon) but not *whole-board* territory (which pays
off dozens of moves later). By also forcing the net to predict, for **every point, who finally owns it**
and the **final score margin**, we make the body learn a global sense of territory and influence — the
thing that separates "hunting" the opponent's stones from playing big points across the board. This is
KataGo's key idea, shrunk to our scale. Both heads are **optional**: nets trained without them (and the
pure-Python server) simply omit the weights and skip the computation, so it's fully backward-compatible.

The key operation is **message passing**: each round, every point looks at the *average* of its
neighbours and updates itself. After K rounds, a point "knows" about everything within K steps —
enough to sense liberties, shape, and eyes. Averaging over neighbours (rather than summing) is what
makes it work on any degree/size — that's the trick that lets one net handle 5- and 6-neighbour boards.

The net is deliberately **tiny** (~15k–26k weights, a few hundred KB of JSON). Real Go nets have
*millions*. We kept it small so it can be hand-evaluated in the browser (no libraries) and in pure
Python on the server — fast enough to call at every node of the search.

---

## 4. The search — MCTS with PUCT (and RAVE)

**Monte-Carlo Tree Search (MCTS)** builds a search tree one simulation at a time. Each simulation:

1. **Select**: from the root, walk down the tree, at each node picking the child that maximises **PUCT**:

   ```
   U(move) = Q(move)  +  c · P(move) · √(N_parent) / (1 + N(move))
             ^exploit    ^--------- explore ---------^
   ```
   - `Q` = average result seen through that move so far (exploit what's working).
   - `P` = the **net's policy prior** for that move (trust the net about where to look).
   - `N` = visit counts; the √N/(1+n) term makes under-explored, high-prior moves attractive.
   - `c` = a constant balancing the two. This formula is the heart of AlphaZero's search.

2. **Expand & evaluate** the leaf you reach: ask the net for its policy (to create the children's
   priors) and a **value** for the leaf. *Or* run a **rollout** — play the game out with a fast policy
   and see who wins. (We use rollouts; see below.)

3. **Backup**: send that result back up the path, updating every `Q` and `N`.

After a fixed budget of simulations, the move actually chosen is the **most-visited** child (robust),
and the *visit distribution* over root moves is the improved policy π we train on. See `simulateRave()`
and `netPuct()` in `docs/hexago_net.js`.

**RAVE (Rapid Action Value Estimation)** — *the single most important trick here.* Plain net-PUCT with
our small net *lost* to the old MC engine (weak priors + few simulations). RAVE fixes the "few
simulations" problem: after a simulation, it credits **every** move that appeared *anywhere* in that
line, not just the one move at each node ("all-moves-as-first"). So one simulation updates *many*
moves' statistics — the search learns far faster from the same compute. Adding RAVE flipped net-PUCT
from *losing* to *beating* the MC engine. (`simulateRave` blends the normal `Q` with the RAVE average
`Q_amaf` using a `beta` that trusts RAVE early and real stats late.)

**Leaf evaluation: rollout vs. value head.** Two ways to score a leaf:
- **rollout** — play a fast semi-random game to the end (reliable, but CPU-only). `GO.rolloutFirst()`.
- **value head** — just ask the net (fast, GPU-batchable, but only as good as the trained value).
We used *rollouts* for self-play (reliable) and later confirmed the value head became strong enough to
use alone (the gate test in Phase C) — that's what would let self-play run on the GPU.

**Life-and-death pruning.** Two Go-specific speedups in `makeNode`/`netPuct`: don't fill your own
already-alive (two-eyed) territory or the opponent's, and pass when only such "settled" moves remain.
"Settled" is computed with **Benson's algorithm** (`settledMask` in `docs/hexago_engine.js`), which
provably identifies unconditionally-alive groups. This stops end-game busywork.

---

## 5. Self-play — making the training data (`net/selfplay.js`)

One self-play game, in pseudocode:

```
state = empty board (rotated among the 6 boards for multi-board training)
while not game over:
    result = netPuct(state, sims, exploration_noise)   # search this position
    record( state, result.visit_distribution )         # π = the training target for policy
    move = (early game) sample ∝ visits^(1/temperature) # explore: don't always play the top move
           (late  game) the most-visited move
    state = play(state, move)
winner = score(final board)
for every recorded position:  z = +1 if that side won, -1 if lost   # training target for value
write each (board, position, π, z) as one JSON line
```

Two details that matter:
- **Temperature sampling + root noise** early in the game → games diverge instead of repeating, so the
  net sees variety. Without exploration, self-play collapses to the same game every time.
- **π is the *search's* visit distribution, not the net's raw policy.** That's the whole point — the
  target is *better* than the current net, so training makes progress.

Each record also carries its `board` tag, so one data file can mix all six boards.

### Symmetry data augmentation (free extra data)

A Go position and its mirror image (or a 60° rotation, on the hexagonal board) are the *same*
position — the best move just moves with it. So every recorded position can be emitted several times,
once per board symmetry, and each copy is a correct, fully-labelled training example we got for free.

`docs/hexago_engine.js`'s `symmetries()` **discovers** these automatically: it takes every rigid
motion about the board's centre (rotations by multiples of 30°, with and without a flip) and keeps the
ones that map the point set exactly onto itself — i.e. the board's *graph automorphisms*. The hexagon
(`tri`) has the full **12** (the dihedral group D6: 6 rotations × 2 mirrors); the elongated strip
(`elong`) has none beyond the identity, because its alternating row offset isn't symmetric.

`selfplay.js` then rewrites each record under each symmetry `P` (a permutation of point indices):
stones, the ko point, and every move in the policy target `π` all move to their image — `turn` and `z`
are unchanged. On `tri` this multiplies the data **~12×**. Two reasons it's worth it:
- **More data, no more games.** Self-play (the MCTS) is the expensive part; augmentation is nearly free.
- **It's a regularizer.** The net is *told* that orientation doesn't matter, so it can't waste capacity
  memorising board-specific quirks — it must learn orientation-independent shape judgment. This is the
  same trick AlphaGo used, and it's exactly what a small net needs to spend its parameters wisely.

Because the GNN only reads adjacency, it is already equivariant to these relabelings: feeding it `P`
of a position yields `P` of the output, to float precision. That's what makes the augmented labels
*exact* rather than approximate. (`argv[9]` caps symmetries per position if you want to bound the
training-set size; the identity is always kept.)

---

## 6. Training — turning data into weights (`net/train.js`, `net/train_mlx.py`)

The loss adds four terms — the two main ones plus the two auxiliary heads (§3):

```
loss =  cross_entropy(net_policy, π)      # make the policy match the search's visit distribution
      +        (net_value − z)²           # make the value predict the game outcome
      + 0.15 · mean_pt (own_pt − t_pt)²   # AUX: predict who finally owns each point
      + 0.15 ·      (net_score − m)²      # AUX: predict the final score margin
```

- **Cross-entropy** pushes probability mass onto the moves the search preferred.
- **MSE** on the value teaches "am I winning?" from the eventual result.
- **Ownership + score** (weighted 0.15 each, so they guide but don't dominate) teach *whole-board*
  understanding. The targets come straight from the final `scoreArea`: `t_pt ∈ {+1 mine, −1 theirs,
  0 neutral}` per point, and `m` = final margin ÷ board-size (mover POV). Predicting them forces the
  body to model territory globally — see §3 for *why* that fixes contact-only ("hunting") play.
  The heads are trained only when a record carries the targets (self-play adds them; older data trains
  policy+value only), and `net2net` widening preserves them exactly like the other heads.

**`net/train.js` is the teaching version:** it implements the network's forward pass *and its
backpropagation by hand* — every gradient is written out explicitly, and a **finite-difference gradient
check** proves the math is right (`node net/train.js --gradcheck`). If you want to understand how
neural-net training actually works under the hood, read this file — nothing is hidden in a framework.
It uses plain **SGD with momentum**.

**`net/train_mlx.py` is the fast version:** the *same* network in Apple's **MLX** framework, which runs
on the Mac GPU and does the backprop for you (autodiff) with the Adam optimiser. It exports the **exact
same JSON weight format**, and a parity check confirms MLX and the hand-written forward agree to ~1e-6
— so a GPU-trained net drops straight into the browser/server unchanged. Multi-board data is grouped by
board (each batch is one board, so the adjacency matrix is fixed within a batch).

---

## 7. The loop, and the lessons (`net/phaseb.sh`, `net/phasec.sh`)

The orchestrator just runs §5 → §6 over and over:

```
current = starting net
repeat:
    self-play N games with `current`  →  data          (3 CPU workers in parallel)
    train (warm-started from `current`) on recent data →  candidate   (GPU in Phase C)
    current = candidate                                 ("always-promote")
    every few iters: probe `current` vs the MC engine to track strength
```

Hard-won lessons baked into the code and comments:

- **RAVE is essential** at small simulation budgets (§4). Without it, self-play never exceeds the
  teacher.
- **Search ≥ target.** Self-play data is only useful if the searcher is stronger than what you're
  trying to beat; otherwise you distil mediocrity.
- **Net2net "widening"** (`net/widen.py`): to make the net *moderately bigger* (H48→H64) without
  throwing away a good net, we copy the small net into a bigger one such that it computes the *exact*
  same function at first (verified diff = 0), then let training use the new capacity. No regression risk.
- **Multi-board is almost free** thanks to the shared-weight GNN — just rotate the board in self-play
  and group by board in training. One net ended up strong on all sizes *and* both adjacency types.
- **Always-promote can drift.** In the 8-hour run the net actually *peaked at iteration 16* and wobbled
  afterwards. We picked the best checkpoint by round-robin (`net/duel.js`) rather than trusting the
  last one. Next time: add **gating** (only promote a candidate that beats the current net).

---

## 8. Evaluation (`net/duel.js`, `net/eval.js`)

`duel.js` plays two players a fixed number of games and reports the win-rate **and average score
margin** (margin keeps discriminating even when the win-rate saturates at 100%). A "player" is either a
weights file (→ net-PUCT) or `"MC"` (the old engine). We used it three ways: net-vs-MC (is it strong?),
net-vs-earlier-net (is it still improving?), and net-vs-champion on every board (is it worth deploying?).

---

## 9. Reading order

1. **`net/README.md`** — this file (the concepts).
2. **`docs/hexago_net.js`** — `features` + `forward` (the network), then `makeNode` + `simulateRave` +
   `netPuct` (the search). The heart of everything.
3. **`net/train.js`** — the hand-written trainer with explicit backprop + gradient check. Best place to
   learn *how training works*. (Heavily commented.)
4. **`net/selfplay.js`** — how a game becomes training data.
5. **`net/train_mlx.py`** — the same net + loss in a GPU framework (compare with #3).
6. **`net/phasec.sh`** — the loop that ties it all together; **`net/widen.py`**, **`net/duel.js`** —
   the supporting tools.
7. **`hexago_net.py`** — the pure-Python mirror of the net (server inference), kept bit-for-bit in sync
   with the JS.

## 10. Where to read more (the real papers)

- **AlphaGo Zero** (Silver et al., 2017) and **AlphaZero** (2018) — the policy+value net + MCTS
  self-play loop this project miniaturises.
- **RAVE / MoGo** (Gelly & Silver, 2007–2011) — the all-moves-as-first idea that made our small-budget
  search strong.
- **PUCT** — the selection formula (a variant of UCT with a policy prior).
- **Benson's algorithm** (1976) — unconditional life in Go, used for the settled-territory pruning.
- **Graph neural networks / message passing** (e.g. Kipf & Welling, 2017) — the network family.
- **Net2Net** (Chen et al., 2016) — function-preserving ways to grow a network (`widen.py`).

Everything here is a deliberately small, dependency-light take on those ideas — built so you can read
all of it in an afternoon.
