"use strict";

const DIFF={easy:[0.25,2],normal:[1,4],hard:[2.5,6]};

class ServerAdapter{
  constructor(){this.mode="server";}
  async _fetch(path,body){
    const opt=body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{};
    const r=await fetch(path,opt);return r.json();
  }
  async getBoards(){return this._fetch("/api/boards");}
  async newGame(boardId,difficulty){return this._fetch("/api/new",{board:boardId,difficulty});}
  async move(id,from,to){return this._fetch("/api/move",{id,from,to});}
  async aiMove(id){return this._fetch("/api/ai",{id});}
  async offerDraw(id){return this._fetch("/api/draw",{id});}
  async getLog(id){return this._fetch(`/api/log?id=${id}`);}
}

class LocalAdapter{
  constructor(){
    this.mode="local";
    this.games={};this._nextId=1;
  }
  async getBoards(){
    const boards={};
    for(const k in BOARDS)boards[k]={name:BOARDS[k].name,desc:BOARDS[k].desc,size:BOARDS[k].size};
    return{boards};
  }
  async newGame(boardId,difficulty){
    const id="local-"+(this._nextId++);
    const board=makeBoard(boardId);
    this.games[id]={board,difficulty:difficulty||"normal",log:[{t:new Date().toISOString(),event:"new_game",board:boardId,difficulty}]};
    return{id,difficulty,state:serialize(board)};
  }
  async move(id,from,to){
    const g=this.games[id];if(!g)return{error:"no such game"};
    const board=g.board;
    if(board.winner()!==null)return{error:"game over",state:serialize(board)};
    const fk=from[0]+","+from[1],tk=to[0]+","+to[1];
    const legal=board.legalMoves(board.toMove);
    if(!legal.some(m=>m[0]===fk&&m[1]===tk))return{error:"illegal move",state:serialize(board)};
    board.apply([fk,tk]);
    g.log.push({t:new Date().toISOString(),event:"move",player:board.toMove^1,from,to});
    const w=board.winner();
    if(w!==null)g.log.push({t:new Date().toISOString(),event:"game_over",winner:w});
    return{state:serialize(board)};
  }
  async aiMove(id){
    const g=this.games[id];if(!g)return{error:"no such game"};
    const board=g.board;
    if(board.winner()!==null)return{state:serialize(board),move:null};
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
    const resp={state:serialize(board),move:moveOut,info};
    if(w===null&&aiWantsDraw(board,1,0.3,3)){
      resp.draw_offer=true;
      g.log.push({t:new Date().toISOString(),event:"ai_draw_offer"});
    }
    return resp;
  }
  async offerDraw(id){
    const g=this.games[id];if(!g)return{error:"no such game"};
    const board=g.board;
    if(board.winner()!==null)return{error:"game over",state:serialize(board)};
    const[accepted,reason]=aiEvaluateDraw(board,1,0.5,4);
    g.log.push({t:new Date().toISOString(),event:"draw_offer",by:"human",accepted,reason});
    if(accepted)g.log.push({t:new Date().toISOString(),event:"game_over",winner:"draw"});
    return{accepted,reason,state:serialize(board),draw_agreed:accepted};
  }
  async getLog(id){
    const g=this.games[id];
    return g?{id,log:g.log}:{error:"no such game"};
  }
}

async function createAdapter(){
  try{
    const r=await fetch("/api/boards",{signal:AbortSignal.timeout(2000)});
    if(r.ok)return new ServerAdapter();
  }catch(e){}
  return new LocalAdapter();
}
