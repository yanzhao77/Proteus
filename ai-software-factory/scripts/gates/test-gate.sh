#!/usr/bin/env bash
# 测试 Gate：运行后端 pytest（在前端目录可选 --frontend-build 检查）
# 用法: test-gate.sh <project-dir> [--frontend-build]
set -uo pipefail
PROJ="$1"; FE_BUILD="${2:-}"
cd "$PROJ/workspace/backend"
if [ ! -x .venv/bin/python ]; then echo "NO_VENV"; exit 2; fi
.venv/bin/python -m pytest -q 2>&1 | tail -20
RC=${PIPESTATUS[0]}
if [ "$RC" -eq 0 ]; then echo "TEST_GATE=PASS"; else echo "TEST_GATE=FAIL($RC)"; fi
if [ "$FE_BUILD" = "--frontend-build" ] && [ -d "$PROJ/workspace/frontend" ]; then
  (cd "$PROJ/workspace/frontend" && npm run build >/tmp/fe-build.log 2>&1 && echo "FE_BUILD=PASS" || { echo "FE_BUILD=FAIL"; tail -20 /tmp/fe-build.log; })
fi
exit 0
