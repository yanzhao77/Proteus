# 发布说明（Release Notes）

## 版本 0.1.0（2026-08-21）— AI Software Factory 生产试运行交付

### 新增
- 用户注册 / 登录（JWT Bearer，bcrypt rounds=12，邮箱小写化，防枚举 404/统一错误消息）
- 待办 CRUD（创建/列表/完成/删除），数据按 user_id 隔离
- 待办可选截止日期 due_date（ISO 日期，显式 null 清除）
- React 单页应用（登录/注册/待办列表，loading/empty/error 三态）
- PostgreSQL 16 数据存储（SQLAlchemy 方言无关模型）

### 修复
- PATCH 显式 null → 400 而非 500（CON-01）
- 密码 UTF-8 字节 ≤72 校验（SEC-01）；登录弱密码 422（CON-03）
- 越权/不存在资源统一 404 防枚举
- PG 兼容 done 默认值（server_default 类型不匹配，Phase 7 实测发现）
- 容器非 root 可读性（源码权限规范化）

### 已知问题（低危，见 security-report.md）
- 登录时序侧信道（SEC-02）、无限流（SEC-04）、token 存 localStorage（SEC-03）→ 后续迭代加固
- nginx 未启用 HTTPS（生产部署需 TLS 终止）

### 部署指引
```bash
cd workspace && cp .env.example .env   # 必须替换 SECRET_KEY / POSTGRES_PASSWORD
docker compose up -d --build
# web: http://localhost:8080 · api: http://localhost:8000（/docs）
```

### 回滚指引
- 代码回滚：git revert <commit> 后 `docker compose up -d --build`
- 数据：db-data 卷保留；如需重置 `docker compose down -v`

### 产物
Dockerfile ×2、docker-compose.yml、README.md、api-spec.yaml、database-schema.sql、测试 63 passed、安全审计 PASS、构建报告、冒烟证据
