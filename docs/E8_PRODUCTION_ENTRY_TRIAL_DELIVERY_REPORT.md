# E8 Production Entry Trial：交付报告

**状态：** E8 PASS / COMPLETE。completion PR #25 已完成远端 CI、标准 merge 与 final master verification：`b23efde961ee34537d907e46bef49df98f0cc55d`。
**生成时间（UTC）：** 2026-08-21T11:00:18Z
**依赖提交：** Stage A2 已通过 PR #24 合并到 `master`：`c5dd19e6c6f7c86cae6ed5ec0910e631d9ec72c5`。

## 1. 交付结论

E8 已在 fresh PostgreSQL 控制数据库与 disposable Todo 数据库中完成真实纵向试验。试验创建并提交一个 creator-scoped Draft，生成确定性的测试 Understanding，提交 Proposal 与 Master Plan，通过 safe approval preview 执行 E4 approval，并在同一 materialized project 上从既有 E4 task、verification plan、check 和 readiness event 进入 P6 autonomous lifecycle。该 lifecycle 经真实首次缺陷、recovery、repair 和 independent verification 后到达 project `ACCEPTED`；E7 snapshot 与 bounded live feed 在相同 project identity 上提供阶段性与最终投影。

| 验收对象 | 结果 |
|---|---|
| Stage A2 依赖 | PR #24 三项 CI 成功后已合并；master clean checkout manifest 为 `174` entries、`0` missing、`0` mismatch |
| E8 same-project vertical trial | PASS — `1` test，`42.901s` |
| E4 durable materialization | PASS — one project、至少 one task 与 verification plan；approval replay 不创建第二个 project |
| P6 continuation / recovery | PASS — existing-entry handoff 复用 E4 identity，真实 defect/recovery/repair/verification 到 `PASSED` 与 `ACCEPTED` |
| E7 snapshot / feed | PASS — `CURRENT` snapshot、bounded feed、cursor-ahead stale fail-close、非 owner concealment |
| 0032 E4 identity compatibility | PASS — E8 log 无 `SECRET_VALUE_FORBIDDEN` 或 `EXEC_ADMISSION_ACTION_ROUTE_UNSUPPORTED` |
| Trial resource cleanup | PASS — `hermes_e8_*` 与 `todo_p6_ci_*` 数据库均不存在 |

## 2. 回归矩阵

| 门禁 | 结果 | 说明 |
|---|---:|---|
| E8 discovered unittest | PASS | `1` run、`42.901s`，fresh migrations 与 real FastAPI/OIDC dispatch |
| no-DB discovery | PASS | `705` run、`438` skipped、`0` failures，`1.233s` |
| Full Runtime | PASS | `705` run、`12` skipped、`0` failures，`429.306s` |
| Frontend Vitest | PASS | `6` files、`40` tests、`1.14s` |
| Frontend production build | PASS | TypeScript + Vite build 通过，`320ms` |
| Frontend oxlint | PASS | `0` warnings、`0` errors |

首次 Stage B Full Runtime 尝试报告两个 `FileNotFoundError`，均指向新隔离 worktree 尚未创建 `examples/golden-todo/.venv/bin/python` 的测试环境前置条件。该文件是 P6 bootstrap tests 明确调用的非提交测试 virtual environment，而不是仓库代码、E8 test 或 0032 的行为回归。按既有受权方式在 Stage B 中依据锁定 `requirements.txt` 创建该环境后，完整 `705` 项回归通过。没有修改 Golden Todo dependency lock、P6 harness、migration 或 authority 语义。

> 最终 Full Runtime 的通过结果是本报告的唯一当前 E8 runtime 证据；前一次环境缺失结果仅保留为基础设施归因记录，不作为功能结论。

## 3. 安全与authority记录

E8 不引入新的 secret policy。forensic 版本中旧的 execution snapshot secret preflight 及其 `_prepared_from_command` 依赖已删除；真实 P6 prepare 仍唯一依赖 0031 structured JSONB helper 与 0032 live sandbox callsite。试验所用 producer 为 typed deterministic test double，不包含网络、provider endpoint、credential 或真实 secret。OIDC 使用 test-local RS256 key；所有临时数据库由 class cleanup 与 Todo bootstrap cleanup 删除。

Approval preview 的 dataclass 被转化为最小 safe DTO。由此 creator 可以组成 approval command，但 frozen blueprint 和 child identities 不对 API caller 暴露。GraphPatch child command type 对齐至现有 `work_graph.apply_patch` handler；P6 driver 的 existing-entry adapter 仅接收 E4 已产生 identity，并观察现有 E7 read model。它不以 SQL 直接写入 authority tables，不创建第二 project，也不改变 P6 state machine。

## 4. Scope 与停止边界

E8 completion 仅包含 E4 preview DTO、安全 command type 对齐、P6 existing-entry/observer adapter、E8 acceptance test、E8 design/delivery documentation，以及 baseline manifest 更新。它不修改 migrations `0001–0032`、E4 durable identity、P6 authority、schema、role 或 grant。E8 在此完成；**不进入 E9**。

下一步仅允许对这一独立 E8 completion 范围执行 manifest reseal、精确暂存、secret scan、cached diff、GitHub PR、CI、合并与最终 master 核验。任何额外业务能力、provider integration 或下一阶段需求均需独立授权。
