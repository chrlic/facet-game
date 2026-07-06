"use strict";
const ORTH=[[1,0],[-1,0],[0,1],[0,-1]];
const DIAG=[[1,1],[1,-1],[-1,1],[-1,-1]];
const KING=[...ORTH,...DIAG];
const KNIGHT_DIRS=[[1,2],[2,1],[-1,2],[-2,1],[1,-2],[2,-1],[-1,-2],[-2,-1]];
const SLIDERS={R:ORTH,B:DIAG,T:KING};
const INF=1e9;
const _EXACT=0,_LOWER=1,_UPPER=2;
const DECAY_MAP={R:'B',B:'N',N:'F',F:'F',T:'T'};
const FOG_RADIUS=2,FOG_MONARCH_RADIUS=3;
const FOG_MEMORY_PLIES=12; // how long the AI remembers an out-of-sight enemy sighting
const DECAY_BOARDS=new Set(['classic','standard8','sprawl','arena9','temple9']);
// standard8 removed 2026-07: with memory-AI validation its fog games collapse
// into a forced first-mover coronation race (P0 0.84-0.95 even at hold 4-5)
const FOG_BOARDS=new Set(['knights','diamond8','temple9','lantern8']);
// momentum: a stone leaving a special tile keeps that rank for one more move.
// 400-game validated boards only (standard8 passed at combined n=800, ratio
// 0.497 CI [0.46, 0.53]); mutually exclusive with decay (combo tested
// degenerate) and fog (untested). Throne-rank included — removing it broke
// balance in validation.
const MOMENTUM_BOARDS=new Set(['classic','citadel','knights','diamond8','standard8']);
const MOMENTUM_GLYPHS=new Set(['R','B','N','T']);

const BOARDS={
classic:{name:"Classic 7x7",desc:"The original — two thrones in the centre corridor.",size:[7,7],rows:["FFFFFFF","FFFFFFF","BFNFNFB","RFTFTFR","BFNFNFB","FFFFFFF","FFFFFFF"]},
knights:{name:"Knight's Arena 7x7",desc:"Gates everywhere — chaotic leaping battles.",size:[7,7],rows:["FNFFFNF","NFFFFFN","NFNFNFN","FFTFTFF","NFNFNFN","NFFFFFN","FNFFFNF"]},
sprawl:{name:"Sprawl 9x9",desc:"Features scattered wide — long sight lines, two thrones.",size:[9,9],rows:["FFFFFFFFF","FNFFFFFNF","FFFBFBFFF","FFFFFFFFF","RFFTFTFFR","FFFFFFFFF","FFFBFBFFF","FNFFFFFNF","FFFFFFFFF"]},
citadel:{name:"Citadel 9x9",desc:"Thrones on the flanks, guarded by a ring of features.",size:[9,9],rows:["FFFFFFFFF","FFBFFFBFF","FNFFFRNFF","FFFFTFFFF","FFFFFFFFF","FFFFTFFFF","FFNRFFFNF","FFBFFFBFF","FFFFFFFFF"]},
crossroads:{name:"Crossroads 7x7",desc:"Features at intersections — control the crossroads to dominate.",size:[7,7],rows:["FFFNFFF","FFBFBFF","FRFFFRF","NFTFTFN","FRFFFRF","FFBFBFF","FFFNFFF"]},
standard8:{name:"Standard 8x8",desc:"Chess-sized board — two thrones, balanced terrain.",size:[8,8],rows:["FFFFFFFF","FFFFFFFF","FBNFFNBF","RFFTFFRF","FRFFTFFR","FBNFFNBF","FFFFFFFF","FFFFFFFF"]},
diamond8:{name:"Diamond 8x8",desc:"Features form a diamond — thrones at the heart.",size:[8,8],rows:["FFFFFFFF","FFFNFFFF","FFBFFBFF","FNFTFNFF","FFNFTFNF","FFBFFBFF","FFFFNFFF","FFFFFFFF"]},
arena9:{name:"Arena 9x9",desc:"Open centre ringed by features — all-out brawl.",size:[9,9],rows:["FFFFFFFFF","FFFFFFFFF","FFNBRBNFF","FFRFFFRFF","FBFTFTFBF","FFRFFFRFF","FFNBRBNFF","FFFFFFFFF","FFFFFFFFF"]},
flux9:{name:"Flux 9x9",desc:"Features spiral around the thrones — fluid, shifting play.",size:[9,9],rows:["FFFFFFFFF","FFNFFFBFF","FFFFRFFFF","FBFFFTFFF","FFFFFFFFF","FFFTFFFBF","FFFFRFFFF","FFBFFFNFF","FFFFFFFFF"]},
temple9:{name:"Temple 9x9",desc:"Power tiles guard the thrones — fight through to coronation.",size:[9,9],rows:["FFFFFFFFF","FFFFFFFFF","FFBRFRBFF","FFNFTFNFF","FFFFFFFFF","FFNFTFNFF","FFBRFRBFF","FFFFFFFFF","FFFFFFFFF"]},
lantern8:{name:"Lantern 8x8",desc:"Thrones on far flanks — built for the fog: no single sortie takes both.",size:[8,8],rows:["FFFFFFFF","FNFFRFNF","FFBFFBFF","FFFNFFTF","FTFFNFFF","FFBFFBFF","FNFRFFNF","FFFFFFFF"]},
};

// boards suitable for plain (no-mode) play; fog-specialist layouts are excluded
const CLASSIC_BOARDS=new Set(Object.keys(BOARDS).filter(k=>k!=='lantern8'));

function _makeBoard(rows,W,H,p0c,p1c){
  const terrain={};
  for(let i=0;i<rows.length;i++){const y=H-1-i;for(let x=0;x<rows[i].length;x++) terrain[x+","+y]=rows[i][x];}
  const mid=W>>1;
  if(!p0c){p0c=[];for(let x=0;x<W;x++) p0c.push([x,0]);}
  if(!p1c){p1c=[];for(let x=0;x<W;x++) p1c.push([x,H-1]);}
  const pieces={};
  const p0back=Math.min(...p0c.map(c=>c[1]));
  const p1back=Math.max(...p1c.map(c=>c[1]));
  for(const[x,y]of p0c) pieces[x+","+y]={owner:0,monarch:x===mid&&y===p0back};
  for(const[x,y]of p1c) pieces[x+","+y]={owner:1,monarch:x===mid&&y===p1back};
  return new Board(W,H,terrain,pieces);
}

function makeBoard(id,modes){
  const spec=BOARDS[id]||BOARDS.classic;
  const[W,H]=spec.size;
  const rows=spec.rows.map(r=>r.replace(/ /g,"").slice(0,W));
  let p0=null,p1=null;
  if(W===9&&H===9){
    p0=[];p1=[];
    for(let x=0;x<W;x++){p0.push([x,0]);p1.push([x,H-1]);}
    p0.push([2,1],[6,1]);p1.push([6,H-2],[2,H-2]);
  }
  const board=_makeBoard(rows,W,H,p0,p1);
  if(modes){board.modes=new Set(modes);if(board.modes.has('decay'))board.terrain={...board.terrain};}
  return board;
}

class Board{
  constructor(W,H,terrain,pieces,toMove=0,throneHeldSince=null,modes=null){
    this.W=W;this.H=H;this.terrain=terrain;this.pieces=pieces;
    this.toMove=toMove;this.throneHeldSince=throneHeldSince;
    this.modes=modes||new Set();
    this.throneHoldPlies=3;
    this.linger={}; // momentum mode: cell -> retained glyph (one move)
  }
  clone(){
    const t=this.modes.has('decay')?{...this.terrain}:this.terrain;
    const b=new Board(this.W,this.H,t,{...this.pieces},this.toMove,this.throneHeldSince,new Set(this.modes));
    b.throneHoldPlies=this.throneHoldPlies;
    b.linger={...this.linger};
    if(this._partial){b._partial=true;b._viewer=this._viewer;b._unseen=this._unseen||0;}return b;
  }
  key(){
    const pk=Object.keys(this.pieces).sort().map(k=>{const p=this.pieces[k];return k+":"+p.owner+p.monarch;}).join("|");
    const th=this.throneHeldSince?this.throneHeldSince[0]+","+this.throneHeldSince[1]:"n";
    let base=pk+"/"+this.toMove+"/"+th;
    if(this.modes.has('decay')) base+="/"+Object.entries(this.terrain).sort().map(([k,v])=>k+v).join("");
    if(this.modes.has('momentum')) base+="/"+Object.entries(this.linger).sort().map(([k,v])=>k+v).join("");
    return base;
  }
  monarchAlive(owner){for(const k in this.pieces){const p=this.pieces[k];if(p.owner===owner&&p.monarch)return true;}return false;}
  monarchCell(owner){for(const k in this.pieces){const p=this.pieces[k];if(p.owner===owner&&p.monarch)return k;}return null;}
  thrones(){const out=[];for(const k in this.terrain)if(this.terrain[k]==="T")out.push(k);return out;}
  throneHolder(){
    const ts=this.thrones();if(!ts.length)return null;
    const owners=new Set();
    for(const c of ts){const p=this.pieces[c];if(!p)return null;owners.add(p.owner);}
    return owners.size===1?[...owners][0]:null;
  }
  pieceCount(owner){let n=0;for(const k in this.pieces)if(this.pieces[k].owner===owner)n++;return n;}
  winner(){
    const pp=this._partial,vw=this._viewer;
    if(!this.monarchAlive(0)){if(!(pp&&0!==vw))return 1;}
    if(!this.monarchAlive(1)){if(!(pp&&1!==vw))return 0;}
    if(!pp){if(this.pieceCount(0)===1)return 1;if(this.pieceCount(1)===1)return 0;}
    const th=this.throneHolder();
    if(th!==null&&this.throneHeldSince&&this.throneHeldSince[0]===th&&this.throneHeldSince[1]>=this.throneHoldPlies)return th;
    if(!this.legalMoves(this.toMove).length)return"draw";
    return null;
  }
  _ok(nx,ny,owner){const k=nx+","+ny;if(!(k in this.terrain))return false;const p=this.pieces[k];return!p||p.owner!==owner;}
  _glyphMoves(ck,g,o){
    const[x,y]=ck.split(",").map(Number);const out=[];
    if(g==="F"){for(const[dx,dy]of KING)if(this._ok(x+dx,y+dy,o))out.push((x+dx)+","+(y+dy));}
    else if(g==="N"){for(const[dx,dy]of KNIGHT_DIRS)if(this._ok(x+dx,y+dy,o))out.push((x+dx)+","+(y+dy));}
    else if(SLIDERS[g]){for(const[dx,dy]of SLIDERS[g]){let nx=x+dx,ny=y+dy;while((nx+","+ny)in this.terrain){const k2=nx+","+ny;const occ=this.pieces[k2];if(!occ)out.push(k2);else{if(occ.owner!==o)out.push(k2);break;}nx+=dx;ny+=dy;}}}
    return out;
  }
  movesFor(ck){
    const p=this.pieces[ck];
    if(p.monarch)return this._glyphMoves(ck,"F",p.owner);
    const g=this.terrain[ck];
    const out=this._glyphMoves(ck,g,p.owner);
    const lg=this.linger[ck];
    if(lg&&lg!==g){ // momentum: retained rank adds to tile moves
      const seen=new Set(out);
      for(const m of this._glyphMoves(ck,lg,p.owner))if(!seen.has(m))out.push(m);
    }
    return out;
  }
  legalMoves(owner){
    const mv=[];for(const ck in this.pieces)if(this.pieces[ck].owner===owner)for(const to of this.movesFor(ck))mv.push([ck,to]);return mv;
  }
  apply(mv){
    const[fr,to]=mv;
    const g=this.terrain[fr]||'F';
    if(this.modes.has('decay'))this.terrain[fr]=DECAY_MAP[g]||g;
    const piece=this.pieces[fr];
    this.pieces[to]=piece;delete this.pieces[fr];
    if(this.modes.has('momentum')){
      delete this.linger[fr];   // retained rank is spent (used or not)
      delete this.linger[to];   // captured piece's rank dies with it
      if(!piece.monarch&&MOMENTUM_GLYPHS.has(g))this.linger[to]=g; // rank travels one move
    }
    this.toMove^=1;
    const th=this.throneHolder();
    if(th!==null){if(this.throneHeldSince&&this.throneHeldSince[0]===th)this.throneHeldSince=[th,this.throneHeldSince[1]+1];else this.throneHeldSince=[th,1];}
    else this.throneHeldSince=null;
  }
  visibleCells(owner){
    const vis=new Set();
    for(const ck in this.pieces){
      const p=this.pieces[ck];if(p.owner!==owner)continue;
      const[cx,cy]=ck.split(",").map(Number);
      const r=p.monarch?FOG_MONARCH_RADIUS:FOG_RADIUS;
      for(let dx=-r;dx<=r;dx++)for(let dy=-r;dy<=r;dy++){
        if(Math.abs(dx)+Math.abs(dy)<=r){const k=(cx+dx)+","+(cy+dy);if(k in this.terrain)vis.add(k);}
      }
    }
    for(const t of this.thrones())vis.add(t);
    return vis;
  }
  fogView(owner){
    if(!this.modes.has('fog'))return this;
    const vis=this.visibleCells(owner);
    const t=this.modes.has('decay')?{...this.terrain}:this.terrain;
    const filtered={};
    for(const k in this.pieces){const p=this.pieces[k];if(p.owner===owner||vis.has(k))filtered[k]=p;}
    const m=new Set(this.modes);m.delete('fog');
    const b=new Board(this.W,this.H,t,filtered,this.toMove,this.throneHeldSince,m);
    b.throneHoldPlies=this.throneHoldPlies;
    b.linger={...this.linger};
    b._partial=true;b._viewer=owner;return b;
  }
}

// Fog movement rule: moves are planned on the mover's fog view, so a slider's
// path may cross a hidden enemy. The slide stops there and captures it ('bump').
// Returns [resolvedMove, bumped].
function resolveFogMove(board,mv,viewer){
  if(!board.modes.has('fog'))return[mv,false];
  const[fk,tk]=mv;
  const p=board.pieces[fk];
  if(!p||p.monarch)return[mv,false];
  if(!SLIDERS[board.terrain[fk]||'F'])return[mv,false];
  const[fx,fy]=fk.split(",").map(Number),[tx,ty]=tk.split(",").map(Number);
  const dx=Math.sign(tx-fx),dy=Math.sign(ty-fy);
  let x=fx+dx,y=fy+dy;
  while((x!==tx||y!==ty)&&((x+","+y)in board.terrain)){
    const occ=board.pieces[x+","+y];
    if(occ){
      if(occ.owner!==viewer)return[[fk,x+","+y],true];
      return[mv,false]; // own pieces are always visible; leave to validation
    }
    x+=dx;y+=dy;
  }
  return[mv,false];
}

// Fog view plus what a human naturally has: memory of recent enemy sightings
// (ghosts, kept FOG_MEMORY_PLIES of the owner's turns) and the count of enemy
// pieces still alive (known from capture accounting). Never widens vision.
function fogViewForAI(board,owner){
  const view=board.fogView(owner);
  if(!board.modes.has('fog'))return view;
  if(!board._aiMemory)board._aiMemory={};
  const mem=board._aiMemory[owner]||(board._aiMemory[owner]={seen:{},seq:0});
  mem.seq++;
  const seq=mem.seq,seen=mem.seen;
  const vis=board.visibleCells(owner);
  for(const c of vis){
    const occ=board.pieces[c];
    if(occ&&occ.owner!==owner){
      if(occ.monarch)for(const k in seen)if(seen[k][0].monarch)delete seen[k];
      seen[c]=[occ,seq];
    }else if(c in seen)delete seen[c];
  }
  for(const c in seen)if(seq-seen[c][1]>FOG_MEMORY_PLIES)delete seen[c];
  let enemyMonVisible=false;
  for(const k in view.pieces){const p=view.pieces[k];if(p.owner!==owner&&p.monarch)enemyMonVisible=true;}
  for(const c in seen){
    if(c in view.pieces||vis.has(c))continue;
    const pc=seen[c][0];
    if(pc.monarch&&enemyMonVisible)continue;
    view.pieces[c]=pc;
  }
  let visibleEnemy=0;
  for(const k in view.pieces)if(view.pieces[k].owner!==owner)visibleEnemy++;
  view._unseen=Math.max(0,board.pieceCount(owner^1)-visibleEnemy);
  return view;
}

// ---- AI ----
function mobility(board,ck){return board.movesFor(ck).length;}

function evaluate(board,owner){
  const pp=board._partial,vw=board._viewer;
  if(!board.monarchAlive(owner)){if(!(pp&&owner!==vw))return-INF;}
  if(!board.monarchAlive(owner^1)){if(!(pp&&(owner^1)!==vw))return INF;}
  if(!pp){if(board.pieceCount(owner)===1)return-INF;if(board.pieceCount(owner^1)===1)return INF;}
  const th=board.throneHolder();
  const hs=board.throneHeldSince;
  if(th!==null&&hs&&hs[0]===th&&hs[1]>=board.throneHoldPlies-1){
    // opponent already had their last chance to contest — effectively won
    return th===owner?INF/2:-INF/2;
  }
  let score=0;
  if(th===owner)score+=12;
  else if(th===(owner^1))score-=12;
  const emc=board.monarchCell(owner^1),mmc=board.monarchCell(owner);
  const ts=board.thrones();
  const myC=board.pieceCount(owner),oppC=board.pieceCount(owner^1);
  const _xy=k=>k.split(",").map(Number);
  for(const ck in board.pieces){
    const p=board.pieces[ck];const[cx,cy]=_xy(ck);
    let val=p.monarch?1000:3+0.6*mobility(board,ck);
    if(!p.monarch){
      const tgt=p.owner===owner?emc:mmc;
      if(tgt){const[tx,ty]=_xy(tgt);const d=Math.abs(cx-tx)+Math.abs(cy-ty);val+=Math.max(0,4-d)*0.45;}
      for(const t of ts){const[tx,ty]=_xy(t);const dt=Math.abs(cx-tx)+Math.abs(cy-ty);if(dt<=2)val+=(3-dt)*0.6;}
    }
    score+=p.owner===owner?val:-val;
  }
  if(!pp){score+=(myC-oppC)*5;if(oppC===2)score+=15;}
  if(myC===2)score-=15;
  if(pp&&vw!==undefined&&vw!==null){
    // unseen enemies exist: reward the viewer for keeping the monarch
    // guarded and the thrones covered instead of overextending
    const unseen=board._unseen||0;
    if(unseen){
      const vmc=board.monarchCell(vw);
      let guards=0;
      if(vmc){
        const[mx,my]=_xy(vmc);
        for(const ck in board.pieces){
          const p=board.pieces[ck];
          if(p.owner===vw&&!p.monarch){
            const[cx,cy]=_xy(ck);
            if(Math.abs(cx-mx)+Math.abs(cy-my)<=2)guards++;
          }
        }
      }
      let cover=0;
      for(const t of ts){
        const[tx,ty]=_xy(t);
        for(const ck in board.pieces){
          const p=board.pieces[ck];
          if(p.owner===vw&&!p.monarch){
            const[cx,cy]=_xy(ck);
            if(Math.abs(cx-tx)+Math.abs(cy-ty)<=2){cover++;break;}
          }
        }
      }
      const caution=(Math.min(guards,3)*0.4+cover*0.35)*Math.min(unseen,6);
      score+=owner===vw?caution:-caution;
    }
  }
  return score;
}

function _order(board,moves,killers,history){
  const score=mv=>{
    const occ=board.pieces[mv[1]];
    if(occ&&occ.monarch)return 0;
    if(occ)return 1e6;
    if(killers&&killers.includes(mv[0]+">"+mv[1]))return 2e6;
    if(board.terrain[mv[1]]==="T")return 3e6;
    const h=history?-(history.get(mv[0]+">"+mv[1])||0):0;
    return 4e6+h;
  };
  return moves.slice().sort((a,b)=>score(a)-score(b));
}

class Searcher{
  constructor(timeBudget=1,maxDepth=5,noise=0){
    this.timeBudget=timeBudget;this.maxDepth=maxDepth;this.noise=noise;
    this.deadline=0;this.tt=new Map();this.nodes=0;
    this.killers={};this.history=new Map();
  }
  _storeKiller(depth,mv){
    const k=mv[0]+">"+mv[1];const pair=this.killers[depth];
    if(!pair)this.killers[depth]=[k,null];
    else if(k!==pair[0]){pair[1]=pair[0];pair[0]=k;}
  }
  search(board,owner){
    this.deadline=Date.now()+this.timeBudget*1000;
    let best=null,bestScore=-INF,reached=0;
    this.history.clear();
    let moves=_order(board,board.legalMoves(board.toMove));
    if(!moves.length)return[null,0,0];
    this.tt.clear();
    for(let depth=1;depth<=this.maxDepth;depth++){
      this.killers={};
      let curBest=null,curScore=-INF,a=-INF;
      const ordered=best?[[best[0],best[1]],...moves.filter(m=>m[0]!==best[0]||m[1]!==best[1])]:moves;
      try{
        for(const mv of ordered){
          const nb=board.clone();nb.apply(mv);
          const v=-this._ab(nb,owner,depth-1,-INF,-a);
          if(v>curScore){curScore=v;curBest=mv;}
          a=Math.max(a,v);
        }
      }catch(e){if(e.message==="timeout")break;throw e;}
      best=curBest;bestScore=curScore;reached=depth;
      if(bestScore>=INF/2)break;
    }
    if(!best)best=moves[0]; // timed out before finishing any move: play something legal
    return[best,bestScore,reached];
  }
  _ab(board,owner,depth,a,b){
    if(Date.now()>this.deadline)throw new Error("timeout");
    this.nodes++;
    const pp=board._partial,vw=board._viewer;
    if(!board.monarchAlive(0)){if(!(pp&&0!==vw))return owner===0?-INF:INF;}
    if(!board.monarchAlive(1)){if(!(pp&&1!==vw))return owner===1?-INF:INF;}
    const th=board.throneHolder();
    if(th!==null&&th===board.toMove){
      const hs=board.throneHeldSince;
      if(hs&&hs[0]===th&&hs[1]>=board.throneHoldPlies-1)return th===owner?INF/2:-INF/2;
    }
    if(depth<=0)return this._quiesce(board,owner,a,b,0);
    const key=board.key();const cached=this.tt.get(key);
    if(cached&&cached[0]>=depth){
      if(cached[1]===_EXACT)return cached[2];
      if(cached[1]===_LOWER&&cached[2]>=b)return cached[2];
      if(cached[1]===_UPPER&&cached[2]<=a)return cached[2];
    }
    const R=2;
    if(depth>=R+1&&!this._inCheck(board,board.toMove)){
      const nb=board.clone();nb.toMove^=1;
      const v=-this._ab(nb,owner,depth-1-R,-b,-b+1);
      if(v>=b)return b;
    }
    const killers=this.killers[depth]||[];
    const moves=_order(board,board.legalMoves(board.toMove),killers,this.history);
    if(!moves.length)return 0;
    let bestVal=-INF,origA=a;
    for(const mv of moves){
      const nb=board.clone();nb.apply(mv);
      const v=-this._ab(nb,owner,depth-1,-b,-a);
      if(v>bestVal)bestVal=v;
      a=Math.max(a,v);
      if(a>=b){
        if(!board.pieces[mv[1]]){
          this._storeKiller(depth,mv);
          const hk=mv[0]+">"+mv[1];this.history.set(hk,(this.history.get(hk)||0)+depth*depth);
        }
        break;
      }
    }
    const flag=bestVal<=origA?_UPPER:bestVal>=b?_LOWER:_EXACT;
    this.tt.set(key,[depth,flag,bestVal]);
    return bestVal;
  }
  _inCheck(board,side){
    const mc=board.monarchCell(side);if(!mc)return true;
    for(const ck in board.pieces)if(board.pieces[ck].owner!==(side)&&board.movesFor(ck).includes(mc))return true;
    return false;
  }
  _quiesce(board,owner,a,b,qd){
    const pp=board._partial,vw=board._viewer;
    if(!board.monarchAlive(owner^1)){if(!(pp&&(owner^1)!==vw))return INF;}
    if(!board.monarchAlive(owner)){if(!(pp&&owner!==vw))return-INF;}
    let stand=evaluate(board,board.toMove);
    if(this.noise>0)stand+=(Math.random()*2-1)*this.noise;
    if(stand>=b)return stand;if(stand>a)a=stand;if(qd>=4)return stand;
    const caps=_order(board,board.legalMoves(board.toMove).filter(m=>board.pieces[m[1]]));
    let best=stand;
    for(const mv of caps){
      if(Date.now()>this.deadline)throw new Error("timeout");
      const nb=board.clone();nb.apply(mv);
      const v=-this._quiesce(nb,owner,-b,-a,qd+1);
      if(v>best)best=v;a=Math.max(a,v);if(a>=b)break;
    }
    return best;
  }
}

function aiMove(board,timeBudget=1,maxDepth=5,fogMemory=true){
  const view=fogMemory?fogViewForAI(board,board.toMove):board.fogView(board.toMove);
  const total=Object.keys(view.pieces).length;
  const noise=total>=12?1.5:total>=8?0.5:0;
  const s=new Searcher(timeBudget,maxDepth,noise);
  let[mv,score,depth]=s.search(view,view.toMove);
  if(mv)[mv]=resolveFogMove(board,mv,board.toMove);
  return[mv,{score:Math.round(score*10)/10,depth,nodes:s.nodes}];
}

function aiEvaluateDraw(board,side,timeBudget=0.5,maxDepth=4){
  const view=board.fogView(side);
  const s=new Searcher(timeBudget,maxDepth,0);
  const[,score]=s.search(view,side);
  if(score<=-5)return[true,"Position looks difficult — draw accepted."];
  if(Math.abs(score)<2)return[true,"Position is roughly equal — draw accepted."];
  return[false,`AI declines the draw (eval ${score>0?"+":""}${score.toFixed(1)} in its favour).`];
}

function aiWantsDraw(board,side,timeBudget=0.5,maxDepth=4){
  const view=board.fogView(side);
  const s=new Searcher(timeBudget,maxDepth,0);
  const[,score]=s.search(view,side);
  return score<=-8;
}

function serialize(board,viewer=0){
  const terrain={},pieces={};
  const fog=board.modes.has('fog');
  const vis=fog?board.visibleCells(viewer):null;
  for(const k in board.terrain)terrain[k]=board.terrain[k];
  for(const k in board.pieces){
    const p=board.pieces[k];
    if(fog&&vis&&!vis.has(k)&&p.owner!==viewer)continue;
    pieces[k]=p;
  }
  const w=board.winner();
  // fog: legal moves come from the mover's own view, so the list never
  // reveals hidden pieces (slides through fog resolve as bumps on apply);
  // and it is only sent to the mover — the opponent gets an empty list
  const hideLegal=w!==null||(fog&&board.toMove!==viewer);
  const src=(fog&&!hideLegal)?board.fogView(board.toMove):board;
  const out={W:board.W,H:board.H,terrain,pieces,to_move:board.toMove,
    thrones:board.thrones().map(k=>k.split(",").map(Number)),
    winner:w,modes:[...board.modes],
    legal:hideLegal?[]:src.legalMoves(board.toMove).map(([f,t])=>[f.split(",").map(Number),t.split(",").map(Number)])};
  if(board.modes.has('momentum'))out.momentum={...board.linger};
  return out;
}
