// HYPERSCALE (spatial + market) engine — v0.5.1.
// Power is SCARCE and BOARD-FIXED, concentrated in a central corridor both
// players must fight over (plus tiny home stations). A datacenter earns only
// when a ROAD connects it to your HQ and it's power-line/adjacency connected to
// a station with spare capacity. You add SERVERS one at a time (1 action each);
// a server consumes 2 GPU + 1 HBM + 1 CPU from the shared, finite, dynamically
// priced market — so cornering GPU starves your opponent. Output = powered
// servers; you pay power + manning (grows with ROAD-PATH length from HQ, so
// walling the enemy into detours raises their costs) every day. Max 4/DC.

const HS_W = 9, HS_H = 9;
const HS_HQ = ["0,0", "8,8"];
// central power corridor (the contested prize) + tiny home stations.
const HS_STATIONS = { "4,3": 5, "4,4": 6, "4,5": 5, "2,2": 2, "6,6": 2 };
const HS_STATION_KEYS = Object.keys(HS_STATIONS);
const HS_TECH = ["GPU", "HBM", "CPU"];
const HS_SERVER = { GPU: 2, HBM: 1, CPU: 1 };            // one server's parts
const HS_BASE_PRICE = { GPU: 3, HBM: 3, CPU: 1 };
const HS_RESERVE0 = { GPU: 44, HBM: 24, CPU: 60 };       // GPU ~ a second scarce cap
const HS_PRICE_K = 2.0;
const HS_COST = { road: 1, powerline: 2, dc: 4 };
const HS_SABOTAGE_COST = 3;   // demolish an adjacent enemy road/power-line piece (1 action, once/day)
const HS_MAX_SERVERS = 4;
const HS_BUY_LOT = 4;   // one "buy" action stockpiles up to this many of one component
const HS_POWER_COST = 1.0, HS_MAN_RATE = 0.15, HS_REV_RATE = 4.0;
const HS_INCOME_BASE = 8, HS_START_CAPITAL = 24, HS_ACTIONS = 3, HS_MAX_DAYS = 24;
const HS_P2_BONUS = 0;   // second-mover capital compensation (P0 claims the centre first)
const HS_POWER_KINDS = new Set(["powerline", "dc"]);   // a power line is a piece on a hex
const HS_ROAD_KINDS = new Set(["road", "dc"]);

const hsKey = (x, y) => x + "," + y;
function hsNeigh(x, y) {
  const d = (y % 2 === 0) ? [[1,0],[-1,0],[0,1],[-1,1],[0,-1],[-1,-1]]
                          : [[1,0],[-1,0],[1,1],[0,1],[1,-1],[0,-1]];
  return d.map(([dx, dy]) => [x + dx, y + dy]);
}
const hsIn = (x, y) => x >= 0 && x < HS_W && y >= 0 && y < HS_H;
function hsAdj(k) { const [x, y] = k.split(",").map(Number); return hsNeigh(x, y).filter(([nx, ny]) => hsIn(nx, ny)).map(([nx, ny]) => hsKey(nx, ny)); }
function hsDist(a, b) {
  const ax = (x, y) => [x - ((y - (y & 1)) >> 1), y];
  const [x1, y1] = a.split(",").map(Number), [x2, y2] = b.split(",").map(Number);
  const [aq, ar] = ax(x1, y1), [bq, br] = ax(x2, y2);
  const dq = aq - bq, dr = ar - br;
  return (Math.abs(dq) + Math.abs(dr) + Math.abs(dq + dr)) >> 1;
}

class HSBoard {
  constructor() {
    this.pieces = {};
    this.dc_servers = {};   // dc hex -> installed servers (0..4)
    this.reserve = Object.assign({}, HS_RESERVE0);   // shared, finite market
    this.stock = [{ GPU: 0, HBM: 0, CPU: 0 }, { GPU: 0, HBM: 0, CPU: 0 }];  // per-player prebought components
    this.capital = [HS_START_CAPITAL, HS_START_CAPITAL + HS_P2_BONUS];
    this.tokens = [0, 0];
    this.produced_last = [0, 0];
    this.earned = [0, 0];        // cumulative cash IN  (base income + token revenue)
    this.spent = [0, 0];         // cumulative cash OUT (opex + builds + servers + market)
    this.dc_produced = {};       // dc hex -> cumulative AI tokens it has output
    this.dayLog = [];            // per-day production/cashflow, for the end-of-day animation
    this.to_move = 0;
    this.actions_left = HS_ACTIONS;
    this.day = 1;
    this.winner = null;
    this._begin_day(0);
  }
  price(r) {
    const depl = 1 - this.reserve[r] / HS_RESERVE0[r];
    return Math.round(HS_BASE_PRICE[r] * (1 + HS_PRICE_K * depl));
  }
  // out-of-pocket cost of a server for `owner`: only the shortfall not covered by
  // their prebought stock is bought from the market at current prices.
  serverCost(owner) { owner = owner ?? this.to_move;
    return HS_TECH.reduce((s, r) => s + Math.max(0, HS_SERVER[r] - this.stock[owner][r]) * this.price(r), 0); }
  canBuyServer(owner) { owner = owner ?? this.to_move;
    return HS_TECH.every(r => this.stock[owner][r] + this.reserve[r] >= HS_SERVER[r]); }
  servers(h) { return this.dc_servers[h] || 0; }
  // connected clusters of the owner's power pieces (dc/powerline). Stations are NOT part of
  // clusters and never bridge them (no cascade / no invisible pooling).
  _powerComponents(owner) {
    const nodes = new Set();
    for (const h in this.pieces) { const p = this.pieces[h]; if (p.owner === owner && HS_POWER_KINDS.has(p.kind)) nodes.add(h); }
    const seen = new Set(), comps = [];
    for (const s of nodes) {
      if (seen.has(s)) continue;
      const comp = new Set(), st = [s]; seen.add(s);
      while (st.length) { const h = st.pop(); comp.add(h); for (const n of hsAdj(h)) if (nodes.has(n) && !seen.has(n)) { seen.add(n); st.push(n); } }
      comps.push(comp);
    }
    return comps;
  }
  _clusterStations(comp) {
    const st = new Set();
    for (const h of comp) for (const n of hsAdj(h)) if (HS_STATIONS[n] !== undefined) st.add(n);
    return [...st];
  }
  _hasStation(comp) { return this._clusterStations(comp).length > 0; }
  _roadDist(owner) {
    const nodes = new Set([HS_HQ[owner]]);
    for (const h in this.pieces) { const p = this.pieces[h]; if (p.owner === owner && HS_ROAD_KINDS.has(p.kind)) nodes.add(h); }
    const dist = { [HS_HQ[owner]]: 0 }, q = [HS_HQ[owner]];
    while (q.length) { const h = q.shift(); for (const n of hsAdj(h)) if (nodes.has(n) && dist[n] === undefined) { dist[n] = dist[h] + 1; q.push(n); } }
    return dist;
  }
  // every station a DC can draw from = stations adjacent to its power-piece cluster
  // (the DC itself + any chain of power-line pieces wired out from it).
  _reachableStations(owner, h) {
    const comp = this._powerComponents(owner).find(c => c.has(h));
    return comp ? this._clusterStations(comp) : [];
  }
  // MULTI-SOURCE partial power: a DC draws its servers from ALL its reachable stations
  // (most-free first, so it spreads load and stays resilient if one source is contested).
  // Stations stay distinct, per-station capped, and shared/contested between both players.
  _allocate() {
    const remaining = {}; for (const s of HS_STATION_KEYS) remaining[s] = HS_STATIONS[s];
    const cands = [];
    for (const owner of [0, 1]) {
      const rr = this._roadDist(owner);
      for (const h in this.pieces) {
        const p = this.pieces[h];
        if (p.owner !== owner || p.kind !== "dc" || this.servers(h) <= 0 || rr[h] === undefined) continue;
        const reach = this._reachableStations(owner, h);
        if (reach.length) cands.push([this.servers(h), owner, h, reach]);
      }
    }
    cands.sort((a, b) => (b[0] - a[0]) || (a[2] < b[2] ? -1 : 1));
    const powered = { 0: {}, 1: {} }, sources = { 0: {}, 1: {} };
    for (const [srv, owner, h, reach] of cands) {
      let need = srv, got = 0; const src = {};
      for (const s of reach.slice().sort((a, b) => remaining[b] - remaining[a] || (a < b ? -1 : 1))) {
        if (need <= 0) break;
        const take = Math.min(need, remaining[s]);
        if (take > 0) { remaining[s] -= take; need -= take; got += take; src[s] = take; }
      }
      if (got > 0) { powered[owner][h] = got; sources[owner][h] = src; }
    }
    return { powered, remaining, sources };
  }
  producing(owner) { return new Set(Object.keys(this._allocate().powered[owner])); }
  dc_status(h) {
    const o = this.pieces[h].owner, srv = this.servers(h), rd = this._roadDist(o), dist = rd[h];
    const reach = this._reachableStations(o, h);
    if (srv === 0) return { state: "no_servers", servers: 0, output: 0, dist: dist ?? hsDist(h, HS_HQ[o]), reach, sources: {} };
    if (dist === undefined) return { state: "no_road", servers: srv, output: 0, dist: hsDist(h, HS_HQ[o]), reach, sources: {} };
    const { powered, sources } = this._allocate();
    const pw = powered[o][h] || 0;
    if (pw > 0)
      return { state: "producing", servers: srv, output: pw, powerCapped: pw < srv, dist, reach, sources: sources[o][h] || {},
        opex: Math.round((pw * HS_POWER_COST + pw * dist * HS_MAN_RATE) * 10) / 10 };
    return { state: reach.length ? "unpowered" : "no_power_line", servers: srv, output: 0, dist, reach, sources: {} };
  }
  _begin_day(owner) {
    const rd = this._roadDist(owner), pw = this._allocate().powered[owner];
    let out = 0, opex = 0; const perDC = {};
    for (const h in pw) { const p = pw[h]; out += p; opex += p * HS_POWER_COST + p * (rd[h] || 0) * HS_MAN_RATE;
      this.dc_produced[h] = (this.dc_produced[h] || 0) + p; perDC[h] = p; }
    this.tokens[owner] += out;
    this.produced_last[owner] = out;
    this.earned[owner] += HS_INCOME_BASE + HS_REV_RATE * out;
    this.spent[owner] += opex;
    this.capital[owner] += HS_INCOME_BASE + HS_REV_RATE * out - opex;
    // per-day record for the "end of day" production animation
    this.dayLog.push({ day: this.day, owner, out, perDC,
      income: HS_INCOME_BASE, revenue: HS_REV_RATE * out, opex: Math.round(opex * 10) / 10 });
    this.actions_left = HS_ACTIONS;
    this.sab_used = false;   // one sabotage per player per day
  }
  _empty(h) { const [x, y] = h.split(",").map(Number); return hsIn(x, y) && !this.pieces[h] && !HS_HQ.includes(h) && HS_STATIONS[h] === undefined; }
  is_legal(action, owner) {
    owner = owner === undefined ? this.to_move : owner;
    if (this.winner !== null || this.actions_left <= 0) return action.a === "pass";
    if (action.a === "pass") return true;
    if (action.a === "build")
      return HS_COST[action.piece] !== undefined && this.capital[owner] >= HS_COST[action.piece] && this._empty(hsKey(action.x, action.y));
    if (action.a === "install") {
      const p = this.pieces[hsKey(action.x, action.y)];
      return p && p.owner === owner && p.kind === "dc" && this.servers(hsKey(action.x, action.y)) < HS_MAX_SERVERS
        && this.canBuyServer(owner) && this.capital[owner] >= this.serverCost(owner);
    }
    if (action.a === "buy")   // prestock one component (hedge price / deny the shared reserve)
      return HS_TECH.includes(action.res) && this.reserve[action.res] > 0 && this.capital[owner] >= this.price(action.res);
    if (action.a === "sabotage") {   // demolish an adjacent enemy road/power-line piece (1/day)
      const k = hsKey(action.x, action.y), p = this.pieces[k];
      return !this.sab_used && p && p.owner !== owner && (p.kind === "road" || p.kind === "powerline")
        && hsAdj(k).some(n => this.pieces[n] && this.pieces[n].owner === owner)
        && this.capital[owner] >= HS_SABOTAGE_COST;
    }
    return false;
  }
  apply(action) {
    const owner = this.to_move;
    if (action.a === "pass") this.actions_left = 0;
    else if (action.a === "build") {
      const k = hsKey(action.x, action.y);
      this.capital[owner] -= HS_COST[action.piece];
      this.spent[owner] += HS_COST[action.piece];
      this.pieces[k] = { owner, kind: action.piece };
      if (action.piece === "dc") this.dc_servers[k] = 0;
      this.actions_left -= 1;
    } else if (action.a === "install") {
      const k = hsKey(action.x, action.y);
      HS_TECH.forEach(r => {          // draw from prebought stock first, then the market
        let need = HS_SERVER[r];
        const fromStock = Math.min(need, this.stock[owner][r]);
        this.stock[owner][r] -= fromStock; need -= fromStock;
        this.capital[owner] -= need * this.price(r);
        this.spent[owner] += need * this.price(r);
        this.reserve[r] -= need;
      });
      this.dc_servers[k] += 1;
      this.actions_left -= 1;
    } else if (action.a === "buy") {
      const r = action.res;
      let n = 0;                      // fill a lot, escalating price as the reserve depletes
      while (n < HS_BUY_LOT && this.reserve[r] > 0 && this.capital[owner] >= this.price(r)) {
        this.capital[owner] -= this.price(r); this.spent[owner] += this.price(r); this.reserve[r] -= 1; this.stock[owner][r] += 1; n++;
      }
      this.actions_left -= 1;
    } else if (action.a === "sabotage") {
      delete this.pieces[hsKey(action.x, action.y)];   // network recomputes from pieces; downstream DCs drop offline
      this.capital[owner] -= HS_SABOTAGE_COST;
      this.spent[owner] += HS_SABOTAGE_COST;
      this.sab_used = true;
      this.actions_left -= 1;
    }
    if (this.actions_left <= 0) this._end_day();
  }
  _end_day() {
    this.to_move ^= 1; this.day += 1;
    if (this.day > HS_MAX_DAYS) { const [a, b] = this.tokens; this.winner = a > b ? 0 : (b > a ? 1 : "draw"); }
    else this._begin_day(this.to_move);
  }
}

// -------------------------------------------------------------- functional AI
// Capital-disciplined: fill existing DCs before building new ones, and never
// build a DC you can't afford to staff. Chases the big central power pool.
function hsAiMove(board, owner) {
  const cap = board.capital[owner], HQ = HS_HQ[owner];
  const rd = board._roadDist(owner), rr = new Set(Object.keys(rd));
  const empties = [];
  for (let y = 0; y < HS_H; y++) for (let x = 0; x < HS_W; x++) { const k = hsKey(x, y); if (board._empty(k)) empties.push(k); }
  if (!empties.length) return { a: "pass" };
  const P = h => { const [x, y] = h.split(",").map(Number); return { x, y }; };
  const { powered, remaining } = board._allocate();
  const open = HS_STATION_KEYS.filter(s => remaining[s] > 0);
  const roadAdj = h => hsAdj(h).some(n => rr.has(n));
  const stationAdjOpen = h => hsAdj(h).some(n => HS_STATIONS[n] !== undefined && remaining[n] > 0);

  const dcs = []; for (const h in board.pieces) if (board.pieces[h].owner === owner && board.pieces[h].kind === "dc") dcs.push(h);
  const comps = board._powerComponents(owner);
  const connectedPow = new Set();
  for (const comp of comps) if (board._hasStation(comp)) for (const h of comp) connectedPow.add(h);

  // a DC can grow if ANY of its reachable stations still has spare capacity (multi-source)
  const powerRoom = h => board._reachableStations(owner, h).some(s => remaining[s] > 0);
  const growable = dcs.filter(h => rr.has(h) && connectedPow.has(h) && board.servers(h) < HS_MAX_SERVERS && powerRoom(h))
    .sort((a, b) => (rd[a] || 9) - (rd[b] || 9));

  const sc = board.serverCost(owner);
  // 1) fill a productive DC — servers are the score, so always prefer this
  if (board.canBuyServer(owner) && cap >= sc && growable.length) return { a: "install", ...P(growable[0]) };

  // 1c) RECONNECT: a DC with servers lost its road/power to a sabotage — rebuild the bridge.
  {
    const strandedRoad = dcs.filter(h => board.servers(h) > 0 && rd[h] === undefined);
    if (strandedRoad.length && cap >= HS_COST.road) {
      const bridge = empties.filter(e => {
        const ns = hsAdj(e);
        return ns.some(n => rr.has(n)) &&
          ns.some(n => { const p = board.pieces[n]; return p && p.owner === owner && HS_ROAD_KINDS.has(p.kind) && !rr.has(n); });
      }).sort((a, b) => hsDist(a, HQ) - hsDist(b, HQ))[0];
      if (bridge) return { a: "build", piece: "road", ...P(bridge) };
    }
    const strandedPow = dcs.filter(h => board.servers(h) > 0 && rd[h] !== undefined && board._reachableStations(owner, h).length === 0);
    if (strandedPow.length && cap >= HS_COST.powerline) {
      for (const h of strandedPow) {
        const cluster = comps.find(c => c.has(h)); if (!cluster) continue;
        const bridge = empties.filter(e => hsAdj(e).some(n => cluster.has(n)) && hsAdj(e).some(n => HS_STATIONS[n] !== undefined))[0];
        if (bridge) return { a: "build", piece: "powerline", ...P(bridge) };
      }
    }
  }

  // 1b) defensive stockpiling: if we still want servers but a scarce component is
  // nearly gone (an opponent may be cornering it), lock some away while we can.
  if (growable.length) {
    for (const r of HS_TECH) {
      if (board.reserve[r] > 0 && board.reserve[r] <= HS_BUY_LOT * 2
          && board.stock[owner][r] < HS_SERVER[r] * 2 && cap >= board.price(r) * 2)
        return { a: "buy", res: r };
    }
  }

  // 1d) SABOTAGE: demolish an adjacent enemy road/power-line that knocks the most of
  // their servers offline (worth it only when the payoff is real — building comes first).
  if (!board.sab_used && cap >= HS_SABOTAGE_COST) {
    const opp = 1 - owner;
    const enemyPow = () => { const pw = board._allocate().powered[opp]; let s = 0; for (const h in pw) s += pw[h]; return s; };
    const base = enemyPow();
    let best = null, bestVal = 0;
    for (const k in board.pieces) {
      const p = board.pieces[k];
      if (p.owner !== opp || !(p.kind === "road" || p.kind === "powerline")) continue;
      if (!hsAdj(k).some(n => board.pieces[n] && board.pieces[n].owner === owner)) continue;
      const saved = board.pieces[k]; delete board.pieces[k];
      const val = base - enemyPow();
      board.pieces[k] = saved;
      if (val > bestVal) { bestVal = val; best = k; }
    }
    if (best && bestVal >= 3) return { a: "sabotage", ...P(best) };
  }

  // value of a new DC hex: biggest open pool it can tap, discounted by reach
  const spotVal = h => { let v = -99; for (const n of hsAdj(h)) if (HS_STATIONS[n] !== undefined && remaining[n] > 0) v = Math.max(v, remaining[n] - hsDist(h, HQ) * 0.3); return v; };
  // 2) claim a NEW DC as soon as a road reaches an open station — but only when
  // nothing can grow (the prior DC is full), so we never pave a spot we can't hold
  if (!growable.length && cap >= HS_COST.dc) {
    const spots = empties.filter(h => roadAdj(h) && stationAdjOpen(h)).sort((a, b) => spotVal(b) - spotVal(a) || hsDist(a, HQ) - hsDist(b, HQ));
    if (spots.length) return { a: "build", piece: "dc", ...P(spots[0]) };
  }
  const oppHQ = HS_HQ[1 - owner];
  // 2b) POWER LINE: a road-connected DC is under-powered (or wants more servers) but every
  // station it reaches is full. Extend a power line from its cluster one hex toward the best
  // open station on our side — when the chain reaches it, the DC draws from it too.
  if (cap >= HS_COST.powerline) {
    const stuck = dcs.filter(h => rr.has(h) &&
      ((powered[owner][h] || 0) < board.servers(h) || (board.servers(h) < HS_MAX_SERVERS && !powerRoom(h))));
    for (const h of stuck) {
      const cluster = comps.find(c => c.has(h)); if (!cluster) continue;
      const reached = new Set(board._reachableStations(owner, h));
      const far = HS_STATION_KEYS.filter(s => remaining[s] > 0 && !reached.has(s) && hsDist(s, HQ) <= hsDist(s, oppHQ));
      if (!far.length) continue;
      const tgt = far.sort((a, b) => remaining[b] - remaining[a])[0];
      const netMin = Math.min(...[...cluster].map(x => hsDist(x, tgt)));
      const step = empties.filter(e => hsAdj(e).some(n => cluster.has(n)) && hsDist(e, tgt) < netMin)
        .sort((a, b) => hsDist(a, tgt) - hsDist(b, tgt))[0];
      if (step) return { a: "build", piece: "powerline", ...P(step) };
    }
  }
  // 3) extend a road ONLY toward an open station we can't yet reach AND that is worth
  // pursuing — i.e. not closer to the enemy's HQ than ours (never march across the board
  // to chase the opponent's home station, which we could never profitably hold). Once a
  // station is reachable, priority 2 builds the DC — so we never lay purposeless roads.
  if (cap >= HS_COST.road) {
    const reaches = s => hsAdj(s).some(n => (board.pieces[n] && board.pieces[n].owner === owner) || (board._empty(n) && roadAdj(n)));
    const wanted = open.filter(s => !reaches(s) && hsDist(s, HQ) <= hsDist(s, oppHQ));
    if (wanted.length) {
      const target = wanted.sort((a, b) => remaining[b] - remaining[a])[0];
      const cands = empties.filter(roadAdj).sort((a, b) => hsDist(a, target) - hsDist(b, target) || hsDist(a, HQ) - hsDist(b, HQ));
      if (cands.length) return { a: "build", piece: "road", ...P(cands[0]) };
    }
  }
  return { a: "pass" };
}

// -------------------------------------------------------------- controller
class HyperscaleMatch {
  constructor(opts = {}) {
    this.humanSide = opts.humanSide === 1 ? 1 : 0;
    this.board = new HSBoard();
    this.log = [];        // human-readable ticker (capped)
    this.history = [];    // full structured move list (uncapped, for download/replay)
    this.aiChanges = [];
    this._runAI();
  }
  aiSide() { return 1 - this.humanSide; }
  _logAct(owner, act) {
    const who = owner === this.humanSide ? "You" : "AI";
    let msg;
    if (act.a === "pass") msg = "ended the day";
    else if (act.a === "install") msg = `added a server at (${act.x},${act.y})`;
    else if (act.a === "buy") msg = `stockpiled ${act.res}`;
    else if (act.a === "sabotage") msg = `⚡ sabotaged a piece at (${act.x},${act.y})`;
    else msg = `built a ${act.piece} at (${act.x},${act.y})`;
    this.log.push({ day: this.board.day, who, msg });
    if (this.log.length > 30) this.log.shift();
    // full history keeps the raw action too, so a game can be replayed/inspected
    this.history.push({ day: this.board.day, side: owner, who, ...act });
  }
  _runAI() {
    if (this.board.winner !== null || this.board.to_move !== this.aiSide()) return;
    this.aiChanges = [];
    let g = 0;
    while (this.board.winner === null && this.board.to_move === this.aiSide() && g++ < 300) {
      const act = hsAiMove(this.board, this.board.to_move);
      const legal = this.board.is_legal(act) ? act : { a: "pass" };
      this._logAct(this.board.to_move, legal);
      if (legal.a === "build" || legal.a === "install" || legal.a === "sabotage") this.aiChanges.push(hsKey(legal.x, legal.y));
      this.board.apply(legal);
    }
  }
  humanAct(action) {
    if (this.board.winner !== null || this.board.to_move !== this.humanSide) return false;
    if (!this.board.is_legal(action, this.humanSide)) return false;
    this._logAct(this.humanSide, action);
    this.board.apply(action);
    this._runAI();
    return true;
  }
  // full snapshot of the game (current status + every move) for download / replay
  exportGame() {
    const b = this.board;
    return {
      game: "hyperscale", version: "0.6",
      humanSide: this.humanSide, aiSide: this.aiSide(),
      day: b.day, max_days: HS_MAX_DAYS, over: b.winner !== null, winner: b.winner,
      scores: { you: Math.round(b.tokens[this.humanSide] * 10) / 10, ai: Math.round(b.tokens[this.aiSide()] * 10) / 10 },
      stations: HS_STATIONS,
      state: {
        pieces: b.pieces, dc_servers: b.dc_servers,
        capital: b.capital, tokens: b.tokens, reserve: b.reserve, stock: b.stock,
      },
      moves: this.history,
    };
  }
  view() {
    const b = this.board, hs = this.humanSide;
    const rd = [b._roadDist(0), b._roadDist(1)];
    const { powered, remaining } = b._allocate();
    const cells = [];
    for (let y = HS_H - 1; y >= 0; y--) for (let x = 0; x < HS_W; x++) {
      const k = hsKey(x, y), p = b.pieces[k] || null;
      let status = null;
      if (p && p.kind === "dc") status = b.dc_status(k);
      const stCap = HS_STATIONS[k];
      const canSabotage = !!p && p.owner !== hs && (p.kind === "road" || p.kind === "powerline")
        && !b.sab_used && b.capital[hs] >= HS_SABOTAGE_COST
        && hsAdj(k).some(n => b.pieces[n] && b.pieces[n].owner === hs);
      cells.push({
        k, x, y, piece: p, status, canSabotage,
        servers: p && p.kind === "dc" ? b.servers(k) : null,
        hq: HS_HQ.indexOf(k), station: stCap !== undefined, isStation: stCap !== undefined,
        stationUsed: stCap !== undefined ? stCap - (remaining[k] || 0) : null, stationCap: stCap ?? null,
        stationRemaining: stCap !== undefined ? (remaining[k] || 0) : null,
        roadNode: p ? (HS_ROAD_KINDS.has(p.kind) && rd[p.owner][k] !== undefined) : false,
        empty: b._empty(k),
      });
    }
    const pv = o => {
      const pw = powered[o];
      const c = { road: 0, powerline: 0, dc: 0 };
      for (const h in b.pieces) if (b.pieces[h].owner === o) c[b.pieces[h].kind]++;
      let servers = 0; for (const h in pw) servers += pw[h];
      return { capital: Math.round(b.capital[o] * 10) / 10, tokens: Math.round(b.tokens[o] * 10) / 10,
        produced_last: b.produced_last[o], counts: c, earning: Object.keys(pw).length, servers };
    };
    const market = {};
    HS_TECH.forEach(r => market[r] = { price: b.price(r), reserve: b.reserve[r], init: HS_RESERVE0[r] });
    return {
      W: HS_W, H: HS_H, day: b.day, max_days: HS_MAX_DAYS,
      over: b.winner !== null, winner: b.winner,
      humanSide: hs, aiSide: this.aiSide(),
      yourTurn: b.winner === null && b.to_move === hs, actions_left: b.actions_left,
      cells, players: [pv(0), pv(1)], market, hq: HS_HQ, stock: [b.stock[0], b.stock[1]],
      costs: HS_COST, tech: HS_TECH, server: HS_SERVER, serverCost: b.serverCost(hs),
      canBuyServer: b.canBuyServer(hs), max_servers: HS_MAX_SERVERS, buyLot: HS_BUY_LOT,
      sabotageCost: HS_SABOTAGE_COST, sabUsed: b.sab_used,
      log: this.log.slice(-8), aiChanges: this.aiChanges.slice(),
      dayLog: b.dayLog, humanHQ: HS_HQ[hs],
      summary: b.winner !== null ? this.summary() : null,
    };
  }
  affordBuild(k) { return this.board.capital[this.humanSide] >= HS_COST[k]; }
  affordServer() { return this.board.capital[this.humanSide] >= this.board.serverCost(this.humanSide) && this.board.canBuyServer(this.humanSide); }
  affordBuy(r) { return this.board.is_legal({ a: "buy", res: r }, this.humanSide); }
  canSabotage(x, y) { return this.board.is_legal({ a: "sabotage", x, y }, this.humanSide); }
  // end-of-game economics for the results animation: per-side tokens/earned/spent
  // plus each datacenter's lifetime token output (and where it sits).
  summary() {
    const b = this.board, dcs = [];
    for (const h in b.dc_produced) {
      if (b.dc_produced[h] > 0 && b.pieces[h] && b.pieces[h].kind === "dc") {
        const [x, y] = h.split(",").map(Number);
        dcs.push({ k: h, x, y, owner: b.pieces[h].owner, produced: Math.round(b.dc_produced[h]) });
      }
    }
    return {
      sides: [0, 1].map(o => ({ tokens: Math.round(b.tokens[o]), earned: Math.round(b.earned[o]), spent: Math.round(b.spent[o]) })),
      dcs,
    };
  }
}

if (typeof module !== "undefined" && module.exports)
  module.exports = { HSBoard, hsAiMove, HyperscaleMatch, HS_MAX_DAYS, HS_COST, HS_TECH, HS_STATIONS, HS_SERVER };
