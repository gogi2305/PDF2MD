"""Эвристическая оценка достоверности распознанного текста и сверка результатов двух движков (diff)."""

import re
from pathlib import Path
from .pages import strip_page_markers

QA_NOISE_RED = 0.25

QA_NOISE_YELLOW = 0.10

QA_ILLEGIBLE_RED = 0.10

QA_ILLEGIBLE_YELLOW = 0.03

QA_MIN_CHARS = 15        # меньше — почти наверняка пустой/провальный результат

_QA_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)     # «слова» из букв (без цифр и _)

_QA_HAS_CYR = re.compile(r"[А-Яа-яЁё]")

_QA_HAS_LAT = re.compile(r"[A-Za-z]")

_QA_ILLEGIBLE = re.compile(r"\[(?:неразборчиво|нечитаемо|unclear|illegible)\]", re.IGNORECASE)

_QA_VOWELS = set("аеёиоуыэюяaeiouyАЕЁИОУЫЭЮЯAEIOUY")

def assess_markdown_quality(text: str):
    """Грубо оценивает достоверность распознанного текста для триажа.

    Возвращает (level, reasons): level ∈ {"надёжно","проверить","сомнительно"}.
    Ловит ЯВНЫЙ мусор — пустой результат, метки [неразборчиво], искажённые слова
    (смешение латиницы/кириллицы, длинные слова без гласных), символы-замены.
    НЕ ловит «гладко выглядящую, но неверно прочитанную» цифру/фамилию — для этого
    нужна сверка вторым движком (часть B) или с оригиналом.
    """
    stripped = strip_page_markers(text or "").strip()
    if len(stripped) < QA_MIN_CHARS:
        return "сомнительно", [f"почти пусто ({len(stripped)} симв.)"]

    words = _QA_WORD.findall(stripped)
    total = len(words) or 1
    illegible = len(_QA_ILLEGIBLE.findall(stripped))
    repl = stripped.count("\ufffd")
    suspicious = 0
    for w in words:
        mixed = bool(_QA_HAS_CYR.search(w) and _QA_HAS_LAT.search(w))      # латиница+кириллица в одном слове
        novowel = len(w) >= 5 and not any(c in _QA_VOWELS for c in w)      # длинное слово без гласных
        if mixed or novowel:
            suspicious += 1
    noise = suspicious / total
    illeg = illegible / total

    flags = []
    if noise >= QA_NOISE_YELLOW: flags.append(f"искажённых слов {noise:.0%}")
    if illeg >= QA_ILLEGIBLE_YELLOW: flags.append(f"меток [неразборчиво] {illeg:.0%}")
    if repl: flags.append(f"символов-замен {repl}")

    if noise >= QA_NOISE_RED or illeg >= QA_ILLEGIBLE_RED or repl > 5:
        return "сомнительно", flags or ["высокий шум"]
    if flags:
        return "проверить", flags
    return "надёжно", []


# --- Сверка двух движков (часть B): сравнение и наглядный diff ---

QA_CROSSCHECK_AGREE = 0.85   # сходство выше этого — считаем, что движки согласны

_CMP_NOISE = re.compile(r"[#*`|>_\-]+")

_CMP_WS = re.compile(r"\s+")

def _normalize_for_compare(t: str) -> str:
    """Снимаем косметику (markdown, регистр, пробелы), чтобы расхождением
    считался смысл текста, а не форматирование."""
    t = strip_page_markers(t or "").lower()
    t = _CMP_NOISE.sub(" ", t)
    t = _CMP_WS.sub(" ", t)
    return t.strip()

def _text_similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    na, nb = _normalize_for_compare(a), _normalize_for_compare(b)
    if not na and not nb:
        return 1.0
    return SequenceMatcher(None, na, nb, autojunk=True).ratio()

def _write_html_diff(first: str, second: str, path: Path, sec_name: str) -> None:
    """Пишет автономный HTML с двумя колонками и подсветкой различий."""
    from difflib import HtmlDiff
    html = HtmlDiff(wrapcolumn=90).make_file(
        first.splitlines(), second.splitlines(),
        fromdesc="Движок 1 (основной)", todesc=f"Движок 2 ({sec_name})",
        context=True, numlines=2)
    path.write_text(html, encoding="utf-8")


# ============================================================
# Воркеры
# ============================================================
