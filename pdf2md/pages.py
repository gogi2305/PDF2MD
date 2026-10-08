"""Метки страниц в Markdown и сверка числа страниц исходника и результата.

Маршруты, которые знают границы страниц (текстовый слой, Mistral, Gemini по
инструкции), ставят перед каждой страницей метку <!-- page N -->. Это
HTML-комментарий: в просмотрщиках Markdown не виден, из чанков для поиска
вырезается. По меткам видно, какие страницы пропали или пришли пустыми.
"""

import re

PAGE_MARKER_RE = re.compile(r"^[ \t]*<!--\s*page\s+(\d+)\s*-->[ \t]*$", re.MULTILINE | re.IGNORECASE)

# Статусы сверки
PAGES_OK = "ok"                  # все страницы на месте и не пустые
PAGES_PROBLEM = "problem"        # есть пропавшие или пустые страницы
PAGES_UNVERIFIED = "unverified"  # в результате нет меток (движок их не даёт / старый результат)


def page_marker(n: int) -> str:
    return f"<!-- page {n} -->"


def join_pages(texts, first_page: int = 1) -> str:
    """Склеивает тексты страниц, ставя перед каждой метку с её номером."""
    return "\n\n".join(f"{page_marker(first_page + i)}\n\n{(t or '').strip()}".rstrip()
                       for i, t in enumerate(texts))


def shift_page_markers(text: str, offset: int) -> str:
    """Сдвигает номера меток на `offset`: кусок PDF со страницы 26 модель
    нумерует с 1, а в документе это 26, 27, ..."""
    if not offset:
        return text
    return PAGE_MARKER_RE.sub(lambda m: page_marker(int(m.group(1)) + offset), text)


def strip_page_markers(text: str) -> str:
    return PAGE_MARKER_RE.sub("", text)


def check_pages(md_text: str, source_pages: int) -> dict:
    """Сверяет страницы результата с числом страниц исходника.

    Возвращает {"status", "source", "found", "missing": [...], "empty": [...]}.
    Без меток проверить нечего — статус unverified, а не «всё хорошо».
    """
    matches = list(PAGE_MARKER_RE.finditer(md_text or ""))
    result = {"status": PAGES_UNVERIFIED, "source": source_pages, "found": 0,
              "missing": [], "empty": []}
    if not matches:
        return result
    content = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_text)
        n = int(m.group(1))
        content[n] = content.get(n, "") + md_text[m.end():end]
    found = {n for n in content if 1 <= n <= source_pages}
    result["found"] = len(found)
    result["missing"] = [n for n in range(1, source_pages + 1) if n not in found]
    result["empty"] = sorted(n for n in found if not content[n].strip())
    result["status"] = PAGES_PROBLEM if (result["missing"] or result["empty"]) else PAGES_OK
    return result


def format_page_list(nums, limit: int = 15) -> str:
    """1,2,3,7,8 → «1–3, 7–8» (длинные списки обрезаются)."""
    ranges, start, prev = [], None, None
    for n in sorted(nums):
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            ranges.append((start, prev)); start = prev = n
    if start is not None:
        ranges.append((start, prev))
    parts = [f"{a}" if a == b else f"{a}–{b}" for a, b in ranges]
    if len(parts) > limit:
        parts = parts[:limit] + ["…"]
    return ", ".join(parts)
