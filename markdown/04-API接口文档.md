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

`owner_user_id` 省略时默认为当前用户，`received_at` 省略时默认为服务端当前时间；`customer_id` 和负责人必须属于当前租户。

`PATCH /inquiries/{inquiry_id}` 可更新 `subject`、`customer_id`、`source_type`、`source_ref`、`raw_body`、`language`、`owner_user_id` 和 `status`。状态变更必须符合下表，非法流转返回 `409 INVALID_STATUS_TRANSITION`。

| 当前状态 | 允许流转 |
|---|---|
| `RECEIVED` | `PARSING`、`NEEDS_INFO`、`READY_FOR_MATCH`、`QUOTE_DRAFTED`、`ARCHIVED` |
| `PARSING` | `NEEDS_INFO`、`READY_FOR_MATCH` |
| `NEEDS_INFO` | `RECEIVED`、`PARSING`、`READY_FOR_MATCH`、`ARCHIVED` |
| `READY_FOR_MATCH` | `MATCHED`、`QUOTE_DRAFTED`、`NEEDS_INFO` |
| `MATCHED` | `QUOTE_DRAFTED`、`NEEDS_INFO` |
| `QUOTE_DRAFTED` | `PENDING_APPROVAL`、`MATCHED` |
| `PENDING_APPROVAL` | `QUOTE_APPROVED`、`QUOTE_DRAFTED` |
| `QUOTE_APPROVED` | `REPLIED`、`LOST` |
| `REPLIED` | `WON`、`LOST`、`QUOTE_DRAFTED` |
| `WON` / `LOST` | `ARCHIVED` |
| `ARCHIVED` | 无 |

需求人工确认请求（`PATCH /inquiries/{inquiry_id}/requirements`）：

```json
{
  "schema_version": 1,
  "confirmed": {
    "material": "SS304",
    "diameter": "M8",
    "length": "50mm",
    "quantity": "5000"
  }
}
```

`schema_version` 省略时为 `1`；同一版本重复提交会覆盖 `confirmed`。`GET` 返回最高 `schema_version` 的记录，尚未生成解析结果时返回 `data: null`。

上传附件（`POST /inquiries/{inquiry_id}/attachments`）使用 `multipart/form-data`，字段名为 `file`：

```bash
curl -X POST "$API/api/v1/inquiries/71a1.../attachments" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -F "file=@rfq-2026-11.xlsx"
```

响应 `201`：

```json
{
  "data": {
    "id": "d0c4...",
    "inquiry_id": "71a1...",
    "filename": "rfq-2026-11.xlsx",
    "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "size_bytes": 48213,
    "checksum": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "scan_status": "PENDING",
    "created_at": "2026-11-03T03:00:00Z"
  }
}
```

单个文件默认上限 20 MB（`ATTACHMENT_MAX_BYTES`），超出返回 `413 ATTACHMENT_TOO_LARGE`；空文件返回 `400 ATTACHMENT_EMPTY`；对象存储不可用返回 `502 STORAGE_UNAVAILABLE`。文件名会剥离路径部分后保存，对象键由服务端生成。上传成功后 `GET /inquiries/{inquiry_id}` 的 `attachments` 字段返回该询盘的附件列表，`scan_status` 初始为 `PENDING`，由后续病毒扫描流程更新。

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

`POST /inquiries/{inquiry_id}/analysis` 返回 `202`，仅允许 `RECEIVED`、`NEEDS_INFO` 状态发起；发起后询盘进入 `PARSING`，并返回 `QUEUED` 的异步任务。存在未结束的解析任务时返回 `409 INQUIRY_ANALYSIS_IN_PROGRESS`，其他状态返回 `409 INQUIRY_STATUS_NOT_ANALYZABLE`，跨租户或不存在的询盘返回 `404 INQUIRY_NOT_FOUND`。Worker 成功后写入新的 `inquiry_requirements` 版本（`schema_version` 递增，`confirmed` 不覆盖），关键字段完整时询盘进入 `READY_FOR_MATCH`，否则进入 `NEEDS_INFO`；解析失败或任务取消时任务进入终态，询盘回到 `NEEDS_INFO`。可通过 `GET /workflow-runs/{run_id}` 轮询任务状态。

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

`POST /inquiries/{inquiry_id}/matches` 为同步接口，仅允许 `READY_FOR_MATCH`、`MATCHED` 状态调用；尚无解析结果返回 `409 REQUIREMENTS_NOT_READY`，缺少产品品类或关键字段返回 `409 REQUIREMENTS_INCOMPLETE`，其他状态返回 `409 INQUIRY_STATUS_NOT_MATCHABLE`，跨租户或不存在的询盘返回 `404 INQUIRY_NOT_FOUND`。匹配使用最新一版 `inquiry_requirements`，人工确认值优先于解析值；先按产品品类硬过滤，仅评估 `ACTIVE` 产品，再对 `standard_code`、`material`、`diameter`、`length`、`surface_finish` 加权评分，硬字段冲突直接判定为 `CONFLICT`，MOQ 不足只写入说明、不参与判定。每次生成会替换该询盘既有候选，最多保留 10 条，并按匹配状态、得分、产品编码排序；存在 `EXACT` 或 `POSSIBLE` 时询盘进入 `MATCHED`。

匹配响应：

```json
{
  "data": {
    "inquiry_id": "71a1...",
    "inquiry_status": "MATCHED",
    "schema_version": 1,
    "matches": [
      {
        "id": "c3f0...",
        "product_id": "7c1d...",
        "product_code": "BOLT-EXT",
        "product_name": "Hex bolt SS304 M8x50",
        "category": "BOLT",
        "standard_code": "DIN933",
        "material": "SS304",
        "grade": "A2-70",
        "diameter": "M8",
        "length": "50mm",
        "surface_finish": "PLAIN",
        "sales_unit": "PCS",
        "moq": "1000",
        "score": "1.0000",
        "match_status": "EXACT",
        "matched_fields": [
          "standard_code",
          "material",
          "grade",
          "diameter",
          "length",
          "surface_finish"
        ],
        "conflict_fields": [],
        "unknown_fields": [],
        "explanation": "所有指定字段均匹配",
        "created_at": "2026-11-03T08:00:00Z"
      }
    ]
  }
}
```

`GET /inquiries/{inquiry_id}/matches` 返回最近一次生成的候选，排序与生成接口一致；尚未生成时 `schema_version` 为 `null`，`matches` 为空数组。

## 7. 报价与审批接口

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/quotes` | `quote:create` | 创建报价草案 |
| GET | `/quotes` | `quote:read` | 报价列表；支持 `status`、`quote_no` 过滤 |
| GET | `/quotes/{quote_id}` | `quote:read` | 报价详情/快照 |
| POST | `/quotes/{quote_id}/versions` | `quote:create` | 从已批准/已发送/已过期报价创建下一版本草案 |
| POST | `/quotes/{quote_id}/recalculate` | `quote:calculate` | 按当前明确指定的价格版本重新计算草案 |
| POST | `/quotes/{quote_id}/submit-approval` | `quote:submit` | 提交审批 |
| POST | `/quotes/{quote_id}/approve` | `quote:approve` | 批准 |
| POST | `/quotes/{quote_id}/reject` | `quote:approve` | 驳回/要求修改 |
| POST | `/quotes/{quote_id}/revise` | `quote:create` | 驳回后重新打开为草案 |
| POST | `/quotes/{quote_id}/send` | `quote:submit` | 人工确认已发送 |
| POST | `/quotes/{quote_id}/expire` | `quote:cancel` | 有效期结束后标记过期 |
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

传入 `inquiry_id` 时，服务端会校验该询盘属于当前租户；不存在或跨租户均返回 `404 INQUIRY_NOT_FOUND`。

关联询盘后，报价生命周期会在同一事务内联动询盘状态：

| 报价动作 | 询盘目标状态 |
|---|---|
| 创建报价草案 | `QUOTE_DRAFTED` |
| 提交审批 | `PENDING_APPROVAL` |
| 批准 | `QUOTE_APPROVED` |
| 驳回 | `QUOTE_DRAFTED` |
| 标记已发送 | `REPLIED` |

仅当询盘当前状态允许流转时才更新；取消、过期等动作暂不改动询盘状态。

批准请求：

```json
{"decision_note": "Verified product and price tier; approved."}
```

后端必须再次检查报价状态、审批人权限、价格底线、价格有效期、必需规格和关联租户，不得仅依据前端按钮是否可用。

重算请求（仅 `DRAFT` 状态允许，`price_as_of` 省略时按当天）：

```json
{"price_as_of": "2026-11-03"}
```

重算会按当前有效价格来源重新计算所有行项目，保留既有折扣、运费和其他费用，并写入 `REVISED` 事件（`event_payload.action = "recalculate"`）。已批准的报价不得重算，必须新建版本并重新审批。

重新打开与发送：

```json
{"note": "emailed to buyer"}
```

`POST /quotes/{quote_id}/revise` 仅允许 `REJECTED` 报价回到 `DRAFT`；`POST /quotes/{quote_id}/send` 仅允许 `APPROVED` 报价，成功后状态变为 `SENT` 并联动询盘为 `REPLIED`。`POST /quotes/{quote_id}/expire` 接受 `{"as_of": "2026-11-03"}`，仅在 `valid_until` 已早于 `as_of` 时把 `APPROVED`/`SENT` 报价置为 `EXPIRED`，否则返回 `400 VALIDITY_NOT_REACHED`。

版本创建（仅 `APPROVED`/`SENT`/`EXPIRED` 报价允许）：

```json
{"valid_until": "2027-01-31"}
```

服务端在同一事务内复制原报价的币种、金额、贸易条款、来源快照和全部行项目，以相同 `quote_no` 与 `version_no + 1` 生成 `DRAFT`，并写入引用原报价 `source_quote_id`/`source_version_no` 的 `CREATED` 事件。`valid_until` 省略时沿用原报价有效期。新版本必须重新提交审批；若下一版本号已存在返回 `409 QUOTE_VERSION_EXISTS`，源报价状态不允许时返回 `409 INVALID_STATUS_TRANSITION`。可先用 `GET /quotes?quote_no=<quote_no>` 查询同一报价的全部版本。

报价文件生成按需渲染，不落库、也不改变报价状态：

```bash
curl -X POST "$API/api/v1/quotes/{quote_id}/documents?format=PDF" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -o quotation.pdf
```

`format` 支持 `PDF`（默认）和 `XLSX`，响应为对应二进制文件，携带 `Content-Disposition: attachment; filename="<quote_no>-v<version>.<ext>"`。生成文件不等同于发送，不能据此把报价标记为 `SENT`。

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

`POST /inquiries/{inquiry_id}/email-drafts` 仅基于已批准报价生成草案，请求可携带 `quote_id` 与 `language`（默认 `en`）；省略 `quote_id` 时使用该询盘最新一版已批准报价。显式指定的报价不存在或不属于该询盘返回 `404 EMAIL_QUOTE_NOT_FOUND`，没有已批准报价返回 `409 EMAIL_QUOTE_NOT_APPROVED`。生成输入仅包含最新解析/人工确认需求、报价行产品快照与报价快照；缺失的贸易条款、有效期或规格以 `To be confirmed` 标记并写入 `missing_information`，不得编造价格、折扣、交期或认证。确定性生成器当前仅支持英文，其他语言返回 `400 EMAIL_UNSUPPORTED_LANGUAGE`；模型供应商异常返回 `502`。生成成功返回 `201` 与 `DRAFT` 状态的草案，并记录 `email.draft.create` 审计事件。

邮件草案响应：

```json
{
  "data": {
    "id": "9c2e...",
    "inquiry_id": "71a1...",
    "quote_id": "a8c2...",
    "subject": "Re: RFQ - stainless steel bolts",
    "body": "Dear Fastener Buyer GmbH Purchasing Team,\n\nThank you for your inquiry...",
    "language": "en",
    "status": "DRAFT",
    "approved_by": null,
    "approved_at": null,
    "model_id": "deterministic-email-generator.v1",
    "claims_used": ["quote:Q-1001:v2", "product:BOLT-EXT", "requirement:material"],
    "missing_information": ["Incoterm", "Lead time"],
    "review_flags": ["MISSING_INFORMATION"],
    "created_at": "2026-11-03T09:00:00Z",
    "updated_at": "2026-11-03T09:00:00Z"
  }
}
```

`PATCH /email-drafts/{draft_id}` 仅允许编辑 `DRAFT` 状态，可更新 `subject`、`body`，至少提供一项，已批准草案返回 `409 EMAIL_DRAFT_NOT_EDITABLE`。`POST /email-drafts/{draft_id}/approve` 仅允许 `DRAFT` 状态且报价仍为 `APPROVED`，否则分别返回 `409 EMAIL_DRAFT_NOT_APPROVABLE`、`409 EMAIL_QUOTE_NOT_APPROVED`；审批成功后状态变为 `APPROVED` 并记录 `approved_by`、`approved_at`。MVP 不提供真实发送接口。

## 9. 工作流与系统接口

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/workflow-runs/{run_id}` | `workflow:read` | 查询任务状态 |
| POST | `/workflow-runs/{run_id}/cancel` | `workflow:cancel` | 尝试取消可取消任务 |
| GET | `/audit-logs` | `audit:read` | 审计日志查询 |
| GET | `/usage/ai` | `usage:read` | AI 调用量统计 |
| GET | `/health/live` | Public/Network | 进程存活 |
| GET | `/health/ready` | Internal | 依赖就绪检查 |

`GET /workflow-runs/{run_id}` 返回当前租户的任务状态：

```json
{
  "data": {
    "id": "b183...",
    "workflow_type": "INQUIRY_ANALYSIS",
    "business_object_type": "INQUIRY",
    "business_object_id": "71a1...",
    "status": "QUEUED",
    "error_code": null,
    "started_at": null,
    "finished_at": null,
    "created_at": "2026-11-03T05:00:00Z",
    "updated_at": "2026-11-03T05:00:00Z"
  }
}
```

状态取值为 `QUEUED`、`RUNNING`、`SUCCEEDED`、`FAILED`、`CANCELLED`。`POST /workflow-runs/{run_id}/cancel` 可携带 `{"note": "wrong attachment"}`，仅 `QUEUED`/`RUNNING` 可取消，成功后状态变为 `CANCELLED` 并记录 `finished_at`；终态任务返回 `409 INVALID_WORKFLOW_STATUS`，跨租户或不存在的任务返回 `404 WORKFLOW_RUN_NOT_FOUND`。取消属于写操作，会写入 `workflow.cancel` 审计事件；运行中的任务由 Worker 在执行过程中检查取消状态。接口不返回内部 `input_ref`/`output_ref` 引用。

`GET /audit-logs` 仅返回当前租户的日志，支持分页和 `action`、`resource_type`、`resource_id`、`actor_id`、`created_from`、`created_to` 过滤，按时间倒序返回。每条日志包含 `actor_id`、`action`、`resource_type`、`resource_id`、`request_id`、`ip_hash`、`metadata` 和 `created_at`；IP 地址只保存加盐 SHA-256 摘要，不保存明文。

已接入审计的写操作：

| resource_type | action |
|---|---|
| `QUOTE` | `quote.create`、`quote.create_version`、`quote.submit`、`quote.approve`、`quote.reject`、`quote.recalculate`、`quote.revise`、`quote.send`、`quote.expire`、`quote.cancel` |
| `INQUIRY` | `inquiry.create`、`inquiry.update`、`inquiry.attachment.upload`、`inquiry.analysis.request`、`inquiry.analysis.completed`、`inquiry.analysis.failed`、`inquiry.matches.generate` |
| `EMAIL_DRAFT` | `email.draft.create`、`email.draft.update`、`email.draft.approve` |
| `WORKFLOW_RUN` | `workflow.cancel` |

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
