"""Самопроверка сборки: PDF2MD.exe --selftest <файл-отчёта>.

У собранного .exe нет консоли, поэтому результат пишется в JSON-файл,
а код выхода — 0 (всё работает) или 1. Проверяет, что в сборку попало всё,
без чего программа молча потеряла бы часть функций: модули, PyMuPDF
(текстовый слой, TIFF), MarkItDown (офисные форматы), Tkinter.
Сеть и API-ключи не нужны.
"""

import json
import tempfile
import traceback
from pathlib import Path


def _check_modules():
    from . import (answerers, archives, chunking, fileutils, gui, imaging,  # noqa: F401
                   index, ocr_clients, pages, pdf_native, quality, workers)
    return "ok"


def _check_pdf_text_layer(tmp):
    import fitz
    from .pages import check_pages
    from .pdf_native import extract_markdown_native
    p = tmp / "t.pdf"
    doc = fitz.open()
    for i in range(2):
        doc.new_page().insert_text((72, 72), f"Selftest page {i + 1}")
    doc.save(str(p))
    doc.close()
    md = extract_markdown_native(p)
    assert "Selftest page 2" in md, md[:200]
    assert check_pages(md, 2)["status"] == "ok"
    return "ok"


def _check_tiff(tmp):
    import fitz
    from PIL import Image
    from .imaging import tiff_to_pdf
    src = tmp / "t.tif"
    frames = [Image.new("1", (200, 300), 1) for _ in range(3)]
    frames[0].save(src, save_all=True, append_images=frames[1:], compression="group4")
    with fitz.open(str(tiff_to_pdf(src, tmp))) as doc:
        assert doc.page_count == 3
    return "ok"


def _check_office(tmp):
    from .pdf_native import extract_markitdown
    p = tmp / "t.html"
    p.write_text("<html><body><h1>Selftest</h1><table><tr><td>a</td></tr></table></body></html>",
                 encoding="utf-8")
    assert "Selftest" in extract_markitdown(p)
    return "ok"


def _check_gui():
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    root.destroy()
    return "ok"


def run(report_path) -> int:
    results = {}
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for name, check in (("modules", _check_modules),
                            ("pdf_text_layer", lambda: _check_pdf_text_layer(tmp)),
                            ("tiff", lambda: _check_tiff(tmp)),
                            ("office_markitdown", lambda: _check_office(tmp)),
                            ("gui_tkinter", _check_gui)):
            try:
                results[name] = check()
            except Exception:
                results[name] = "FAIL: " + traceback.format_exc(limit=3)
    ok = all(v == "ok" for v in results.values())
    from . import __version__
    Path(report_path).write_text(json.dumps({"version": __version__, "ok": ok, "checks": results},
                                            ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if ok else 1
