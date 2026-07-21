"""Net2net widen a trained net to a larger hidden size H, IDENTITY-PRESERVING: the widened net computes
EXACTLY the same function as the source (new channels don't affect the heads), so it starts at the
source's strength and only gains capacity to learn. Keeps K, F, Hv. Usage:
  python net/widen.py <src.json> <out.json> <newH>
"""
import json
import math
import random
import sys


def he(n, fan):
    s = math.sqrt(2.0 / fan)
    return [(random.random() * 2 - 1) * s for _ in range(n)]


def widen(src, newH):
    F, oldH, K, Hv = src["F"], src["H"], src["K"], src["Hv"]
    assert newH >= oldH
    ext = newH - oldH

    def widen_rows(mat, rows_old, cols, new_rows):     # [rows_old,cols] -> [new_rows,cols]; new rows random
        out = []
        for r in range(new_rows):
            if r < rows_old:
                out += mat[r * cols:(r + 1) * cols]
            else:
                out += he(cols, cols)
        return out

    def widen_sq(mat, old, new):                       # [old,old] -> [new,new]. old->old block copied;
        out = [0.0] * (new * new)                       # old-out<-new-in = 0 (preserve old channels);
        for r in range(new):                            # new-out rows = random.
            for c in range(new):
                if r < old and c < old:
                    out[r * new + c] = mat[r * old + c]
                elif r < old and c >= old:
                    out[r * new + c] = 0.0
                else:
                    out[r * new + c] = (random.random() * 2 - 1) * math.sqrt(2.0 / new)
        return out

    def widen_vec(v, old, new, pad=0.0):               # [old] -> [new]
        return list(v) + [pad] * (new - old)

    w = {"F": F, "H": newH, "K": K, "Hv": Hv}
    w["inW"] = widen_rows(src["inW"], oldH, F, newH)   # [newH,F]; new input-proj rows active
    w["inB"] = widen_vec(src["inB"], oldH, newH, 0.0)
    w["layers"] = []
    for L in src["layers"]:
        w["layers"].append({
            "selfW": widen_sq(L["selfW"], oldH, newH),
            "nbW": widen_sq(L["nbW"], oldH, newH),
            "b": widen_vec(L["b"], oldH, newH, 0.0),
        })
    w["polW"] = widen_vec(src["polW"], oldH, newH, 0.0)  # new channels -> 0 weight -> don't affect policy
    w["polB"] = src["polB"]
    w["passW"] = [0.0] * newH
    w["passB"] = src.get("passB", 0.0)
    # valW1 is [Hv, oldH] row-major -> [Hv, newH]; pad each row's new columns with 0 (identity)
    vw1 = []
    for r in range(Hv):
        vw1 += list(src["valW1"][r * oldH:(r + 1) * oldH]) + [0.0] * ext
    w["valW1"] = vw1
    w["valB1"] = src["valB1"]
    w["valW2"] = src["valW2"]
    w["valB2"] = src["valB2"]
    w["board"] = src.get("board", "tri/m")
    return w


if __name__ == "__main__":
    src = json.load(open(sys.argv[1]))
    out = widen(src, int(sys.argv[3]))
    json.dump(out, open(sys.argv[2], "w"))
    print(f"widened H{src['H']} -> H{out['H']} (K{out['K']}) -> {sys.argv[2]}")
