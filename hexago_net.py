"""HEXA-GO neural evaluator (server) — pure-Python forward pass of the tiny graph net, IDENTICAL to
docs/hexago_net.js. Loads the same weights JSON. The server picks a move from the policy head (one
forward pass ~ tens of ms in pure Python), which is a big jump over the greedy heuristic and fast
enough for turn-based play. Keep in sync with the JS version (parity-tested)."""
import json
import math
import os

_W = None


def load_weights(path=None):
    global _W
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "docs", "hexago-weights.json")
    if os.path.exists(path):
        with open(path) as f:
            _W = json.load(f)
    return _W is not None


def set_weights(w):
    global _W
    _W = w


def loaded():
    return _W is not None


def _relu(x):
    return x if x > 0 else 0.0


def _matvec(M, x, rows, cols, b):
    out = [0.0] * rows
    for r in range(rows):
        s = b[r] if b is not None else 0.0
        o = r * cols
        for c in range(cols):
            s += M[o + c] * x[c]
        out[r] = s
    return out


def _atari_mask(col, adj, NP):
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


def _features(state, adj, bd, NP):
    W = _W
    F = W["F"]
    me = state["turn"]
    opp = 3 - me
    col = state["color"]
    atari = _atari_mask(col, adj, NP)
    feat = [0.0] * (NP * F)
    for v in range(NP):
        b = v * F
        c = col[v]
        feat[b] = 1.0 if c == me else 0.0
        feat[b + 1] = 1.0 if c == opp else 0.0
        feat[b + 2] = 1.0 if c == 0 else 0.0
        feat[b + 3] = min(bd[v], 4) / 4.0
        feat[b + 4] = 1.0 if v == state["ko"] else 0.0
        feat[b + 5] = 1.0 if (c == me and atari[v]) else 0.0
        feat[b + 6] = 1.0 if (c == opp and atari[v]) else 0.0
    return feat


def forward(state, adj, bd, NP):
    """Return (policy list[NP], pass_logit, value). Mirrors hexago_net.js forward()."""
    W = _W
    F, H, K, Hv = W["F"], W["H"], W["K"], W["Hv"]
    feat = _features(state, adj, bd, NP)
    # input projection -> h (NP*H)
    h = [0.0] * (NP * H)
    for v in range(NP):
        fb = v * F
        row = _matvec(W["inW"], feat[fb:fb + F], H, F, W["inB"])
        vb = v * H
        for i in range(H):
            h[vb + i] = _relu(row[i])
    # K graph-conv layers
    for k in range(K):
        L = W["layers"][k]
        selfW, nbW, lb = L["selfW"], L["nbW"], L["b"]
        nh = [0.0] * (NP * H)
        for v in range(NP):
            ns = adj[v]
            nn = len(ns)
            agg = [0.0] * H
            for u in ns:
                ub = u * H
                for i in range(H):
                    agg[i] += h[ub + i]
            if nn:
                for i in range(H):
                    agg[i] /= nn
            vb = v * H
            hv = h[vb:vb + H]
            sv = _matvec(selfW, hv, H, H, None)
            nv = _matvec(nbW, agg, H, H, None)
            for i in range(H):
                nh[vb + i] = _relu(sv[i] + nv[i] + lb[i])
        h = nh
    # pooled
    pooled = [0.0] * H
    for v in range(NP):
        pb = v * H
        for i in range(H):
            pooled[i] += h[pb + i]
    for i in range(H):
        pooled[i] /= NP
    # policy + pass
    policy = [0.0] * NP
    polW, polB = W["polW"], W["polB"]
    for v in range(NP):
        s = polB
        hb = v * H
        for i in range(H):
            s += h[hb + i] * polW[i]
        policy[v] = s
    pass_logit = W["passB"]
    passW = W["passW"]
    for i in range(H):
        pass_logit += pooled[i] * passW[i]
    # value head
    vh = _matvec(W["valW1"], pooled, Hv, H, W["valB1"])
    for i in range(Hv):
        vh[i] = _relu(vh[i])
    vo = W["valB2"]
    for i in range(Hv):
        vo += vh[i] * W["valW2"][i]
    value = math.tanh(vo)
    return policy, pass_logit, value


def policy_probs(state, adj, bd, NP):
    """Softmax over legal empty points (+ pass). Returns (dict id->p, pass_p, value)."""
    policy, pass_logit, value = forward(state, adj, bd, NP)
    col = state["color"]
    ids = [v for v in range(NP) if col[v] == 0]
    mx = pass_logit
    for v in ids:
        if policy[v] > mx:
            mx = policy[v]
    probs = {}
    Z = 0.0
    for v in ids:
        e = math.exp(policy[v] - mx)
        probs[v] = e
        Z += e
    pass_p = math.exp(pass_logit - mx)
    Z += pass_p
    for v in list(probs):
        probs[v] /= Z
    pass_p /= Z
    return probs, pass_p, value
