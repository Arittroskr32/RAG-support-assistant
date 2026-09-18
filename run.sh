#!/usr/bin/env bash
# Start the Secure RAG Support Assistant from a clean state.
#
# The chat UI (frontend/) is served by the backend itself, on the same port, so one
# server gives you both: http://localhost:8000 (UI) and the API underneath it. The strict
# Content-Security-Policy (connect-src 'self') requires the UI and API to share an origin.
#
# Every run:
#   1. stops a previous run started by this script
#   2. wipes the vector database (chroma_db/) and the dataset split, and moves the previous
#      run's logs to logs/previous/
#   3. rebuilds KB-6, KB-5, KB-2 (if the datasets are present) and KB-4 from data/
#   4. starts the local LLM (Ollama) if it isn't running, and pulls the model if needed
#   5. starts the backend + UI and waits until it's healthy
# Kept between runs: .venv, downloaded models, config/api_keys.yaml, .env, eval/results.
#
# Usage:
#   ./run.sh                 full start (local LLM + backend + UI)
#   ./run.sh --calibrate     also re-calibrate thresholds (needs datasets; slow)
#   ./run.sh --mock          UI only, with canned answers (no models, GPU or LLM needed)
#   ./run.sh --port 8080     use another port (default 8000; mock default 8765)
#   ./run.sh --no-llm        don't start/pull the local LLM (use one you manage yourself)
#   ./run.sh --stop          stop a running instance and exit
# Ctrl+C stops everything this script started.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

RUN_DIR="$ROOT/.run"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
HOST="${HOST:-127.0.0.1}"
PORT=""
MODE="full"
CALIBRATE=0
MANAGE_LLM=1

# ---------------------------------------------------------------- helpers
c_blue=$'\033[1;34m'; c_green=$'\033[1;32m'; c_yellow=$'\033[1;33m'; c_red=$'\033[1;31m'; c_off=$'\033[0m'
step() { printf '%s==>%s %s\n' "$c_blue" "$c_off" "$*"; }
ok()   { printf '%s ✓%s %s\n' "$c_green" "$c_off" "$*"; }
warn() { printf '%s !%s %s\n' "$c_yellow" "$c_off" "$*"; }
die()  { printf '%s ✗%s %s\n' "$c_red" "$c_off" "$*" >&2; exit 1; }

usage() { sed -n '2,/^# Ctrl+C/p' "$0" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mock) MODE="mock" ;;
    --calibrate) CALIBRATE=1 ;;
    --no-llm) MANAGE_LLM=0 ;;
    --port) PORT="${2:?--port needs a value}"; shift ;;
    --stop) MODE="stop" ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1 (see ./run.sh --help)" ;;
  esac
  shift
done
[[ -z "$PORT" ]] && { [[ "$MODE" == "mock" ]] && PORT=8765 || PORT=8000; }

# .env (the Python code loads it too; bash needs LOCAL_LLM_* / GENERATION_BACKEND here)
if [[ -f .env ]]; then set -a; # shellcheck disable=SC1091
  source .env; set +a; fi
GENERATION_BACKEND="${GENERATION_BACKEND:-local}"
LOCAL_LLM_BASE_URL="${LOCAL_LLM_BASE_URL:-http://localhost:11434/v1}"
LOCAL_LLM_MODEL="${LOCAL_LLM_MODEL:-llama3.1:8b}"

mkdir -p "$RUN_DIR"
STARTED_PIDS=()

stop_pidfile() {   # stop_pidfile <name>
  local f="$RUN_DIR/$1.pid"
  [[ -f "$f" ]] || return 0
  local pid; pid="$(cat "$f")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
    kill -9 "$pid" 2>/dev/null || true
    ok "stopped previous $1 (pid $pid)"
  fi
  rm -f "$f"
}

port_in_use() { ss -ltn "sport = :$1" 2>/dev/null | grep -q LISTEN; }

cleanup() {
  trap - INT TERM EXIT
  if [[ ${#STARTED_PIDS[@]} -gt 0 ]]; then
    echo; step "Stopping…"
    for pid in "${STARTED_PIDS[@]}"; do
      kill "$pid" 2>/dev/null || true
      # remove only our own pid files (a newer run may already have written its own)
      for f in "$RUN_DIR"/*.pid; do [[ -f "$f" && "$(cat "$f")" == "$pid" ]] && rm -f "$f"; done
    done
    wait 2>/dev/null || true
    ok "all processes started by run.sh are stopped"
  fi
}
trap cleanup INT TERM EXIT

wait_for_http() {   # wait_for_http <url> <timeout_s> <pid> <logfile>
  local url="$1" timeout="$2" pid="$3" log="$4" waited=0
  until curl -fsS -o /dev/null "$url" 2>/dev/null; do
    kill -0 "$pid" 2>/dev/null || { tail -n 30 "$log" >&2; die "process exited during startup (log: $log)"; }
    if (( waited >= timeout )); then tail -n 30 "$log" >&2; die "not ready after ${timeout}s (log: $log)"; fi
    sleep 2; waited=$((waited + 2))
    if (( waited % 20 == 0 )); then printf '   still starting… %ss (first start downloads models)\n' "$waited"; fi
  done
  return 0   # (a loop's status is its last body command's status, which set -e would trip on)
}

# ---------------------------------------------------------------- 1. stop previous run
step "Stopping any previous run"
stop_pidfile backend; stop_pidfile mock; stop_pidfile ollama
[[ "$MODE" == "stop" ]] && { ok "done"; exit 0; }
port_in_use "$PORT" && die "port $PORT is used by another program (not started by run.sh). Free it or use --port."

# ---------------------------------------------------------------- 2. python environment
step "Checking the Python environment (.venv)"
[[ -x "$PY" ]] || { python3 -m venv "$VENV" || die "could not create .venv (need python3 -m venv)"; }
if [[ "$MODE" == "mock" ]]; then
  "$PY" -c "import fastapi, uvicorn, yaml" 2>/dev/null \
    || "$PY" -m pip install -q fastapi==0.141.1 uvicorn==0.53.0 pydantic==2.13.5 pyyaml==6.0.3 python-dotenv==1.2.3
else
  if ! "$PY" -c "import torch, sentence_transformers, chromadb, fastapi, uvicorn, httpx, faker, peft, transformers" 2>/dev/null; then
    warn "installing requirements (first run only; torch is large)…"
    "$PY" -m pip install -q --upgrade pip
    "$PY" -m pip install -q -r requirements-dev.txt || die "pip install failed"
  fi
fi
ok "python environment ready"

# ---------------------------------------------------------------- mock mode
if [[ "$MODE" == "mock" ]]; then
  step "Starting the UI with canned answers (mock server, no models)"
  PORT="$PORT" "$PY" -c "import os, uvicorn; from frontend.dev.mock_server import app; uvicorn.run(app, host='$HOST', port=int(os.environ['PORT']))" \
    > "$RUN_DIR/mock.log" 2>&1 &
  pid=$!; STARTED_PIDS+=("$pid"); echo "$pid" > "$RUN_DIR/mock.pid"
  wait_for_http "http://$HOST:$PORT/info" 30 "$pid" "$RUN_DIR/mock.log"
  ok "UI ready → ${c_green}http://$HOST:$PORT${c_off}  (try: diagram / table / chart / ignore / error)"
  echo "   Ctrl+C to stop."
  wait "$pid"; exit 0
fi

# ---------------------------------------------------------------- 3. clean state
step "Resetting state (fresh start)"
rm -rf chroma_db data/security_datasets/splits.json
if [[ -d logs ]] && compgen -G "logs/*.jsonl" > /dev/null; then
  rm -rf logs/previous && mkdir -p logs/previous && mv logs/*.jsonl logs/previous/
  ok "previous run's logs moved to logs/previous/"
fi
mkdir -p logs
ok "vector database wiped"

# ---------------------------------------------------------------- 4. guardrail access check
if "$PY" -c "from config.settings import get_thresholds; import sys; sys.exit(0 if get_thresholds().enable_l3 else 1)"; then
  "$PY" -c "from huggingface_hub import get_token; import sys; sys.exit(0 if get_token() else 1)" 2>/dev/null \
    || die "the L3 guardrail needs the gated model meta-llama/Llama-Guard-3-1B: accept its license on Hugging Face, then run 'huggingface-cli login' (or set enable_l3: false in config/thresholds.yaml)."
  ok "Hugging Face token found for the L3 guardrail"
fi

# ---------------------------------------------------------------- 5. rebuild knowledge bases
step "Rebuilding knowledge bases"
"$PY" -m knowledge_bases.build_kb6_narrative
"$PY" -m knowledge_bases.build_kb5_pii
if [[ -f data/security_datasets/train_dataset.jsonl && -f data/security_datasets/test_dataset.jsonl ]]; then
  "$PY" -m knowledge_bases.build_kb2_attacks
  if (( CALIBRATE )); then
    step "Calibrating thresholds (this takes a while)"
    "$PY" -m eval.calibrate_thresholds --with-l3
  fi
else
  warn "data/security_datasets/{train,test}_dataset.jsonl not found: KB-2 (known attacks) stays empty."
  warn "copy the datasets there for the KB-2 match layer and calibration."
  if (( CALIBRATE )); then warn "--calibrate skipped (no datasets)."; fi
fi
"$PY" -m ingestion.build_kb4
ok "knowledge bases rebuilt"

# ---------------------------------------------------------------- 6. local LLM
if [[ "$GENERATION_BACKEND" == "local" ]]; then
  step "Local LLM ($LOCAL_LLM_MODEL at $LOCAL_LLM_BASE_URL)"
  if curl -fsS -o /dev/null "$LOCAL_LLM_BASE_URL/models" 2>/dev/null; then
    ok "already running"
  elif (( MANAGE_LLM )) && command -v ollama >/dev/null && [[ "$LOCAL_LLM_BASE_URL" == *":11434"* ]]; then
    ollama serve > "$RUN_DIR/ollama.log" 2>&1 &
    pid=$!; STARTED_PIDS+=("$pid"); echo "$pid" > "$RUN_DIR/ollama.pid"
    wait_for_http "$LOCAL_LLM_BASE_URL/models" 60 "$pid" "$RUN_DIR/ollama.log"
    ok "ollama started"
  else
    warn "no local LLM reachable. Answers will fail with 'temporarily unavailable' until one runs."
    warn "install Ollama (https://ollama.com) or start LM Studio / llama.cpp and set LOCAL_LLM_BASE_URL."
  fi
  if (( MANAGE_LLM )) && command -v ollama >/dev/null && curl -fsS -o /dev/null "$LOCAL_LLM_BASE_URL/models" 2>/dev/null; then
    if ! ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "$LOCAL_LLM_MODEL"; then
      warn "pulling $LOCAL_LLM_MODEL (first time only)…"
      ollama pull "$LOCAL_LLM_MODEL"
    fi
    ok "model $LOCAL_LLM_MODEL available"
  fi
else
  step "Generation backend: $GENERATION_BACKEND"
  [[ -n "${ANTHROPIC_API_KEY:-}" ]] || warn "ANTHROPIC_API_KEY is not set; answers will fail."
fi

# ---------------------------------------------------------------- 7. backend + UI
step "Starting backend + chat UI on http://$HOST:$PORT"
"$PY" -m uvicorn api.main:app --host "$HOST" --port "$PORT" > "$RUN_DIR/backend.log" 2>&1 &
pid=$!; STARTED_PIDS+=("$pid"); echo "$pid" > "$RUN_DIR/backend.pid"
wait_for_http "http://$HOST:$PORT/health" 900 "$pid" "$RUN_DIR/backend.log"

echo
ok "Ready → ${c_green}http://$HOST:$PORT${c_off}"
echo "   API key: python -m api.create_api_key --user-id you --role customer  (paste it under Settings)"
echo "   Logs:    .run/backend.log, logs/security_events.jsonl"
echo "   Ctrl+C to stop."
wait "$pid"
