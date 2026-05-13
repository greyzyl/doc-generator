#!/usr/bin/env python3
"""Flask API for the official document generator."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request, send_file, stream_with_context

from generate_official_doc import (
    ALLOWED_BLOCK_TYPES,
    render_docx,
)
from official_doc_api import (
    BASE_PATH,
    DEFAULT_TEMPLATE_ID,
    GENERATED_DIR,
    ROOT,
    UPLOAD_DIR,
    api_response,
    classify_body_text_by_strategy,
    classify_body_text_by_strategy_stream,
    classify_text_with_llm_examples,
    classify_text_with_llm_examples_stream,
    classify_with_llm,
    load_state,
    new_id,
    paragraphs_to_blocks,
    read_body_file,
    resolve_template,
    safe_filename,
    save_state,
    template_is_ready,
    template_response,
    template_disables_level3,
    template_llm_profile,
    validate_metadata,
    write_generation_data,
)


app = Flask(__name__)
app.json.ensure_ascii = False


def json_ok(data: Any = None):
    return jsonify(api_response(data))


def json_error(status: int, code: int, message: str, data: Any = None):
    return jsonify(api_response(data, code=code, message=message)), status


def sse_event(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def parse_metadata(raw_metadata: str | None) -> dict[str, Any]:
    if not raw_metadata:
        return {}
    metadata = json.loads(raw_metadata)
    if not isinstance(metadata, dict):
        raise ValueError("metadata 必须是 JSON 对象")
    return metadata


@app.errorhandler(json.JSONDecodeError)
def handle_json_decode_error(_: json.JSONDecodeError):
    return json_error(400, 40002, "JSON 请求体格式错误")


@app.errorhandler(Exception)
def handle_uncaught_error(exc: Exception):
    return json_error(500, 50001, str(exc))


@app.get(f"{BASE_PATH}/document-templates")
def get_document_templates():
    return json_ok(template_response())


@app.post(f"{BASE_PATH}/document-drafts")
def create_document_draft():
    template_ref = request.form.get("templateType") or request.form.get("templateId") or DEFAULT_TEMPLATE_ID
    template = resolve_template(template_ref)
    if not template:
        return json_error(404, 40001, "模板不存在")
    if not template_is_ready(template):
        return json_error(
            400,
            40013,
            f"{template['templateType']} 模板文件未配置，请补充 template/{template['templateType']}/template.docx（或 std_template.docx）和 std_format.json",
        )

    metadata = parse_metadata(request.form.get("metadata"))
    errors = validate_metadata(metadata, template)
    if errors:
        return json_error(400, 40008, "必填字段缺失", {"errors": errors})

    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        return json_error(400, 40009, "正文文件不能为空")

    original_name = safe_filename(uploaded.filename)
    suffix = Path(original_name).suffix.lower()
    if suffix not in {".doc", ".docx", ".txt"}:
        return json_error(400, 40010, "正文文件类型仅支持 .doc、.docx、.txt")

    state = load_state()
    draft_id = new_id("draft")
    file_id = new_id("file")
    stored_path = UPLOAD_DIR / f"{file_id}{suffix}"
    uploaded.save(stored_path)

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
        "documentName": request.form.get("documentName") or Path(original_name).stem,
        "metadata": metadata,
        "bodyFileId": file_id,
        "status": "CREATED",
    }
    state["files"][file_id] = file_record
    state["drafts"][draft_id] = draft
    save_state(state)

    response_data = {
        **draft,
        "bodyFile": {
            key: file_record[key]
            for key in ["fileId", "fileName", "fileType", "fileSize", "uploadTime"]
        },
    }
    response_data.pop("bodyFileId", None)
    return json_ok(response_data)


@app.post(f"{BASE_PATH}/document-drafts/<draft_id>/body/parse")
def parse_body(draft_id: str):
    payload = request.get_json(silent=True) or {}
    state = load_state()
    draft = state["drafts"].get(draft_id)
    if not draft:
        return json_error(404, 40003, "草稿不存在")

    file_id = payload.get("fileId") or draft.get("bodyFileId")
    file_record = state["files"].get(file_id)
    if not file_record:
        return json_error(404, 40004, "正文文件不存在")

    strategy = str(payload.get("strategy") or "RULE").upper()
    if strategy not in {"RULE", "LLM"}:
        return json_error(400, 40005, "strategy 仅支持 RULE 或 LLM")

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
        return json_error(502, 50003, str(exc))
    parse_id = new_id("parse")
    parse_record = {
        "parseId": parse_id,
        "draftId": draft_id,
        "strategy": strategy,
        "paragraphs": paragraphs,
    }
    state["parses"][parse_id] = parse_record
    save_state(state)
    return json_ok(parse_record)


@app.post(f"{BASE_PATH}/document-drafts/<draft_id>/body/parse/stream")
def parse_body_stream(draft_id: str):
    payload = request.get_json(silent=True) or {}
    state = load_state()
    draft = state["drafts"].get(draft_id)
    if not draft:
        return json_error(404, 40003, "草稿不存在")

    file_id = payload.get("fileId") or draft.get("bodyFileId")
    file_record = state["files"].get(file_id)
    if not file_record:
        return json_error(404, 40004, "正文文件不存在")

    strategy = str(payload.get("strategy") or "RULE").upper()
    if strategy not in {"RULE", "LLM"}:
        return json_error(400, 40005, "strategy 仅支持 RULE 或 LLM")

    body_text = read_body_file(file_record)
    parse_id = new_id("parse")
    disable_level3 = template_disables_level3(draft)
    prompt_profile = template_llm_profile(draft)

    def generate_events():
        paragraphs: list[dict[str, Any]] = []
        yield sse_event("status", {"message": "已开始解析正文"})
        yield sse_event(
            "parseStart",
            {"draftId": draft_id, "parseId": parse_id, "strategy": strategy},
        )

        try:
            for paragraph in classify_body_text_by_strategy_stream(
                body_text,
                strategy,
                disable_level3=disable_level3,
                prompt_profile=prompt_profile,
            ):
                paragraph = {**paragraph, "index": int(paragraph.get("index") or len(paragraphs) + 1)}
                paragraphs.append(paragraph)
                yield sse_event(
                    "paragraph",
                    {
                        "draftId": draft_id,
                        "parseId": parse_id,
                        "strategy": strategy,
                        "paragraph": paragraph,
                        "count": len(paragraphs),
                    },
                )

            if strategy == "LLM" and not paragraphs:
                yield sse_event("error", {"code": 50003, "message": "LLM 未返回可解析段落"})
                return

            paragraphs.sort(key=lambda item: int(item.get("index") or 0))
            for index, paragraph in enumerate(paragraphs, start=1):
                paragraph["index"] = index

            parse_record = {
                "parseId": parse_id,
                "draftId": draft_id,
                "strategy": strategy,
                "paragraphs": paragraphs,
            }
            latest_state = load_state()
            latest_state["parses"][parse_id] = parse_record
            save_state(latest_state)
            yield sse_event("done", parse_record)
        except RuntimeError as exc:
            yield sse_event("error", {"code": 50003, "message": str(exc)})
        except Exception as exc:
            yield sse_event("error", {"code": 50001, "message": str(exc)})

    return Response(
        stream_with_context(generate_events()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post(f"{BASE_PATH}/document-drafts/<draft_id>/body/classify")
def classify_body(draft_id: str):
    payload = request.get_json(silent=True) or {}
    state = load_state()
    if draft_id not in state["drafts"]:
        return json_error(404, 40003, "草稿不存在")

    parse_id = payload.get("parseId")
    paragraphs = payload.get("paragraphs")
    if not isinstance(paragraphs, list):
        parse_record = state["parses"].get(parse_id)
        paragraphs = parse_record.get("paragraphs") if parse_record else None
    if not isinstance(paragraphs, list):
        return json_error(400, 40006, "paragraphs 不能为空")

    try:
        examples = payload.get("examples")
        use_examples = bool(payload.get("useExamples")) or isinstance(examples, list)
        if use_examples:
            file_id = payload.get("fileId") or state["drafts"][draft_id].get("bodyFileId")
            file_record = state["files"].get(file_id)
            if not file_record:
                return json_error(404, 40004, "正文文件不存在")
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
        return json_error(502, 50003, str(exc))

    parse_id = parse_id or new_id("parse")
    parse_record = {
        "draftId": draft_id,
        "parseId": parse_id,
        "strategy": "LLM_EXAMPLE" if use_examples else "LLM",
        "paragraphs": classified,
    }
    state["parses"][parse_id] = parse_record
    save_state(state)
    return json_ok(parse_record)


@app.post(f"{BASE_PATH}/document-drafts/<draft_id>/body/classify/stream")
def classify_body_stream(draft_id: str):
    payload = request.get_json(silent=True) or {}
    state = load_state()
    if draft_id not in state["drafts"]:
        return json_error(404, 40003, "草稿不存在")

    parse_id = payload.get("parseId")
    paragraphs = payload.get("paragraphs")
    if not isinstance(paragraphs, list):
        parse_record = state["parses"].get(parse_id)
        paragraphs = parse_record.get("paragraphs") if parse_record else None
    if not isinstance(paragraphs, list):
        return json_error(400, 40006, "paragraphs 不能为空")

    examples = payload.get("examples")
    use_examples = bool(payload.get("useExamples")) or isinstance(examples, list)
    if use_examples:
        file_id = payload.get("fileId") or state["drafts"][draft_id].get("bodyFileId")
        file_record = state["files"].get(file_id)
        if not file_record:
            return json_error(404, 40004, "正文文件不存在")
        body_text = read_body_file(file_record)
        example_paragraphs = examples if isinstance(examples, list) else paragraphs
    else:
        body_text = "\n".join(str(paragraph.get("text") or "") for paragraph in paragraphs)
        example_paragraphs = []

    parse_id = parse_id or new_id("parse")
    strategy = "LLM_EXAMPLE" if use_examples else "LLM"
    draft = state["drafts"][draft_id]
    disable_level3 = template_disables_level3(draft)
    prompt_profile = template_llm_profile(draft)

    def generate_events():
        classified_paragraphs: list[dict[str, Any]] = []
        yield sse_event(
            "status",
            {"message": "已开始按修改示例重整解析" if use_examples else "已开始重新解析正文"},
        )
        yield sse_event(
            "parseStart",
            {"draftId": draft_id, "parseId": parse_id, "strategy": strategy},
        )

        try:
            paragraph_stream = (
                classify_text_with_llm_examples_stream(
                    body_text,
                    example_paragraphs,
                    disable_level3=disable_level3,
                    prompt_profile=prompt_profile,
                )
                if use_examples
                else classify_body_text_by_strategy_stream(
                    body_text,
                    "LLM",
                    disable_level3=disable_level3,
                    prompt_profile=prompt_profile,
                )
            )
            for paragraph in paragraph_stream:
                paragraph = {**paragraph, "index": int(paragraph.get("index") or len(classified_paragraphs) + 1)}
                classified_paragraphs.append(paragraph)
                yield sse_event(
                    "paragraph",
                    {
                        "draftId": draft_id,
                        "parseId": parse_id,
                        "strategy": strategy,
                        "paragraph": paragraph,
                        "count": len(classified_paragraphs),
                    },
                )

            if not classified_paragraphs:
                yield sse_event("error", {"code": 50003, "message": "LLM 未返回可解析段落"})
                return

            classified_paragraphs.sort(key=lambda item: int(item.get("index") or 0))
            for index, paragraph in enumerate(classified_paragraphs, start=1):
                paragraph["index"] = index

            parse_record = {
                "draftId": draft_id,
                "parseId": parse_id,
                "strategy": strategy,
                "paragraphs": classified_paragraphs,
            }
            latest_state = load_state()
            latest_state["parses"][parse_id] = parse_record
            save_state(latest_state)
            yield sse_event("done", parse_record)
        except RuntimeError as exc:
            yield sse_event("error", {"code": 50003, "message": str(exc)})
        except Exception as exc:
            yield sse_event("error", {"code": 50001, "message": str(exc)})

    return Response(
        stream_with_context(generate_events()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.patch(f"{BASE_PATH}/document-drafts/<draft_id>/body/paragraph-types")
def patch_paragraph_types(draft_id: str):
    payload = request.get_json(silent=True) or {}
    state = load_state()
    if draft_id not in state["drafts"]:
        return json_error(404, 40003, "草稿不存在")

    parse_id = payload.get("parseId")
    parse_record = state["parses"].get(parse_id)
    if not parse_record:
        return json_error(404, 40007, "解析结果不存在")

    updates = payload.get("updates") or []
    if not isinstance(updates, list):
        return json_error(400, 40011, "updates 必须是数组")

    by_index = {int(update["index"]): update for update in updates if "index" in update}
    updated_count = 0
    for paragraph in parse_record["paragraphs"]:
        update = by_index.get(int(paragraph["index"]))
        if not update:
            continue
        new_type = str(update.get("type") or "")
        if new_type not in ALLOWED_BLOCK_TYPES:
            return json_error(400, 40012, f"不支持的段落类型：{new_type}")
        paragraph["type"] = new_type
        paragraph.pop("segments", None)
        updated_count += 1

    save_state(state)
    return json_ok(
        {
            "draftId": draft_id,
            "parseId": parse_id,
            "updatedCount": updated_count,
            "paragraphs": parse_record["paragraphs"],
        }
    )


@app.post(f"{BASE_PATH}/document-drafts/<draft_id>/generate")
def generate_document(draft_id: str):
    payload = request.get_json(silent=True) or {}
    state = load_state()
    draft = state["drafts"].get(draft_id)
    if not draft:
        return json_error(404, 40003, "草稿不存在")

    template_ref = (
        payload.get("templateType")
        or payload.get("templateId")
        or draft.get("templateType")
        or draft.get("templateId")
        or DEFAULT_TEMPLATE_ID
    )
    template = resolve_template(template_ref)
    if not template:
        return json_error(404, 40001, "模板不存在")
    if not template_is_ready(template):
        return json_error(
            400,
            40013,
            f"{template['templateType']} 模板文件未配置，请补充 template/{template['templateType']}/template.docx（或 std_template.docx）和 std_format.json",
        )

    parse_id = payload.get("parseId")
    paragraphs = payload.get("paragraphs")
    if not isinstance(paragraphs, list):
        parse_record = state["parses"].get(parse_id)
        paragraphs = parse_record.get("paragraphs") if parse_record else None
    if not isinstance(paragraphs, list):
        return json_error(400, 40006, "paragraphs 不能为空")

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
        return json_error(
            500,
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
    return json_ok(document_record)


@app.get(f"{BASE_PATH}/files/<file_id>/download")
def download_file(file_id: str):
    state = load_state()
    file_record = state["files"].get(file_id)
    if not file_record:
        return json_error(404, 40004, "文件不存在")

    file_path = ROOT / file_record["path"]
    if not file_path.exists():
        return json_error(404, 40004, "文件不存在")

    return send_file(
        file_path,
        as_attachment=True,
        download_name=file_record["fileName"],
    )


def run(host: str = "127.0.0.1", port: int = 8000, debug: bool = False) -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run the Flask official document API server.")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    run(args.host, args.port, args.debug)
