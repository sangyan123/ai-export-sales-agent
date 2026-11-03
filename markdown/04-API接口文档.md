# 04 API 接口文档

**项目名称：** Fastener AI Export Sales Agent  
**文档编号：** API-004  
**版本：** v0.9  
**日期：** 2026-10-30  
**API 前缀：** `/api/v1`  
**协议：** HTTPS + JSON；文件上传使用 `multipart/form-data`

## 1. 通用约定

### 1.1 认证

除登录、注册、健康检查和公开邀请接受接口外，所有接口均要求 `Authorization: Bearer <access_token>`。用户切换企业时，后端根据 membership 验证用户是否属于目标租户，并生成服务端租户上下文。客户端传入的 `tenant_id` 不得作为授权依据。

### 1.2 请求头

| Header | 用途 |
|---|---|
| Authorization | Bearer JWT |
| Content-Type | `application/json` 或 multipart |
| X-Request-ID | 调用链追踪 ID；无则由服务端生成 |
| Idempotency-Key | 创建工作流、报价等有副作用操作的幂等键 |
| Accept-Language | 可选，界面/错误信息语言偏好 |

### 1.3 统一成功响应

```json
{
  "data": {},
  "meta": {
    "request_id": "req_01J...",
    "timestamp": "2026-10-30T02:00:00Z"
  }
}
```

列表响应：

```json
{
  "data": [],
  "meta": {
    "page": 1,
    "page_size": 20,
    "total": 135,
    "request_id": "req_01J..."
  }
}
```

### 1.4 统一错误响应

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "请求参数校验失败",
    "details": [{"field": "quantity", "reason": "must_be_positive"}],
    "request_id": "req_01J..."
  }
}
```

常见 HTTP 状态：`400` 参数/业务规则错误；`401` 未认证；`403` 无权限；`404` 资源不存在或不可见；`409` 状态冲突/重复请求；`413` 文件过大；`422` Schema 校验失败；`429` 限流；`500` 未预期错误；`503` 外部模型/服务不可用。

## 2. 统一数据约定

- ID：UUID 字符串。
- 时间：ISO 8601 UTC，例如 `2026-10-30T02:00:00Z`。
- 金额：JSON 字符串表示十进制，例如 `"125.50"`，避免 IEEE 浮点精度问题。
- 币种：ISO 4217 三位代码，例如 `USD`。
- 分页：`page` 默认 1，`page_size` 默认 20，最大 100。
- 所有写操作必须执行角色和资源级权限检查。

## 3. 核心资源状态

询盘状态：`RECEIVED`、`PARSING`、`NEEDS_INFO`、`READY_FOR_MATCH`、`MATCHED`、`QUOTE_DRAFTED`、`PENDING_APPROVAL`、`QUOTE_APPROVED`、`REPLIED`、`WON`、`LOST`、`ARCHIVED`。

报价状态：`DRAFT`、`PENDING_APPROVAL`、`APPROVED`、`REJECTED`、`SENT`、`EXPIRED`、`CANCELLED`。

工作流状态：`QUEUED`、`RUNNING`、`SUCCEEDED`、`FAILED`、`CANCELLED`、`WAITING_HUMAN`。

## 4. 认证与租户接口

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/auth/register` | Public | 创建用户及企业（受邀请/注册策略控制） |
| POST | `/auth/login` | Public | 登录 |
| POST | `/auth/refresh` | Auth refresh token | 刷新访问令牌 |
| POST | `/auth/logout` | Auth | 注销当前会话/刷新令牌 |
| GET | `/users/me` | Auth | 当前用户信息 |
| GET | `/tenants/current` | Auth + membership | 当前企业 |
| GET | `/tenants/{tenant_id}/members` | `member:read` | 成员列表；服务端验证租户归属 |
| POST | `/tenants/{tenant_id}/members/invitations` | `member:invite` | 邀请成员 |

登录请求需指定目标企业（`tenant_slug` 或 `tenant_id` 二选一），服务端验证用户是否为目标企业有效成员：

```json
{
  "email": "sales@example.com",
  "password": "user-entered-password",
  "tenant_slug": "acme-fasteners"
}
```

登录成功返回 `access_token`、`refresh_token`（如采用 Cookie，应使用 HttpOnly/Secure/SameSite 设置）、`token_type`、`expires_in` 和 `refresh_expires_in`。Access Token 短时效，Refresh Token 每次刷新轮换；重复使用已轮换的 Refresh Token 会撤销该用户全部刷新令牌。密码永远不返回或记录日志。

## 5. 产品与资料接口

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/products` | `product:read` | 分页查询产品 |
| POST | `/products` | `product:create` | 创建产品 |
| GET | `/products/{product_id}` | `product:read` | 产品详情 |
| PATCH | `/products/{product_id}` | `product:update` | 更新产品 |
| POST | `/products/imports` | `product:import` | 上传产品 Excel，返回导入任务 ID |
| GET | `/products/imports/{job_id}` | `product:read` | 查询导入结果 |
| GET | `/products/import-template` | `product:read` | 下载模板 |
| POST | `/knowledge/files` | `knowledge:create` | 上传产品/企业资料 |
| GET | `/knowledge/files` | `knowledge:read` | 文件列表 |
| GET | `/knowledge/files/{file_id}` | `knowledge:read` | 文件解析状态 |
| DELETE | `/knowledge/files/{file_id}` | `knowledge:delete` | 归档/删除文件 |

产品创建请求示例：

```json
{
  "product_code": "BOLT-SS304-M8-50",
  "product_name": "Stainless Steel Hex Bolt",
  "category": "BOLT",
  "standard_code": "DIN 933",
  "material": "SS304",
  "grade": null,
  "diameter": "M8",
  "length": "50mm",
  "thread_pitch": null,
  "surface_finish": "Plain",
  "sales_unit": "PCS",
  "moq": "1000"
}
```

## 6. 询盘接口

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/inquiries` | `inquiry:read` | 查询询盘 |
| POST | `/inquiries` | `inquiry:create` | 手动创建询盘 |
| GET | `/inquiries/{inquiry_id}` | `inquiry:read` | 询盘详情 |
| PATCH | `/inquiries/{inquiry_id}` | `inquiry:update` | 更新标题、客户、负责人等 |
| POST | `/inquiries/{inquiry_id}/attachments` | `inquiry:update` | 上传附件 |
| POST | `/inquiries/{inquiry_id}/analysis` | `ai:run` | 创建解析任务，异步返回 |
| GET | `/inquiries/{inquiry_id}/requirements` | `inquiry:read` | 获取解析和人工确认结果 |
| PATCH | `/inquiries/{inquiry_id}/requirements` | `inquiry:update` | 人工修正已解析字段 |
| POST | `/inquiries/{inquiry_id}/matches` | `ai:run` | 生成产品候选匹配 |
| GET | `/inquiries/{inquiry_id}/matches` | `inquiry:read` | 获取候选结果 |

创建询盘请求：

```json
{
  "customer_id": "8a2b...",
  "subject": "RFQ - stainless steel bolts",
  "source_type": "MANUAL",
  "raw_body": "We need 5000 pcs of SS304 M8 x 50mm hex bolts...",
  "received_at": "2026-10-30T02:00:00Z"
}
```

解析任务响应：

```json
{
  "data": {
    "workflow_run_id": "b183...",
    "status": "QUEUED",
    "inquiry_id": "71a1..."
  }
}
```

解析结果示例：

```json
{
  "product_category": {"value": "BOLT", "confidence": 0.98, "evidence": "hex bolts"},
  "standard_code": {"value": null, "confidence": 0.0, "evidence": null},
  "material": {"value": "SS304", "confidence": 0.99, "evidence": "SS304"},
  "diameter": {"value": "M8", "confidence": 0.99, "evidence": "M8"},
  "length": {"value": "50mm", "confidence": 0.98, "evidence": "50mm"},
  "quantity": {"value": "5000", "confidence": 0.99, "evidence": "5000 pcs"},
  "destination_country": {"value": "DE", "confidence": 0.93, "evidence": "Germany"},
  "missing_fields": ["standard_code", "packaging"]
}
```

## 7. 报价与审批接口

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/quotes` | `quote:create` | 创建报价草案 |
| GET | `/quotes` | `quote:read` | 报价列表 |
| GET | `/quotes/{quote_id}` | `quote:read` | 报价详情/快照 |
| POST | `/quotes/{quote_id}/recalculate` | `quote:calculate` | 按当前明确指定的价格版本重新计算 |
| POST | `/quotes/{quote_id}/submit-approval` | `quote:submit` | 提交审批 |
| POST | `/quotes/{quote_id}/approve` | `quote:approve` | 批准 |
| POST | `/quotes/{quote_id}/reject` | `quote:approve` | 驳回/要求修改 |
| POST | `/quotes/{quote_id}/documents` | `quote:read` | 生成 PDF/XLSX 报价文件 |
| POST | `/quotes/{quote_id}/cancel` | `quote:cancel` | 取消报价 |

创建报价请求：

```json
{
  "inquiry_id": "71a1...",
  "currency": "USD",
  "price_list_id": "a8c2...",
  "valid_until": "2026-11-15",
  "items": [
    {"product_id": "7c1d...", "quantity": "5000", "unit": "PCS"}
  ],
  "terms": {
    "incoterm": null,
    "payment_terms": null,
    "lead_time": null,
    "shipping_cost": null
  }
}
```

批准请求：

```json
{"decision_note": "Verified product and price tier; approved."}
```

后端必须再次检查报价状态、审批人权限、价格底线、价格有效期、必需规格和关联租户，不得仅依据前端按钮是否可用。

## 8. 客户、邮件草案与跟进接口

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET/POST | `/customers` | customer:read/create | 客户列表/创建 |
| GET/PATCH | `/customers/{customer_id}` | customer:read/update | 客户详情/更新 |
| POST | `/customers/{customer_id}/contacts` | customer:update | 添加联系人 |
| POST | `/inquiries/{inquiry_id}/email-drafts` | email:draft | 生成邮件草案 |
| GET | `/email-drafts/{draft_id}` | email:read | 查看邮件草案 |
| PATCH | `/email-drafts/{draft_id}` | email:update | 编辑邮件 |
| POST | `/email-drafts/{draft_id}/approve` | email:approve | 批准邮件 |
| POST | `/email-drafts/{draft_id}/send` | email:send | 后续版本启用；仅批准后发送 |
| GET/POST | `/followups` | followup:read/create | 跟进任务列表/创建 |
| PATCH | `/followups/{task_id}` | followup:update | 完成/重新安排任务 |

MVP 的邮件可只生成草案、复制文本或下载文件；`send` 接口可以暂不开放，避免出现未完成邮件供应商和审批机制就对外承诺可发送。

## 9. 工作流与系统接口

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/workflow-runs/{run_id}` | `workflow:read` | 查询任务状态 |
| POST | `/workflow-runs/{run_id}/cancel` | `workflow:cancel` | 尝试取消可取消任务 |
| GET | `/audit-logs` | `audit:read` | 审计日志查询 |
| GET | `/usage/ai` | `usage:read` | AI 调用量统计 |
| GET | `/health/live` | Public/Network | 进程存活 |
| GET | `/health/ready` | Internal | 依赖就绪检查 |

## 10. OpenAPI 规范要求

- 所有请求/响应 Schema 必须维护在 FastAPI/Pydantic 模型中，由 OpenAPI 自动生成。
- 对外发布的 API 文档不得包含真实密钥、内部管理 URL 或客户数据。
- 示例金额使用字符串；枚举值来自共享常量。
- 所有会创建异步任务的端点返回 `workflow_run_id`，客户端轮询任务状态。
- 所有有副作用的创建操作支持幂等键，并对重复键返回原任务/资源。
- API 版本以 `/v1` 为边界；不兼容变更使用新版本或明确迁移窗口。

## 11. API 验收

- 未认证不能访问受保护接口；错误租户不能访问资源。
- 参数错误返回统一错误结构和 request_id。
- 异步任务接口不阻塞等待模型响应；可查询最终状态和错误码。
- 重复请求不生成重复报价或重复发送邮件。
- OpenAPI 与实际路由、Pydantic Schema、权限规则一致。
