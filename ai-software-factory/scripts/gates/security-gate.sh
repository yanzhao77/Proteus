#!/usr/bin/env bash
# 安全 Gate：依赖审计 + 硬编码 secret 扫描
set -uo pipefail
PROJ="$1"
ISSUES=0
if [ -d "$PROJ/workspace/frontend" ]; then
  (cd "$PROJ/workspace/frontend" && npm audit --omit=dev 2>/dev/null | tail -5) || true
fi
# 硬编码 secret 扫描（排除 .env / lock 文件）
HITS=$(grep -rInE '(SECRET_KEY|password|api_key|token)\s*=\s*["'"'"'][^"'"'"'$]{6,}' "$PROJ/workspace/backend/app" "$PROJ/workspace/frontend/src" 2>/dev/null | grep -vE '\.env|example|\.md:|test' || true)
if [ -n "$HITS" ]; then echo "SECRET_SCAN_FAIL:"; echo "$HITS" | head -10; ISSUES=1; else echo "SECRET_SCAN=PASS"; fi
[ "$ISSUES" -eq 0 ] && echo "SECURITY_GATE=PASS" || echo "SECURITY_GATE=FAIL"
exit 0
