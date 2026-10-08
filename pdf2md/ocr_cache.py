"""Кэш результатов OCR по хешу содержимого файла — повторная обработка не тратит квоту API."""

import hashlib
from pathlib import Path
from .fileutils import file_content_hash

def ocr_cache_key(path: Path, service: str, extra: str = "") -> str:
    """Уникальный ключ кэша: hash файла + сервис + доп. метка (язык/режим)."""
    digest = file_content_hash(path)
    raw = f"{digest}|{service}|{extra}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def ocr_cache_path(cache_dir: Path, key: str) -> Path:
    # Двухуровневая раскладка, чтобы не класть тысячи файлов в одну папку
    return cache_dir / key[:2] / f"{key}.md"

def ocr_cache_get(cache_dir, path, service, extra=""):
    """Вернуть закэшированный Markdown или None."""
    if not cache_dir:
        return None
    key = ocr_cache_key(path, service, extra)
    p = ocr_cache_path(cache_dir, key)
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return None
    return None

def ocr_cache_put(cache_dir: Path, path: Path, service: str, text: str, extra: str = "") -> None:
    """Сохранить результат OCR в кэш."""
    if not cache_dir or not text:
        return
    key = ocr_cache_key(path, service, extra)
    p = ocr_cache_path(cache_dir, key)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    except Exception:
        pass  # кэш — best-effort, ошибка записи не должна ронять конвертацию
