"""文档接入：PDF / Word / 纯文本 -> RawDoc。

这条路径此前没有测试覆盖，但「支持 PDF 与 Word」是这个系统的入口能力 ——
它在别人机器上第一次上传就炸掉的话，后面所有设计都无从谈起。

测试文件在运行时现造，不往仓库里塞二进制夹具：二进制既 review 不了，
也看不出哪一版改了什么。
"""

from __future__ import annotations

import io

import pytest

from ingest.loader import SUPPORTED, load_file, load_text


# ------------------------------------------------------------------ 造测试文件


def _minimal_pdf(lines) -> bytes:
    """手写一个最小可用的 PDF。

    用手写而不是引第三方生成库：只为测试就多一个依赖不划算，而 PDF 的这点
    结构（对象表 + 文本流 + xref）本身是稳定的。用 Helvetica 内置字体，
    因此只放 ASCII —— 中文要嵌字体，那是另一回事，也不是这里要验的东西。
    """
    content = (
        "BT /F1 12 Tf 72 720 Td 14 TL\n"
        + "".join(f"({line}) Tj T*\n" for line in lines)
        + "ET"
    )
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        " /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    buf = io.BytesIO()
    buf.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(buf.tell())
        buf.write(f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = buf.tell()
    buf.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        buf.write(f"{off:010d} 00000 n \n".encode())
    buf.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode()
    )
    return buf.getvalue()


def _docx(tmp_path, paragraphs, table_rows=None):
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    if table_rows:
        table = doc.add_table(rows=len(table_rows), cols=len(table_rows[0]))
        for r, row in enumerate(table_rows):
            for c, value in enumerate(row):
                table.cell(r, c).text = value
    path = tmp_path / "resume.docx"
    doc.save(str(path))
    return path


# ------------------------------------------------------------------ PDF


def test_pdf_text_is_extracted(tmp_path):
    pytest.importorskip("pypdf")
    path = tmp_path / "resume.pdf"
    path.write_bytes(_minimal_pdf([
        "Li Ming  Bachelor of Computer Science",
        "Skills: Python, pandas, FastAPI",
    ]))

    doc = load_file(path)

    assert "Li Ming" in doc.full_text
    assert "FastAPI" in doc.full_text
    assert doc.filename == "resume.pdf"
    assert doc.chunks, "分块结果为空会让后续所有引用定位失效"


def test_image_only_pdf_fails_loudly(tmp_path):
    """扫描件抽不出文本时必须报错。

    静默返回空字符串的后果是：模型拿到一份空简历，照样能编出一套完整的
    结构化结果，而且每个字段都「言之凿凿」—— 这种错误在下游根本看不出来。
    """
    pytest.importorskip("pypdf")
    path = tmp_path / "scan.pdf"
    path.write_bytes(_minimal_pdf([]))

    with pytest.raises(ValueError, match="OCR"):
        load_file(path)


# ------------------------------------------------------------------ Word


def test_docx_paragraphs_and_tables_are_extracted(tmp_path):
    """表格必须抽出来 —— 简历里的教育与技能栏大量使用表格排版，
    只读段落会丢掉半份简历，而且丢得毫无征兆。
    """
    path = _docx(
        tmp_path,
        paragraphs=["李明", "项目经历", "基于 LangChain 搭建检索问答系统"],
        table_rows=[["学校", "华中科技大学"], ["专业", "计算机科学与技术"]],
    )

    doc = load_file(path)

    assert "李明" in doc.full_text
    assert "LangChain" in doc.full_text
    assert "华中科技大学" in doc.full_text, "表格内容被丢掉了"
    assert "计算机科学与技术" in doc.full_text


def test_empty_docx_fails_loudly(tmp_path):
    path = _docx(tmp_path, paragraphs=["", "   "])

    with pytest.raises(ValueError, match="未能提取到任何文本"):
        load_file(path)


# ------------------------------------------------------------------ 通用


def test_unsupported_suffix_is_rejected(tmp_path):
    path = tmp_path / "resume.pages"
    path.write_bytes(b"whatever")

    with pytest.raises(ValueError, match="不支持的文件类型"):
        load_file(path)

    assert ".pages" not in SUPPORTED


@pytest.mark.parametrize("suffix", [".txt", ".md"])
def test_plain_text_roundtrip(tmp_path, suffix):
    path = tmp_path / f"resume{suffix}"
    path.write_text("李明\n\n技能\n熟悉 Python", encoding="utf-8")

    doc = load_file(path)

    assert "熟悉 Python" in doc.full_text
    assert doc.doc_id


def test_same_content_different_path_gets_different_doc_id(tmp_path):
    """doc_id 掺入路径：同一批里上传两份内容相同的简历时，
    它们仍是两位候选人，共用一个 id 会让结果互相覆盖。
    """
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    for p in (a, b):
        p.write_text("同一份内容", encoding="utf-8")

    assert load_file(a).doc_id != load_file(b).doc_id


def test_load_text_normalizes_and_chunks():
    doc = load_text("第一行\r\n\r\n\r\n第二行", filename="jd")

    assert "\r" not in doc.full_text
    assert doc.chunks
