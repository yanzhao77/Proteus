#!/usr/bin/env bash
# 调度闸：每次派发/推进前检查项目 runStatus，PAUSED/BLOCKED/WAITING_APPROVAL 时禁止派发
# 用法: pipeline-check.sh <project-dir> <action-name>
set -uo pipefail
PROJ="$1"; ACTION="${2:-dispatch}"
RS=$(python3 -c "import json; print(json.load(open('$PROJ/project.json')).get('runStatus','UNKNOWN'))" 2>/dev/null)
ST=$(python3 -c "import json; print(json.load(open('$PROJ/project.json')).get('status','UNKNOWN'))" 2>/dev/null)
echo "pipeline-check: status=$ST runStatus=$RS action=$ACTION"
case "$RS" in
  RUNNING|COMPLETED) echo "ALLOWED"; exit 0 ;;
  PAUSED)           echo "DENIED_PAUSED: user paused the project; wait for resume"; exit 3 ;;
  BLOCKED)          echo "DENIED_BLOCKED: blocked ($(python3 -c "import json; print(json.load(open('$PROJ/project.json')).get('blockedReason',''))"))"; exit 4 ;;
  WAITING_APPROVAL) echo "DENIED_WAITING_APPROVAL: awaiting user decision"; exit 5 ;;
  RETRYING)         echo "ALLOWED_RETRYING: fix loop in progress"; exit 0 ;;
  FAILED)           echo "DENIED_FAILED: project failed; needs recovery decision"; exit 6 ;;
  *) echo "UNKNOWN runStatus $RS"; exit 2 ;;
esac
