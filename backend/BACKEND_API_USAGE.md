# 标准格式公文生成系统后端接口调用说明

本文档给前端联调用。推荐后端入口文件是 `official_doc_flask_api.py`，接口基准路径为 `/api/v1`。

## 1. 启动后端

```bash
source .venv/bin/activate
python official_doc_flask_api.py --host 127.0.0.1 --port 8000
```

首次部署依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

本项目当前已创建 `.venv`。本机调试时如果 Flask 已在系统 Python 中存在，也可以使用当前项目里的 `.venv` 直接启动。

本地调试 Base URL：

```text
http://127.0.0.1:8000/api/v1
```

所有 JSON 接口统一返回：

```json
{
  "code": 0,
  "message": "success",
  "data": {},
  "requestId": "req_20260506_xxxxxxxx"
}
```

`code === 0` 表示成功；非 0 表示失败，前端应展示 `message`。

## 2. 推荐业务流程

1. 调 `GET /document-template-types` 获取可选模板类型。
2. 用户选择模板类型，例如 `LETTER`。
3. 调 `GET /document-templates/{templateType}` 获取该模板的版头版记字段和段落类型。
4. 用户填写 `fixedFields` 表单，并上传正文文件。
5. 调 `POST /document-drafts` 创建草稿，拿到 `draftId` 和 `bodyFile.fileId`。
6. 用户选择字段匹配策略：`RULE` 规则库，或 `LLM` 大模型。
7. 调 `POST /document-drafts/{draftId}/body/parse` 做初次字段匹配，拿到 `parseId` 和 `paragraphs`。
8. 前端用 TXT 样式渲染 `paragraphs`，允许用户右键修改段落类型。
9. 用户修改分类时调 `PATCH /document-drafts/{draftId}/body/paragraph-types`。
10. 用户确认后调 `POST /document-drafts/{draftId}/generate`。
11. 用返回的 `downloadUrl` 下载生成的 DOCX。

## 3. 枚举

### 模板类型 `templateType`

```json
["REPORT", "NOTICE", "REQUEST", "LETTER", "MEETING_MINUTES", "OTHER"]
```

当前只有 `LETTER` 已放置真实模板文件：

```text
template/LETTER/std_template.docx
template/LETTER/std_format.json
```

后端也兼容下面的 DOCX 文件名：

```text
template/{templateType}/template.docx
template/{templateType}/std_template.docx
```

`std_format.json` 文件名固定。

### 段落类型 `paragraph.type`

```json
[
  "MAIN_TITLE",
  "SUB_TITLE",
  "RECIPIENT",
  "BODY_PARAGRAPH",
  "LEVEL_1_TITLE",
  "LEVEL_2_TITLE",
  "LEVEL_3_TITLE",
  "MIXED_LEVEL_3_BODY",
  "ATTACHMENT_HEADER",
  "ATTACHMENT_ITEM",
  "SIGNING_COMPANY",
  "SIGNING_DATE",
  "CONTACT_INFO"
]
```

`MIXED_LEVEL_3_BODY` 表示“三级标题 + 同段正文”，可能带 `segments`：

```json
{
  "index": 3,
  "text": "1.专业化施工。坚持专业化发展思路...",
  "type": "MIXED_LEVEL_3_BODY",
  "segments": [
    { "type": "LEVEL_3_TITLE_INLINE", "text": "1.专业化施工。" },
    { "type": "BODY_TEXT", "text": "坚持专业化发展思路..." }
  ]
}
```

前端展示时可以优先使用 `text`。生成时如果前端把 `segments` 原样传回，后端会保留三级标题加粗信息；如果不传，后端会尝试按文本重新拆分。

## 4. 获取模板类型、字段和段落类型

```http
GET /api/v1/document-template-types
```

第一步只获取可选模板类型：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "templateTypes": [
      { "value": "LETTER", "label": "函类公文模板" }
    ],
    "templates": [
      {
        "templateId": "LETTER",
        "templateName": "函类公文模板",
        "templateType": "LETTER",
        "status": "ACTIVE",
        "available": true
      },
      {
        "templateId": "REPORT",
        "templateName": "报告类公文模板",
        "templateType": "REPORT",
        "status": "PENDING",
        "available": false
      }
    ]
  },
  "requestId": "req_xxx"
}
```

用户选择模板后，第二步按模板类型获取字段和段落类型：

```http
GET /api/v1/document-templates/LETTER
```

响应示例：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "template": {
      "templateId": "LETTER",
      "templateType": "LETTER",
      "status": "ACTIVE",
      "available": true
    },
    "fields": [
      {
        "fieldKey": "issuingUnit",
        "fieldName": "发文单位",
        "fieldType": "text",
        "required": true,
        "placeholder": "请输入发文单位"
      },
      {
        "fieldKey": "docNumber",
        "fieldName": "发文字号",
        "fieldType": "text",
        "required": true
      }
    ],
    "paragraphTypes": [
      { "value": "MAIN_TITLE", "label": "主标题" },
      { "value": "BODY_PARAGRAPH", "label": "普通正文" }
    ]
  },
  "requestId": "req_xxx"
}
```

字段来源：

- `fields` 来自 `template/{templateType}/std_format.json` 的 `placeholderMap`。
- `TEMPLATE_FIELDS` 保存所有模板可能用到的字段元信息。
- 只有某字段出现在当前模板的 `placeholderMap` 中，才会返回给前端，并且 `required: true`。
- `paragraphTypes` 来自 `template/{templateType}/para_type.txt`，一行一个类型。
- LLM 提示词来自 `template/{templateType}/prompt.py`。

## 5. 创建草稿并上传正文

```http
POST /api/v1/document-drafts
Content-Type: multipart/form-data
```

表单字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `templateType` | 否 | 推荐传，例如 `LETTER`。不传默认 `LETTER` |
| `templateId` | 否 | 可传 `LETTER`，也兼容旧值 `tpl_letter_001` |
| `documentName` | 否 | 公文名称，生成文件默认使用它 |
| `fixedFields` | 是 | 字符串形式 JSON，字段来自上一步返回的 `fields` |
| `file` | 是 | 正文文件，支持 `.docx`、`.txt`；接口暂接收 `.doc` 但当前解析只支持 `.docx` 和 `.txt` |

`fixedFields` 示例：

```json
{
  "issuingUnit": "中铁二十四局集团有限公司",
  "docNumber": "中铁二十四局〔2026〕12号",
  "signer": "张三",
  "copyTo": "中国铁道建筑集团有限公司办公厅",
  "printingUnit": "中铁二十四局集团有限公司办公室",
  "printingDate": "2026年4月30日"
}
```

必填字段以 `GET /document-templates/{templateType}` 返回的 `fields` 为准。

`curl` 示例：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/document-drafts \
  -F templateType=LETTER \
  -F documentName=接口验证公文 \
  -F 'fixedFields={"issuingUnit":"中铁二十四局集团有限公司","docNumber":"中铁二十四局〔2026〕12号","signer":"张三","copyTo":"中国铁道建筑集团有限公司办公厅","printingUnit":"中铁二十四局集团有限公司办公室","printingDate":"2026年4月30日"}' \
  -F file=@files/test1.docx
```

成功响应：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "draftId": "draft_20260506_xxxxxxxx",
    "templateId": "LETTER",
    "templateType": "LETTER",
    "documentName": "接口验证公文",
    "fixedFields": {},
    "status": "CREATED",
    "bodyFile": {
      "fileId": "file_20260506_xxxxxxxx",
      "fileName": "test1.docx",
      "fileType": "docx",
      "fileSize": 32159,
      "uploadTime": "2026-05-06T09:46:47+00:00"
    }
  },
  "requestId": "req_xxx"
}
```

前端保存：

- `draftId`
- `bodyFile.fileId`
- `templateType`
- `fixedFields`

## 6. 初次字段匹配正文

```http
POST /api/v1/document-drafts/{draftId}/body/parse
Content-Type: application/json
```

请求体：

```json
{
  "fileId": "file_20260506_xxxxxxxx",
  "strategy": "RULE",
  "options": {
    "splitByEmptyLine": true,
    "detectTitle": true,
    "detectHeadingNumber": true,
    "detectSignatureAndDate": true
  }
}
```

`strategy` 支持：

- `RULE`：使用规则库做字段/段落匹配。
- `LLM`：使用大模型做字段/段落匹配。

用户应在初次解析前选择策略，然后前端把所选策略传给本接口。`options` 目前保留给前端/后续扩展，后端不强依赖。

LLM 请求示例：

```json
{
  "fileId": "file_20260506_xxxxxxxx",
  "strategy": "LLM"
}
```

使用 `LLM` 时，运行后端前需要配置 `DASHSCOPE_API_KEY` 或 `OPENAI_API_KEY` 等环境变量，否则会返回 `50003`。

成功响应：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "parseId": "parse_20260506_xxxxxxxx",
    "draftId": "draft_20260506_xxxxxxxx",
    "strategy": "RULE",
    "paragraphs": [
      {
        "index": 1,
        "text": "关于办理产权登记的函",
        "type": "MAIN_TITLE"
      },
      {
        "index": 2,
        "text": "中国铁道建筑集团有限公司：",
        "type": "RECIPIENT"
      }
    ]
  },
  "requestId": "req_xxx"
}
```

前端保存：

- `parseId`
- `paragraphs`

## 7. 兼容接口：对当前段落再用 LLM 分类

主流程不需要调用本接口。现在推荐在第 6 节的 `body/parse` 接口里直接传 `strategy: "LLM"` 完成初次字段匹配。

```http
POST /api/v1/document-drafts/{draftId}/body/classify
Content-Type: application/json
```

请求体：

```json
{
  "parseId": "parse_20260506_xxxxxxxx",
  "strategy": "LLM",
  "paragraphs": [
    {
      "index": 1,
      "text": "关于办理产权登记的函",
      "type": "MAIN_TITLE"
    }
  ]
}
```

说明：

- 这是为了兼容旧流程保留的接口。
- 前端如已在 `body/parse` 中选择 `LLM`，不要再额外调用本接口。
- 运行后端时需要配置 `DASHSCOPE_API_KEY` 或 `OPENAI_API_KEY` 等环境变量，否则会失败。

成功响应结构与规则解析类似：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "draftId": "draft_20260506_xxxxxxxx",
    "parseId": "parse_20260506_xxxxxxxx",
    "strategy": "LLM",
    "paragraphs": []
  },
  "requestId": "req_xxx"
}
```

## 8. 批量修改段落类型

```http
PATCH /api/v1/document-drafts/{draftId}/body/paragraph-types
Content-Type: application/json
```

请求体：

```json
{
  "parseId": "parse_20260506_xxxxxxxx",
  "updates": [
    {
      "index": 3,
      "type": "LEVEL_1_TITLE"
    },
    {
      "index": 4,
      "type": "BODY_PARAGRAPH"
    }
  ]
}
```

说明：

- 只修改 `type`，不修改 `text`。
- 可一次改一个，也可一次改多个。
- 后端会返回更新后的完整 `paragraphs`。
- 如果把某段改成 `MIXED_LEVEL_3_BODY`，后端会清掉该段旧 `segments`，生成时再按文本尝试拆分。

成功响应：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "draftId": "draft_20260506_xxxxxxxx",
    "parseId": "parse_20260506_xxxxxxxx",
    "updatedCount": 2,
    "paragraphs": []
  },
  "requestId": "req_xxx"
}
```

## 9. 生成公文

```http
POST /api/v1/document-drafts/{draftId}/generate
Content-Type: application/json
```

请求体：

```json
{
  "templateType": "LETTER",
  "parseId": "parse_20260506_xxxxxxxx",
  "outputFormat": "DOCX",
  "fixedFields": {
    "issuingUnit": "中铁二十四局集团有限公司",
    "docNumber": "中铁二十四局〔2026〕12号",
    "signer": "张三",
    "copyTo": "中国铁道建筑集团有限公司办公厅",
    "printingUnit": "中铁二十四局集团有限公司办公室",
    "printingDate": "2026年4月30日"
  },
  "paragraphs": [
    {
      "index": 1,
      "text": "关于办理产权登记的函",
      "type": "MAIN_TITLE"
    }
  ],
  "options": {
    "includePageNumber": true,
    "strictOfficialFormat": true
  }
}
```

说明：

- `templateType` 推荐传当前用户选择的模板类型。
- `parseId` 和 `paragraphs` 二选一也可以，但前端推荐传最新 `paragraphs`，确保用户手动修改后的结果用于生成。
- `fixedFields` 会覆盖创建草稿时的同名字段。
- `outputFormat` 当前只实际生成 DOCX。
- `options` 目前保留给前端/后续扩展，后端不强依赖。

成功响应：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "draftId": "draft_20260506_xxxxxxxx",
    "documentId": "doc_20260506_xxxxxxxx",
    "status": "GENERATED",
    "outputFiles": [
      {
        "fileId": "generated_docx_20260506_xxxxxxxx",
        "fileType": "DOCX",
        "fileName": "接口验证公文.docx",
        "downloadUrl": "/api/v1/files/generated_docx_20260506_xxxxxxxx/download"
      }
    ]
  },
  "requestId": "req_xxx"
}
```

前端下载链接：

```text
http://127.0.0.1:8000 + downloadUrl
```

## 10. 下载文件

```http
GET /api/v1/files/{fileId}/download
```

响应是文件流，不是 JSON。

前端示例：

```ts
async function downloadDocx(baseUrl: string, downloadUrl: string) {
  const response = await fetch(`${baseUrl}${downloadUrl}`);
  if (!response.ok) throw new Error("下载失败");

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "生成公文.docx";
  a.click();
  URL.revokeObjectURL(url);
}
```

## 11. 前端 TXT 编辑区建议

后端返回的 `paragraphs` 按 `index` 升序排列。前端可按如下方式渲染：

```html
<div class="document-editor">
  <p data-index="1" data-type="MAIN_TITLE">关于办理产权登记的函</p>
  <p data-index="2" data-type="RECIPIENT">中国铁道建筑集团有限公司：</p>
</div>
```

右键修改分类时：

1. 根据被选中的段落取 `data-index`。
2. 从 `paragraphTypes` 菜单选新 `type`。
3. 本地先更新该段 `type`。
4. 调批量修改接口同步后端。
5. 用后端返回的 `paragraphs` 覆盖本地状态。

## 12. 常见错误

| code | message | 说明 |
| --- | --- | --- |
| `40001` | 模板不存在 | 传入了未知 `templateType/templateId` |
| `40002` | JSON 请求体格式错误 | JSON 解析失败 |
| `40003` | 草稿不存在 | `draftId` 无效 |
| `40004` | 文件不存在 / 正文文件不存在 | `fileId` 无效或文件丢失 |
| `40005` | strategy 仅支持 RULE 或 LLM | parse 接口传了非法策略 |
| `40006` | paragraphs 不能为空 | 生成或 LLM 分类时缺少段落数据 |
| `40007` | 解析结果不存在 | `parseId` 无效 |
| `40008` | 必填字段缺失 | `fixedFields` 缺少当前模板要求的字段 |
| `40009` | 正文文件不能为空 | 创建草稿时没有上传文件 |
| `40010` | 正文文件类型仅支持 .doc、.docx、.txt | 文件扩展名不支持 |
| `40012` | 不支持的段落类型 | 前端传了非法 paragraph type |
| `40013` | 模板文件未配置 | 选择的模板类型还没有放 DOCX/JSON 文件 |
| `50002` | 公文生成失败 | 模板、格式 JSON、占位符或段落数据导致渲染失败 |
| `50003` | LLM 请求失败 | LLM 配置或网络调用失败 |

## 13. 前端最小联调代码

```ts
const API_BASE = "http://127.0.0.1:8000/api/v1";

async function getTemplateTypes() {
  const res = await fetch(`${API_BASE}/document-template-types`);
  const json = await res.json();
  if (json.code !== 0) throw new Error(json.message);
  return json.data;
}

async function getTemplateDetail(templateType: string) {
  const res = await fetch(`${API_BASE}/document-templates/${templateType}`);
  const json = await res.json();
  if (json.code !== 0) throw new Error(json.message);
  return json.data;
}

async function createDraft(file: File, fixedFields: Record<string, string>) {
  const form = new FormData();
  form.append("templateType", "LETTER");
  form.append("documentName", "接口验证公文");
  form.append("fixedFields", JSON.stringify(fixedFields));
  form.append("file", file);

  const res = await fetch(`${API_BASE}/document-drafts`, {
    method: "POST",
    body: form
  });
  const json = await res.json();
  if (json.code !== 0) throw new Error(json.message);
  return json.data;
}

async function parseBody(draftId: string, fileId: string, strategy: "RULE" | "LLM") {
  const res = await fetch(`${API_BASE}/document-drafts/${draftId}/body/parse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fileId, strategy })
  });
  const json = await res.json();
  if (json.code !== 0) throw new Error(json.message);
  return json.data;
}

async function generateDoc(draftId: string, parseId: string, fixedFields: object, paragraphs: object[]) {
  const res = await fetch(`${API_BASE}/document-drafts/${draftId}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      templateType: "LETTER",
      parseId,
      outputFormat: "DOCX",
      fixedFields,
      paragraphs
    })
  });
  const json = await res.json();
  if (json.code !== 0) throw new Error(json.message);
  return json.data.outputFiles[0].downloadUrl;
}
```
