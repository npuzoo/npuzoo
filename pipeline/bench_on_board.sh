#!/usr/bin/env bash
# Run on the BOARD. Benchmarks one converted model: NPU (rkllm) vs CPU (llama.cpp).
# Usage: ./bench_on_board.sh model.rkllm model.gguf [prompt_tokens=128] [gen_tokens=128]
# Appends a JSON line to bench_results.jsonl — publish.py merges it into the index.
set -euo pipefail

RKLLM_MODEL="${1:?model.rkllm}"
GGUF_MODEL="${2:-}"
NPROMPT="${3:-128}"
NGEN="${4:-128}"
OUT="bench_results.jsonl"

board=$(tr -d '\0' </proc/device-tree/model 2>/dev/null || echo unknown)
driver=$(grep -o 'v[0-9.]*' /sys/kernel/debug/rknpu/version 2>/dev/null || echo unknown)
kernel=$(uname -r)

echo "board : $board"
echo "driver: $driver  kernel: $kernel"

npu_tps=null
if command -v rkllm_bench >/dev/null 2>&1; then
  npu_tps=$(rkllm_bench "$RKLLM_MODEL" --prompt-tokens "$NPROMPT" --gen-tokens "$NGEN" | awk '/tokens\/s/{print $NF}')
else
  echo "! rkllm_bench not found — NPU numbers skipped (install via npuzoo pull, or build examples from airockchip/rknn-llm)"
fi

cpu_tps=null
if [ -n "$GGUF_MODEL" ] && command -v llama-bench >/dev/null 2>&1; then
  cpu_tps=$(llama-bench -m "$GGUF_MODEL" -p "$NPROMPT" -n "$NGEN" -o json 2>/dev/null \
            | python3 -c 'import json,sys; r=json.load(sys.stdin); print(round(r[-1]["avg_ts"],2))' || echo null)
else
  echo "! llama-bench or gguf missing — CPU comparison skipped"
fi

python3 - "$RKLLM_MODEL" "$board" "$driver" "$kernel" "$npu_tps" "$cpu_tps" <<'EOF' >>"$OUT"
import json, sys, datetime
m, board, driver, kernel, npu, cpu = sys.argv[1:7]
def num(x):
    try: return float(x)
    except ValueError: return None
print(json.dumps({
  "model_file": m, "board": board, "npu_driver": driver, "kernel": kernel,
  "npu_tps": num(npu), "cpu_tps": num(cpu),
  "date": datetime.date.today().isoformat(),
}))
EOF
echo "✓ appended to $OUT"
