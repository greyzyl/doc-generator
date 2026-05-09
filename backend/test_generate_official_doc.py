#!/usr/bin/env python3
"""Smoke tests for DOCX generation."""

from __future__ import annotations

import re
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from generate_official_doc import (
    classify_plain_text,
    extract_docx_text,
    normalize_body_blocks,
    parse_json_payload,
)


NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    return "\n".join(
        "".join(t.text or "" for t in p.findall(".//w:t", NS))
        for p in root.findall(".//w:p", NS)
    )


def docx_paragraphs(path: Path) -> list[ET.Element]:
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    return root.findall(".//w:p", NS)


def paragraph_text(p: ET.Element) -> str:
    return "".join(t.text or "" for t in p.findall(".//w:t", NS))


def word_attr(element: ET.Element | None, name: str) -> str | None:
    if element is None:
        return None
    return element.get(f"{{{NS['w']}}}{name}")


def paragraph_by_text(path: Path, expected_text: str) -> ET.Element:
    for paragraph in docx_paragraphs(path):
        if paragraph_text(paragraph) == expected_text:
            return paragraph
    raise AssertionError(f"Paragraph not found: {expected_text}")


def paragraph_containing_text(path: Path, expected_text: str) -> ET.Element:
    for paragraph in docx_paragraphs(path):
        if expected_text in paragraph_text(paragraph):
            return paragraph
    raise AssertionError(f"Paragraph containing text not found: {expected_text}")


def assert_paragraph_format(
    path: Path,
    expected_text: str,
    *,
    left: str | None = None,
    right: str | None = None,
    line: str | None = None,
    line_rule: str | None = None,
) -> None:
    paragraph = paragraph_by_text(path, expected_text)
    paragraph_properties = paragraph.find("w:pPr", NS)
    indent = paragraph_properties.find("w:ind", NS) if paragraph_properties is not None else None
    spacing = paragraph_properties.find("w:spacing", NS) if paragraph_properties is not None else None

    assert word_attr(indent, "left") == left
    assert word_attr(indent, "right") == right
    assert word_attr(spacing, "line") == line
    assert word_attr(spacing, "lineRule") == line_rule


def assert_existing_paragraph_format(
    paragraph: ET.Element,
    *,
    left: str | None = None,
    right: str | None = None,
    first_line: str | None = None,
    first_line_chars: str | None = None,
    before: str | None = None,
    after: str | None = None,
    line: str | None = None,
    line_rule: str | None = None,
    adjust_right_ind: str | None = None,
    snap_to_grid: str | None = None,
) -> None:
    paragraph_properties = paragraph.find("w:pPr", NS)
    indent = paragraph_properties.find("w:ind", NS) if paragraph_properties is not None else None
    spacing = paragraph_properties.find("w:spacing", NS) if paragraph_properties is not None else None
    adjust_right_ind_node = paragraph_properties.find("w:adjustRightInd", NS) if paragraph_properties is not None else None
    snap_to_grid_node = paragraph_properties.find("w:snapToGrid", NS) if paragraph_properties is not None else None

    assert word_attr(indent, "left") == left
    assert word_attr(indent, "right") == right
    assert word_attr(spacing, "line") == line
    assert word_attr(spacing, "lineRule") == line_rule
    if first_line is not None:
        assert word_attr(indent, "firstLine") == first_line
    if first_line_chars is not None:
        assert word_attr(indent, "firstLineChars") == first_line_chars
    if before is not None:
        assert word_attr(spacing, "before") == before
    if after is not None:
        assert word_attr(spacing, "after") == after
    if adjust_right_ind is not None:
        assert word_attr(adjust_right_ind_node, "val") == adjust_right_ind
    if snap_to_grid is not None:
        assert word_attr(snap_to_grid_node, "val") == snap_to_grid


def assert_first_run_fonts(
    path: Path,
    expected_text: str,
    *,
    east_asia: str,
    ascii_font: str,
    h_ansi: str,
) -> None:
    paragraph = paragraph_by_text(path, expected_text)
    first_run = paragraph.find("w:r", NS)
    run_fonts = first_run.find("w:rPr/w:rFonts", NS) if first_run is not None else None

    assert word_attr(run_fonts, "eastAsia") == east_asia
    assert word_attr(run_fonts, "ascii") == ascii_font
    assert word_attr(run_fonts, "hAnsi") == h_ansi


def assert_doc_number_and_signer_are_tab_separated(path: Path) -> None:
    paragraph = paragraph_containing_text(path, "签发人：张三")
    direct_texts = [node.text or "" for node in paragraph.findall("w:r/w:t", NS)]
    assert direct_texts[0] == "中铁二十四局〔2026〕12号"
    assert direct_texts[-1] == "签发人：张三"
    assert len(paragraph.findall(".//w:tab", NS)) >= 1


def main() -> None:
    parsed = parse_json_payload(
        "```json\n"
        "{\"bodyBlocks\":[{\"type\":\"BODY_PARAGRAPH\",\"text\":\"1.5倍的居民收入开始增长。\"}]}"
        "\n```"
    )
    assert normalize_body_blocks(parsed) == [
        {"type": "BODY_PARAGRAPH", "text": "1.5倍的居民收入开始增长。"}
    ]
    assert normalize_body_blocks(
        [
            {
                "type": "MIXED_LEVEL_3_BODY",
                "segments": [
                    {"type": "LEVEL_3_TITLE_INLINE", "text": "1.以安全为引领。"},
                    {"type": "BODY_TEXT", "text": "持续完善机制。"},
                ],
            },
            {"type": "UNKNOWN", "text": "无法识别时保守作为正文。"},
        ]
    ) == [
        {
            "type": "MIXED_LEVEL_3_BODY",
            "segments": [
                {"type": "LEVEL_3_TITLE_INLINE", "text": "1.以安全为引领。"},
                {"type": "BODY_TEXT", "text": "持续完善机制。"},
            ],
        },
        {"type": "BODY_PARAGRAPH", "text": "无法识别时保守作为正文。"},
    ]

    body_text = extract_docx_text(Path("files/test1.docx"))
    blocks = classify_plain_text(body_text)
    block_types = [block["type"] for block in blocks]
    assert "MIXED_LEVEL_2_BODY" not in block_types
    assert block_types[:9] == [
        "MAIN_TITLE",
        "SUB_TITLE",
        "RECIPIENT",
        "BODY_PARAGRAPH",
        "LEVEL_1_TITLE",
        "BODY_PARAGRAPH",
        "LEVEL_1_TITLE",
        "BODY_PARAGRAPH",
        "MIXED_LEVEL_3_BODY",
    ]

    subtitle_blocks = classify_plain_text(
        "中铁二十四局集团有限公司关于办理产权登记的报告\n"
        "办理产权登记事项说明\n"
        "中国铁道建筑集团有限公司：\n"
        "现将有关事项报告如下："
    )
    assert [block["type"] for block in subtitle_blocks] == [
        "MAIN_TITLE",
        "SUB_TITLE",
        "RECIPIENT",
        "BODY_PARAGRAPH",
    ]

    output = Path("output/上行文_生成结果.docx")
    subprocess.run(
        [
            "python3",
            "generate_official_doc.py",
            "--template",
            "上行文.docx",
            "--config",
            "上行文.json",
            "--data",
            "testdata/upward_document_case.json",
            "--body-docx",
            "files/test1.docx",
            "--output",
            str(output),
        ],
        check=True,
    )

    text = docx_text(output)
    expected = [
        "中铁二十四局集团有限公司文件",
        "中铁二十四局〔2026〕12号",
        "签发人：张三",
        "持续打造“1234+”涉铁项目管理体系",
        "----中铁二十四局集团有限公司新建南通至宁波高速铁路",
        "尊敬的各位领导、同仁们：",
        "一、做实“一种模式”，推动营业线施工高标开局",
        "二、做好“两项引领”，激活营业线施工潜能动力",
        "1.以本质安全为引领，构建涉铁施工“大安全”格局。",
        "中铁二十四局集团有限公司办公室",
    ]
    missing = [item for item in expected if item not in text]
    assert not missing, "Missing generated text: " + ", ".join(missing)
    assert "{{BODY_BLOCKS}}" not in text
    assert not re.search(r"\{\{[A-Z0-9_]+\}\}", text), "Unresolved placeholder found"
    assert_doc_number_and_signer_are_tab_separated(output)

    assert_paragraph_format(
        output,
        "一、做实“一种模式”，推动营业线施工高标开局",
        left="170",
        right="289",
        line="411",
        line_rule="exact",
    )
    assert_existing_paragraph_format(
        paragraph_containing_text(output, "1.以本质安全为引领"),
        left="0",
        right="0",
        first_line="640",
        first_line_chars="200",
        before="0",
        after="0",
        line="560",
        line_rule="exact",
        adjust_right_ind="1",
        snap_to_grid="1",
    )
    assert_first_run_fonts(
        output,
        "持续打造“1234+”涉铁项目管理体系以穿透式管理确保营业线施工安全",
        east_asia="方正小标宋简体",
        ascii_font="方正小标宋简体",
        h_ansi="方正小标宋简体",
    )
    assert_first_run_fonts(
        output,
        "一、做实“一种模式”，推动营业线施工高标开局",
        east_asia="黑体",
        ascii_font="黑体",
        h_ansi="黑体",
    )

    print(f"OK: {output}")


if __name__ == "__main__":
    main()
