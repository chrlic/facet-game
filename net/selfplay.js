// Phase-B self-play: BOTH sides play net-PUCT (net priors + rollout leaf value) with root noise +
// temperature sampling for diversity. Records (state, root visit distribution pi, outcome z). Runnable
// in parallel (each process appends to its own file). Usage:
//   node net/selfplay.js <weights> <nGames> <sims> <outFile> [board] [size] [tempMoves]
const fs = require("fs");
const GO = require("../docs/hexago_engine.js");
const NET = require("../docs/hexago_net.js");

const wfile = process.argv[2] || "docs/hexago-weights.json";
const nGames = +(process.argv[3] || 20);
const sims = +(process.argv[4] || 60);
const outFile = process.argv[5] || "net/sp.jsonl";
// argv[6] = board list "tri/m,tri/s,elong/s" (rotated per game) OR just "tri" with argv[7]=size (legacy)
const boardsArg = process.argv[6] || "tri/m";
const boards = boardsArg.includes("/")
  ? boardsArg.split(",").map(b => b.split("/"))
  : [[boardsArg, process.argv[7] || "m"]];
const tempMoves = +(process.argv[8] || 18);
// argv[9] = max symmetries per position (data augmentation). Default: use ALL of the board's
// symmetries (12 on tri, 1 on elong). Set a smaller number to cap training-set blow-up; identity is
// always kept and the rest are sampled. See docs/hexago_engine.js symmetries() for the theory.
const maxSyms = +(process.argv[9] || 99);
NET.setWeights(JSON.parse(fs.readFileSync(wfile, "utf8")));

// Rewrite one record under a symmetry permutation P (P[i] = point that i maps to). A rotated/mirrored
// board is the SAME position to the net, so this is a correct, label-preserving copy: stones, the ko
// point, and every move in the policy target pi all move to their image; turn and outcome are unchanged.
function applySym(rec, P) {
  const n = P.length, c = new Array(n);
  for (let i = 0; i < n; i++) c[P[i]] = rec.c[i];               // stone at i now sits at P[i]
  const ko = (typeof rec.ko === "number" && rec.ko >= 0 && rec.ko < n) ? P[rec.ko] : rec.ko;
  const pi = rec.pi.map(([id, v]) => [P[id], v]);               // each visited move maps to its image
  return { c: c.join(""), turn: rec.turn, ko: ko, pi: pi };
}

// Pick which symmetries to emit for this board: identity (index 0) always, plus up to maxSyms-1 more.
function chooseSyms(syms) {
  if (syms.length <= maxSyms) return syms;
  const rest = syms.slice(1);
  for (let i = rest.length - 1; i > 0; i--) { const j = (Math.random() * (i + 1)) | 0; const t = rest[i]; rest[i] = rest[j]; rest[j] = t; }
  return [syms[0]].concat(rest.slice(0, maxSyms - 1));
}

function sample(dist, temp) {           // sample id ∝ visits^(1/temp)
  let tot = 0; const w = dist.map(([, n]) => { const x = Math.pow(n, 1 / temp); tot += x; return x; });
  let r = Math.random() * tot, acc = 0;
  for (let i = 0; i < dist.length; i++) { acc += w[i]; if (r <= acc) return dist[i][0]; }
  return dist[dist.length - 1][0];
}

let totalPos = 0;
for (let g = 0; g < nGames; g++) {
  const [bt, bsz] = boards[g % boards.length];          // rotate boards (multi-board self-play)
  GO.setBoard(bt, bsz);
  const NP = GO.board().size, maxM = 3 * NP, bkey = bt + "/" + bsz;
  let s = GO.initial(); const recs = []; let mv = 0;
  while (mv < maxM) {
    const m = NET.netPuct(s, 0, { sims: sims, rollout: true, noise: 0.25, k: 24 });
    if (m.pass || !m.dist || !m.dist.length) { s = GO.pass(s); if (GO.status(s).over) break; mv++; continue; }
    recs.push({ c: Array.from(s.color).join(""), turn: s.turn, ko: s.ko, pi: m.dist });
    const id = mv < tempMoves ? sample(m.dist, 1.0) : m.id;
    s = GO.play(s, id);
    if (GO.status(s).over) break;
    mv++;
  }
  const w = GO.scoreArea(s, 160).winner;
  const syms = chooseSyms(GO.symmetries());       // symmetry views of THIS board (set above via setBoard)
  let buf = "", nWritten = 0;
  for (const r of recs) {
    const z = w === "draw" ? 0 : (((w === "black" ? 1 : 2) === r.turn) ? 1 : -1);
    for (const P of syms) {                        // emit the position once per symmetry (free extra data)
      const a = applySym(r, P);
      buf += JSON.stringify({ c: a.c, turn: a.turn, ko: a.ko, pi: a.pi, z, board: bkey }) + "\n";
      nWritten++;
    }
  }
  fs.appendFileSync(outFile, buf);
  totalPos += nWritten;
  process.stderr.write(`[${outFile}] game ${g + 1}/${nGames} ${bkey} moves ${mv} winner ${w} x${syms.length}sym +${nWritten} (tot ${totalPos})\n`);
}
process.stderr.write(`DONE ${outFile}: ${totalPos} positions\n`);
