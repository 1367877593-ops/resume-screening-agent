"""按段落切块，保持语义边界。

简历不长，切块目前只服务于 UI 的原文高亮定位，不做检索，
所以刻意保持简单 —— 没有必要为一份两页的简历上滑动窗口。
"""

from __future__ import annotations

from typing import List

from ingest.normalizer import split_paragraphs
from schema.document import Chunk

MAX_CHARS = 800


def chunk_text(doc_id: str, text: str, max_chars: int = MAX_CHARS) -> List[Chunk]:
    chunks: List[Chunk] = []
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf.strip():
            chunks.append(
                Chunk(chunk_id=f"{doc_id}-{len(chunks):03d}", doc_id=doc_id,
                      text=buf.strip(), order=len(chunks))
            )
        buf = ""

    for para in split_paragraphs(text):
        if len(buf) + len(para) > max_chars:
            flush()
        buf = f"{buf}\n\n{para}" if buf else para
    flush()
    return chunks
