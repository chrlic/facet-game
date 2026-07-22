#!/bin/bash
# Phase-C (REDO, 2026-07-22): multi-board self-play (CPU, <=3 workers) + MLX GPU training, starting from
# the champion widened to a moderately bigger net. Now with the FIXED scorer, SYMMETRY AUGMENTATION, the
# OWNERSHIP+SCORE aux heads, and — the key lesson from the last run — NET-VS-CHAMPION GATING (promote a
# candidate only if it actually beats the current champion; never blindly always-promote). All artifacts
# under net/spc/. Uses at most $WORKERS CPU cores for self-play; training is on the GPU (MLX).
#   net/phasec.sh <budgetSeconds> <workers> <games> <sims> <epochs>
cd /Users/mdivis/Documents/playground/games || exit 1
BUDGET=${1:-41400}; WORKERS=${2:-3}; GAMES=${3:-36}; SIMS=${4:-160}; EPOCHS=${5:-6}
NEWH=64; LR=2e-3; DSIMS=120; MAXSYM=4        # cap symmetries/position (tri->4x, elong->1x): aug without starving self-play
GATE=0.55                                    # promote candidate only if it wins >= GATE vs champion (tri/m + elong/m combined)
BOARDS="tri/s,tri/m,tri/l,elong/s,elong/m,elong/l"     # all sizes + both adjacencies (deg-6 and deg-5)
D=net/spc; mkdir -p "$D"; : > "$D/sp.log"; : > "$D/duel.log"
# champion = the frozen best-so-far (self-play + warm-start always use THIS). Start = widened H48 champion.
python3 net/widen.py docs/hexago-weights.json "$D/best.json" $NEWH
echo "PHASE C(redo) start $(date)  budget=${BUDGET}s workers=$WORKERS games=$GAMES sims=$SIMS H=$NEWH maxsym=$MAXSYM gate=$GATE"
echo "  boards=$BOARDS"
echo -n "iter0 (widened champion) vs MC tri/m: "; node net/duel.js "$D/best.json" MC 6 $DSIMS tri m 200 2>>"$D/duel.log"

promos=0
it=0
while [ $SECONDS -lt "$BUDGET" ]; do
  it=$((it+1))
  echo "=== ITER $it self-play $(date +%H:%M:%S) [elapsed ${SECONDS}s, promos $promos] ==="
  rm -f "$D"/it${it}_*.jsonl
  per=$(( (GAMES + WORKERS - 1) / WORKERS ))
  for w in $(seq 1 "$WORKERS"); do
    # self-play from the CHAMPION; arg9 = MAXSYM caps symmetry augmentation per position
    node net/selfplay.js "$D/best.json" "$per" "$SIMS" "$D/it${it}_${w}.jsonl" "$BOARDS" - 16 $MAXSYM 2>>"$D/sp.log" &
  done
  wait
  cat "$D"/it${it}_*.jsonl > "$D/it${it}.jsonl" 2>/dev/null; rm -f "$D"/it${it}_*.jsonl
  prev=$((it-1))
  if [ -f "$D/it${prev}.jsonl" ]; then cat "$D/it${it}.jsonl" "$D/it${prev}.jsonl" > "$D/train.jsonl"; else cp "$D/it${it}.jsonl" "$D/train.jsonl"; fi
  echo "ITER $it train ($(wc -l < "$D/train.jsonl") pos, GPU) $(date +%H:%M:%S)"
  # warm-start from the CHAMPION (adds aux heads on iter1); candidate -> itNw.json
  python3 net/train_mlx.py --data "$D/train.jsonl" --out "$D/it${it}w.json" --epochs $EPOCHS --lr $LR --warm "$D/best.json" 2>&1 | tail -1
  # GATE: duel candidate vs champion on two boards; promote only if combined win-rate >= GATE
  wa=$(node net/duel.js "$D/it${it}w.json" "$D/best.json" 6 $DSIMS tri   m 200 2>>"$D/duel.log")
  wb=$(node net/duel.js "$D/it${it}w.json" "$D/best.json" 6 $DSIMS elong m 200 2>>"$D/duel.log")
  comb=$(awk "BEGIN{print ($wa+$wb)/2}")
  pass=$(awk "BEGIN{print ($comb>=$GATE)?1:0}")
  if [ "$pass" = "1" ]; then
    cp "$D/it${it}w.json" "$D/best.json"; promos=$((promos+1))
    echo "ITER $it candidate vs champion: tri/m $wa  elong/m $wb  combined $comb  -> PROMOTED (#$promos)"
    echo -n "  new champion vs MC tri/m: ";   node net/duel.js "$D/best.json" MC 6 $DSIMS tri   m 200 2>>"$D/duel.log"
    echo -n "  new champion vs MC elong/m: "; node net/duel.js "$D/best.json" MC 6 $DSIMS elong m 200 2>>"$D/duel.log"
  else
    echo "ITER $it candidate vs champion: tri/m $wa  elong/m $wb  combined $comb  -> kept champion"
  fi
done
echo "PHASE C(redo) done $(date)  $it iterations, $promos promotions, ${SECONDS}s elapsed"
echo "champion = $D/best.json  (NOT auto-deployed; review before copying to docs/hexago-weights.json)"
echo "=== final champion vs H48 deployed champion + MC (all boards) ==="
for bs in "tri m" "tri l" "elong m" "elong l"; do
  set -- $bs
  echo -n "  vs H48-champ $1/$2: "; node net/duel.js "$D/best.json" docs/hexago-weights.json 8 $DSIMS $1 $2 200 2>>"$D/duel.log"
  echo -n "  vs MC        $1/$2: "; node net/duel.js "$D/best.json" MC 8 $DSIMS $1 $2 200 2>>"$D/duel.log"
done
