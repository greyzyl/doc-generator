#!/usr/bin/env python3
"""Generate a formatted official DOCX from a placeholder template.

The implementation intentionally uses only the Python standard library so it
can run in a minimal backend environment. It edits the DOCX OOXML directly:
fixed fields are replaced in place, while the BODY_BLOCKS anchor paragraph is
replaced by dynamically generated paragraphs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

# 这三行是在告诉 Python，Word 文档 XML 里的 w: 是什么，
# 以及读写 Word 段落、文字、样式标签时该怎么正确识别和输出它。
NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}
W = f"{{{NS['w']}}}"
ET.register_namespace("w", NS["w"])


SEMANTIC_CLASSIFICATION_PROMPT = """\
你是公文正文结构解析助手。请把用户提供的无格式正文解析成 JSON。

要求：
1. 只输出 JSON，不输出解释、不要输出 markdown、不要输出多余文本。
2. JSON 顶层必须是一个对象，并包含 bodyBlocks 数组。
3. 输入中的每个非空行都对应一个且仅一个 bodyBlocks 元素；不要合并、拆分、改写、润色原文。
4. type 只能使用：
   MAIN_TITLE, SUB_TITLE, RECIPIENT, BODY_PARAGRAPH,
   LEVEL_1_TITLE, LEVEL_2_TITLE,
   LEVEL_3_TITLE, MIXED_LEVEL_3_BODY,
   ATTACHMENT_HEADER, ATTACHMENT_ITEM,
   SIGNING_COMPANY, SIGNING_DATE, CONTACT_INFO。
5. text 和 segments 内的 text 必须逐字保留输入原文，包括编号、标点和空格。
6. 主标题一般是第一行公文标题，例如“关于……的报告/请示/函/通知”。
7. RECIPIENT 表示主送对象或称呼，需结合位置、语义和冒号判断：
   - “中国铁道建筑集团有限公司：”“各相关单位：”“尊敬的各位领导、同仁们：”可识别为 RECIPIENT。
   - RECIPIENT 通常出现在主标题/副标题之后、正式主体展开之前；如果前面已有少量背景介绍或导语，
     仍可将后续明显的称呼行识别为 RECIPIENT。
   - “现将……如下：”“下面结合……作简要汇报：”这类导语或正文过渡句，即使以冒号结尾，也识别为 BODY_PARAGRAPH。
8. SUB_TITLE 表示主标题下的副标题或说明性标题。请按以下分支判断：
   A. 主标题之后、RECIPIENT之前，若出现短标题性行，可识别为 SUB_TITLE；
      它不一定紧邻 RECIPIENT，也不要求下一行必须是 RECIPIENT。
   B. 副标题一般是 4 到 60 字之间，无明显完整正文句式；通常不以“。；，、”等正文句末标点结尾。
   C. “这是新的起点。”“我们将持续推进改革，现将有关事项通知如下：”这类完整陈述句或导语，
      即使短，也识别为 BODY_PARAGRAPH。
9. “一、二、三、……” 开头的独立段识别为 LEVEL_1_TITLE。
10. “（一）（二）（三）……” 开头的段落识别为 LEVEL_2_TITLE。
   二级标题必须单独作为一个 Word 段落，正文另起段落。
11. “1. / 1． / 1、” 开头且后接正文时识别为 MIXED_LEVEL_3_BODY；
   第一个 segment type=LEVEL_3_TITLE_INLINE，第二个 segment type=BODY_TEXT。
12. 三级标题判定必须先看上下文中的同级编号序列，再看局部语义。请按以下分支判断：
   A. 先找“无争议三级标题”：段落开头是“数字+点/顿号/全角点”，且点后直接是文字而非数字，
      例如“2.新征程即将开启，我们应做好准备。”、“4.加强组织领导。”。
      这类通常可直接视为三级标题，并作为同级编号序列的锚点。
   B. 再处理“混淆候选”：段落开头形如“数字+点+数字/数量表达”，
      例如“1.5倍的居民收入开始增长。”、“3.6倍速度快速增长。”。
      它既可能是小数/数量开头的正文，也可能是编号为 1 或 3 的三级标题，标题内容从点后的数字开始。
   C. 对混淆候选，优先判断它的编号是否是当前同级序列中缺失的编号：
      - 如果已有同编号的无争议三级标题，则混淆候选是正文。
      - 如果上文已有无争议三级标题“2.xxx”，上下文没有其它编号为 3 的三级标题，
        且下文出现无争议三级标题“4.xxx”，那么位于 2 与 4 之间的“3.6倍速度快速增长。”
        可认定为编号 3 的三级标题。
      - 如果上文已有“2.xxx”，下文再无三级标题，但当前位置正好承接编号 2，
        且段落语义像分项论述标题，也可认定为编号 3 的三级标题。
      - 如果同一上下文中已有更明确的编号 3 三级标题，尤其是“3.”后直接接文字的候选，
        则“3.6倍...”这类混淆候选通常识别为 BODY_PARAGRAPH。
      - 如果存在多个同编号混淆候选，结合位置顺序和上下文语义选择最符合连续编号的位置；
        通常三级标题按 1、2、3、4 顺序接连出现。
   D. 若没有可靠的编号序列证据，或将其作为三级标题会造成编号重复、跳号无法解释、语义牵强，
      则保守识别为 BODY_PARAGRAPH。
13. MIXED_LEVEL_3_BODY 的 segment 拆分方式：
   - LEVEL_3_TITLE_INLINE 应包含编号和标题结束标点，例如“1.以本质安全为引领，构建涉铁施工“大安全”格局。”
   - BODY_TEXT 放该段剩余正文；若没有剩余正文，BODY_TEXT 可以是空字符串。
   - 不要把正文句子误放入 LEVEL_3_TITLE_INLINE。
14. 附件区域判定请按以下分支处理：
   A. “附件：1．正文模板格式确认清单”“附件：2.未来工作计划”这类整行识别为 ATTACHMENT_HEADER。
   B. ATTACHMENT_HEADER 之后，凡是语义上继续说明、列举或展开该附件内容的后续段落，
      即使有多个自然段，也连续识别为 ATTACHMENT_ITEM；不要只把紧跟的一行识别为附件条目。
   C. 若后续段落明显切回正文结束语、总结语、请求语或与附件主题无关，
      例如“以上报告，请审示。”“各位领导、同仁们，……”“我们将以此次会议为契机……”，
      则从该段开始停止附件识别，改为 BODY_PARAGRAPH 或其它更合适类型。
   D. 如果附件条目后出现 SIGNING_COMPANY、SIGNING_DATE、CONTACT_INFO，应按签署区/联系方式识别，
      不要继续识别为 ATTACHMENT_ITEM。
15. 末尾单位名称识别为 SIGNING_COMPANY，日期识别为 SIGNING_DATE；
    联系人/联系电话括号内容识别为 CONTACT_INFO。
16. 置信度低时保守识别为 BODY_PARAGRAPH。不要为了套格式而过度识别标题。

输出示例：
{
  "bodyBlocks": [
    {"type": "MAIN_TITLE", "text": "关于...的报告"},
    {"type": "SUB_TITLE", "text": "1.0版本施工安全概要"},
    {"type": "BODY_PARAGRAPH", "text": "这是新的起点。"},
    {"type": "BODY_PARAGRAPH", "text": "我们将持续推进改革，现将有关事项通知如下："},
    {"type": "RECIPIENT", "text": "领导："},
    {"type": "MIXED_LEVEL_3_BODY", "segments": [
      {"type": "LEVEL_3_TITLE_INLINE", "text": "1. 标题。"},
      {"type": "BODY_TEXT", "text": "这里是正文内容。"}
    ]},
    {"type": "BODY_PARAGRAPH", "text": "1.5倍的居民收入开始增长。"},
    {"type": "MIXED_LEVEL_3_BODY", "segments": [
      {"type": "LEVEL_3_TITLE_INLINE", "text": "3.6倍速度快速增长。"},
      {"type": "BODY_TEXT", "text": ""}
    ]},
    {"type": "ATTACHMENT_HEADER", "text": "附件：2.未来工作计划"},
    {"type": "ATTACHMENT_ITEM", "text": "后续将围绕安全、质量、进度开展专项提升。"},
    {"type": "ATTACHMENT_ITEM", "text": "同步完善台账资料，形成闭环管理。"},
    {"type": "BODY_PARAGRAPH", "text": "以上报告，请审示。"}
  ]
}
"""

STREAMING_CLASSIFICATION_PROMPT = SEMANTIC_CLASSIFICATION_PROMPT + """

流式输出补充要求：
1. 本次输入会以 JSON 数组给出，每项包含 index 和 text。
2. 请按输入 index 顺序输出 JSON Lines，每一行是一个独立 JSON 对象。
3. 每行对象必须包含 index 和 type；普通段落包含 text；MIXED_LEVEL_3_BODY 包含 segments。
4. 不要输出 JSON 数组，不要输出逗号分隔，不要输出 markdown，不要输出解释。
5. 每输出完一个对象立即换行，格式示例：
{"index":1,"type":"MAIN_TITLE","text":"关于...的函"}
{"index":2,"type":"RECIPIENT","text":"某单位："}
"""

ALLOWED_BLOCK_TYPES = {
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
    "CONTACT_INFO",
}

ALLOWED_SEGMENT_TYPES = {"LEVEL_3_TITLE_INLINE", "BODY_TEXT"}

# 定义一组正则规则，后面用来判断一行正文属于什么类型
CN_NUM = "一二三四五六七八九十" #各级标题
LEVEL_1_RE = re.compile(rf"^[{CN_NUM}]+、") #一级标题，从一行开头开始匹配，一个或多个”CN_NUM“的数字，后边跟着”、“
LEVEL_2_RE = re.compile(rf"^(（[{CN_NUM}]+）)(.+)") # 二级标题，分”（一）“这样的前缀+后文匹配，后面代码还会继续判断它是不是“标题 + 正文”混在同一段。
LEVEL_3_RE = re.compile(r"^(\d+[\.．、])\s*(?!\d)(.+)") # 三级标题，分”1.“这样的前缀+后文匹配，排除“1.5”等小数开头
DATE_RE = re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日$") # 匹配”xxxx年xx月xx日“，不会匹配”xxxx-xx-xx“、”xxxx年xx月xx日印发“
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z0-9_]+\}\}") # 识别模板里的占位符，如{{ISSUING_UNIT}}、{{DOC_NUMBER}}、{{BODY_BLOCKS}}，这个规则后面主要用于清理没有被替换掉的占位符，也就是把剩下的 {{XXX}} 删除掉


# 把普通标签名转成 ElementTree 能识别的 Word XML 标签名，也就是qn("p")--->"{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"，也就是 Word 里的 <w:p> 段落标签。
def qn(local: str) -> str:
    return W + local

# 用于读取“格式.json”，里面有模板占位符映射、正文锚点、段落样式、字体样式等。
# 用于读取“文字内容信息”，里面有固定字段和正文内容。
"""
"fixedFields": {
  "issuingUnit": "中铁二十四局集团有限公司",
  "docNumber": "中铁二十四局〔2026〕12号"
}
"bodyDocx": "files/test2.docx"
"""
def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# 取出一个 Word 段落里的全部文字
def paragraph_text(p: ET.Element) -> str:
    return "".join(t.text or "" for t in p.findall(".//w:t", NS))


# 从 docx 的 word/document.xml 抽取段落文本
def extract_docx_text(docx_path: Path) -> str:
    with zipfile.ZipFile(docx_path) as docx_zip:
        root = ET.fromstring(docx_zip.read("word/document.xml"))
    lines = [
        paragraph_text(paragraph).strip()
        for paragraph in root.findall(".//w:p", NS)
    ]
    return "\n".join(line for line in lines if line)


#正文来源优先级为：
# 命令行 --body-docx
# 数据 JSON 中的 bodyDocx
# --body-dir 目录下第一个 .docx
# 兼容旧逻辑：没有 docx 时才用 bodyText
def resolve_body_docx(data: dict[str, Any], body_docx: Path | None, body_dir: Path | None) -> Path | None:
    if body_docx:
        return body_docx

    configured = data.get("bodyDocx")
    if configured:
        return Path(configured)

    if body_dir and body_dir.exists():
        candidates = sorted(body_dir.glob("*.docx"))
        if candidates:
            return candidates[0]

    return None


# 给 <w:t> 设置文本，并且在文本首尾有空格时告诉 XML 不要吞掉空格。
def set_text_preserve_space(t: ET.Element, text: str) -> None:
    t.text = text
    if text.startswith(" ") or text.endswith(" "):
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def replace_text_in_paragraph(
    p: ET.Element,
    replacements: dict[str, str],
    cleanup_unresolved: bool = False,
) -> None:
    """Replace placeholders while preserving existing runs and tabs when possible."""
    texts = p.findall(".//w:t", NS)
    if not texts:
        return

    changed = False
    for text_node in texts:
        value = text_node.text or ""
        new_value = value
        for marker, replacement in replacements.items():
            new_value = new_value.replace(marker, replacement or "")
        if cleanup_unresolved:
            new_value = PLACEHOLDER_RE.sub("", new_value)
        if new_value != value:
            set_text_preserve_space(text_node, new_value)
            changed = True

    if changed:
        return

    combined = "".join(t.text or "" for t in texts)
    original = combined
    for marker, value in replacements.items():
        combined = combined.replace(marker, value or "")
    if cleanup_unresolved:
        combined = PLACEHOLDER_RE.sub("", combined)
    if combined == original:
        return

    set_text_preserve_space(texts[0], combined)
    for t in texts[1:]:
        t.text = ""


# 把普通多行正文识别成结构化段落。
"""
它的判断规则主要是：
第一行：MAIN_TITLE
主标题后一行且下一行是主送对象：SUB_TITLE

只有当一行满足这些条件时才识别为 SUB_TITLE：
必须是主标题后的第 2 行，也就是 index == 1 
下一行必须像主送对象，例如 中国铁道建筑集团有限公司： 
长度必须在 8 到 50 字之间
不能以正文常见标点结尾，如 。；：，
不能匹配一级、二级、三级标题、日期、附件、联系人等类型

日期格式：SIGNING_DATE
附件： 开头：ATTACHMENT_HEADER
包含联系人/联系电话：CONTACT_INFO
标题后短单位称呼且冒号结尾：RECIPIENT
一、 开头：LEVEL_1_TITLE
（一） 开头：二级标题
1. / 1． / 1、 开头：三级标题正文混合段
靠近末尾且像单位名称：SIGNING_COMPANY
其他：BODY_PARAGRAPH
"""
def classify_plain_text(text: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    blocks: list[dict[str, Any]] = []
    next_line_is_attachment_item = False

    for index, line in enumerate(lines):
        block_type = "BODY_PARAGRAPH"
        if next_line_is_attachment_item:
            block_type = "ATTACHMENT_ITEM"
            next_line_is_attachment_item = False
        elif index == 0:
            block_type = "MAIN_TITLE"
        elif is_subtitle_line(index, line, lines):
            block_type = "SUB_TITLE"
        elif DATE_RE.match(line):
            block_type = "SIGNING_DATE"
        elif line.startswith("附件：") or line.startswith("附件:"):
            block_type = "ATTACHMENT_HEADER"
            next_line_is_attachment_item = True
        elif line.startswith("（联系人") or "联系电话" in line:
            block_type = "CONTACT_INFO"
        elif is_recipient_line(index, line):
            block_type = "RECIPIENT"
        elif LEVEL_1_RE.match(line):
            block_type = "LEVEL_1_TITLE"
        elif LEVEL_2_RE.match(line):
            block_type = "LEVEL_2_TITLE"
        elif LEVEL_3_RE.match(line):
            prefix, rest = split_numbered_title(line, LEVEL_3_RE)
            blocks.append(
                {
                    "type": "MIXED_LEVEL_3_BODY",
                    "segments": [
                        {"type": "LEVEL_3_TITLE_INLINE", "text": prefix},
                        {"type": "BODY_TEXT", "text": rest},
                    ],
                }
            )
            continue
        elif index >= max(0, len(lines) - 3) and line.endswith(("公司", "委员会", "办公室", "集团")):
            block_type = "SIGNING_COMPANY"

        blocks.append({"type": block_type, "text": line})
    return blocks


def classify_plain_text_with_llm(
    text: str,
    *,
    model: str,
    base_url: str,
    api_key: str,
    timeout: float = 60.0,
) -> list[dict[str, Any]]:
    if not text.strip():
        return []

    raw_response = call_chat_completion(
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=[
            {"role": "system", "content": SEMANTIC_CLASSIFICATION_PROMPT},
            {"role": "user", "content": "请解析以下正文：\n\n" + text},
        ],
        timeout=timeout,
    )
    return normalize_body_blocks(parse_json_payload(raw_response))


def classify_plain_text_with_llm_stream(
    text: str,
    *,
    model: str,
    base_url: str,
    api_key: str,
    timeout: float = 60.0,
):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return

    input_items = [
        {"index": index, "text": line}
        for index, line in enumerate(lines, start=1)
    ]
    raw_parts: list[str] = []
    buffer = ""
    yielded: set[int] = set()

    for delta in call_chat_completion_stream(
        base_url=base_url,
        api_key=api_key,
        model=model,
        messages=[
            {"role": "system", "content": STREAMING_CLASSIFICATION_PROMPT},
            {"role": "user", "content": "请按 JSON Lines 解析以下正文：\n\n" + json.dumps(input_items, ensure_ascii=False)},
        ],
        timeout=timeout,
    ):
        raw_parts.append(delta)
        buffer += delta
        while "\n" in buffer:
            raw_line, buffer = buffer.split("\n", 1)
            parsed = parse_json_line_block(raw_line)
            if not parsed:
                continue
            index, block = parsed
            if index in yielded:
                continue
            yielded.add(index)
            yield index, block

    parsed = parse_json_line_block(buffer)
    if parsed:
        index, block = parsed
        if index not in yielded:
            yielded.add(index)
            yield index, block

    if len(yielded) == len(input_items):
        return

    raw_response = "".join(raw_parts)
    fallback_blocks = parse_streaming_fallback_blocks(raw_response)
    for index, block in fallback_blocks:
        if index in yielded:
            continue
        yielded.add(index)
        yield index, block


def parse_json_line_block(raw_line: str) -> tuple[int, dict[str, Any]] | None:
    line = raw_line.strip().rstrip(",")
    if not line or line.startswith("```"):
        return None
    if not line.startswith("{") or not line.endswith("}"):
        return None
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    index = int(payload.get("index") or 0)
    if index <= 0:
        return None
    blocks = normalize_body_blocks([payload])
    if not blocks:
        return None
    return index, blocks[0]


def parse_streaming_fallback_blocks(raw_response: str) -> list[tuple[int, dict[str, Any]]]:
    indexed_blocks: list[tuple[int, dict[str, Any]]] = []
    for raw_line in raw_response.splitlines():
        parsed = parse_json_line_block(raw_line)
        if parsed:
            indexed_blocks.append(parsed)
    if indexed_blocks:
        return indexed_blocks

    try:
        blocks = normalize_body_blocks(parse_json_payload(raw_response))
    except Exception:
        return []
    return [(index, block) for index, block in enumerate(blocks, start=1)]


def call_chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: float,
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM request failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM request failed: {exc}") from exc

    try:
        return response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected LLM response: {response_payload}") from exc


def call_chat_completion_stream(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    timeout: float,
):
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "stream": True,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = (
                    payload.get("choices", [{}])[0]
                    .get("delta", {})
                    .get("content")
                )
                if delta:
                    yield str(delta)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM request failed: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM request failed: {exc}") from exc


def parse_json_payload(raw_text: str) -> Any:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min(
            (index for index in [text.find("{"), text.find("[")] if index >= 0),
            default=-1,
        )
        end = max(text.rfind("}"), text.rfind("]"))
        if start < 0 or end < start:
            raise
        return json.loads(text[start : end + 1])


def normalize_body_blocks(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        raw_blocks = payload
    elif isinstance(payload, dict) and isinstance(payload.get("bodyBlocks"), list):
        raw_blocks = payload["bodyBlocks"]
    else:
        raise ValueError("LLM output must be a JSON object with bodyBlocks array, or a bodyBlocks array.")

    blocks: list[dict[str, Any]] = []
    for raw_block in raw_blocks:
        if not isinstance(raw_block, dict):
            continue
        block_type = str(raw_block.get("type") or "BODY_PARAGRAPH")
        if block_type not in ALLOWED_BLOCK_TYPES:
            block_type = "BODY_PARAGRAPH"

        segments = raw_block.get("segments")
        if block_type == "MIXED_LEVEL_3_BODY" and isinstance(segments, list):
            normalized_segments: list[dict[str, str]] = []
            for raw_segment in segments:
                if not isinstance(raw_segment, dict):
                    continue
                segment_type = str(raw_segment.get("type") or "BODY_TEXT")
                if segment_type not in ALLOWED_SEGMENT_TYPES:
                    segment_type = "BODY_TEXT"
                normalized_segments.append(
                    {
                        "type": segment_type,
                        "text": str(raw_segment.get("text") or ""),
                    }
                )
            if normalized_segments:
                blocks.append({"type": block_type, "segments": normalized_segments})
                continue

        text = str(raw_block.get("text") or "")
        if text or block_type != "BODY_PARAGRAPH":
            blocks.append({"type": block_type, "text": text})

    return blocks


def resolve_llm_api_key(explicit_api_key: str | None, api_key_env: str) -> str:
    if explicit_api_key:
        return explicit_api_key
    for env_name in [api_key_env, "DASHSCOPE_API_KEY", "OPENAI_API_KEY"]:
        value = os.environ.get(env_name)
        if value:
            return value
    raise RuntimeError(
        f"LLM classifier requires an API key. Set {api_key_env}, DASHSCOPE_API_KEY, "
        "or OPENAI_API_KEY; or pass --llm-api-key."
    )


# 返回已结构划分类的字段bodyblocks，如果输入里已经有bodyBlocks，就直接规范化返回；如果没有，就用纯文本分类器或LLM分类后返回。
def resolve_body_blocks(
    data: dict[str, Any],
    *,
    classifier: str = "rule",
    llm_model: str = "qwen-plus",
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    llm_api_key: str | None = None,
    llm_api_key_env: str = "DASHSCOPE_API_KEY",
    llm_timeout: float = 60.0,
) -> list[dict[str, Any]]:
    blocks = data.get("bodyBlocks")
    if blocks:
        return normalize_body_blocks(blocks)

    body_text = data.get("bodyText", "")
    if classifier == "llm":
        return classify_plain_text_with_llm(
            body_text,
            model=llm_model,
            base_url=llm_base_url,
            api_key=resolve_llm_api_key(llm_api_key, llm_api_key_env),
            timeout=llm_timeout,
        )
    return classify_plain_text(body_text)

# 将读取的文本内容bodyText加入到data里（upward_document_case.json），并返回更新的json
def load_generation_data(
    data_path: Path,
    body_docx: Path | None = None,
    body_dir: Path | None = Path("files"),
) -> dict[str, Any]:
    data = load_json(data_path)
    source_docx = resolve_body_docx(data, body_docx, body_dir)
    if source_docx:
        if not source_docx.exists():
            raise FileNotFoundError(f"Body DOCX not found: {source_docx}")
        data["bodyText"] = extract_docx_text(source_docx)
    return data


def is_recipient_line(index: int, line: str) -> bool:
    if index > 2 or not line.endswith(("：", ":")):
        return False
    if "如下" in line:
        return False
    return len(line) <= 40


def is_subtitle_line(index: int, line: str, lines: list[str]) -> bool:
    if index != 1 or index + 1 >= len(lines):
        return False
    if not is_recipient_line(index + 1, lines[index + 1]):
        return False
    if len(line) < 8 or len(line) > 50:
        return False
    if line.endswith(("。", "；", ";", "：", ":", "，", ",")):
        return False
    if LEVEL_1_RE.match(line) or LEVEL_2_RE.match(line) or LEVEL_3_RE.match(line):
        return False
    if DATE_RE.match(line) or line.startswith(("附件：", "附件:", "（联系人")):
        return False
    return True


# 把“编号标题 + 正文”拆开。优先找这些标点作为标题结束位置 ————> 。 ； ; : ： 如果找不到，就尝试按空格拆。
def split_numbered_title(line: str, pattern: re.Pattern[str]) -> tuple[str, str]:
    match = pattern.match(line)
    if not match:
        return line, ""
    head = match.group(1)
    rest = match.group(2).strip()
    title_end = re.search(r"[。；;:：]", rest)
    if title_end:
        end = title_end.end()
        return head + rest[:end], rest[end:].strip()
    parts = rest.split(maxsplit=1)
    if len(parts) == 2:
        return head + parts[0], parts[1]
    return line, ""


# 根据配置生成 Word 段落属性 <w:pPr>
def word_bool(value: Any) -> str:
    if isinstance(value, str):
        return "0" if value.strip().lower() in {"0", "false", "no", "off"} else "1"
    return "1" if value else "0"


def make_p_pr(style: dict[str, Any]) -> ET.Element:
    p_pr = ET.Element(qn("pPr"))

    for style_key, element_name in (
        ("adjustRightIndent", "adjustRightInd"),
        ("snapToGrid", "snapToGrid"),
    ):
        if style_key in style:
            ET.SubElement(p_pr, qn(element_name), {qn("val"): word_bool(style[style_key])})

    spacing_attrs: dict[str, str] = {}
    if "spaceBefore" in style:
        spacing_attrs[qn("before")] = str(round(float(style["spaceBefore"]) * 20))
    if "spaceAfter" in style:
        spacing_attrs[qn("after")] = str(round(float(style["spaceAfter"]) * 20))
    if "lineSpacing" in style:
        rule = style.get("lineSpacingRule")
        if rule == "exact":
            spacing_attrs[qn("line")] = str(round(float(style["lineSpacing"]) * 20))
            spacing_attrs[qn("lineRule")] = "exact"
        else:
            spacing_attrs[qn("line")] = str(round(float(style["lineSpacing"])))
            spacing_attrs[qn("lineRule")] = "auto"
    if spacing_attrs:
        ET.SubElement(p_pr, qn("spacing"), spacing_attrs)

    ind_attrs: dict[str, str] = {}
    if "leftIndent" in style:
        ind_attrs[qn("left")] = str(round(float(style["leftIndent"])))
    if "rightIndent" in style:
        ind_attrs[qn("right")] = str(round(float(style["rightIndent"])))
    if "firstLineIndentChars" in style:
        chars = float(style["firstLineIndentChars"])
        ind_attrs[qn("firstLineChars")] = str(round(chars * 100))
        ind_attrs[qn("firstLine")] = str(round(chars * 320))
    if "hangingIndent" in style:
        ind_attrs[qn("hanging")] = str(round(float(style["hangingIndent"])))
    if "hangingIndentChars" in style:
        chars = float(style["hangingIndentChars"])
        ind_attrs[qn("hangingChars")] = str(round(chars * 100))
        ind_attrs[qn("hanging")] = str(round(chars * 320))
    if ind_attrs:
        ET.SubElement(p_pr, qn("ind"), ind_attrs)

    alignment = style.get("alignment")
    if alignment:
        ET.SubElement(p_pr, qn("jc"), {qn("val"): alignment})

    return p_pr

# 根据配置生成 Word 文字属性 <w:rPr>
def make_r_pr(style: dict[str, Any]) -> ET.Element:
    r_pr = ET.Element(qn("rPr"))
    fonts: dict[str, str] = {}
    if style.get("asciiFont"):
        fonts[qn("ascii")] = str(style["asciiFont"])
    if style.get("eastAsiaFont"):
        fonts[qn("eastAsia")] = str(style["eastAsiaFont"])
    if style.get("hAnsiFont"):
        fonts[qn("hAnsi")] = str(style["hAnsiFont"])
    if style.get("csFont"):
        fonts[qn("cs")] = str(style["csFont"])
    if fonts:
        ET.SubElement(r_pr, qn("rFonts"), fonts)
    if style.get("bold"):
        ET.SubElement(r_pr, qn("b"))
    size = style.get("fontSizePt")
    if size:
        half_points = str(round(float(size) * 2)) # 注意 Word XML 里的字号单位是“半磅”，所以代码里*2
        ET.SubElement(r_pr, qn("sz"), {qn("val"): half_points})
        ET.SubElement(r_pr, qn("szCs"), {qn("val"): half_points})
    return r_pr


# 生成一个 Word 文本片段 <w:r>，先创建一个run，先加文字样式，再加文本内容
def make_run(text: str, run_style: dict[str, Any]) -> ET.Element:
    r = ET.Element(qn("r"))
    r.append(make_r_pr(run_style))
    t = ET.SubElement(r, qn("t"))
    set_text_preserve_space(t, text)
    return r


# 根据段落类型，决定使用哪个段落样式和哪个文字样式。比如"MAIN_TITLE"，返回：("MAIN_TITLE", "MAIN_TITLE_TEXT")，即段落样式用 paragraphStyles["MAIN_TITLE"]，文字样式用 runStyles["MAIN_TITLE_TEXT"]
# 如果是普通正文，就返回：("BODY_PARAGRAPH", "BODY_TEXT")
def style_for_block(block_type: str, config: dict[str, Any]) -> tuple[str, str]:
    configured = config.get("blockStyleMap", {}).get(block_type)
    if configured:
        return configured.get("paragraphStyle", "BODY_PARAGRAPH"), configured.get("runStyle", "BODY_TEXT")

    if block_type == "MAIN_TITLE":
        return "MAIN_TITLE", "MAIN_TITLE_TEXT"
    if block_type == "LEVEL_1_TITLE":
        return "LEVEL_1_TITLE", "LEVEL_1_TITLE_TEXT"
    if block_type == "LEVEL_2_TITLE":
        return "LEVEL_2_TITLE", "LEVEL_2_TITLE_TEXT"
    if block_type == "LEVEL_3_TITLE":
        return "LEVEL_3_TITLE", "LEVEL_3_TITLE_INLINE"
    if block_type == "MIXED_LEVEL_3_BODY":
        return "BODY_PARAGRAPH", "BODY_TEXT"
    if block_type == "SUB_TITLE":
        return "SUB_TITLE", "BODY_TEXT"
    if block_type == "RECIPIENT":
        return "RECIPIENT", "BODY_TEXT"
    if block_type == "SIGNING_COMPANY":
        return "SIGNING_COMPANY", "BODY_TEXT"
    if block_type == "SIGNING_DATE":
        return "SIGNING_DATE", "BODY_TEXT"
    if block_type == "ATTACHMENT_HEADER":
        return "ATTACHMENT_HEADER", "BODY_TEXT"
    if block_type == "ATTACHMENT_ITEM":
        return "ATTACHMENT_ITEM", "BODY_TEXT"
    if block_type == "CONTACT_INFO":
        return "CONTACT_INFO", "BODY_TEXT"
    return "BODY_PARAGRAPH", "BODY_TEXT"


# 给混合段里的不同片段选择文字样式。
def style_for_segment(segment_type: str) -> str:
    if segment_type == "LEVEL_3_TITLE_INLINE":
        return "LEVEL_3_TITLE_INLINE"
    return "BODY_TEXT"


# 把一个结构化 block 变成一个 Word 段落 <w:p>。如果 block 是普通段落,它就生成一个段落，里面一个 run。如果 block 是混合段,它就生成一个段落，里面多个 run，每个 run 可以有不同字体/加粗效果。
"""
{"type": "BODY_PARAGRAPH", "text": "这是正文。"}
"""
def make_paragraph(block: dict[str, Any], config: dict[str, Any]) -> ET.Element:
    block_type = block.get("type", "BODY_PARAGRAPH")
    p_style_key, r_style_key = style_for_block(block_type, config)
    p = ET.Element(qn("p"))
    p.append(make_p_pr(config["paragraphStyles"].get(p_style_key, {})))

    segments = block.get("segments")
    if segments:
        for segment in segments:
            run_style = config["runStyles"].get(style_for_segment(segment.get("type", "")), {})
            p.append(make_run(segment.get("text", ""), run_style))
        return p

    run_style = config["runStyles"].get(r_style_key, config["runStyles"].get("BODY_TEXT", {}))
    p.append(make_run(block.get("text", ""), run_style))
    return p


# 找到模板里的正文锚点 {{BODY_BLOCKS}}，然后替换成真正的正文段落。
# 遍历 word/document.xml 里的所有 body 子节点,找到包含锚点的段落后：
# 1. 删除这个锚点段落
# 2. 把 blocks 一个个转成 Word 段落
# 3. 插入原来的位置
# 如果找不到锚点，就报错
def insert_body_blocks(root: ET.Element, config: dict[str, Any], blocks: list[dict[str, Any]]) -> None:
    body = root.find("w:body", NS)
    if body is None:
        raise ValueError("word/document.xml missing w:body")
    anchor = config.get("bodyAnchor", "{{BODY_BLOCKS}}")

    children = list(body)
    for index, child in enumerate(children):
        if child.tag == qn("p") and anchor in paragraph_text(child):
            body.remove(child)
            for offset, block in enumerate(blocks):
                body.insert(index + offset, make_paragraph(block, config))
            return
    raise ValueError(f"Body anchor not found: {anchor}")


# 完整生成 DOCX 的主流程
"""
1. 读取样式配置 JSON
2. 读取数据 JSON
3. 获取固定字段 fixedFields
4. 获取正文 bodyBlocks，如果没有，则优先读取正文 DOCX 并写入运行时 bodyText，再自动分类
bodyBlocks 有两个来源，第一优先级：从数据 JSON 里直接读取 bodyBlocks（--data 指向的文件），
如果这个 JSON 里有：
{
  "bodyBlocks": [
    {"type": "MAIN_TITLE", "text": "..."},
    {"type": "RECIPIENT", "text": "..."}
  ]
}
直接使用它。
第二优先级：如果没有 bodyBlocks，就从 --body-docx、data.bodyDocx 或 --body-dir 指向的 DOCX 抽取正文；
第三优先级：兼容旧数据，如果没有正文 DOCX，就从 data.bodyText 自动生成

5. 根据 placeholderMap 准备占位符替换表
6. 创建临时目录
7. 解压模板 .docx
8. 解析 word/document.xml
9. 替换固定占位符
10. 插入正文段落
11. 清理剩余未替换占位符
12. 写回 XML
13. 重新压缩成目标 .docx
"""
def render_docx(
    template: Path,
    config_path: Path,
    data_path: Path,
    output: Path,
    body_docx: Path | None = None,
    body_dir: Path | None = Path("files"),
    classifier: str = "rule",
    llm_model: str = "qwen-plus",
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    llm_api_key: str | None = None,
    llm_api_key_env: str = "DASHSCOPE_API_KEY",
    llm_timeout: float = 60.0,
    body_blocks: list[dict[str, Any]] | None = None,
) -> None:
    config = load_json(config_path) #获取格式json
    data = load_generation_data(data_path, body_docx, body_dir) # 获取待填入的固定字段和正文内容，实际上就是补充了实际正文文本内容的upward_document_case.json

    fixed_fields = data.get("fixedFields", {})
    blocks = body_blocks
    if blocks is None:
        blocks = resolve_body_blocks(
            data,
            classifier=classifier,
            llm_model=llm_model,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_api_key_env=llm_api_key_env,
            llm_timeout=llm_timeout,
        )

    placeholder_map = config.get("placeholderMap", {})
    missing_fixed_field_text = str(config.get("missingFixedFieldText", "XXXX"))
    replacements = {
        marker: str(fixed_fields.get(field) or missing_fixed_field_text)
        for field, marker in placeholder_map.items()
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        with zipfile.ZipFile(template) as source_zip:
            source_zip.extractall(temp_path)

        document_path = temp_path / "word" / "document.xml"
        tree = ET.parse(document_path)
        root = tree.getroot()

        for p in root.findall(".//w:p", NS):
            replace_text_in_paragraph(p, replacements)
        insert_body_blocks(root, config, blocks)
        for p in root.findall(".//w:p", NS):
            replace_text_in_paragraph(p, {}, cleanup_unresolved=True)

        tree.write(document_path, encoding="utf-8", xml_declaration=True)

        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target_zip:
            for file_path in temp_path.rglob("*"):
                if file_path.is_file():
                    target_zip.write(file_path, file_path.relative_to(temp_path).as_posix())


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate official DOCX from a fixed template.")
    parser.add_argument("--template", default="上行文.docx") # word模板文件，包含版头、版记、正文blcok替换符。
    parser.add_argument("--config", default="上行文.json") # 指定样式和占位符配置文件。
    parser.add_argument("--data", default="testdata/upward_document_case.json") # 指定生成文档的数据文件，包含版头版记文字内容以及正文内容文件路径
    parser.add_argument("--body-docx", default=None, help="正文内容 DOCX 文件路径，优先级高于 data.bodyDocx。")
    parser.add_argument("--body-dir", default="files", help="未指定正文 DOCX 时，从该目录读取第一个 .docx。")
    parser.add_argument("--output", default="output/test1_生成结果.docx")
    parser.add_argument(
        "--classifier",
        choices=["rule", "llm"],
        default="rule",
        help="正文结构识别方式：rule 使用现有规则库；llm 调用大模型识别。",
    )
    parser.add_argument(
        "--llm-model",
        default=os.environ.get("DASHSCOPE_MODEL") or os.environ.get("LLM_MODEL") or "qwen-plus",
        help="LLM 模型名，仅在 --classifier llm 时使用。",
    )
    parser.add_argument(
        "--llm-base-url",
        default=(
            os.environ.get("DASHSCOPE_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        help="OpenAI 兼容接口 base URL，仅在 --classifier llm 时使用。",
    )
    parser.add_argument(
        "--llm-api-key",
        default=None,
        help="LLM API Key。一般不建议在命令行明文传入，优先使用环境变量。",
    )
    parser.add_argument(
        "--llm-api-key-env",
        default="DASHSCOPE_API_KEY",
        help="读取 LLM API Key 的环境变量名；默认 DASHSCOPE_API_KEY。",
    )
    parser.add_argument(
        "--llm-timeout",
        type=float,
        default=480.0,
        help="LLM 请求超时时间，单位秒。",
    )
    parser.add_argument(
        "--print-body-blocks",
        action="store_true",
        help="打印最终用于写入正文的 bodyBlocks JSON，便于检查规则库/LLM 匹配结果。",
    )
    parser.add_argument("--print-prompt", action="store_true", help="Print the optimized LLM prompt.")
    args = parser.parse_args()

    if args.print_prompt:
        print(SEMANTIC_CLASSIFICATION_PROMPT)
        return

    body_blocks = None
    if args.print_body_blocks:
        data = load_generation_data(
            Path(args.data),
            body_docx=Path(args.body_docx) if args.body_docx else None,
            body_dir=Path(args.body_dir) if args.body_dir else None,
        )
        # 在分类字段之前，data中已有固定字段、原始文本内容bodyText，下边通过不同分类器获得结构化blocks
        body_blocks = resolve_body_blocks(
            data,
            classifier=args.classifier,
            llm_model=args.llm_model,
            llm_base_url=args.llm_base_url,
            llm_api_key=args.llm_api_key,
            llm_api_key_env=args.llm_api_key_env,
            llm_timeout=args.llm_timeout,
        )
        print(json.dumps({"bodyBlocks": body_blocks}, ensure_ascii=False, indent=2))

    render_docx(
        Path(args.template),
        Path(args.config),
        Path(args.data),
        Path(args.output),
        body_docx=Path(args.body_docx) if args.body_docx else None,
        body_dir=Path(args.body_dir) if args.body_dir else None,
        classifier=args.classifier,
        llm_model=args.llm_model,
        llm_base_url=args.llm_base_url,
        llm_api_key=args.llm_api_key,
        llm_api_key_env=args.llm_api_key_env,
        llm_timeout=args.llm_timeout,
        body_blocks=body_blocks,
    )
    print(f"Generated: {args.output}")


if __name__ == "__main__":
    main()
