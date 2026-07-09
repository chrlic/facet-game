"use strict";
// BACKBONE game engine + AI — JS port of backbone_engine.py (keep in sync).
// Hex keys are "x,y" strings; actions are the same JSON dicts as Python.

const BB_W = 9, BB_H = 9;
const BB_CITIES = [[1,4],[7,4],[3,1],[5,7],[5,1],[3,7],[4,4]];
// The rulebook's city set is mirrored in OFFSET coordinates, which is not a
// hex isometry — P2 is strictly closer to most cities. This set keeps the
// rulebook's intent but uses the true 180-degree hex rotation about (4,4):
const BB_SYM_CITIES = [[1,4],[7,4],[3,1],[4,7],[5,1],[2,7],[4,4]];
const BB_START = ["0,0", "8,8"];
const BB_SERVER_START = ["1,0", "7,8"];
const BB_PIECES = ["router", "switch", "ap", "firewall", "server", "dc"];
const BB_SUPPLY = {router:14, switch:8, ap:5, firewall:6, server:6, dc:4};
const BB_COST = {router:2, switch:1, ap:3, firewall:2, server:3, dc:6};
const BB_TARGET_VP = 12, BB_HAND_LIMIT = 10, BB_INCOME_BASE = 3;
const BB_HACK_COST = 2, BB_MAX_DISABLED = 6;

function bbKey(x, y){ return x + "," + y; }
function bbXY(k){ const i = k.indexOf(","); return [ +k.slice(0, i), +k.slice(i + 1) ]; }
function bbIn(x, y){ return x >= 0 && x < BB_W && y >= 0 && y < BB_H; }

function bbNeighbors(x, y){
  const d = (y % 2 === 0)
    ? [[1,0],[-1,0],[0,1],[-1,1],[0,-1],[-1,-1]]
    : [[1,0],[-1,0],[1,1],[0,1],[1,-1],[0,-1]];
  return d.map(([dx,dy]) => [x+dx, y+dy]);
}

function bbToAxial(x, y){ return [x - ((y - (y & 1)) >> 1), y]; }
function bbFromAxial(q, r){ return [q + ((r - (r & 1)) >> 1), r]; }
const BB_AXIAL_DIRS = [[1,0],[-1,0],[0,1],[0,-1],[1,-1],[-1,1]];

function bbJumpTargets(x, y){
  const [q, r] = bbToAxial(x, y);
  const out = [];
  for(const [dq, dr] of BB_AXIAL_DIRS){
    const mid = bbFromAxial(q + dq, r + dr);
    const far = bbFromAxial(q + 2*dq, r + 2*dr);
    if(bbIn(far[0], far[1])) out.push([mid, far]);
  }
  return out;
}

function bbHexDistance(a, b){
  const [aq, ar] = bbToAxial(a[0], a[1]);
  const [bq, br] = bbToAxial(b[0], b[1]);
  const dq = aq - bq, dr = ar - br;
  return (Math.abs(dq) + Math.abs(dr) + Math.abs(dq + dr)) / 2;
}

class BackboneBoard{
  constructor(opts){
    opts = opts || {};
    this.recoverBeforeScore = opts.recover_before_score || false;
    this.targetVp = opts.target_vp === undefined ? 10 : opts.target_vp;
    this.hackCost = opts.hack_cost === undefined ? 1 : opts.hack_cost;
    this.hackLimit = opts.hack_limit === undefined ? 1 : opts.hack_limit;
    this.hacksThisTurn = 0;
    this.cities = opts.cities || BB_SYM_CITIES;
    this.citySet = new Set(this.cities.map(c => bbKey(c[0], c[1])));
    this.finalTurn = opts.final_turn === undefined ? true : opts.final_turn;
    this.finalPending = false;
    this.pieces = {};        // "x,y" -> {owner, kind}
    this.firewalls = new Set();
    this.disabled = new Set();
    this.serverCity = {};    // server hex -> "x,y" of served city
    const bonus = opts.p2_bonus_bw === undefined ? 2 : opts.p2_bonus_bw;
    this.bw = [3, 3 + bonus];
    this.supply = [{...BB_SUPPLY}, {...BB_SUPPLY}];
    this.toMove = 0;
    this.actionsLeft = 2;
    this.turnNo = 1;
    this.passStreak = 0;
    this.winner = null;
    for(const p of [0, 1]){
      this.pieces[BB_START[p]] = {owner: p, kind: "router"};
      this.pieces[BB_SERVER_START[p]] = {owner: p, kind: "server"};
      this.supply[p].router -= 1;
      this.supply[p].server -= 1;
    }
    this._income(0);
  }

  clone(){
    const b = Object.create(BackboneBoard.prototype);
    b.recoverBeforeScore = this.recoverBeforeScore;
    b.targetVp = this.targetVp;
    b.hackCost = this.hackCost;
    b.hackLimit = this.hackLimit;
    b.hacksThisTurn = this.hacksThisTurn;
    b.cities = this.cities;
    b.citySet = this.citySet;
    b.finalTurn = this.finalTurn;
    b.finalPending = this.finalPending;
    b.pieces = {...this.pieces};
    b.firewalls = new Set(this.firewalls);
    b.disabled = new Set(this.disabled);
    b.serverCity = {...this.serverCity};
    b.bw = [...this.bw];
    b.supply = [{...this.supply[0]}, {...this.supply[1]}];
    b.toMove = this.toMove;
    b.actionsLeft = this.actionsLeft;
    b.turnNo = this.turnNo;
    b.passStreak = this.passStreak;
    b.winner = this.winner;
    return b;
  }

  _connNeighbors(k){
    const [x, y] = bbXY(k);
    const {owner, kind} = this.pieces[k];
    const out = [];
    for(const [nx, ny] of bbNeighbors(x, y)) if(bbIn(nx, ny)) out.push(bbKey(nx, ny));
    if(kind === "ap"){
      for(const [, far] of bbJumpTargets(x, y)) out.push(bbKey(far[0], far[1]));
    }else{
      for(const [, far] of bbJumpTargets(x, y)){
        const fk = bbKey(far[0], far[1]);
        const p = this.pieces[fk];
        if(p && p.owner === owner && p.kind === "ap") out.push(fk);
      }
    }
    return out;
  }

  network(owner){
    const root = BB_START[owner];
    const p = this.pieces[root];
    const seen = new Set();
    if(!p || p.owner !== owner || this.disabled.has(root)) return seen;
    seen.add(root);
    const stack = [root];
    while(stack.length){
      const h = stack.pop();
      for(const n of this._connNeighbors(h)){
        if(seen.has(n) || this.disabled.has(n)) continue;
        const q = this.pieces[n];
        if(q && q.owner === owner){ seen.add(n); stack.push(n); }
      }
    }
    return seen;
  }

  frontier(owner, net){
    net = net || this.network(owner);
    const out = new Set();
    for(const h of net){
      const [x, y] = bbXY(h);
      const cand = bbNeighbors(x, y).filter(([nx,ny]) => bbIn(nx, ny))
        .map(([nx,ny]) => bbKey(nx, ny));
      if(this.pieces[h].kind === "ap")
        for(const [, far] of bbJumpTargets(x, y)) cand.push(bbKey(far[0], far[1]));
      for(const n of cand)
        if(!(n in this.pieces) && !this.citySet.has(n)) out.add(n);
    }
    return out;
  }

  hackable(owner, net){
    net = net || this.network(owner);
    const out = new Set();
    for(const h of net){
      const [x, y] = bbXY(h);
      const cand = bbNeighbors(x, y).filter(([nx,ny]) => bbIn(nx, ny))
        .map(([nx,ny]) => bbKey(nx, ny));
      if(this.pieces[h].kind === "ap")
        for(const [, far] of bbJumpTargets(x, y)) cand.push(bbKey(far[0], far[1]));
      for(const n of cand){
        const q = this.pieces[n];
        if(q && q.owner !== owner && !this.disabled.has(n)) out.add(n);
      }
    }
    return out;
  }

  connectedCities(owner, net){
    net = net || this.network(owner);
    const cities = new Set();
    for(const h in this.serverCity){
      const p = this.pieces[h];
      if(p && p.owner === owner && net.has(h) && !this.disabled.has(h))
        cities.add(this.serverCity[h]);
    }
    return cities;
  }

  dcOnline(h, net){
    const owner = this.pieces[h].owner;
    net = net || this.network(owner);
    if(!net.has(h) || this.disabled.has(h)) return false;
    const [x, y] = bbXY(h);
    let routers = 0;
    for(const [nx, ny] of bbNeighbors(x, y)){
      if(!bbIn(nx, ny)) continue;
      const k = bbKey(nx, ny);
      const p = this.pieces[k];
      if(p && p.owner === owner && p.kind === "router" && !this.disabled.has(k))
        routers++;
    }
    if(routers < 2) return false;
    for(const s of net) if(this.pieces[s].kind === "server") return true;
    return false;
  }

  score(owner){
    const net = this.network(owner);
    let vp = this.connectedCities(owner, net).size;
    const dcs = [];
    for(const h in this.pieces){
      const p = this.pieces[h];
      if(p.owner === owner && p.kind === "dc" && net.has(h)
         && !this.disabled.has(h)) dcs.push(h);
    }
    for(const h of dcs) if(this.dcOnline(h, net)) vp++;
    if(dcs.length >= 2) vp += 2;
    return vp;
  }

  _placeOk(owner, kind, k, net){
    if(k in this.pieces || this.citySet.has(k)) return false;
    const [x, y] = bbXY(k);
    if(!bbIn(x, y)) return false;
    if(!this.frontier(owner, net).has(k)) return false;
    if(kind === "switch"){
      let adj = 0;
      for(const [nx, ny] of bbNeighbors(x, y)){
        const p = this.pieces[bbKey(nx, ny)];
        if(p && p.owner === owner) adj++;
      }
      if(adj < 2) return false;
    }
    return true;
  }

  legalActions(owner){
    if(this.winner !== null) return [];
    owner = owner === undefined ? this.toMove : owner;
    const acts = [{a: "pass"}];
    const net = this.network(owner);
    const bw = this.bw[owner];
    const front = this.frontier(owner, net);
    for(const kind of BB_PIECES){
      if(this.supply[owner][kind] < 1 || BB_COST[kind] > bw) continue;
      if(kind === "firewall"){
        for(const h in this.pieces){
          const p = this.pieces[h];
          if(p.owner === owner && !this.firewalls.has(h)){
            const [x, y] = bbXY(h);
            acts.push({a: "build", piece: "firewall", x, y});
          }
        }
        continue;
      }
      for(const h of front){
        const [x, y] = bbXY(h);
        if(kind === "switch"){
          let adj = 0;
          for(const [nx, ny] of bbNeighbors(x, y)){
            const p = this.pieces[bbKey(nx, ny)];
            if(p && p.owner === owner) adj++;
          }
          if(adj < 2) continue;
        }
        if(kind === "server"){
          const adjC = bbNeighbors(x, y).map(([nx,ny]) => bbKey(nx, ny))
            .filter(k => this.citySet.has(k));
          if(adjC.length){
            for(const c of adjC){
              const [cx, cy] = bbXY(c);
              acts.push({a: "build", piece: "server", x, y, city: [cx, cy]});
            }
            continue;
          }
        }
        acts.push({a: "build", piece: kind, x, y});
      }
    }
    if(bw >= this.hackCost && this.disabled.size < BB_MAX_DISABLED
       && (this.hackLimit === null || this.hacksThisTurn < this.hackLimit)){
      for(const h of this.hackable(owner, net)){
        const [x, y] = bbXY(h);
        acts.push({a: "hack", x, y});
      }
    }
    for(const h in this.pieces){
      const p = this.pieces[h];
      if(p.owner !== owner || (p.kind !== "switch" && p.kind !== "ap")) continue;
      if(this.disabled.has(h) || BB_START.includes(h)) continue;
      const [fx, fy] = bbXY(h);
      for(const t of this._rerouteTargets(owner, h)){
        const [tx, ty] = bbXY(t);
        acts.push({a: "reroute", fx, fy, tx, ty});
      }
    }
    return acts;
  }

  _rerouteTargets(owner, h){
    const kind = this.pieces[h].kind;
    const before = this.network(owner).size;
    const trial = this.clone();
    const piece = trial.pieces[h];
    delete trial.pieces[h];
    trial.firewalls.delete(h);
    const out = [];
    const net = trial.network(owner);
    for(const t of trial.frontier(owner, net)){
      if(t === h) continue; // rulebook: reroute moves to a DIFFERENT hex
      const [x, y] = bbXY(t);
      if(kind === "switch"){
        let adj = 0;
        for(const [nx, ny] of bbNeighbors(x, y)){
          const p = trial.pieces[bbKey(nx, ny)];
          if(p && p.owner === owner) adj++;
        }
        if(adj < 2) continue;
      }
      trial.pieces[t] = piece;
      if(trial.network(owner).size >= before) out.push(t);
      delete trial.pieces[t];
    }
    return out;
  }

  isLegal(action, owner){
    owner = owner === undefined ? this.toMove : owner;
    if(this.winner !== null) return false;
    const a = action && action.a;
    if(a === "pass") return true;
    const net = this.network(owner);
    if(a === "build"){
      const kind = action.piece;
      const k = bbKey(action.x, action.y);
      if(!BB_PIECES.includes(kind) || this.supply[owner][kind] < 1
         || this.bw[owner] < BB_COST[kind]) return false;
      if(kind === "firewall"){
        const p = this.pieces[k];
        return !!p && p.owner === owner && !this.firewalls.has(k);
      }
      if(!this._placeOk(owner, kind, k, net)) return false;
      if(kind === "server"){
        const adjC = bbNeighbors(action.x, action.y)
          .map(([nx,ny]) => bbKey(nx, ny)).filter(c => this.citySet.has(c));
        if(adjC.length){
          return action.city != null
            && adjC.includes(bbKey(action.city[0], action.city[1]));
        }
        return action.city == null;
      }
      return true;
    }
    if(a === "hack"){
      const k = bbKey(action.x, action.y);
      return this.bw[owner] >= this.hackCost
        && this.disabled.size < BB_MAX_DISABLED
        && (this.hackLimit === null || this.hacksThisTurn < this.hackLimit)
        && this.hackable(owner, net).has(k);
    }
    if(a === "reroute"){
      const f = bbKey(action.fx, action.fy);
      const t = bbKey(action.tx, action.ty);
      const p = this.pieces[f];
      if(!p || p.owner !== owner || (p.kind !== "switch" && p.kind !== "ap")
         || this.disabled.has(f) || BB_START.includes(f)) return false;
      return this._rerouteTargets(owner, f).includes(t);
    }
    return false;
  }

  apply(action){
    const owner = this.toMove;
    const a = action.a;
    if(a === "pass") this.passStreak += 1;
    else this.passStreak = 0;
    if(a === "build"){
      const kind = action.piece;
      const k = bbKey(action.x, action.y);
      this.bw[owner] -= BB_COST[kind];
      this.supply[owner][kind] -= 1;
      if(kind === "firewall") this.firewalls.add(k);
      else{
        this.pieces[k] = {owner, kind};
        if(kind === "server" && action.city != null)
          this.serverCity[k] = bbKey(action.city[0], action.city[1]);
      }
    }else if(a === "hack"){
      const k = bbKey(action.x, action.y);
      this.bw[owner] -= this.hackCost;
      this.hacksThisTurn += 1;
      if(this.firewalls.has(k)){
        this.firewalls.delete(k);
        this.supply[this.pieces[k].owner].firewall += 1;
      }else this.disabled.add(k);
    }else if(a === "reroute"){
      const f = bbKey(action.fx, action.fy);
      const t = bbKey(action.tx, action.ty);
      const moved = this.pieces[f];
      delete this.pieces[f];
      this.pieces[t] = moved;
      if(this.firewalls.has(f)){ this.firewalls.delete(f); this.firewalls.add(t); }
      if(f in this.serverCity){ this.serverCity[t] = this.serverCity[f]; delete this.serverCity[f]; }
    }
    this.actionsLeft -= 1;
    if(this.actionsLeft <= 0) this._endTurn(owner);
  }

  _endTurn(owner){
    if(this.recoverBeforeScore)
      this.disabled = new Set([...this.disabled]
        .filter(h => this.pieces[h].owner !== owner));
    const s = this.score(owner);
    if(this.finalPending && owner === 1){
      // P1 reached the target last turn; P2 just took the equalizer
      const s0 = this.score(0);
      if(s > s0) this.winner = 1;
      else if(s === s0){
        const c0 = this.connectedCities(0).size, c1 = this.connectedCities(1).size;
        this.winner = c1 > c0 ? 1 : c0 > c1 ? 0 : "draw";
      }else this.winner = 0;
      return;
    }
    if(s >= this.targetVp){
      if(this.finalTurn && owner === 0){
        this.finalPending = true;  // P2 gets one last turn
      }else{
        this.winner = owner;
        return;
      }
    }
    if(this.passStreak >= 4){
      const s0 = this.score(0), s1 = this.score(1);
      if(s0 !== s1) this.winner = s0 > s1 ? 0 : 1;
      else{
        const c0 = this.connectedCities(0).size, c1 = this.connectedCities(1).size;
        this.winner = c0 > c1 ? 0 : c1 > c0 ? 1 : "draw";
      }
      return;
    }
    this.disabled = new Set([...this.disabled]
      .filter(h => this.pieces[h].owner !== owner));
    this.toMove ^= 1;
    this.actionsLeft = 2;
    this.hacksThisTurn = 0;
    this.turnNo += 1;
    this._income(this.toMove);
  }

  _income(owner){
    const gain = BB_INCOME_BASE + this.connectedCities(owner).size;
    this.bw[owner] = Math.min(BB_HAND_LIMIT, this.bw[owner] + gain);
  }
}

// ---------------- AI (port of backbone_engine.evaluate / ai_action) ----------------
function bbEvaluate(board, owner){
  if(board.winner !== null){
    if(board.winner === owner) return 10000;
    if(board.winner === (owner ^ 1)) return -10000;
    return 0;
  }
  function side(o){
    const net = board.network(o);
    let v = board.score(o) * 120.0;
    v += board.bw[o] * 1.5;
    const cities = board.connectedCities(o, net);
    v += cities.size * 10;
    let serversOk = false;
    for(const h of net) if(board.pieces[h].kind === "server"){ serversOk = true; break; }
    for(const h in board.pieces){
      const p = board.pieces[h];
      if(p.owner !== o) continue;
      if(p.kind === "dc"){
        const [x, y] = bbXY(h);
        let routers = 0;
        for(const [nx, ny] of bbNeighbors(x, y)){
          const k = bbKey(nx, ny);
          const q = board.pieces[k];
          if(q && q.owner === o && q.kind === "router" && !board.disabled.has(k)) routers++;
        }
        v += Math.min(routers, 2) * 8;
        if(net.has(h)){ v += 6; if(serversOk) v += 6; }
      }
      if(board.disabled.has(h)) v -= 9;
    }
    for(const c of board.cities){
      const ck = bbKey(c[0], c[1]);
      if(cities.has(ck)) continue;
      let d = 9;
      for(const h of net) d = Math.min(d, bbHexDistance(bbXY(h), c));
      v += Math.max(0, 5 - d) * 1.2;
    }
    v += net.size * 1.0;
    const threat = board.hackable(o ^ 1);
    for(const h of threat){
      const p = board.pieces[h];
      if(p.owner === o && !board.firewalls.has(h))
        v -= (p.kind === "server" || p.kind === "dc") ? 6 : 2;
    }
    return v;
  }
  return side(owner) - side(owner ^ 1);
}

function bbCandidates(board, owner, cap){
  cap = cap || 26;
  const acts = board.legalActions(owner);
  if(acts.length <= 1) return acts;
  const scored = [];
  for(const act of acts){
    const nb = board.clone();
    nb.actionsLeft = 99;
    nb.apply(act);
    scored.push([bbEvaluate(nb, owner), act]);
  }
  scored.sort((a, b) => b[0] - a[0]);
  return scored.slice(0, cap).map(s => s[1]);
}

function bbAiAction(board, timeBudget, width, noise){
  timeBudget = timeBudget || 0.5; width = width || 8; noise = noise || 0;
  const owner = board.toMove;
  const deadline = Date.now() + timeBudget * 1000;
  const cands = bbCandidates(board, owner);
  if(!cands.length) return {a: "pass"};
  if(cands.length === 1) return cands[0];
  let best = cands[0], bestV = -1e18;
  for(const act of cands.slice(0, width)){
    const nb = board.clone();
    nb.apply(act);
    if(nb.winner === owner) return act;
    let v;
    if(nb.toMove === owner && nb.winner === null){
      v = -1e18;
      for(const act2 of bbCandidates(nb, owner, 10)){
        const nb2 = nb.clone();
        nb2.apply(act2);
        v = Math.max(v, bbEvaluate(nb2, owner));
        if(Date.now() > deadline) break;
      }
    }else v = bbEvaluate(nb, owner);
    if(noise) v += (Math.random() * 2 - 1) * noise;
    if(v > bestV){ bestV = v; best = act; }
    if(Date.now() > deadline) break;
  }
  return best;
}

const BB_DIFF = {easy: [0.15, 3, 25.0], normal: [0.6, 8, 4.0], hard: [1.5, 14, 0.0]};

function bbAiMove(board, difficulty){
  const [budget, width, noise] = BB_DIFF[difficulty] || BB_DIFF.normal;
  return bbAiAction(board, budget, width, noise);
}

// ---------------- plain-language move explanations ----------------
const BB_KIND_NAMES = {router:"Router", switch:"Switch", ap:"Wireless AP",
                       firewall:"Firewall", server:"Server", dc:"Datacenter"};

function bbClosestUnclaimedCityDist(board, owner, h){
  const owned=board.connectedCities(owner);
  const others=board.cities.filter(c=>!owned.has(bbKey(c[0],c[1])));
  if(!others.length) return null;
  return Math.min(...others.map(c=>bbHexDistance(h,c)));
}

function bbNetworkSplitSize(board, victimOwner, hexToDisable){
  const before=board.network(victimOwner).size;
  const trial=board.clone();
  trial.disabled.add(hexToDisable);
  const after=trial.network(victimOwner).size;
  return Math.max(0, before-after-1);
}

function bbIsBridge(board, owner, h){
  const before=board.network(owner).size;
  const trial=board.clone();
  trial.disabled.add(h);
  const after=trial.network(owner).size;
  return after<before-1;
}

function bbFeedsADc(board, owner, routerHex){
  const [rx,ry]=bbXY(routerHex);
  for(const h in board.pieces){
    const p=board.pieces[h];
    if(p.owner===owner && p.kind==="dc"){
      const [x,y]=bbXY(h);
      if(bbNeighbors(x,y).some(([nx,ny])=>bbKey(nx,ny)===routerHex)){
        let cnt=0;
        for(const [nx,ny] of bbNeighbors(x,y)){
          const nk=bbKey(nx,ny);
          const q=board.pieces[nk];
          if(q && q.owner===owner && q.kind==="router" && !board.disabled.has(nk)) cnt++;
        }
        if(cnt<=2) return true;
      }
    }
  }
  return false;
}

function bbExplainAction(board, action, owner){
  const a=action.a, opp=owner^1;
  if(a==="pass") return {text:"Nothing productive left to do this action — saving it.", aim:"wait"};
  if(a==="hack"){
    const h=bbKey(action.x,action.y);
    const p=board.pieces[h];
    const kind=p?p.kind:"piece";
    const bits=[];
    const split=bbNetworkSplitSize(board,opp,h);
    if(split>0) bits.push(`cutting ${split} of their piece${split!==1?'s':''} off from their network`);
    if(kind==="server" && board.serverCity[h]) bits.push("breaking their connection to a City");
    if(kind==="dc") bits.push("taking a Datacenter offline");
    if(kind==="router" && bbFeedsADc(board,opp,h)) bits.push("undermining a Datacenter's Router support");
    if(!bits.length) bits.push("denying them a piece and some tempo for a turn");
    return {text:`Hacked the enemy ${BB_KIND_NAMES[kind]||kind} — `+bits.join("; ")+".", aim:"disrupt"};
  }
  if(a==="reroute"){
    const f=bbKey(action.fx,action.fy), t=bbKey(action.tx,action.ty);
    const kind=board.pieces[f].kind;
    const d0=bbClosestUnclaimedCityDist(board,owner,bbXY(f));
    const d1=bbClosestUnclaimedCityDist(board,owner,bbXY(t));
    if(d0!==null && d1!==null && d1<d0)
      return {text:`Repositioned a ${BB_KIND_NAMES[kind]} to reach closer toward an unclaimed City.`, aim:"expand"};
    return {text:`Repositioned a ${BB_KIND_NAMES[kind]} to firm up the network's shape.`, aim:"consolidate"};
  }
  if(a==="build"){
    const kind=action.piece, h=bbKey(action.x,action.y), hxy=[action.x,action.y];
    if(kind==="dc"){
      let routers=0;
      for(const [nx,ny] of bbNeighbors(action.x,action.y)){
        const q=board.pieces[bbKey(nx,ny)];
        if(q && q.owner===owner && q.kind==="router") routers++;
      }
      if(routers>=2) return {text:"Built a Datacenter — already backed by 2 Routers, so it comes online immediately for +1 AI token.", aim:"score"};
      return {text:`Built a Datacenter — needs ${2-routers} more adjacent Router(s) before it starts earning AI tokens.`, aim:"expand"};
    }
    if(kind==="server"){
      if(action.city!=null) return {text:"Built a Server to connect a City — +1 AI token as long as it stays networked.", aim:"score"};
      return {text:"Built a Server to satisfy a nearby Datacenter's requirement (no City adjacent here).", aim:"expand"};
    }
    if(kind==="router"){
      const enemyNear=bbNeighbors(action.x,action.y).some(([nx,ny])=>{
        const q=board.pieces[bbKey(nx,ny)]; return q && q.owner===opp;
      });
      const d=bbClosestUnclaimedCityDist(board,owner,hxy);
      if(enemyNear) return {text:"Pushed a Router into contested ground, within reach of the enemy's pieces.", aim:"expand"};
      if(d!==null && d<=3) return {text:"Extended a Router toward an unclaimed City to set up a Server there.", aim:"expand"};
      return {text:"Extended the network with a Router to open up more building room.", aim:"expand"};
    }
    if(kind==="switch") return {text:"Filled a gap with a Switch — cheap glue to keep the network efficient.", aim:"consolidate"};
    if(kind==="ap") return {text:"Placed a Wireless AP to jump the network across a hex it couldn't otherwise cross.", aim:"expand"};
    if(kind==="firewall"){
      if(bbIsBridge(board,owner,h)) return {text:"Shielded the piece holding two halves of the network together.", aim:"defend"};
      const p=board.pieces[h];
      if(p && p.kind==="dc") return {text:"Shielded a Datacenter from being hacked offline.", aim:"defend"};
      if(board.serverCity[h]) return {text:"Shielded the Server feeding a City connection.", aim:"defend"};
      return {text:"Placed a Firewall to protect a piece from the next hack.", aim:"defend"};
    }
  }
  return {text:"Took an action.", aim:"other"};
}

function bbSerialize(board){
  const pieces = {};
  for(const k in board.pieces)
    pieces[k] = {owner: board.pieces[k].owner, kind: board.pieces[k].kind};
  const sc = {};
  for(const k in board.serverCity) sc[k] = bbXY(board.serverCity[k]);
  return {
    game: "backbone", W: BB_W, H: BB_H,
    cities: board.cities.map(c => [...c]),
    start: [bbXY(BB_START[0]), bbXY(BB_START[1])],
    pieces,
    firewalls: [...board.firewalls],
    disabled: [...board.disabled],
    server_city: sc,
    bw: [...board.bw],
    supply: [{...board.supply[0]}, {...board.supply[1]}],
    to_move: board.toMove,
    actions_left: board.actionsLeft,
    turn_no: board.turnNo,
    vp: [board.score(0), board.score(1)],
    cities_connected: [
      [...board.connectedCities(0)].map(bbXY),
      [...board.connectedCities(1)].map(bbXY)],
    network: [
      [...board.network(0)].map(bbXY),
      [...board.network(1)].map(bbXY)],
    dc_online: (()=>{
      const out={};
      for(const k in board.pieces) if(board.pieces[k].kind==="dc") out[k]=board.dcOnline(k);
      return out;
    })(),
    winner: board.winner,
    legal: board.winner === null ? board.legalActions() : [],
  };
}

// Offline adapter for standalone play (mirrors ServerAdapter shape).
class BackboneLocalAdapter{
  constructor(){this.mode="local";this.online=false;this.games={};this._n=1;}
  _meta(id){
    const g=this.games[id];
    const w=g.b.winner;
    return {id, game_type:"backbone", type:"ai",
      status: w===null?"active":"finished",
      your_side:g.human, white:g.human===0?"you":"AI",
      black:g.human===1?"you":"AI",
      winner: w===null?null:(w==="draw"?"draw":String(w)),
      win_type: w===null?null:"victory", ply:g.ply, draw_offer_by:null,
      rated:false};
  }
  async newGameTyped(gt,difficulty,humanSide){
    const id="local-"+(this._n++);
    const human=(humanSide===1)?1:0;
    this.games[id]={b:new BackboneBoard(),difficulty:difficulty||"normal",human,ply:0};
    return {id, game_id:id, human_side:human,
            state:bbSerialize(this.games[id].b), meta:this._meta(id)};
  }
  async moveAction(id,action){
    const g=this.games[id];
    if(!g) return {error:"no such game"};
    if(!g.b.isLegal(action)) return {error:"illegal action"};
    g.b.apply(action); g.ply++;
    return {move:action, state:bbSerialize(g.b), meta:this._meta(id)};
  }
  async aiMove(id){
    const g=this.games[id];
    if(!g) return {error:"no such game"};
    if(g.b.winner!==null) return {move:null, state:bbSerialize(g.b), meta:this._meta(id)};
    const aiSide=g.human^1;
    const act=bbAiMove(g.b,g.difficulty);
    const explain=bbExplainAction(g.b,act,aiSide);
    g.b.apply(act); g.ply++;
    return {move:act, info:{difficulty:g.difficulty, explain},
            state:bbSerialize(g.b), meta:this._meta(id)};
  }
  async state(id){
    const g=this.games[id];
    return g?{state:bbSerialize(g.b),meta:this._meta(id),v:g.ply}:{error:"no such game"};
  }
  async resign(id){
    const g=this.games[id];
    g.b.winner=g.human^1;
    return {state:bbSerialize(g.b), meta:this._meta(id)};
  }
}
