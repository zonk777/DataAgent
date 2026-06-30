from __future__ import annotations

import io
from pathlib import Path

from docx import Document

from ..db import connect


def extract_document_text(filename: str | None, content: bytes) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in {".md", ".markdown", ".txt"}:
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return content.decode("utf-8", errors="ignore")
    if suffix == ".docx":
        doc = Document(io.BytesIO(content))
        paragraphs = [paragraph.text.strip() for paragraph in doc.paragraphs if paragraph.text.strip()]
        return "\n".join(paragraphs)
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError("未安装 pypdf，无法解析 PDF；请先执行 pip install pypdf") from exc
        reader = PdfReader(io.BytesIO(content))
        return "\n".join((page.extract_text() or "").strip() for page in reader.pages)
    raise ValueError("知识文档仅支持 Word(.docx)、PDF、Markdown、TXT 格式")


def chunk_text(text: str, max_chars: int = 900) -> list[str]:
    paragraphs = [item.strip() for item in text.replace("\r\n", "\n").split("\n") if item.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(paragraph), max_chars):
                part = paragraph[start : start + max_chars].strip()
                if part:
                    chunks.append(part)
            continue
        candidate = f"{current}\n{paragraph}".strip() if current else paragraph
        if len(candidate) > max_chars and current:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def import_knowledge_document(
    *,
    filename: str | None,
    content: bytes,
    title: str | None,
    category: str,
    dataset_id: int | None,
) -> list[dict]:
    text = extract_document_text(filename, content)
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("文档中没有可解析的文字内容")
    base_title = title or Path(filename or "知识文档").stem
    inserted: list[dict] = []
    with connect() as conn:
        for index, chunk in enumerate(chunks, 1):
            chunk_title = base_title if len(chunks) == 1 else f"{base_title} - 片段 {index}"
            cursor = conn.execute(
                "INSERT INTO knowledge_chunks(title, content, category, dataset_id) VALUES (?, ?, ?, ?)",
                (chunk_title, chunk, category, dataset_id),
            )
            row = conn.execute("SELECT * FROM knowledge_chunks WHERE id = ?", (cursor.lastrowid,)).fetchone()
            inserted.append(dict(row))
    return inserted
