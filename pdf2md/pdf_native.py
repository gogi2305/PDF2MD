"""Извлечение Markdown из PDF без OCR (текстовый слой) и из офисных форматов через MarkItDown."""

import io
from pathlib import Path
from .messages import tr
from .pages import join_pages

def pdf_page_count(data: bytes) -> int:
    """Число страниц PDF, заданного байтами."""
    try:
        from pypdf import PdfReader
        return len(PdfReader(io.BytesIO(data)).pages)
    except ImportError:
        pass
    try:
        import fitz
        with fitz.open(stream=bytes(data), filetype="pdf") as doc:
            return doc.page_count
    except ImportError:
        pass
    raise RuntimeError(tr("need_pypdf"))

def split_pdf_to_chunks(pdf_path, pages_per_chunk: int):
    """Режет PDF на куски по `pages_per_chunk` страниц.

    `pdf_path` — путь к файлу или байты PDF (чтобы дорезать уже вырезанный кусок).
    Возвращает ([(bytes, первая_стр, последняя_стр), ...], всего_страниц).
    """
    is_bytes = isinstance(pdf_path, (bytes, bytearray))
    try:
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(io.BytesIO(pdf_path) if is_bytes else str(pdf_path))
        total = len(reader.pages)
        result = []
        for start in range(0, total, pages_per_chunk):
            end = min(start + pages_per_chunk, total)
            writer = PdfWriter()
            for i in range(start, end):
                writer.add_page(reader.pages[i])
            buf = io.BytesIO()
            writer.write(buf)
            result.append((buf.getvalue(), start + 1, end))
        return result, total
    except ImportError:
        pass
    try:
        import fitz
        doc = fitz.open(stream=bytes(pdf_path), filetype="pdf") if is_bytes else fitz.open(str(pdf_path))
        total = doc.page_count
        result = []
        for start in range(0, total, pages_per_chunk):
            end = min(start + pages_per_chunk, total)
            sub = fitz.open()
            sub.insert_pdf(doc, from_page=start, to_page=end - 1)
            data = sub.tobytes()
            sub.close()
            result.append((data, start + 1, end))
        doc.close()
        return result, total
    except ImportError:
        pass
    raise RuntimeError(tr("need_pypdf"))

def pdf_has_text_layer(pdf_path: Path, sample: int = 12,
                       min_chars: int = 40, min_ratio: float = 0.5) -> bool:
    """True, если у PDF есть пригодный текстовый слой (цифровой документ).

    Берём первые `sample` страниц и считаем, у скольких есть осмысленный
    текст (>= `min_chars`). Если их доля >= `min_ratio` — документ цифровой,
    его не нужно гнать через OCR. Скан вернёт ~0 текста → False.
    """
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        n = doc.page_count
        checked = min(sample, n) or 1
        hits = sum(1 for i in range(checked)
                   if len(doc[i].get_text("text").strip()) >= min_chars)
        doc.close()
        return hits / checked >= min_ratio
    except ImportError:
        pass
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        n = len(reader.pages)
        checked = min(sample, n) or 1
        hits = 0
        for i in range(checked):
            try:
                t = reader.pages[i].extract_text() or ""
            except Exception:
                t = ""
            if len(t.strip()) >= min_chars:
                hits += 1
        return hits / checked >= min_ratio
    except Exception:
        return False  # не смогли прочитать слой — пусть решает OCR

def extract_markdown_native(pdf_path: Path) -> str:
    """Достаёт Markdown прямо из текстового слоя PDF, без OCR.

    Приоритет: pymupdf4llm (заголовки/таблицы/порядок чтения) →
    PyMuPDF (текст постранично) → pypdf (последний резерв).
    Каждая страница начинается с метки <!-- page N -->: пустая страница
    (например, вклеенный скан без текстового слоя) видна в отчёте.
    """
    try:
        import pymupdf4llm
        pages = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True)
        return join_pages([p.get("text", "") for p in pages])
    except ImportError:
        pass
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        parts = [doc[i].get_text("text") for i in range(doc.page_count)]
        doc.close()
        return join_pages(parts)
    except ImportError:
        pass
    from pypdf import PdfReader
    reader = PdfReader(str(pdf_path))
    parts = []
    for pg in reader.pages:
        try:
            parts.append(pg.extract_text() or "")
        except Exception:
            parts.append("")
    return join_pages(parts)

def pdf_file_page_count(pdf_path: Path):
    """Число страниц PDF-файла или None, если файл не читается."""
    try:
        import fitz
        with fitz.open(str(pdf_path)) as doc:
            return doc.page_count
    except ImportError:
        pass
    except Exception:
        return None
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(pdf_path)).pages)
    except Exception:
        return None

def extract_markitdown(path: Path) -> str:
    """Конвертирует офисный/веб/данные-документ в Markdown через MarkItDown.

    Это готовый текст — без OCR, без обращений к API. Плагины выключены намеренно:
    OCR/описание картинок у нас делает свой, лучший конвейер, а MarkItDown здесь
    отвечает только за форматы с настоящим текстовым содержимым.
    """
    from markitdown import MarkItDown
    md = MarkItDown(enable_plugins=False)
    result = md.convert(str(path))
    return (result.text_content or "").strip()


# ============================================================
# Парсеры PDF (Bckend) — те же что и раньше
# ============================================================
