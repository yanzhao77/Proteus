#!/usr/bin/env bash
# 生产冒烟：docker compose up 后验证全流程
set -uo pipefail
PROJ="$1"
cd "$PROJ/workspace"
echo "== building =="; docker compose build 2>&1 | tail -5
echo "== up =="; docker compose up -d 2>&1 | tail -5
echo "== wait health =="
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then echo "health OK"; break; fi
  sleep 3
done
echo "== register =="
curl -s -X POST http://localhost:8000/api/v1/auth/register -H 'Content-Type: application/json' -d '{"email":"smoke@example.com","password":"Passw0rd!"}' | head -c 300; echo
echo "== login =="
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' -d '{"email":"smoke@example.com","password":"Passw0rd!"}' | python3 -c "import json,sys; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
echo "token_len=${#TOKEN}"
echo "== create todo =="
curl -s -X POST http://localhost:8000/api/v1/todos -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"title":"smoke todo"}' | head -c 300; echo
echo "== list todos =="
curl -s http://localhost:8000/api/v1/todos -H "Authorization: Bearer $TOKEN" | head -c 300; echo
echo "== web page =="
curl -s -o /dev/null -w "web http_code=%{http_code}\n" http://localhost:8080/
echo "SMOKE_DONE"
