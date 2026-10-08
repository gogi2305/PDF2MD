"""Разбиение Markdown на чанки для индексации (с оверлапом)."""

import re
import hashlib
from .constants import MAX_CHARS, OVERLAP_CHARS
from .pages import strip_page_markers

MIN_PIECE_CHARS = 200    # не дробим мельче, даже если заголовки съели почти весь лимит

_SENTENCE_END = re.compile(r"((?<=[.!?…;])\s+)")

def chunk_hash(text: str, source: str) -> str:
    return hashlib.md5(f"{source}::{text}".encode("utf-8")).hexdigest()[:16]

def _hard_split(text: str, limit: int) -> list:
    """Режет строку без знаков препинания по `limit`, по возможности на пробеле."""
    pieces = []
    while len(text) > limit:
        cut = max(text.rfind(" ", 0, limit), text.rfind("\n", 0, limit))
        if cut < limit // 2:          # пробела нет или он слишком близко к началу
            cut = limit
        pieces.append(text[:cut].strip())
        text = text[cut:].lstrip()
    if text.strip():
        pieces.append(text.strip())
    return pieces

def _split_text(text: str, limit: int) -> list:
    """Делит абзац на куски не длиннее `limit`: по границам предложений,
    а слишком длинное предложение — по словам. Текст не теряется и не дублируется."""
    parts = _SENTENCE_END.split(text)     # [предложение, разделитель, предложение, ...]
    pieces, cur = [], ""
    for i in range(0, len(parts), 2):
        sent = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        if len(sent) > limit:
            if cur.strip(): pieces.append(cur.strip())
            pieces += _hard_split(sent, limit)
            cur = ""
            continue
        if cur and len(cur) + len(sent) > limit:
            pieces.append(cur.strip())
            cur = ""
        cur += sent + sep
    if cur.strip():
        pieces.append(cur.strip())
    return pieces

def _split_table(table: str, limit: int) -> list:
    """Делит Markdown-таблицу по строкам, повторяя шапку в каждом куске,
    чтобы у каждого чанка были названия столбцов."""
    lines = table.split("\n")
    if len(lines) > 1 and re.match(r"^\s*\|?\s*:?-{2,}", lines[1]):
        head, rows = lines[:2], lines[2:]
    else:
        head, rows = [], lines
    head_text = "\n".join(head)
    pieces, cur = [], []
    for row in rows:
        size = len(head_text) + sum(len(r) + 1 for r in cur) + len(row) + 1
        if cur and size > limit:
            pieces.append("\n".join(head + cur))
            cur = []
        cur.append(row)
    if cur:
        pieces.append("\n".join(head + cur))
    return pieces

def chunk_markdown(text):
    # Метки страниц — служебная разметка, в текст для поиска не идут
    lines = strip_page_markers(text).split("\n")
    sections, header_stack, current_body = [], [], []

    def flush():
        if current_body:
            sections.append((list(header_stack), "\n".join(current_body).strip()))

    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            flush()
            current_body.clear()
            level = len(m.group(1))
            htext = m.group(2).strip()
            if len(htext) > 120:
                current_body.append(line); continue
            while header_stack and header_stack[-1][0] >= level:
                header_stack.pop()
            header_stack.append((level, htext))
        else:
            current_body.append(line)
    flush()

    chunks = []
    for headers, body in sections:
        if not body.strip(): continue
        header_prefix = "\n".join(f"{'#' * lvl} {ht}" for lvl, ht in headers)
        header_titles = [ht for _, ht in headers]

        blocks, cur_lines, in_table = [], [], False
        for line in body.split("\n"):
            is_table = line.lstrip().startswith("|")
            if is_table:
                if not in_table and cur_lines:
                    blocks.append(("para", "\n".join(cur_lines).strip())); cur_lines = []
                in_table = True; cur_lines.append(line)
            else:
                if in_table:
                    blocks.append(("table", "\n".join(cur_lines))); cur_lines = []; in_table = False
                if line.strip() == "":
                    if cur_lines:
                        blocks.append(("para", "\n".join(cur_lines).strip())); cur_lines = []
                else:
                    cur_lines.append(line)
        if cur_lines:
            blocks.append(("table" if in_table else "para", "\n".join(cur_lines)))

        # Блок длиннее лимита (сплошной абзац, огромная таблица) иначе ушёл бы
        # одним чанком на 15 000 символов. Режем заранее, оставляя место под
        # заголовки и оверлап, чтобы итоговый чанк уложился в MAX_CHARS.
        head_len = len(header_prefix) + 2 if header_prefix else 0
        para_limit = max(MIN_PIECE_CHARS, MAX_CHARS - head_len - OVERLAP_CHARS - 2)
        table_limit = max(MIN_PIECE_CHARS, MAX_CHARS - head_len)
        sized = []
        for kind, content in blocks:
            if kind == "para" and len(content) > para_limit:
                sized += [("para", p) for p in _split_text(content, para_limit)]
            elif kind == "table" and len(content) > table_limit:
                sized += [("table", t) for t in _split_table(content, table_limit)]
            else:
                sized.append((kind, content))
        blocks = sized

        buf = ""
        for kind, content in blocks:
            if not content.strip(): continue
            if kind == "table":
                if buf:
                    chunks.append({"text": f"{header_prefix}\n\n{buf}".strip() if header_prefix else buf.strip(), "headers": header_titles})
                    buf = ""
                chunks.append({"text": f"{header_prefix}\n\n{content}".strip() if header_prefix else content.strip(), "headers": header_titles})
                continue
            candidate = f"{buf}\n\n{content}".strip() if buf else content
            full_len = len(header_prefix) + 2 + len(candidate) if header_prefix else len(candidate)
            if full_len > MAX_CHARS and buf:
                chunks.append({"text": f"{header_prefix}\n\n{buf}".strip() if header_prefix else buf.strip(), "headers": header_titles})
                overlap = buf[-OVERLAP_CHARS:] if len(buf) > OVERLAP_CHARS else ""
                buf = (overlap + "\n\n" + content).strip() if overlap else content
            else:
                buf = candidate
        if buf.strip():
            chunks.append({"text": f"{header_prefix}\n\n{buf}".strip() if header_prefix else buf.strip(), "headers": header_titles})
    return chunks


# ============================================================
# RAG: эмбеддинги и поиск
# ============================================================
