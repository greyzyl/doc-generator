# 标准格式公文生成前端

这是一个基于 React + Vite + TypeScript 的前端项目，已经对接以下后端接口：

```http
GET  /api/v1/document-templates
POST /api/v1/document-drafts
POST /api/v1/document-drafts/{draftId}/body/parse
POST /api/v1/document-drafts/{draftId}/body/classify  # 兼容旧流程，主流程不再需要
PATCH /api/v1/document-drafts/{draftId}/body/paragraph-types
POST /api/v1/document-drafts/{draftId}/generate
GET  /api/v1/files/{fileId}/download
```

## 1. 安装和启动

```bash
npm install
npm run dev
```

默认访问：

```text
http://localhost:5173
```

## 2. 配置后端接口地址

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

设置：

```env
VITE_API_BASE_URL=/api/v1
```

开发环境默认通过 Vite 把 `/api` 代理到 `http://127.0.0.1:8000`。如果后端已配置 CORS，也可以直接指向后端，例如：

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

## 3. 核心数据流

前端编辑态采用字符级结构：

```text
后端 paragraphs JSON
→ paragraphsToCharUnits
→ 用户在字符级编辑区框选并修改类别
→ charUnitsToParagraphs
→ 拆回无换行 text 的 paragraphs JSON
→ 保存或生成公文
```

后端仍然只需要接收：

```json
{
  "parseId": "parse_20260505_0001",
  "paragraphs": [
    {
      "index": 1,
      "text": "正文模板格式确认样例",
      "type": "MAIN_TITLE"
    }
  ]
}
```

## 4. 段落划分约定

后端当前约定：

```text
paragraphs 之间天然是换行关系，text 字段内不再携带 \n。
```

前端编辑区为了显示 TXT 效果，会在相邻 paragraphs 之间插入前端专用换行分隔符；生成提交时会去掉这些分隔符，不写入 `text`。

```json
[
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
```

## 5. 重要文件说明

```text
src/App.tsx                         完整业务流程编排
src/api/client.ts                    通用接口请求封装
src/api/documentApi.ts                后端接口封装
src/components/CharacterEditor.tsx    字符级标注核心组件
src/components/WorkflowSidebar.tsx    模板、上传、解析、生成操作区
src/components/JsonPreview.tsx        提交给后端的 paragraphs 实时预览
src/utils/paragraphBlocks.ts          paragraphs 与 charUnits 互转、段落分隔、更新
src/utils/selection.ts                浏览器选区到字符 index 的转换
src/utils/typeStyles.ts               各类别颜色映射
src/types/document.ts                 后端接口类型定义
```

## 6. 同步段落类型接口说明

后端当前只支持按段落 `index` 批量修改 `type`，前端调用：

```http
PATCH /api/v1/document-drafts/{draftId}/body/paragraph-types
```

请求体：

```json
{
  "parseId": "parse_20260505_0001",
  "updates": [
    {
      "index": 1,
      "type": "MAIN_TITLE"
    }
  ]
}
```

点击“生成公文”时，前端仍会把当前拆分后的完整 `paragraphs` 提交给生成接口。
