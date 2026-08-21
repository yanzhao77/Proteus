#!/usr/bin/env bash
# 构建 Gate：后端编译检查 + 前端 build
set -uo pipefail
PROJ="$1"
cd "$PROJ/workspace/backend"
if [ -x .venv/bin/python ]; then
  .venv/bin/python -m compileall -q app && echo "PY_COMPILE=PASS" || echo "PY_COMPILE=FAIL"
fi
if [ -d "$PROJ/workspace/frontend" ]; then
  (cd "$PROJ/workspace/frontend" && npm run build >/tmp/fe-build.log 2>&1 && echo "FE_BUILD=PASS" || { echo "FE_BUILD=FAIL"; tail -20 /tmp/fe-build.log; })
fi
exit 0
