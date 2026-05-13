#!/usr/bin/env python3
"""HTTP API wrapper for the official document generator.

The generator in generate_official_doc.py owns the DOCX rendering and paragraph
classification logic. This module keeps the backend interface thin: it accepts
the MVP HTTP contracts, stores draft state locally, and delegates rendering.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import tempfile
import uuid
import warnings
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

warnings.filterwarnings("ignore", category=DeprecationWarning, module="cgi")
import cgi

from generate_official_doc import (
    ALLOWED_BLOCK_TYPES,
    classify_plain_text,
    classify_plain_text_with_llm,
    classify_plain_text_with_llm_examples,
    classify_plain_text_with_llm_examples_stream,
    classify_plain_text_with_llm_stream,
    extract_docx_text,
    normalize_body_blocks,
    render_docx,
    resolve_llm_api_key,
    split_article_paragraph_segments,
    split_numbered_title,
    LEVEL_3_RE,
)


BASE_PATH = "/api/v1"
ROOT = Path(__file__).resolve().parent
STORAGE_DIR = ROOT / ".api_storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
GENERATED_DIR = STORAGE_DIR / "generated"
STATE_PATH = STORAGE_DIR / "state.json" # 记录草稿、文件、解析结果和生成文档的元信息
ENV_PATH = ROOT / ".env"

TEMPLATE_ROOT = ROOT / "template"
TEMPLATE_TYPES = ["LETTER", "DOWNWARD", "PARALLEL", "MEETING_MINUTES", "PLAIN_ARTICLE"]
DEFAULT_TEMPLATE_TYPE = "LETTER"
DEFAULT_TEMPLATE_ID = DEFAULT_TEMPLATE_TYPE
TEMPLATE_ASSET_DIRS = {
    "LETTER": "LETTER",
    "DOWNWARD": "DOWNWARD",
    "PARALLEL": "PARALLEL",
    "MEETING_MINUTES": "MEETING_MINUTES",
    "PLAIN_ARTICLE": "PLAIN_ARTICLE",
}
TEMPLATE_ASSET_DIR_ALIASES = {
    "PARALLEL": ["PARALLEL", "Parallel"],
    "MEETING_MINUTES": ["MEETING_MINUTES", "Meeting_Minutes", "Meeting_MIniutes", "MEETING_MINIUTES"],
}

TEMPLATE_TYPE_LABELS = {
    "LETTER": "上行文",
    "DOWNWARD": "下行文",
    "PARALLEL": "平行文",
    "MEETING_MINUTES": "会议纪要",
    "PLAIN_ARTICLE": "无红头交流文件",
}

TEMPLATE_TYPE_DESCRIPTIONS = {
    "LETTER": "适用于请示、报告等上行文",
    "DOWNWARD": "适用于通知、批复等下行文",
    "PARALLEL": "适用于函、意见等平行文",
    "MEETING_MINUTES": "适用于会议纪要类公文",
    "PLAIN_ARTICLE": "不含红头，仅保留交流材料标题和正文格式",
}

TEMPLATE_ALIASES = {
    "REPORT": "LETTER",
    "REQUEST": "LETTER",
    "UPWARD": "LETTER",
    "UPWARD_DOCUMENT": "LETTER",
    "TPL_REPORT_001": "LETTER",
    "TPL_REQUEST_001": "LETTER",
    "TPL_LETTER_001": "LETTER",
    "NOTICE": "DOWNWARD",
    "DOWNWARD_DOCUMENT": "DOWNWARD",
    "TPL_NOTICE_001": "DOWNWARD",
    "PARALLEL_DOCUMENT": "PARALLEL",
    "TPL_MEETING_MINUTES_001": "MEETING_MINUTES",
    "OTHER": "PLAIN_ARTICLE",
    "TPL_OTHER_001": "PLAIN_ARTICLE",
    "TPL_PLAIN_ARTICLE_001": "PLAIN_ARTICLE",
}


def load_local_env(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_local_env()

def redhead_fields(
    *,
    issuing_org: str,
    doc_number: str,
    cc_recipients: str,
    issuer: str | None,
    print_org: str,
    print_date: str = "2026-05-01",
) -> list[dict[str, Any]]:
    fields = [
        {
            "fieldKey": "issuingOrg",
            "fieldName": "发文单位",
            "fieldType": "text",
            "required": False,
            "defaultValue": issuing_org,
            "placeholder": "请输入发文单位",
            "maxLength": 100,
        },
        {
            "fieldKey": "docNumber",
            "fieldName": "发文字号",
            "fieldType": "text",
            "required": False,
            "defaultValue": doc_number,
            "placeholder": "例如：中铁二十四局办〔2026〕12号",
        },
        {
            "fieldKey": "ccRecipients",
            "fieldName": "抄送机关",
            "fieldType": "textarea",
            "required": False,
            "defaultValue": cc_recipients,
            "placeholder": "请输入抄送机关",
        },
    ]
    if issuer is not None:
        fields.append({
            "fieldKey": "issuer",
            "fieldName": "签发人",
            "fieldType": "text",
            "required": False,
            "defaultValue": issuer,
            "placeholder": "请输入签发人",
        })
    fields.extend([
        {
            "fieldKey": "printOrg",
            "fieldName": "印发机关",
            "fieldType": "text",
            "required": False,
            "defaultValue": print_org,
            "placeholder": "请输入印发机关",
        },
        {
            "fieldKey": "printDate",
            "fieldName": "印发日期",
            "fieldType": "date",
            "required": False,
            "defaultValue": print_date,
        },
    ])
    return fields


def simple_redhead_fields(
    *,
    issuing_org: str,
    doc_number: str,
    print_org: str,
    print_date: str = "2026-05-01",
) -> list[dict[str, Any]]:
    return [
        {
            "fieldKey": "issuingOrg",
            "fieldName": "发文单位",
            "fieldType": "text",
            "required": False,
            "defaultValue": issuing_org,
            "placeholder": "请输入发文单位",
            "maxLength": 100,
        },
        {
            "fieldKey": "docNumber",
            "fieldName": "发文字号",
            "fieldType": "text",
            "required": False,
            "defaultValue": doc_number,
            "placeholder": "例如：中铁二十四局函〔2026〕5号",
        },
        {
            "fieldKey": "printOrg",
            "fieldName": "印发机关",
            "fieldType": "text",
            "required": False,
            "defaultValue": print_org,
            "placeholder": "请输入印发机关",
        },
        {
            "fieldKey": "printDate",
            "fieldName": "印发日期",
            "fieldType": "date",
            "required": False,
            "defaultValue": print_date,
        },
    ]


def meeting_minutes_fields() -> list[dict[str, Any]]:
    return [
        {
            "fieldKey": "meetingTitle",
            "fieldName": "纪要标题",
            "fieldType": "text",
            "required": False,
            "defaultValue": "中铁二十四局集团有限公司总经理办公会纪要",
            "placeholder": "请输入会议纪要标题",
            "maxLength": 100,
        },
        {
            "fieldKey": "meetingNumber",
            "fieldName": "纪要编号",
            "fieldType": "text",
            "required": False,
            "defaultValue": "(2024年第13次)",
            "placeholder": "例如：〔2026〕3号",
        },
        {
            "fieldKey": "printOrg",
            "fieldName": "印发机关",
            "fieldType": "text",
            "required": False,
            "defaultValue": "中铁二十四局集团有限公司办公室",
            "placeholder": "请输入印发机关",
        },
        {
            "fieldKey": "printDate",
            "fieldName": "印发日期",
            "fieldType": "date",
            "required": False,
            "defaultValue": "2026-05-01",
        },
        {
            "fieldKey": "ccRecipients",
            "fieldName": "抄送机关",
            "fieldType": "textarea",
            "required": False,
            "defaultValue": "集团公司领导",
            "placeholder": "请输入抄送机关",
        },
    ]


TEMPLATE_FIELD_OVERRIDES: dict[str, list[dict[str, Any]]] = {
    "LETTER": redhead_fields(
        issuing_org="中铁二十四局集团有限公司",
        doc_number=" 二十四局财资〔2026〕113号",
        cc_recipients="中铁二十四局集团有限公司",
        issuer="支卫清",
        print_org="中铁二十四局集团有限公司",
    ),
    "DOWNWARD": redhead_fields(
        issuing_org="中铁二十四局集团有限公司",
        doc_number="二十四局财资〔2026〕113号",
        cc_recipients="中铁二十四局集团有限公司",
        issuer=None,
        print_org="中铁二十四局集团有限公司",
    ),
    "PARALLEL": simple_redhead_fields(
        issuing_org="中铁二十四局集团有限公司",
        doc_number=" 二十四局财资〔2026〕113号",
        print_org="中铁二十四局集团有限公司",
    ),
    "MEETING_MINUTES": meeting_minutes_fields(),
    "PLAIN_ARTICLE": [],
}
TEMPLATE_FIELDS = TEMPLATE_FIELD_OVERRIDES["LETTER"]
TEMPLATES_WITHOUT_LEVEL3 = {"PARALLEL", "MEETING_MINUTES"}
TEMPLATE_LLM_PROFILES = {"DOWNWARD": "DOWNWARD"}

PARAGRAPH_TYPE_LABELS = {
    "MAIN_TITLE": "主标题",
    "SUB_TITLE": "副标题",
    "RECIPIENT": "主送机关",
    "BODY_PARAGRAPH": "普通正文",
    "LEVEL_1_TITLE": "一级标题",
    "LEVEL_2_TITLE": "二级标题",
    "LEVEL_3_TITLE": "三级标题",
    "MIXED_LEVEL_3_BODY": "三级标题+可能的同段正文内容",
    "ATTACHMENT_HEADER": "附件标题",
    "ATTACHMENT_ITEM": "附件条目",
    "APPENDIX_TITLE": "附件正文标题",
    "CHAPTER_TITLE": "章标题",
    "ARTICLE_PARAGRAPH": "条文正文",
    "SIGNING_COMPANY": "落款单位",
    "SIGNING_DATE": "落款日期",
    "CONTACT_INFO": "联系人信息",
}

FIXED_FIELD_MAP = {
    "issuingOrg": "issuingUnit",
    "docNumber": "docNumber",
    "meetingTitle": "meetingTitle",
    "meetingNumber": "meetingNumber",
    "issuer": "signer",
    "ccRecipients": "copyTo",
    "printOrg": "printingUnit",
    "printDate": "printingDate",
}

MISSING_FIXED_FIELD_TEXT = "XXXX"

# 获取当前时间戳，格式为 YYYYMMDD_HHMMSS
def now_token() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

# 生成一个新的 ID，格式为 prefix_当前时间戳_uuid4 前 8 位
def new_id(prefix: str) -> str:
    return f"{prefix}_{now_token()}_{uuid.uuid4().hex[:8]}"

# 生成response时使用的requestId，格式为 req_当前时间戳_uuid4 前 8 位
def request_id() -> str:
    return new_id("req")

# ensure_storage 会在需要时创建存储目录和初始状态文件
def ensure_storage() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.exists():
        save_state({"drafts": {}, "files": {}, "parses": {}, "documents": {}})

# load_state 从状态文件中读取草稿、文件、解析结果和生成文档的元信息，并返回一个字典
def load_state() -> dict[str, Any]:
    ensure_storage()
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))

# save_state 将草稿、文件、解析结果和生成文档的元信息保存到状态文件中，使用原子写入方式避免并发问题
def save_state(state: dict[str, Any]) -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = STATE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(STATE_PATH)

# api_response 是一个辅助函数，用于生成符合 API 规范的 JSON 响应体，包含 code、message、data 和 requestId 字段
def api_response(data: Any = None, *, code: int = 0, message: str = "success") -> dict[str, Any]:
    return {"code": code, "message": message, "data": data, "requestId": request_id()}


def find_template_docx(template_dir: Path) -> Path | None:
    for filename in ["template.docx", "std_template.docx", "std_template_unified.docx"]:
        candidate = template_dir / filename
        if candidate.exists():
            return candidate
    return None


def find_template_config(template_dir: Path) -> Path | None:
    for filename in ["std_format.json", "std_format_unified.json"]:
        candidate = template_dir / filename
        if candidate.exists():
            return candidate
    return None


def candidate_template_dirs(template_type: str) -> list[Path]:
    configured = TEMPLATE_ASSET_DIRS.get(template_type, template_type)
    candidates = [configured, *TEMPLATE_ASSET_DIR_ALIASES.get(template_type, [])]
    unique_candidates = list(dict.fromkeys(candidates))
    return [TEMPLATE_ROOT / directory for directory in unique_candidates]


def discover_templates() -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for template_type in TEMPLATE_TYPES:
        template_dir = candidate_template_dirs(template_type)[0]
        template_docx = None
        config_path = None
        for candidate_dir in candidate_template_dirs(template_type):
            candidate_docx = find_template_docx(candidate_dir)
            candidate_config = find_template_config(candidate_dir)
            if candidate_docx is not None or candidate_config is not None:
                template_dir = candidate_dir
            if candidate_docx is not None and candidate_config is not None:
                template_docx = candidate_docx
                config_path = candidate_config
                break
        is_available = template_docx is not None and config_path is not None
        registry[template_type] = {
            "templateId": template_type,
            "templateName": TEMPLATE_TYPE_LABELS[template_type],
            "templateType": template_type,
            "description": TEMPLATE_TYPE_DESCRIPTIONS[template_type],
            "version": "1.0.0",
            "status": "ACTIVE" if is_available else "PENDING",
            "available": is_available,
            "templatePath": str(template_docx.relative_to(ROOT)) if template_docx else None,
            "configPath": str(config_path.relative_to(ROOT)) if config_path else None,
        }
    return registry


def resolve_template(template_id_or_type: str | None) -> dict[str, Any] | None:
    value = (template_id_or_type or DEFAULT_TEMPLATE_ID).upper()
    value = TEMPLATE_ALIASES.get(value, value)
    registry = discover_templates()
    if value in registry:
        return registry[value]
    for template in registry.values():
        if value == str(template["templateId"]).upper() or value == str(template["templateType"]).upper():
            return template
    return None


def template_is_ready(template: dict[str, Any]) -> bool:
    return bool(template.get("available") and template.get("templatePath") and template.get("configPath"))


def fields_for_template(template: dict[str, Any] | str | None) -> list[dict[str, Any]]:
    if isinstance(template, dict):
        template_type = str(template.get("templateType") or template.get("templateId") or "").upper()
    else:
        template_type = str(template or "").upper()
    return TEMPLATE_FIELD_OVERRIDES.get(template_type, TEMPLATE_FIELDS)


def template_disables_level3(template: dict[str, Any] | str | None) -> bool:
    if isinstance(template, dict):
        template_type = str(template.get("templateType") or template.get("templateId") or "").upper()
    else:
        template_type = str(template or "").upper()
    template_type = TEMPLATE_ALIASES.get(template_type, template_type)
    return template_type in TEMPLATES_WITHOUT_LEVEL3


def template_llm_profile(template: dict[str, Any] | str | None) -> str:
    if isinstance(template, dict):
        template_type = str(template.get("templateType") or template.get("templateId") or "").upper()
    else:
        template_type = str(template or "").upper()
    template_type = TEMPLATE_ALIASES.get(template_type, template_type)
    return TEMPLATE_LLM_PROFILES.get(template_type, "DEFAULT")

# template_response 构造一个包含可用模板列表和段落类型选项的响应体，用于前端获取模板信息和段落分类选项
def template_response() -> dict[str, Any]:
    templates = []
    for template in discover_templates().values():
        public_template = {
            key: value
            for key, value in template.items()
            if key not in {"templatePath", "configPath"}
        }
        public_template["fields"] = fields_for_template(template)
        templates.append(public_template)
    paragraph_types = [
        {"value": value, "label": PARAGRAPH_TYPE_LABELS[value]}
        for value in PARAGRAPH_TYPE_LABELS
    ]
    template_types = [{"value": value, "label": TEMPLATE_TYPE_LABELS[value]} for value in TEMPLATE_TYPES]
    return {"templateTypes": template_types, "templates": templates, "paragraphTypes": paragraph_types}

# metadata_to_fixed_fields 将 API 请求中的 metadata 字段映射为模板渲染所需的固定字段，使用 FIXED_FIELD_MAP 定义映射关系
def format_official_date(value: str) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", value.strip())
    if not match:
        return value
    year, month, day = match.groups()
    return f"{year}年{int(month)}月{int(day)}日"


def metadata_to_fixed_fields(metadata: dict[str, Any]) -> dict[str, str]:
    fixed_fields: dict[str, str] = {}
    for api_key, generator_key in FIXED_FIELD_MAP.items():
        value = str(metadata.get(api_key) or "").strip()
        if api_key == "printDate":
            value = format_official_date(value)
        fixed_fields[generator_key] = value or MISSING_FIXED_FIELD_TEXT
    return fixed_fields

# validate_metadata 检查 API 请求中的 metadata 字段是否包含所有必填字段，并返回一个错误列表，如果没有错误则返回空列表
def validate_metadata(metadata: dict[str, Any], template: dict[str, Any] | None = None) -> list[dict[str, str]]:
    errors = []
    for field in fields_for_template(template):
        if not field.get("required"):
            continue
        field_key = field["fieldKey"]
        if not str(metadata.get(field_key) or "").strip():
            errors.append({"fieldKey": field_key, "message": f"{field['fieldName']}不能为空"})
    return errors

# parse_json_body 从 HTTP 请求体中读取 JSON 数据并解析为字典，如果请求体为空或不是有效的 JSON，则返回一个空字典
def parse_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw) if raw.strip() else {}

# parse_multipart 从 HTTP 请求体中解析 multipart/form-data 数据，返回一个包含字段和值的字典，以及一个包含上传文件信息的字典（如果有的话）
def parse_multipart(handler: BaseHTTPRequestHandler) -> tuple[dict[str, str], dict[str, Any] | None]:
    form = cgi.FieldStorage(
        fp=handler.rfile,
        headers=handler.headers,
        environ={
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": handler.headers.get("Content-Type", ""),
            "CONTENT_LENGTH": handler.headers.get("Content-Length", "0"),
        },
        keep_blank_values=True,
    )
    fields: dict[str, str] = {}
    uploaded_file: dict[str, Any] | None = None
    for key in form:
        item = form[key]
        if isinstance(item, list):
            item = item[0]
        if item.filename:
            uploaded_file = {"fieldName": key, "fileName": item.filename, "content": item.file.read()}
        else:
            fields[key] = item.value
    return fields, uploaded_file

# safe_filename 从上传的文件名中提取安全的文件名，避免路径穿越等安全问题，如果提取后为空则返回一个默认文件名
def safe_filename(filename: str) -> str:
    cleaned = Path(filename.replace("\\", "/")).name
    return cleaned or "body.txt"


def read_body_file(file_record: dict[str, Any]) -> str:
    file_path = ROOT / file_record["path"]
    suffix = file_path.suffix.lower()
    if suffix == ".docx":
        return extract_docx_text(file_path)
    if suffix == ".txt":
        return file_path.read_text(encoding="utf-8-sig")
    raise ValueError("当前后端解析仅支持 .docx 和 .txt 文件")


def block_text(block: dict[str, Any]) -> str:
    if isinstance(block.get("segments"), list):
        return "".join(str(segment.get("text") or "") for segment in block["segments"])
    return str(block.get("text") or "")


def blocks_to_paragraphs(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paragraphs = []
    for index, block in enumerate(normalize_body_blocks(blocks), start=1):
        paragraph = {
            "index": index,
            "text": block_text(block),
            "type": block.get("type", "BODY_PARAGRAPH"),
        }
        if block.get("segments"):
            paragraph["segments"] = block["segments"]
        paragraphs.append(paragraph)
    return paragraphs


def block_to_paragraph(index: int, block: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_body_blocks([block])
    if not normalized:
        return {"index": index, "text": "", "type": "BODY_PARAGRAPH"}
    normalized_block = normalized[0]
    paragraph = {
        "index": index,
        "text": block_text(normalized_block),
        "type": normalized_block.get("type", "BODY_PARAGRAPH"),
    }
    if normalized_block.get("segments"):
        paragraph["segments"] = normalized_block["segments"]
    return paragraph


def paragraphs_to_blocks(paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks = []
    for paragraph in sorted(paragraphs, key=lambda item: int(item.get("index") or 0)):
        block_type = str(paragraph.get("type") or "BODY_PARAGRAPH")
        if block_type not in ALLOWED_BLOCK_TYPES:
            block_type = "BODY_PARAGRAPH"
        segments = paragraph.get("segments")
        if block_type in {"MIXED_LEVEL_3_BODY", "ARTICLE_PARAGRAPH"} and isinstance(segments, list):
            blocks.append({"type": block_type, "segments": segments})
            continue
        text = str(paragraph.get("text") or "")
        if block_type == "MIXED_LEVEL_3_BODY":
            title, body = split_numbered_title(text, LEVEL_3_RE)
            blocks.append(
                {
                    "type": block_type,
                    "segments": [
                        {"type": "LEVEL_3_TITLE_INLINE", "text": title},
                        {"type": "BODY_TEXT", "text": body},
                    ],
                }
            )
        elif block_type == "ARTICLE_PARAGRAPH":
            article_segments = split_article_paragraph_segments(text)
            if article_segments:
                blocks.append({"type": block_type, "segments": article_segments})
            else:
                blocks.append({"type": block_type, "text": text})
        else:
            blocks.append({"type": block_type, "text": text})
    return normalize_body_blocks(blocks)


def classify_with_llm(
    paragraphs: list[dict[str, Any]],
    *,
    disable_level3: bool = False,
    prompt_profile: str = "DEFAULT",
) -> list[dict[str, Any]]:
    text = "\n".join(str(paragraph.get("text") or "") for paragraph in paragraphs)
    api_key = resolve_llm_api_key(None, "DASHSCOPE_API_KEY")
    blocks = classify_plain_text_with_llm(
        text,
        model=os.environ.get("DASHSCOPE_MODEL") or os.environ.get("LLM_MODEL") or "qwen-plus",
        base_url=(
            os.environ.get("DASHSCOPE_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        api_key=api_key,
        timeout=float(os.environ.get("LLM_TIMEOUT", "480")),
        disable_level3=disable_level3,
        prompt_profile=prompt_profile,
    )
    return blocks_to_paragraphs(blocks)


def classify_text_with_llm_examples(
    text: str,
    examples: list[dict[str, Any]],
    *,
    disable_level3: bool = False,
    prompt_profile: str = "DEFAULT",
) -> list[dict[str, Any]]:
    api_key = resolve_llm_api_key(None, "DASHSCOPE_API_KEY")
    blocks = classify_plain_text_with_llm_examples(
        text,
        examples=paragraphs_to_blocks(examples),
        model=os.environ.get("DASHSCOPE_MODEL") or os.environ.get("LLM_MODEL") or "qwen-plus",
        base_url=(
            os.environ.get("DASHSCOPE_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        api_key=api_key,
        timeout=float(os.environ.get("LLM_TIMEOUT", "480")),
        disable_level3=disable_level3,
        prompt_profile=prompt_profile,
    )
    return blocks_to_paragraphs(blocks)


def classify_text_with_llm_examples_stream(
    text: str,
    examples: list[dict[str, Any]],
    *,
    disable_level3: bool = False,
    prompt_profile: str = "DEFAULT",
):
    api_key = resolve_llm_api_key(None, "DASHSCOPE_API_KEY")
    for index, block in classify_plain_text_with_llm_examples_stream(
        text,
        examples=paragraphs_to_blocks(examples),
        model=os.environ.get("DASHSCOPE_MODEL") or os.environ.get("LLM_MODEL") or "qwen-plus",
        base_url=(
            os.environ.get("DASHSCOPE_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        api_key=api_key,
        timeout=float(os.environ.get("LLM_TIMEOUT", "480")),
        disable_level3=disable_level3,
        prompt_profile=prompt_profile,
    ):
        yield block_to_paragraph(index, block)


def classify_text_with_llm_stream(text: str, *, disable_level3: bool = False, prompt_profile: str = "DEFAULT"):
    api_key = resolve_llm_api_key(None, "DASHSCOPE_API_KEY")
    for index, block in classify_plain_text_with_llm_stream(
        text,
        model=os.environ.get("DASHSCOPE_MODEL") or os.environ.get("LLM_MODEL") or "qwen-plus",
        base_url=(
            os.environ.get("DASHSCOPE_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        api_key=api_key,
        timeout=float(os.environ.get("LLM_TIMEOUT", "480")),
        disable_level3=disable_level3,
        prompt_profile=prompt_profile,
    ):
        yield block_to_paragraph(index, block)


def text_to_plain_paragraphs(text: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [
        {"index": index, "text": line, "type": "BODY_PARAGRAPH"}
        for index, line in enumerate(lines, start=1)
    ]


def classify_body_text_by_strategy(
    text: str,
    strategy: str,
    *,
    disable_level3: bool = False,
    prompt_profile: str = "DEFAULT",
) -> list[dict[str, Any]]:
    normalized_strategy = strategy.upper()
    if normalized_strategy == "RULE":
        return blocks_to_paragraphs(classify_plain_text(text, disable_level3=disable_level3))
    if normalized_strategy == "LLM":
        return classify_with_llm(
            text_to_plain_paragraphs(text),
            disable_level3=disable_level3,
            prompt_profile=prompt_profile,
        )
    raise ValueError("strategy 仅支持 RULE 或 LLM")


def classify_body_text_by_strategy_stream(
    text: str,
    strategy: str,
    *,
    disable_level3: bool = False,
    prompt_profile: str = "DEFAULT",
):
    normalized_strategy = strategy.upper()
    if normalized_strategy == "RULE":
        for paragraph in blocks_to_paragraphs(classify_plain_text(text, disable_level3=disable_level3)):
            yield paragraph
        return
    if normalized_strategy == "LLM":
        yield from classify_text_with_llm_stream(
            text,
            disable_level3=disable_level3,
            prompt_profile=prompt_profile,
        )
        return
    raise ValueError("strategy 仅支持 RULE 或 LLM")


def write_generation_data(metadata: dict[str, Any], paragraphs: list[dict[str, Any]]) -> Path:
    data = {
        "fixedFields": metadata_to_fixed_fields(metadata),
        "bodyBlocks": paragraphs_to_blocks(paragraphs),
    }
    fd, temp_name = tempfile.mkstemp(prefix="official_doc_data_", suffix=".json", dir=STORAGE_DIR)
    with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
        json.dump(data, temp_file, ensure_ascii=False, indent=2)
    return Path(temp_name)


class OfficialDocHandler(BaseHTTPRequestHandler):
    server_version = "OfficialDocAPI/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_error_json(self, status: int, code: int, message: str, data: Any = None) -> None:
        self.send_json(api_response(data, code=code, message=message), status)

    def do_GET(self) -> None:
        try:
            path = urlparse(self.path).path
            if path == f"{BASE_PATH}/document-templates":
                self.send_json(api_response(template_response()))
                return
            if path.startswith(f"{BASE_PATH}/files/") and path.endswith("/download"):
                self.handle_download(path)
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, 40401, "接口不存在")
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, 50001, str(exc))

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path
            parts = [unquote(part) for part in path.removeprefix(BASE_PATH).strip("/").split("/") if part]
            if path == f"{BASE_PATH}/document-drafts":
                self.handle_create_draft()
                return
            if len(parts) == 4 and parts[0] == "document-drafts" and parts[2:] == ["body", "parse"]:
                self.handle_parse_body(parts[1])
                return
            if len(parts) == 4 and parts[0] == "document-drafts" and parts[2:] == ["body", "classify"]:
                self.handle_classify_body(parts[1])
                return
            if len(parts) == 3 and parts[0] == "document-drafts" and parts[2] == "generate":
                self.handle_generate(parts[1])
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, 40401, "接口不存在")
        except json.JSONDecodeError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, 40002, "JSON 请求体格式错误")
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, 50001, str(exc))

    def do_PATCH(self) -> None:
        try:
            path = urlparse(self.path).path
            parts = [unquote(part) for part in path.removeprefix(BASE_PATH).strip("/").split("/") if part]
            if len(parts) == 4 and parts[0] == "document-drafts" and parts[2:] == ["body", "paragraph-types"]:
                self.handle_patch_paragraph_types(parts[1])
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, 40401, "接口不存在")
        except json.JSONDecodeError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, 40002, "JSON 请求体格式错误")
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, 50001, str(exc))

    def handle_create_draft(self) -> None:
        fields, uploaded = parse_multipart(self)
        template_ref = fields.get("templateType") or fields.get("templateId") or DEFAULT_TEMPLATE_ID
        template = resolve_template(template_ref)
        if not template:
            self.send_error_json(HTTPStatus.NOT_FOUND, 40001, "模板不存在")
            return
        if not template_is_ready(template):
            self.send_error_json(
                HTTPStatus.BAD_REQUEST,
                40013,
                f"{template['templateType']} 模板文件未配置，请补充 template/{template['templateType']}/template.docx（或 std_template.docx）和 std_format.json",
            )
            return
        metadata = json.loads(fields.get("metadata") or "{}")
        errors = validate_metadata(metadata, template)
        if errors:
            self.send_error_json(HTTPStatus.BAD_REQUEST, 40008, "必填字段缺失", {"errors": errors})
            return
        if not uploaded:
            self.send_error_json(HTTPStatus.BAD_REQUEST, 40009, "正文文件不能为空")
            return

        original_name = safe_filename(uploaded["fileName"])
        suffix = Path(original_name).suffix.lower()
        if suffix not in {".doc", ".docx", ".txt"}:
            self.send_error_json(HTTPStatus.BAD_REQUEST, 40010, "正文文件类型仅支持 .doc、.docx、.txt")
            return

        state = load_state()
        draft_id = new_id("draft")
        file_id = new_id("file")
        stored_name = f"{file_id}{suffix}"
        stored_path = UPLOAD_DIR / stored_name
        with stored_path.open("wb") as output_file:
            output_file.write(uploaded["content"])

        file_record = {
            "fileId": file_id,
            "fileName": original_name,
            "fileType": suffix.lstrip("."),
            "fileSize": stored_path.stat().st_size,
            "uploadTime": datetime.now(timezone.utc).isoformat(),
            "path": str(stored_path.relative_to(ROOT)),
        }
        draft = {
            "draftId": draft_id,
            "templateId": template["templateId"],
            "templateType": template["templateType"],
            "documentName": fields.get("documentName") or Path(original_name).stem,
            "metadata": metadata,
            "bodyFileId": file_id,
            "status": "CREATED",
        }
        state["files"][file_id] = file_record
        state["drafts"][draft_id] = draft
        save_state(state)

        response_data = {**draft, "bodyFile": {key: file_record[key] for key in ["fileId", "fileName", "fileType", "fileSize", "uploadTime"]}}
        response_data.pop("bodyFileId", None)
        self.send_json(api_response(response_data))

    def handle_parse_body(self, draft_id: str) -> None:
        payload = parse_json_body(self)
        state = load_state()
        draft = state["drafts"].get(draft_id)
        if not draft:
            self.send_error_json(HTTPStatus.NOT_FOUND, 40003, "草稿不存在")
            return
        file_id = payload.get("fileId") or draft.get("bodyFileId")
        file_record = state["files"].get(file_id)
        if not file_record:
            self.send_error_json(HTTPStatus.NOT_FOUND, 40004, "正文文件不存在")
            return
        strategy = str(payload.get("strategy") or "RULE").upper()
        if strategy not in {"RULE", "LLM"}:
            self.send_error_json(HTTPStatus.BAD_REQUEST, 40005, "strategy 仅支持 RULE 或 LLM")
            return

        body_text = read_body_file(file_record)
        disable_level3 = template_disables_level3(draft)
        prompt_profile = template_llm_profile(draft)
        try:
            paragraphs = classify_body_text_by_strategy(
                body_text,
                strategy,
                disable_level3=disable_level3,
                prompt_profile=prompt_profile,
            )
        except RuntimeError as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, 50003, str(exc))
            return
        parse_id = new_id("parse")
        parse_record = {
            "parseId": parse_id,
            "draftId": draft_id,
            "strategy": strategy,
            "paragraphs": paragraphs,
        }
        state["parses"][parse_id] = parse_record
        save_state(state)
        self.send_json(api_response(parse_record))

    def handle_classify_body(self, draft_id: str) -> None:
        payload = parse_json_body(self)
        state = load_state()
        if draft_id not in state["drafts"]:
            self.send_error_json(HTTPStatus.NOT_FOUND, 40003, "草稿不存在")
            return
        parse_id = payload.get("parseId")
        paragraphs = payload.get("paragraphs")
        if not isinstance(paragraphs, list):
            parse_record = state["parses"].get(parse_id)
            paragraphs = parse_record.get("paragraphs") if parse_record else None
        if not isinstance(paragraphs, list):
            self.send_error_json(HTTPStatus.BAD_REQUEST, 40006, "paragraphs 不能为空")
            return

        try:
            examples = payload.get("examples")
            use_examples = bool(payload.get("useExamples")) or isinstance(examples, list)
            if use_examples:
                file_id = payload.get("fileId") or state["drafts"][draft_id].get("bodyFileId")
                file_record = state["files"].get(file_id)
                if not file_record:
                    self.send_error_json(HTTPStatus.NOT_FOUND, 40004, "正文文件不存在")
                    return
                body_text = read_body_file(file_record)
                example_paragraphs = examples if isinstance(examples, list) else paragraphs
                classified = classify_text_with_llm_examples(
                    body_text,
                    example_paragraphs,
                    disable_level3=template_disables_level3(state["drafts"][draft_id]),
                    prompt_profile=template_llm_profile(state["drafts"][draft_id]),
                )
            else:
                classified = classify_with_llm(
                    paragraphs,
                    disable_level3=template_disables_level3(state["drafts"][draft_id]),
                    prompt_profile=template_llm_profile(state["drafts"][draft_id]),
                )
        except RuntimeError as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, 50003, str(exc))
            return
        parse_id = parse_id or new_id("parse")
        parse_record = {
            "draftId": draft_id,
            "parseId": parse_id,
            "strategy": "LLM_EXAMPLE" if use_examples else "LLM",
            "paragraphs": classified,
        }
        state["parses"][parse_id] = parse_record
        save_state(state)
        self.send_json(api_response(parse_record))

    def handle_patch_paragraph_types(self, draft_id: str) -> None:
        payload = parse_json_body(self)
        state = load_state()
        if draft_id not in state["drafts"]:
            self.send_error_json(HTTPStatus.NOT_FOUND, 40003, "草稿不存在")
            return
        parse_id = payload.get("parseId")
        parse_record = state["parses"].get(parse_id)
        if not parse_record:
            self.send_error_json(HTTPStatus.NOT_FOUND, 40007, "解析结果不存在")
            return
        updates = payload.get("updates") or []
        if not isinstance(updates, list):
            self.send_error_json(HTTPStatus.BAD_REQUEST, 40011, "updates 必须是数组")
            return
        by_index = {int(update["index"]): update for update in updates if "index" in update}
        updated_count = 0
        for paragraph in parse_record["paragraphs"]:
            update = by_index.get(int(paragraph["index"]))
            if not update:
                continue
            new_type = str(update.get("type") or "")
            if new_type not in ALLOWED_BLOCK_TYPES:
                self.send_error_json(HTTPStatus.BAD_REQUEST, 40012, f"不支持的段落类型：{new_type}")
                return
            paragraph["type"] = new_type
            paragraph.pop("segments", None)
            updated_count += 1
        save_state(state)
        self.send_json(
            api_response(
                {
                    "draftId": draft_id,
                    "parseId": parse_id,
                    "updatedCount": updated_count,
                    "paragraphs": parse_record["paragraphs"],
                }
            )
        )

    def handle_generate(self, draft_id: str) -> None:
        payload = parse_json_body(self)
        state = load_state()
        draft = state["drafts"].get(draft_id)
        if not draft:
            self.send_error_json(HTTPStatus.NOT_FOUND, 40003, "草稿不存在")
            return
        template_ref = payload.get("templateType") or payload.get("templateId") or draft.get("templateType") or draft.get("templateId") or DEFAULT_TEMPLATE_ID
        template = resolve_template(template_ref)
        if not template:
            self.send_error_json(HTTPStatus.NOT_FOUND, 40001, "模板不存在")
            return
        if not template_is_ready(template):
            self.send_error_json(
                HTTPStatus.BAD_REQUEST,
                40013,
                f"{template['templateType']} 模板文件未配置，请补充 template/{template['templateType']}/template.docx（或 std_template.docx）和 std_format.json",
            )
            return
        parse_id = payload.get("parseId")
        paragraphs = payload.get("paragraphs")
        if not isinstance(paragraphs, list):
            parse_record = state["parses"].get(parse_id)
            paragraphs = parse_record.get("paragraphs") if parse_record else None
        if not isinstance(paragraphs, list):
            self.send_error_json(HTTPStatus.BAD_REQUEST, 40006, "paragraphs 不能为空")
            return

        metadata = draft.get("metadata", {}).copy()
        metadata.update(payload.get("metadata") or {})
        document_id = new_id("doc")
        file_id = new_id("generated_docx")
        filename = safe_filename(f"{payload.get('documentName') or draft.get('documentName') or document_id}.docx")
        output_path = GENERATED_DIR / f"{file_id}.docx"
        data_path = write_generation_data(metadata, paragraphs)
        try:
            render_docx(
                ROOT / template["templatePath"],
                ROOT / template["configPath"],
                data_path,
                output_path,
                body_dir=None,
                body_blocks=paragraphs_to_blocks(paragraphs),
            )
        except Exception as exc:
            self.send_error_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                50002,
                "公文生成失败",
                {
                    "draftId": draft_id,
                    "status": "FAILED",
                    "error": {
                        "code": "RENDER_FAILED",
                        "message": f"公文生成失败，请检查模板字段和正文段落分类：{exc}",
                    },
                },
            )
            return
        finally:
            try:
                data_path.unlink()
            except OSError:
                pass

        file_record = {
            "fileId": file_id,
            "fileName": filename,
            "fileType": "DOCX",
            "fileSize": output_path.stat().st_size,
            "path": str(output_path.relative_to(ROOT)),
        }
        document_record = {
            "draftId": draft_id,
            "documentId": document_id,
            "status": "GENERATED",
            "outputFiles": [
                {
                    "fileId": file_id,
                    "fileType": "DOCX",
                    "fileName": filename,
                    "downloadUrl": f"{BASE_PATH}/files/{file_id}/download",
                }
            ],
        }
        state["files"][file_id] = file_record
        state["documents"][document_id] = document_record
        save_state(state)
        self.send_json(api_response(document_record))

    def handle_download(self, path: str) -> None:
        file_id = path.removeprefix(f"{BASE_PATH}/files/").removesuffix("/download")
        state = load_state()
        file_record = state["files"].get(file_id)
        if not file_record:
            self.send_error_json(HTTPStatus.NOT_FOUND, 40004, "文件不存在")
            return
        file_path = ROOT / file_record["path"]
        if not file_path.exists():
            self.send_error_json(HTTPStatus.NOT_FOUND, 40004, "文件不存在")
            return
        content_type = mimetypes.guess_type(file_record["fileName"])[0]
        content_type = content_type or "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(file_path.stat().st_size))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(file_record['fileName'])}")
        self.end_headers()
        with file_path.open("rb") as input_file:
            shutil.copyfileobj(input_file, self.wfile)


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    ensure_storage()
    server = ThreadingHTTPServer((host, port), OfficialDocHandler)
    print(f"Official document API running at http://{host}:{port}{BASE_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the official document API server.")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()
    run(args.host, args.port)
