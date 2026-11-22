#!/bin/bash
# Build every SkillsBench task image for linux/amd64 (Modal's arch); record pass/fail; delete image after to save disk.
T=$(cd "$(dirname "$0")/../../external/skillsbench/tasks" && pwd); OUT=$1
: > $OUT/results.tsv
for d in $T/*/; do n=$(basename $d)
  s=$(date +%s)
  if docker build --platform linux/amd64 -q -t sb-$n $d/environment > $OUT/$n.log 2>&1; then r=ok; else r=FAIL; fi
  echo -e "$n\t$r\t$(( $(date +%s)-s ))" >> $OUT/results.tsv
  docker rmi -f sb-$n >/dev/null 2>&1; docker builder prune -af >/dev/null 2>&1
done
echo DONE >> $OUT/results.tsv
