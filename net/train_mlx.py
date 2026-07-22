"""Phase-C GPU trainer (MLX, Apple Silicon). Trains the SAME graph net as docs/hexago_net.js and
exports the SAME JSON weight format, so a GPU-trained net drops straight into the browser + server
inference. Supports a moderately larger net (H/K args) and multi-board data (records may carry a
"board" field; batches are per-board so each uses its own adjacency). Loss = masked policy
cross-entropy (target = MC/self-play visit dist) + value MSE.

Usage:
  python net/train_mlx.py --data <jsonl> --out <weights.json> [--epochs 8] [--H 48] [--K 3]
                          [--board tri] [--size m] [--lr 2e-3] [--warm <weights.json>] [--parity]
"""
import argparse
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root (hexago_engine.py)

import mlx.core as mx
import mlx.optimizers as optim

import hexago_engine as H

F = 7  # feature planes (must match hexago_net.js / .py)
COWN, CSC = 0.15, 0.15  # auxiliary-head loss weights (ownership, score) — must match net/train.js


def board_tensors(btype, bsize):
    """Return (A_norm [NP,NP] row-normalised adjacency, BD list, NP) for a board."""
    H.set_board(btype, bsize)
    NP, ADJ, BD = H.NP, H.ADJ, H.BD
    A = [[0.0] * NP for _ in range(NP)]
    for v in range(NP):
        d = len(ADJ[v])
        if d:
            for u in ADJ[v]:
                A[v][u] = 1.0 / d
    return mx.array(A), list(BD), NP, ADJ


def atari_mask(col, adj, NP):
    mask = [0] * NP
    seen = [False] * NP
    for i in range(NP):
        if col[i] == 0 or seen[i]:
            continue
        c = col[i]
        stack = [i]
        grp = []
        libs = set()
        seen[i] = True
        while stack:
            v = stack.pop()
            grp.append(v)
            for u in adj[v]:
                if col[u] == 0:
                    libs.add(u)
                elif col[u] == c and not seen[u]:
                    seen[u] = True
                    stack.append(u)
        if len(libs) == 1:
            for g in grp:
                mask[g] = 1
    return mask


def features(color, turn, ko, adj, bd, NP):
    opp = 3 - turn
    atari = atari_mask(color, adj, NP)
    f = [[0.0] * F for _ in range(NP)]
    for v in range(NP):
        c = color[v]
        f[v][0] = 1.0 if c == turn else 0.0
        f[v][1] = 1.0 if c == opp else 0.0
        f[v][2] = 1.0 if c == 0 else 0.0
        f[v][3] = min(bd[v], 4) / 4.0
        f[v][4] = 1.0 if v == ko else 0.0
        f[v][5] = 1.0 if (c == turn and atari[v]) else 0.0
        f[v][6] = 1.0 if (c == opp and atari[v]) else 0.0
    return f


def init_params(Hd, K, Hv, warm=None):
    def he(shape, fan):
        return mx.random.normal(shape) * math.sqrt(2.0 / fan)

    def aux_heads(w, Hd, Hv):
        # ownership (per-node tanh) + score (linear off pooled) heads. Load from `w` if present, else
        # initialise fresh — so we can warm-start a net that predates these heads and still learn them.
        if w and "ownW" in w:
            return {"ownW": mx.array(w["ownW"]), "ownB": mx.array([w["ownB"]]),
                    "scoreW1": mx.array(w["scoreW1"]).reshape(w["Hv"], w["H"]), "scoreB1": mx.array(w["scoreB1"]),
                    "scoreW2": mx.array(w["scoreW2"]), "scoreB2": mx.array([w["scoreB2"]])}
        return {"ownW": he((Hd,), Hd), "ownB": mx.zeros((1,)),
                "scoreW1": he((Hv, Hd), Hd), "scoreB1": mx.zeros((Hv,)), "scoreW2": he((Hv,), Hv), "scoreB2": mx.zeros((1,))}

    if warm:
        w = json.load(open(warm))
        p = {
            "inW": mx.array(w["inW"]).reshape(w["H"], w["F"]), "inB": mx.array(w["inB"]),
            "layers": [{"selfW": mx.array(L["selfW"]).reshape(w["H"], w["H"]),
                        "nbW": mx.array(L["nbW"]).reshape(w["H"], w["H"]), "b": mx.array(L["b"])} for L in w["layers"]],
            "polW": mx.array(w["polW"]), "polB": mx.array([w["polB"]]),
            "valW1": mx.array(w["valW1"]).reshape(w["Hv"], w["H"]), "valB1": mx.array(w["valB1"]),
            "valW2": mx.array(w["valW2"]), "valB2": mx.array([w["valB2"]]),
        }
        p.update(aux_heads(w, w["H"], w["Hv"]))
        return p, w["H"], w["K"], w["Hv"]

    p = {
        "inW": he((Hd, F), F), "inB": mx.zeros((Hd,)),
        "layers": [{"selfW": he((Hd, Hd), Hd), "nbW": he((Hd, Hd), Hd), "b": mx.zeros((Hd,))} for _ in range(K)],
        "polW": he((Hd,), Hd), "polB": mx.zeros((1,)),
        "valW1": he((Hv, Hd), Hd), "valB1": mx.zeros((Hv,)), "valW2": he((Hv,), Hv), "valB2": mx.zeros((1,)),
    }
    p.update(aux_heads(None, Hd, Hv))
    return p, Hd, K, Hv


def forward(p, feats, A):
    # feats [B,NP,F], A [NP,NP] -> policy_logits [B,NP], value [B], ownership [B,NP], score [B]
    h = mx.maximum(feats @ p["inW"].T + p["inB"], 0)
    for L in p["layers"]:
        agg = mx.matmul(A, h)                              # mean over neighbours (A is row-normalised)
        h = mx.maximum(h @ L["selfW"].T + agg @ L["nbW"].T + L["b"], 0)
    pooled = mx.mean(h, axis=1)                            # [B,H]
    policy = mx.matmul(h, p["polW"]) + p["polB"]           # [B,NP]
    vh = mx.maximum(pooled @ p["valW1"].T + p["valB1"], 0)
    value = mx.tanh(mx.matmul(vh, p["valW2"]) + p["valB2"][0])
    own = mx.tanh(mx.matmul(h, p["ownW"]) + p["ownB"][0])  # [B,NP] per-point ownership
    sh = mx.maximum(pooled @ p["scoreW1"].T + p["scoreB1"], 0)
    score = mx.matmul(sh, p["scoreW2"]) + p["scoreB2"][0]  # [B] linear final-margin estimate
    return policy, value, own, score


def loss_fn(p, feats, A, legal, tgt, z, own_t, sm, am):
    policy, value, own, score = forward(p, feats, A)
    masked = mx.where(legal > 0, policy, -1e9)
    logZ = mx.logsumexp(masked, axis=1, keepdims=True)
    logp = masked - logZ
    pol = -mx.sum(tgt * logp, axis=1)
    val = (value - z) ** 2
    own_l = mx.mean((own - own_t) ** 2, axis=1) * am       # ownership MSE (masked: 0 if record has no aux)
    sc_l = (score - sm) ** 2 * am
    return mx.mean(pol + val + COWN * own_l + CSC * sc_l)


def to_json(p, Hd, K, Hv, board):
    return {
        "F": F, "H": Hd, "K": K, "Hv": Hv,
        "inW": p["inW"].reshape(-1).tolist(), "inB": p["inB"].tolist(),
        "layers": [{"selfW": L["selfW"].reshape(-1).tolist(), "nbW": L["nbW"].reshape(-1).tolist(), "b": L["b"].tolist()} for L in p["layers"]],
        "polW": p["polW"].tolist(), "polB": float(p["polB"][0]),
        "passW": [0.0] * Hd, "passB": 0.0,                 # pass head untrained (handled by pass logic)
        "valW1": p["valW1"].reshape(-1).tolist(), "valB1": p["valB1"].tolist(),
        "valW2": p["valW2"].tolist(), "valB2": float(p["valB2"][0]),
        "ownW": p["ownW"].tolist(), "ownB": float(p["ownB"][0]),
        "scoreW1": p["scoreW1"].reshape(-1).tolist(), "scoreB1": p["scoreB1"].tolist(),
        "scoreW2": p["scoreW2"].tolist(), "scoreB2": float(p["scoreB2"][0]), "board": board,
    }


def load_board_data(records, btype, bsize):
    A, BD, NP, ADJ = board_tensors(btype, bsize)
    feats, legal, tgt, z, own_t, sm, am = [], [], [], [], [], [], []
    for r in records:
        col = [ord(ch) - 48 for ch in r["c"]]
        feats.append(features(col, r["turn"], r["ko"], ADJ, BD, NP))
        lg = [1.0 if col[v] == 0 else 0.0 for v in range(NP)]
        t = [0.0] * NP
        raw = {}
        for idx, n in r["pi"]:
            raw[idx] = raw.get(idx, 0) + n
        tot = sum(v ** 2 for v in raw.values()) or 1.0      # sharpen^2 (matches JS trainer)
        for idx, v in raw.items():
            t[idx] = (v ** 2) / tot
        legal.append(lg); tgt.append(t); z.append(float(r["z"]))
        # aux targets: ownership per point (+1 mine / -1 theirs / 0 neutral) and normalised score margin.
        # am (aux mask) is 1 when the record carries them, 0 otherwise -> old data trains policy+value only.
        if "own" in r:
            own_t.append([1.0 if ch == "1" else -1.0 if ch == "2" else 0.0 for ch in r["own"]])
            sm.append(float(r.get("sm", 0.0))); am.append(1.0)
        else:
            own_t.append([0.0] * NP); sm.append(0.0); am.append(0.0)
    return (A, mx.array(feats), mx.array(legal), mx.array(tgt), mx.array(z),
            mx.array(own_t), mx.array(sm), mx.array(am), NP)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="net/data.jsonl")
    ap.add_argument("--out", default="net/mlx-weights.json")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--H", type=int, default=48)
    ap.add_argument("--K", type=int, default=3)
    ap.add_argument("--Hv", type=int, default=16)
    ap.add_argument("--board", default="tri")
    ap.add_argument("--size", default="m")
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--warm", default=None)
    ap.add_argument("--parity", action="store_true")
    a = ap.parse_args()

    data = [json.loads(l) for l in open(a.data) if l.strip()]
    # group by board (records may carry "board":"tri/m"); default to --board/--size
    groups = {}
    for r in data:
        key = r.get("board", f"{a.board}/{a.size}")
        groups.setdefault(key, []).append(r)
    print(f"data {len(data)} positions across boards: {{" + ", ".join(f'{k}:{len(v)}' for k, v in groups.items()) + "}}")

    params, Hd, K, Hv = init_params(a.H, a.K, a.Hv, a.warm)
    boards = {}
    for key, recs in groups.items():
        bt, bs = key.split("/")
        boards[key] = load_board_data(recs, bt, bs)

    opt = optim.Adam(learning_rate=a.lr)
    vg = mx.value_and_grad(loss_fn)
    for ep in range(a.epochs):
        tot, nb = 0.0, 0
        for key, (A, feats, legal, tgt, z, own_t, sm, am, NP) in boards.items():
            n = feats.shape[0]
            idx = list(range(n)); random.shuffle(idx)
            for b in range(0, n, a.batch):
                sl = idx[b:b + a.batch]
                bf, bl, bt2, bz = feats[sl], legal[sl], tgt[sl], z[sl]
                bo, bsm, bam = own_t[sl], sm[sl], am[sl]
                loss, grads = vg(params, bf, A, bl, bt2, bz, bo, bsm, bam)
                opt.update(params, grads)
                mx.eval(params, opt.state)
                tot += float(loss); nb += 1
        print(f"epoch {ep+1}/{a.epochs}  loss {tot/max(nb,1):.4f}")

    key0 = next(iter(groups))
    outw = to_json(params, Hd, K, Hv, key0)
    json.dump(outw, open(a.out, "w"))
    print(f"saved -> {a.out} (H{Hd} K{K}, {len(json.dumps(outw))//1024} KB)")

    if a.parity:
        # MLX forward vs the exported-JSON pure-Python forward on one position -> must match
        import hexago_net as N
        N.set_weights(outw)
        bt, bs = key0.split("/")
        A, BD, NP, ADJ = board_tensors(bt, bs)
        s = H.initial()
        for m in [63, 64, 40, 50, 30]:
            s = H.play(s, m)
        f = mx.array([features(s["color"], s["turn"], s["ko"], ADJ, BD, NP)])
        pol_mlx, val_mlx, _own, _sc = forward(params, f, A)
        pol_py, _pl, val_py = N.forward(s, ADJ, BD, NP)
        dpol = max(abs(float(pol_mlx[0][i]) - pol_py[i]) for i in range(NP))
        print(f"PARITY MLX-vs-exported-Python: value {float(val_mlx[0]):.6f} vs {val_py:.6f} | max policy diff {dpol:.2e}",
              "OK" if dpol < 1e-3 else "MISMATCH")


if __name__ == "__main__":
    main()
