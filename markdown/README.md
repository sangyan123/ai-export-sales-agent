# Fastener AI Export Sales Agent - 项目文档包

版本：v0.9（首版基线草案）  
日期：2026-10-30  
项目范围：中国中小型工业紧固件出口制造企业；首批品类为螺栓、螺母、螺钉、垫圈。

## 文档清单

1. `01-PRD-产品需求文档`：产品定位、用户、范围、业务流程、功能和验收目标。
2. `02-系统架构设计文档`：技术栈、模块边界、运行时架构、架构决策。
3. `03-数据库设计文档`：ER 关系、核心表、字段、索引、租户隔离和 Migration 规则。
4. `04-API接口文档`：REST API、请求/响应约定、权限、状态、错误码。
5. `05-AI-Agent专项设计`：工作流、Tools、Prompt、RAG、产品匹配和 AI 安全。
6. `06-报价规则设计文档`：价格来源、阶梯价、计价单位、币种、审批和快照。
7. `07-安全与权限设计文档`：RBAC、多租户、审计、AI 安全和数据保护。
8. `08-测试与验收文档`：功能测试、AI 评测、报价测试、安全、UAT 和发布门槛。
9. `09-部署与运维文档`：Docker Compose、配置、发布、私有化交付、备份、监控。

## 项目统一基线

- 前端：Vue 3 + TypeScript + Vite + Element Plus + Pinia + Vue Router。
- 后端：Python 3.12+ + FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic。
- 数据库：PostgreSQL 16+ + pgvector。
- 缓存/队列：Redis 7+ + Celery。
- 文件：S3 兼容对象存储，开发/私有化可使用 MinIO。
- 部署：初期 Docker Compose；暂不引入 Kubernetes 和微服务。
- 架构：模块化单体 + 异步 Worker；LLM Provider、邮件 Provider、对象存储可替换。
- 数据隔离：共享数据库/Schema，多租户 `tenant_id` + PostgreSQL RLS + 服务端权限校验。
- 核心原则：LLM 负责理解/生成，确定性业务服务负责价格、权限、审批和执行。

## 关键枚举基线

### Inquiry Status

`RECEIVED`、`PARSING`、`NEEDS_INFO`、`READY_FOR_MATCH`、`MATCHED`、`QUOTE_DRAFTED`、`PENDING_APPROVAL`、`QUOTE_APPROVED`、`REPLIED`、`WON`、`LOST`、`ARCHIVED`。

### Quote Status

`DRAFT`、`PENDING_APPROVAL`、`APPROVED`、`REJECTED`、`SENT`、`EXPIRED`、`CANCELLED`。

### Workflow Status

`QUEUED`、`RUNNING`、`SUCCEEDED`、`FAILED`、`CANCELLED`、`WAITING_HUMAN`。

### Product Category

`BOLT`、`NUT`、`SCREW`、`WASHER`、`OTHER`。

## 重要假设与限制

1. 紧固件为首个验证行业；具体工厂需求、询盘来源和付费意愿尚待真实访谈与试点验证。
2. MVP 默认手动录入/上传询盘，不默认接入国际站等第三方平台，不自动抓取客户信息。
3. MVP 报价需要人工审批；模型不得自行编造价格、库存、交期、认证或付款条件。
4. 报价币种转换仅在有明确汇率来源和快照时执行；最简 MVP 可要求直接维护目标币种价格。
5. 私有化部署规格、SaaS SLA、RPO/RTO、套餐价格和合规方案需结合真实客户合同另行确认。
6. 本套文档是 v0.9 设计基线，不是已经实现或经过真实企业验收的系统说明。

## 推荐实施顺序

先完成 PRD 和业务样本确认，再设计数据库与 API；之后并行实现产品/价格基础数据与询盘处理工作流；再接入报价与审批、邮件草案、CRM，最后完成安全、测试、部署和真实企业试点。

## 变更管理

涉及状态枚举、API 路径、数据库字段、价格规则、租户隔离和审批权限的变更，应同步更新相关文档。每次发布使用版本号、变更记录、数据库 Migration 和回归测试报告，不允许只修改代码而不更新接口/数据契约。
