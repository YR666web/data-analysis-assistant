"""Discover and read real session files through bounded, explicit tools."""
from pathlib import Path

from langchain_core.tools import tool

from api import context
from tools.table_tools import TABLE_EXTENSIONS, inspect_table, session_file


@tool
def list_session_files() -> dict:
    """列出当前会话真实文件。上传附件不在内置 ls/read_file 的虚拟文件系统中。"""
    directory = context.get_session_dir()
    if not directory:
        return {"status": "error", "error": "未设置会话目录"}
    root = Path(directory).resolve()
    files = [{"filename": p.name, "bytes": p.stat().st_size, "type": p.suffix.lower()}
             for p in sorted(root.iterdir()) if p.is_file() and not p.is_symlink()]
    return {"status": "ok", "files": files}


@tool
def read_file_content(filename: str, instruction: str = "提取全部内容",
                      offset: int = 0, limit: int = 12000) -> dict:
    """分页读取文本、Word（含表格）、PDF。offset 为字符位置，next_offset 非空时继续读取。

    instruction 仅为兼容旧调用，不执行分析或筛选。表格文件返回结构概览，
    完整行数据、筛选与统计请调用 analyze_table，不能把预览当成全文。
    """
    try:
        if offset < 0 or not 1 <= limit <= 20000:
            raise ValueError("offset 须非负，limit 须为 1–20000")
        path = session_file(filename)
        ext = path.suffix.lower()
        if ext in TABLE_EXTENSIONS:
            return inspect_table.invoke({"filename": filename})
        if ext in {".txt", ".md"}:
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                text = path.read_text(encoding="gb18030")
        elif ext == ".docx":
            from docx import Document
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            document = Document(path)
            parts = []
            for element in document.element.body:
                if element.tag.endswith("}p"):
                    parts.append(Paragraph(element, document).text)
                elif element.tag.endswith("}tbl"):
                    parts.extend(" | ".join(cell.text for cell in row.cells)
                                 for row in Table(element, document).rows)
            text = "\n".join(parts)
        elif ext == ".pdf":
            from pypdf import PdfReader
            text = "\n\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
            if not text.strip():
                raise ValueError("PDF 未提取到文字，可能是扫描件；当前未启用 OCR")
        else:
            raise ValueError(f"不支持的文件类型：{ext}")
        return {"status": "ok", "source": filename, "total_characters": len(text),
                "offset": offset, "next_offset": offset + limit if offset + limit < len(text) else None,
                "content": text[offset:offset + limit]}
    except Exception as exc:
        return {"status": "error", "source": filename, "error": str(exc)}
