#!/bin/sh

set -u

tmpdir="/tmp/ataka-batch-$$"
mkdir -p "$tmpdir"
trap 'rm -rf "$tmpdir"' EXIT INT TERM

index=0
pids=""
while [ "$index" -lt "$ATAKA_BATCH_SIZE" ]; do
  eval "execution_id=\${ATAKA_EXECUTION_ID_${index}}"
  eval "target_ip=\${ATAKA_TARGET_IP_${index}}"
  eval "target_extra=\${ATAKA_TARGET_EXTRA_${index}}"
  output="$tmpdir/$index.output"
  result="$tmpdir/$index.result"

  (
    TARGET_IP="$target_ip" TARGET_EXTRA="$target_extra" ATAKA_CENTRAL_EXECUTION=TRUE "$@" >"$output" 2>&1
    exit_code=$?
    printf '__ATAKA_BATCH_START__:%s\n' "$execution_id" >"$result"
    cat "$output" >>"$result"
    printf '__ATAKA_BATCH_END__:%s:%s\n' "$execution_id" "$exit_code" >>"$result"
  ) &
  pids="$pids $!"
  index=$((index + 1))
done

for pid in $pids; do
  wait "$pid" || true
done

index=0
while [ "$index" -lt "$ATAKA_BATCH_SIZE" ]; do
  cat "$tmpdir/$index.result"
  index=$((index + 1))
done
