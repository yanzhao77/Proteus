# ADR-0001: 错误语义决策（Review CON-02/04/05）

日期: 2026-08-21 · 决策者: Factory Manager

## 背景
Review 发现 api-spec 与实现的三处语义偏差：弱密码/title 校验（400 vs 422）、/health database enum、422 detail 数组。

## 决策
1. **业务校验一律 422**（Pydantic 默认，统一校验面）：api-spec 错误语义描述更新为"业务校验失败（密码强度/title 约束）→ 422"；删除 400 的业务校验描述（保留空 PATCH 400 语义）。
2. **/health database 允许 degraded**：DB 降级时 status=ok + database=degraded 且仍 200（可用性优先，健康检查由上层判定）；api-spec HealthResponse.database enum 增加 degraded。
3. **422 detail 可为数组**（FastAPI/Pydantic 默认）：api-spec 注明 Error.detail 为 string 或 string[]。

## 影响
api-spec.yaml 修订；前端已兼容 detail 数组；无需代码改动。
