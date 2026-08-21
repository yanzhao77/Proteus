#!/usr/bin/env bash
# 实例化工厂项目骨架
# 用法: project-init.sh <project-id> [target-dir]   （默认 <factory-root>/projects/<project-id>）
set -euo pipefail
ID="$1"
FACTORY_ROOT="${FACTORY_ROOT:-$(pwd)/ai-software-factory}"
SKEL="$FACTORY_ROOT/templates/project-skeleton"
TARGET="${2:-$FACTORY_ROOT/projects/$ID}"
if [[ ! "$ID" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then echo "非法 project-id: $ID" >&2; exit 1; fi
if [[ -e "$TARGET" ]]; then echo "目标已存在: $TARGET" >&2; exit 1; fi
mkdir -p "$TARGET"
cp -R "$SKEL/." "$TARGET/"
mkdir -p "$TARGET/workspace"
sed -i '' "s/p-000/$ID/" "$TARGET/project.json" 2>/dev/null || sed -i "s/p-000/$ID/" "$TARGET/project.json"
if command -v git >/dev/null 2>&1; then
  git init -q "$TARGET/workspace" 2>/dev/null || true
fi
echo "project $ID initialized at $TARGET"
