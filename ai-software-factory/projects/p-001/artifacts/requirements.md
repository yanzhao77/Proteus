# 需求说明（Requirements）— p-001 Todo SaaS

## 项目背景
为个人与团队提供轻量待办管理 SaaS（Phase 2 最小闭环；Phase 7 升级 PostgreSQL + Docker 部署）。

## 用户目标
- 用户可注册 / 登录，管理自己的待办事项。

## 功能需求
- [ ] FR-1 (P0): 用户注册（邮箱 + 密码，密码 bcrypt 哈希）
- [ ] FR-2 (P0): 用户登录（返回 JWT token）
- [ ] FR-3 (P0): 待办 CRUD（创建 / 列表 / 更新完成状态 / 删除），仅本人可见
- [ ] FR-4 (P1): 前端单页应用（登录 / 注册 / 待办列表）
- [ ] FR-5 (P1): 健康检查端点 /health

## 非功能需求
- 性能: P95 < 500ms（本地开发环境）
- 安全: JWT 认证、密码 bcrypt、无硬编码 secret、输入校验
- 可用性: 本地 docker compose 一键启动

## 边界与假设（用户确认无暂停模式，按以下假设执行，记录于 memory/changes）
- 假设 A1: 数据库 Phase 2 用 SQLite（零依赖快速闭环），Phase 7 切换 PostgreSQL
- 假设 A2: 前端用 React + Vite，构建产物可静态部署
- 假设 A3: 单用户数据隔离（按 user_id 过滤）
- 假设 A4: 不实现邮件验证 / 找回密码 / 团队协作（Out of Scope，Phase 7 也保持）

## 待澄清问题（按假设默认化，可在后续需求变更阶段调整）
- 无（A1-A4 已记录）
