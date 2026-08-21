-- ============================================================================
-- p-001 Todo SaaS — 数据库 Schema（PostgreSQL 方言）
-- ----------------------------------------------------------------------------
-- 用途：
--   * Phase 7 切换 PostgreSQL 时可直接执行本文件（docker compose 挂载初始化）；
--   * Phase 2（SQLite）由 SQLAlchemy 模型生成等价结构 —— 因此本 Schema 与
--     模型约定一致：主键使用 BIGINT（SQLite 映射为 64 位 INTEGER，兼容），
--     且全部类型均为方言无关类型（BigInteger / VARCHAR / BOOLEAN / TIMESTAMPTZ）。
-- 与 api-spec.yaml 的一致性：字段名、长度约束（email ≤255 / title ≤200）、
--   默认值（done=false）与 API 对外 schema 一一对应。
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 用户表（对应 models/user.py；API: UserOut）
-- ----------------------------------------------------------------------------
CREATE TABLE users (
    id            BIGSERIAL    PRIMARY KEY,             -- BigInteger 主键（Phase 2 SQLite 映射为 INTEGER）
    email         VARCHAR(255) NOT NULL,                -- 应用层统一转小写后存储
    password_hash VARCHAR(255) NOT NULL,                -- bcrypt 哈希（rounds=12），永不明文
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),  -- 响应序列化为 ISO 8601（UTC）
    CONSTRAINT uq_users_email UNIQUE (email)            -- 注册时先查重，冲突返回 409
);

-- ----------------------------------------------------------------------------
-- 待办表（对应 models/todo.py；API: TodoOut —— user_id 为内部隔离键不返回）
-- ----------------------------------------------------------------------------
CREATE TABLE todos (
    id         BIGSERIAL    PRIMARY KEY,               -- BigInteger 主键
    user_id    BIGINT       NOT NULL,                  -- 数据隔离键（A3）：所有查询强制按此过滤
    title      VARCHAR(200) NOT NULL,
    due_date   DATE          NULL,  -- 可选截止日期（ISO 日期）FR-6（与 api-spec format: date 一致）
    done       BOOLEAN      NOT NULL DEFAULT FALSE,    -- 与 api-spec default=false 一致
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT now(),    -- 由 SQLAlchemy onupdate 维护（见下）
    CONSTRAINT fk_todos_user_id FOREIGN KEY (user_id)
        REFERENCES users (id) ON DELETE CASCADE        -- 用户删除时级联清理其待办
);

-- ----------------------------------------------------------------------------
-- 索引：列表接口按 user_id 过滤 + 排序，必须走该索引
-- ----------------------------------------------------------------------------
CREATE INDEX ix_todos_user_id ON todos (user_id);

-- ============================================================================
-- 设计说明
-- ----------------------------------------------------------------------------
-- 1) updated_at 由应用层（SQLAlchemy 列 onupdate=func.now()）维护，不使用
--    PostgreSQL 触发器 —— 保证 SQLite / PostgreSQL 行为完全一致。
-- 2) email 唯一约束在 PG 下区分大小写；应用层注册/登录统一 lowercase，
--    避免 "Foo@x.com" 与 "foo@x.com" 双账号歧义（不引入 citext 扩展）。
-- 3) 不引入 JSON / JSONB / ARRAY / Enum 等方言专有类型，Phase 2→7 零迁移成本。
-- 4) 如需进一步优化列表排序，可追加复合索引 (user_id, created_at)，
--    当前数据规模（个人待办）单列索引已足够，保持最小化。
-- ============================================================================
