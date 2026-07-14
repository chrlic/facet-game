// HYPERSCALE (spatial) balance probe. Runs bots against the JS engine to check:
//  1) is power actually contested (demand > supply, shared central station)?
//  2) does contesting the centre beat turtling at your home station?
//  3) does the market bite (GPU run low, prices climb)?
// Usage: node sim_hyperscale.js [games]
const { HSBoard, HS_STATIONS } = require("./docs/hyperscale_engine.js");
const KEYS = Object.keys(HS_STATIONS);
const HQ = ["0,0", "8,8"];
const MAXS = 4;
function dist(a, b) {
  const ax = (x, y) => [x - ((y - (y & 1)) >> 1), y];
  const [x1, y1] = a.split(",").map(Number), [x2, y2] = b.split(",").map(Number);
  const [aq, ar] = ax(x1, y1), [bq, br] = ax(x2, y2);
  const dq = aq - bq, dr = ar - br; return (Math.abs(dq) + Math.abs(dr) + Math.abs(dq + dr)) >> 1;
}
function neigh(k) { const [x, y] = k.split(",").map(Number);
  const d = (y % 2 === 0) ? [[1,0],[-1,0],[0,1],[-1,1],[0,-1],[-1,-1]] : [[1,0],[-1,0],[1,1],[0,1],[1,-1],[0,-1]];
  return d.map(([dx, dy]) => [x + dx, y + dy]).filter(([a, b]) => a >= 0 && a < 9 && b >= 0 && b < 9).map(([a, b]) => a + "," + b); }

// parametrised bot: `allowed` = which station hexes it will build toward.
// Same capital-disciplined logic as the engine AI (fill DCs before building new,
// never build a DC you can't staff), restricted to `allowed` stations.
function bot(board, owner, allowed) {
  const cap = board.capital[owner], hq = HQ[owner];
  const rd = board._roadDist(owner), rr = new Set(Object.keys(rd));
  const { remaining } = board._allocate();
  const open = allowed.filter(s => remaining[s] > 0);
  const empties = [];
  for (let y = 0; y < 9; y++) for (let x = 0; x < 9; x++) { const k = x + "," + y; if (board._empty(k)) empties.push(k); }
  if (!empties.length) return { a: "pass" };
  const P = h => { const [x, y] = h.split(",").map(Number); return { x, y }; };
  const roadAdj = h => neigh(h).some(n => rr.has(n));
  const stAdjOpen = h => neigh(h).some(n => open.includes(n));
  const dcs = []; for (const h in board.pieces) if (board.pieces[h].owner === owner && board.pieces[h].kind === "dc") dcs.push(h);
  const comps = board._powerComponents(owner);
  const connPow = new Set();
  for (const comp of comps) if (board._hasStation(comp)) for (const h of comp) connPow.add(h);
  const room = h => board._reachableStations(owner, h).some(s => remaining[s] > 0);
  const grow = dcs.filter(h => rr.has(h) && connPow.has(h) && board.servers(h) < MAXS && room(h))
    .sort((a, b) => (rd[a] || 9) - (rd[b] || 9));

  const sc = board.serverCost();
  if (board.canBuyServer() && cap >= sc && grow.length) return { a: "install", ...P(grow[0]) };

  const spotVal = h => { let v = -99; for (const n of neigh(h)) if (open.includes(n)) v = Math.max(v, remaining[n] - dist(h, hq) * 0.3); return v; };
  if (!grow.length && cap >= 4) {
    const g = empties.filter(h => roadAdj(h) && stAdjOpen(h)).sort((a, b) => spotVal(b) - spotVal(a) || dist(a, hq) - dist(b, hq));
    if (g.length) return { a: "build", piece: "dc", ...P(g[0]) };
  }
  if (cap >= 1) {
    const oppHQ = HQ[1 - owner];
    const reaches = s => neigh(s).some(k => { const p = board.pieces[k]; return (p && p.owner === owner) || (board._empty(k) && roadAdj(k)); });
    const wanted = open.filter(s => !reaches(s) && dist(s, hq) <= dist(s, oppHQ));
    if (wanted.length) {
      const target = wanted.sort((a, b) => remaining[b] - remaining[a])[0];
      const c = empties.filter(roadAdj).sort((a, b) => dist(a, target) - dist(b, target) || dist(a, hq) - dist(b, hq));
      if (c.length) return { a: "build", piece: "road", ...P(c[0]) };
    }
  }
  return { a: "pass" };
}
const contest = o => KEYS;                                   // will build toward any open station
const home = o => [KEYS.slice().sort((a, b) => dist(a, HQ[o]) - dist(b, HQ[o]))[0]];  // only its nearest station

function play(botA, botB) {
  const b = new HSBoard();
  let g = 0;
  while (b.winner === null && g++ < 6000) {
    const o = b.to_move, f = o === 0 ? botA : botB;
    const act = f(b, o); b.apply(b.is_legal(act) ? act : { a: "pass" });
  }
  const { remaining } = b._allocate();
  const capUsed = KEYS.reduce((s, k) => s + (HS_STATIONS[k] - remaining[k]), 0);
  const capTot = KEYS.reduce((s, k) => s + HS_STATIONS[k], 0);
  return { winner: b.winner, tokens: b.tokens.map(Math.round), capUsed, capTot,
    center: HS_STATIONS["4,4"]-remaining["4,4"], centerTot: HS_STATIONS["4,4"], reserve: b.reserve };
}

function main() {
  console.log("stations:", HS_STATIONS, "total power", KEYS.reduce((s, k) => s + HS_STATIONS[k], 0), "\n");
  // 1) symmetric contest vs contest
  let r = play((b, o) => bot(b, o, contest(o)), (b, o) => bot(b, o, contest(o)));
  console.log("contest vs contest:", r.tokens, "| power used", r.capUsed + "/" + r.capTot,
    "| centre used", r.center + "/" + HS_STATIONS["4,4"], "| GPU left", r.reserve.GPU);
  // 2) does contesting the centre beat turtling at home?
  let cw = 0, hw = 0, tokC = [], tokH = [];
  for (let i = 0; i < 2; i++) {
    // i=0: contest is P0; i=1: contest is P1 (seat swap)
    const A = i === 0 ? ((b, o) => bot(b, o, contest(o))) : ((b, o) => bot(b, o, home(o)));
    const B = i === 0 ? ((b, o) => bot(b, o, home(o))) : ((b, o) => bot(b, o, contest(o)));
    const res = play(A, B);
    const contestTok = i === 0 ? res.tokens[0] : res.tokens[1];
    const homeTok = i === 0 ? res.tokens[1] : res.tokens[0];
    tokC.push(contestTok); tokH.push(homeTok);
    if (contestTok > homeTok) cw++; else if (homeTok > contestTok) hw++;
  }
  console.log("\ncontest-the-centre vs turtle-at-home (both seats):");
  console.log("  contest tokens", tokC, "| turtle tokens", tokH, "| contest wins", cw + "/2");
  console.log("\nverdict: power contested?", r.capUsed >= r.capTot - 4 ? "YES (near-full, scarce)" : "no (slack power)",
    "| centre a flashpoint?", r.center >= 6 ? "YES" : "partly",
    "| turtle punished?", tokC.every((c, i) => c > tokH[i]) ? "YES" : "no");
}
main();
