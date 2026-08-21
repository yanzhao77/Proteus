#!/usr/bin/env bash
# 记录 Gate 结果到 reports/<stage>-gate.md（追加）
set -uo pipefail
PROJ="$1"; STAGE="$2"; RESULT="$3"; NOTE="${4:-}"
F="$PROJ/reports/$STAGE-gate.md"
{
  echo "## $(date -u +%Y-%m-%dT%H:%M:%SZ) — $RESULT"
  [ -n "$NOTE" ] && echo "evidence: $NOTE"
} >> "$F"
echo "recorded -> $F"
