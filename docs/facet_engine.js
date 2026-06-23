"use strict";
const ORTH=[[1,0],[-1,0],[0,1],[0,-1]];
const DIAG=[[1,1],[1,-1],[-1,1],[-1,-1]];
const KING=[...ORTH,...DIAG];
const KNIGHT_DIRS=[[1,2],[2,1],[-1,2],[-2,1],[1,-2],[2,-1],[-1,-2],[-2,-1]];
const SLIDERS={R:ORTH,B:DIAG,T:KING};
const INF=1e9;
const _EXACT=0,_LOWER=1,_UPPER=2;

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
};

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

function makeBoard(id){
  const spec=BOARDS[id]||BOARDS.classic;
  const[W,H]=spec.size;
  const rows=spec.rows.map(r=>r.replace(/ /g,"").slice(0,W));
  let p0=null,p1=null;
  if(W===9&&H===9){
    p0=[];p1=[];
    for(let x=0;x<W;x++){p0.push([x,0]);p1.push([x,H-1]);}
    p0.push([2,1],[6,1]);p1.push([6,H-2],[2,H-2]);
  }
  return _makeBoard(rows,W,H,p0,p1);
}

class Board{
  constructor(W,H,terrain,pieces,toMove=0,throneHeldSince=null){
    this.W=W;this.H=H;this.terrain=terrain;this.pieces=pieces;
    this.toMove=toMove;this.throneHeldSince=throneHeldSince;
  }
  clone(){return new Board(this.W,this.H,this.terrain,{...this.pieces},this.toMove,this.throneHeldSince);}
  key(){
    const pk=Object.keys(this.pieces).sort().map(k=>{const p=this.pieces[k];return k+":"+p.owner+p.monarch;}).join("|");
    const th=this.throneHeldSince?this.throneHeldSince[0]+","+this.throneHeldSince[1]:"n";
    return pk+"/"+this.toMove+"/"+th;
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
    if(!this.monarchAlive(0))return 1;
    if(!this.monarchAlive(1))return 0;
    if(this.pieceCount(0)===1)return 1;
    if(this.pieceCount(1)===1)return 0;
    const th=this.throneHolder();
    if(th!==null&&this.throneHeldSince&&this.throneHeldSince[0]===th&&this.throneHeldSince[1]>=3)return th;
    if(!this.legalMoves(this.toMove).length)return"draw";
    return null;
  }
  _ok(nx,ny,owner){const k=nx+","+ny;if(!(k in this.terrain))return false;const p=this.pieces[k];return!p||p.owner!==owner;}
  movesFor(ck){
    const[x,y]=ck.split(",").map(Number);const p=this.pieces[ck];
    const o=p.owner,isMon=p.monarch;
    const g=isMon?"F":this.terrain[ck];const out=[];
    if(isMon||g==="F"){for(const[dx,dy]of KING)if(this._ok(x+dx,y+dy,o))out.push((x+dx)+","+(y+dy));}
    else if(g==="N"){for(const[dx,dy]of KNIGHT_DIRS)if(this._ok(x+dx,y+dy,o))out.push((x+dx)+","+(y+dy));}
    else if(SLIDERS[g]){for(const[dx,dy]of SLIDERS[g]){let nx=x+dx,ny=y+dy;while((nx+","+ny)in this.terrain){const k2=nx+","+ny;const occ=this.pieces[k2];if(!occ)out.push(k2);else{if(occ.owner!==o)out.push(k2);break;}nx+=dx;ny+=dy;}}}
    return out;
  }
  legalMoves(owner){
    const mv=[];for(const ck in this.pieces)if(this.pieces[ck].owner===owner)for(const to of this.movesFor(ck))mv.push([ck,to]);return mv;
  }
  apply(mv){
    const[fr,to]=mv;this.pieces[to]=this.pieces[fr];delete this.pieces[fr];this.toMove^=1;
    const th=this.throneHolder();
    if(th!==null){if(this.throneHeldSince&&this.throneHeldSince[0]===th)this.throneHeldSince=[th,this.throneHeldSince[1]+1];else this.throneHeldSince=[th,1];}
    else this.throneHeldSince=null;
  }
}

// ---- AI ----
function mobility(board,ck){return board.movesFor(ck).length;}

function evaluate(board,owner){
  if(!board.monarchAlive(owner))return-INF;
  if(!board.monarchAlive(owner^1))return INF;
  if(board.pieceCount(owner)===1)return-INF;
  if(board.pieceCount(owner^1)===1)return INF;
  const th=board.throneHolder();
  if(th===owner)return INF/2;
  if(th===(owner^1))return-INF/2;
  let score=0;
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
  score+=(myC-oppC)*5;
  if(oppC===2)score+=15;if(myC===2)score-=15;
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
    for(let depth=1;depth<=this.maxDepth;depth++){
      this.tt.clear();this.killers={};
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
    return[best,bestScore,reached];
  }
  _ab(board,owner,depth,a,b){
    if(Date.now()>this.deadline)throw new Error("timeout");
    this.nodes++;
    if(!board.monarchAlive(0))return owner===0?-INF:INF;
    if(!board.monarchAlive(1))return owner===1?-INF:INF;
    const th=board.throneHolder();
    if(th!==null&&th===board.toMove)return th===owner?INF/2:-INF/2;
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
    if(!board.monarchAlive(owner^1))return INF;
    if(!board.monarchAlive(owner))return-INF;
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

function aiMove(board,timeBudget=1,maxDepth=5){
  const total=Object.keys(board.pieces).length;
  const noise=total>=12?1.5:total>=8?0.5:0;
  const s=new Searcher(timeBudget,maxDepth,noise);
  const[mv,score,depth]=s.search(board,board.toMove);
  return[mv,{score:Math.round(score*10)/10,depth,nodes:s.nodes}];
}

function aiEvaluateDraw(board,side,timeBudget=0.5,maxDepth=4){
  const s=new Searcher(timeBudget,maxDepth,0);
  const[,score]=s.search(board,side);
  if(score<=-5)return[true,"Position looks difficult — draw accepted."];
  if(Math.abs(score)<2)return[true,"Position is roughly equal — draw accepted."];
  return[false,`AI declines the draw (eval ${score>0?"+":""}${score.toFixed(1)} in its favour).`];
}

function aiWantsDraw(board,side,timeBudget=0.5,maxDepth=4){
  const s=new Searcher(timeBudget,maxDepth,0);
  const[,score]=s.search(board,side);
  return score<=-8;
}

function serialize(board){
  const terrain={},pieces={};
  for(const k in board.terrain)terrain[k]=board.terrain[k];
  for(const k in board.pieces)pieces[k]=board.pieces[k];
  const w=board.winner();
  return{W:board.W,H:board.H,terrain,pieces,to_move:board.toMove,
    thrones:board.thrones().map(k=>k.split(",").map(Number)),
    winner:w,
    legal:w!==null?[]:board.legalMoves(board.toMove).map(([f,t])=>[f.split(",").map(Number),t.split(",").map(Number)])};
}
