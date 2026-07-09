"use strict";

const DIFF={easy:[0.25,2],normal:[1,4],hard:[2.5,6]};

class ServerAdapter{
  constructor(){
    this.mode="server";this.online=true;
    this.token=localStorage.getItem("facet_token")||null;
  }
  _setToken(t){
    this.token=t;
    if(t)localStorage.setItem("facet_token",t);
    else localStorage.removeItem("facet_token");
  }
  async _fetch(path,body,method){
    const opt={method:method||(body!==undefined?"POST":"GET"),headers:{}};
    if(body!==undefined){opt.headers["Content-Type"]="application/json";opt.body=JSON.stringify(body);}
    if(this.token)opt.headers["Authorization"]="Bearer "+this.token;
    const r=await fetch(path,opt);
    return r.json();
  }
  // ---- auth ----
  async ensureAuth(){
    if(this.token){
      const r=await this._fetch("/api/v1/me");
      if(r&&r.player)return r;
      this._setToken(null);
    }
    const g=await this._fetch("/api/v1/auth/guest",{});
    if(g.token){this._setToken(g.token);return this._fetch("/api/v1/me");}
    return{error:g.error||"authentication failed"};
  }
  async register(name,password){
    const r=await this._fetch("/api/v1/auth/register",{name,password});
    if(r.token)this._setToken(r.token);
    return r;
  }
  async login(name,password){
    const r=await this._fetch("/api/v1/auth/login",{name,password});
    if(r.token)this._setToken(r.token);
    return r;
  }
  async claim(name,password){return this._fetch("/api/v1/auth/claim",{name,password});}
  async rename(name){return this._fetch("/api/v1/auth/rename",{name});}
  async logout(){await this._fetch("/api/v1/auth/logout",{});this._setToken(null);}
  async me(){return this._fetch("/api/v1/me");}
  async leaderboard(){return this._fetch("/api/v1/leaderboard");}
  async profile(name){return this._fetch(`/api/v1/players/${encodeURIComponent(name)}`);}
  // ---- games ----
  async getBoards(){return this._fetch("/api/v1/boards");}
  async newGame(boardId,difficulty,modes,humanSide){
    const r=await this._fetch("/api/v1/games",
      {board:boardId,difficulty,modes:modes||[],human_side:humanSide||0});
    if(r.game_id){r.id=r.game_id;r.human_side=r.meta.your_side;r.modes=r.meta.modes;}
    return r;
  }
  async move(id,from,to){return this._fetch(`/api/v1/games/${id}/move`,{from,to});}
  async newGameTyped(gameType,difficulty,humanSide){
    const r=await this._fetch("/api/v1/games",
      {game_type:gameType,difficulty,human_side:humanSide||0});
    if(r.game_id){r.id=r.game_id;r.human_side=r.meta.your_side;}
    return r;
  }
  async moveAction(id,action){return this._fetch(`/api/v1/games/${id}/move`,{action});}
  async aiMove(id){return this._fetch(`/api/v1/games/${id}/ai`,{});}
  async offerDraw(id){return this._fetch(`/api/v1/games/${id}/draw`,{action:"offer"});}
  async drawAction(id,action){return this._fetch(`/api/v1/games/${id}/draw`,{action});}
  async resign(id){return this._fetch(`/api/v1/games/${id}/resign`,{});}
  async abort(id){return this._fetch(`/api/v1/games/${id}/abort`,{});}
  async state(id,v,wait){
    return this._fetch(`/api/v1/games/${id}/state?v=${v===undefined?-1:v}${wait?"&wait=1":""}`);
  }
  async getLog(id){
    const r=await this._fetch(`/api/v1/games/${id}/moves`);
    return{id,log:r.moves||[]};
  }
  // ---- lobby ----
  async getSeeks(){return this._fetch("/api/v1/seeks");}
  async createSeek(board,modes,sidePref,rated,target,gameType){
    return this._fetch("/api/v1/seeks",{board,modes:modes||[],side_pref:sidePref,rated:!!rated,target:target||null,game_type:gameType||"facet"});
  }
  async cancelSeek(id){return this._fetch(`/api/v1/seeks/${id}/cancel`,{});}
  async acceptSeek(id){
    const r=await this._fetch(`/api/v1/seeks/${id}/accept`,{});
    if(r.game_id)r.id=r.game_id;
    return r;
  }
  async myGames(){return this._fetch("/api/v1/games?status=active");}
}

class LocalAdapter{
  constructor(){
    this.mode="local";this.online=false;
    this.games={};this._nextId=1;
  }
  async getBoards(){
    const boards={};
    for(const k in BOARDS)boards[k]={name:BOARDS[k].name,desc:BOARDS[k].desc,size:BOARDS[k].size,
      supports_classic:CLASSIC_BOARDS.has(k),
      supports_decay:DECAY_BOARDS.has(k),supports_fog:FOG_BOARDS.has(k),
      supports_momentum:MOMENTUM_BOARDS.has(k)};
    return{boards};
  }
  async newGame(boardId,difficulty,modes,humanSide){
    const id="local-"+(this._nextId++);
    const mset=new Set(modes||[]);
    if(mset.has('decay')&&!DECAY_BOARDS.has(boardId))mset.delete('decay');
    if(mset.has('fog')&&!FOG_BOARDS.has(boardId))mset.delete('fog');
    // momentum is mutually exclusive with decay/fog (validation data)
    if(mset.has('momentum')&&(!MOMENTUM_BOARDS.has(boardId)||mset.has('decay')||mset.has('fog')))mset.delete('momentum');
    if(!mset.size&&!CLASSIC_BOARDS.has(boardId))boardId='classic';
    const human=(humanSide===1)?1:0;
    const board=makeBoard(boardId,[...mset]);
    this.games[id]={board,difficulty:difficulty||"normal",human,log:[{t:new Date().toISOString(),event:"new_game",board:boardId,difficulty,modes:[...mset],human_side:human}]};
    return{id,difficulty,modes:[...mset],human_side:human,state:serialize(board,human)};
  }
  async move(id,from,to){
    const g=this.games[id];if(!g)return{error:"no such game"};
    const board=g.board,human=g.human||0;
    if(board.winner()!==null)return{error:"game over",state:serialize(board,human)};
    const fk=from[0]+","+from[1],tk=to[0]+","+to[1];
    const src=board.modes.has('fog')?board.fogView(board.toMove):board;
    const legal=src.legalMoves(board.toMove);
    if(!legal.some(m=>m[0]===fk&&m[1]===tk))return{error:"illegal move",state:serialize(board,human)};
    const[mv,bumped]=resolveFogMove(board,[fk,tk],board.toMove);
    board.apply(mv);
    g.log.push({t:new Date().toISOString(),event:"move",player:board.toMove^1,from,to:mv[1].split(",").map(Number),bumped});
    const w=board.winner();
    if(w!==null)g.log.push({t:new Date().toISOString(),event:"game_over",winner:w});
    return{state:serialize(board,human),move:[mv[0].split(",").map(Number),mv[1].split(",").map(Number)],bumped};
  }
  async aiMove(id){
    const g=this.games[id];if(!g)return{error:"no such game"};
    const board=g.board,human=g.human||0,aiSide=human^1;
    if(board.winner()!==null)return{state:serialize(board,human),move:null};
    const[budget,depth]=DIFF[g.difficulty]||DIFF.normal;
    const t0=Date.now();
    const[mv,info]=aiMove(board,budget,depth);
    info.time_s=Math.round((Date.now()-t0)/1000*1000)/1000;
    let moveOut=null;
    if(mv){
      board.apply(mv);
      moveOut=[mv[0].split(",").map(Number),mv[1].split(",").map(Number)];
    }
    g.log.push({t:new Date().toISOString(),event:"ai_move",move:moveOut,info});
    const w=board.winner();
    if(w!==null)g.log.push({t:new Date().toISOString(),event:"game_over",winner:w});
    const resp={state:serialize(board,human),move:moveOut,info};
    if(w===null&&aiWantsDraw(board,aiSide,0.3,3)){
      resp.draw_offer=true;
      g.log.push({t:new Date().toISOString(),event:"ai_draw_offer"});
    }
    return resp;
  }
  async offerDraw(id){
    const g=this.games[id];if(!g)return{error:"no such game"};
    const board=g.board,human=g.human||0;
    if(board.winner()!==null)return{error:"game over",state:serialize(board,human)};
    const[accepted,reason]=aiEvaluateDraw(board,human^1,0.5,4);
    g.log.push({t:new Date().toISOString(),event:"draw_offer",by:"human",accepted,reason});
    if(accepted)g.log.push({t:new Date().toISOString(),event:"game_over",winner:"draw"});
    return{accepted,reason,state:serialize(board,human),draw_agreed:accepted};
  }
  async getLog(id){
    const g=this.games[id];
    return g?{id,log:g.log}:{error:"no such game"};
  }
}

async function createAdapter(){
  try{
    const r=await fetch("/api/v1/boards",{signal:AbortSignal.timeout(2000)});
    if(r.ok)return new ServerAdapter();
  }catch(e){}
  return new LocalAdapter();
}
