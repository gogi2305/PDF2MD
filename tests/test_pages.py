"""Сверка числа страниц PDF: метки <!-- page N -->, разметка во всех
маршрутах, отчёт. Без сети: OCR-клиенты подменяются заглушками."""
import json
import queue
import shutil
import threading

import pytest

KEY = "SECRET-TEST-KEY"


@pytest.fixture()
def tmp(tmp_path):
    yield tmp_path
    shutil.rmtree(tmp_path, ignore_errors=True)


def _make_pdf(path, texts):
    """PDF, где texts[i] — текст страницы i+1 (пустая строка = страница без текста)."""
    import fitz
    doc = fitz.open()
    for t in texts:
        page = doc.new_page()
        if t:
            page.insert_text((72, 72), t)
    doc.save(str(path))
    doc.close()


# ---------- разбор меток ----------

def test_check_pages_statuses():
    from pdf2md.pages import check_pages, join_pages

    ok = check_pages(join_pages(["a", "b", "c"]), 3)
    assert ok["status"] == "ok" and ok["found"] == 3

    gap = check_pages(join_pages(["a", "", "c"]) .replace("<!-- page 3 -->", "<!-- page 4 -->"), 4)
    assert gap["status"] == "problem"
    assert gap["missing"] == [3] and gap["empty"] == [2]

    assert check_pages("# просто текст без меток", 5)["status"] == "unverified"


def test_shift_and_strip_markers():
    from pdf2md.pages import join_pages, shift_page_markers, strip_page_markers, check_pages

    shifted = shift_page_markers(join_pages(["x", "y"]), 25)
    assert "<!-- page 26 -->" in shifted and "<!-- page 27 -->" in shifted
    assert "page" not in strip_page_markers(shifted)
    # Метка внутри строки текста — не метка (не путаем с содержимым документа)
    assert check_pages("текст <!-- page 1 --> текст", 1)["status"] == "unverified"


def test_format_page_list():
    from pdf2md.pages import format_page_list

    assert format_page_list([1, 2, 3, 7, 9, 10]) == "1–3, 7, 9–10"


def test_markers_not_in_chunks_or_quality():
    from pdf2md.chunking import chunk_markdown
    from pdf2md.pages import join_pages
    from pdf2md.quality import assess_markdown_quality

    md = join_pages(["# Договор\n\nСтороны договорились о следующем.", "Подписи сторон."])
    assert all("<!--" not in c["text"] for c in chunk_markdown(md))
    assert assess_markdown_quality(join_pages(["", ""]))[0] == "сомнительно"   # только метки = пусто


# ---------- маршруты ставят метки ----------

def test_native_text_layer_marks_every_page(tmp):
    from pdf2md.pdf_native import extract_markdown_native
    from pdf2md.pages import check_pages

    p = tmp / "mixed.pdf"
    _make_pdf(p, ["Page one text here", "", "Page three text here"])   # стр. 2 — «вклеенный скан»
    check = check_pages(extract_markdown_native(p), 3)
    assert check["status"] == "problem" and check["empty"] == [2] and check["missing"] == []


def test_gemini_piece_markers_get_document_numbers(tmp, monkeypatch):
    import fitz
    from pdf2md.ocr_clients import GeminiClient, GeminiTruncatedError
    from pdf2md.pages import check_pages, join_pages

    p = tmp / "long.pdf"
    _make_pdf(p, [f"P{i}" for i in range(1, 7)])
    client = GeminiClient(KEY)

    def call(data, cancel_event=None):
        with fitz.open(stream=data, filetype="pdf") as d:
            n = d.page_count
        if n > 2:
            raise GeminiTruncatedError("cut")
        return join_pages(["текст"] * n)          # модель нумерует страницы куска с 1

    monkeypatch.setattr(client, "_call_api", call)
    md = client.parse_pdf(p)
    check = check_pages(md, 6)
    assert check["status"] == "ok"                 # 1..6 без дыр и повторов
    assert [int(x) for x in __import__("re").findall(r"page (\d+)", md)] == [1, 2, 3, 4, 5, 6]


# ---------- отчёт ----------

def test_report_lists_page_mismatches(tmp, monkeypatch):
    from pdf2md import workers
    from pdf2md.pages import join_pages

    src = tmp / "src"
    src.mkdir()
    _make_pdf(src / "full.pdf", ["a", "b", "c"])
    _make_pdf(src / "lost.pdf", ["a", "b", "c", "d"])
    _make_pdf(src / "plain.pdf", ["a", "b"])

    class FakeClient:
        def parse_pdf(self, path, cancel_event=None):
            if path.name == "full.pdf":
                return join_pages(["Первая страница договора.", "Вторая страница.", "Третья."])
            if path.name == "lost.pdf":       # OCR потерял стр. 3–4
                return join_pages(["Первая страница договора.", "Вторая страница."])
            return "Распознанный текст без разметки страниц."

    monkeypatch.setattr(workers, "make_client", lambda *a: FakeClient())
    q = queue.Queue()
    workers.ConvertWorker([src], tmp / "out", "mistral", KEY,
                          {"auto_route": False, "make_chunks": False, "assess_quality": True,
                           "use_ocr_cache": False, "workers": 1}, q, threading.Event())._run()
    done = [m[1] for m in list(q.queue) if m[0] == "done"][0]
    assert done["pages"] == {"ok": 1, "problem": 1, "unverified": 1}

    report = (tmp / "out" / "report.md").read_text(encoding="utf-8")
    assert "## Сверка страниц PDF" in report
    assert "`lost.pdf` — распознано 2 из 4; нет: 3–4" in report
    assert "`plain.pdf`" in report.split("### Не проверено")[1]

    data = {d["source"]: d for d in json.loads((tmp / "out" / "report.json").read_text(encoding="utf-8"))}
    assert data["lost.pdf"]["level"] == "сомнительно"          # потеря страниц = сомнительно
    assert data["lost.pdf"]["pages"]["missing"] == [3, 4]
    assert data["full.pdf"]["pages"]["status"] == "ok"


@pytest.fixture()
def english():
    from pdf2md import messages
    messages.set_language("en")
    yield
    messages.set_language("ru")


def test_report_follows_interface_language(tmp, monkeypatch, english):
    import re
    from pdf2md import workers
    from pdf2md.pages import join_pages

    src = tmp / "src"
    src.mkdir()
    _make_pdf(src / "lost.pdf", ["a", "b", "c", "d"])
    _make_pdf(src / "plain.pdf", ["a", "b"])
    (src / "empty.pdf").write_bytes(b"%PDF")       # не читается → «почти пусто», без сверки страниц

    class FakeClient:
        def parse_pdf(self, path, cancel_event=None):
            if path.name == "lost.pdf":
                return join_pages(["First page of the contract.", "Second page."])
            if path.name == "empty.pdf":
                return ""
            return "Recognized text without page markers."

    monkeypatch.setattr(workers, "make_client", lambda *a: FakeClient())
    workers.ConvertWorker([src], tmp / "out", "mistral", KEY,
                          {"auto_route": False, "make_chunks": False, "assess_quality": True,
                           "use_ocr_cache": False, "workers": 1}, queue.Queue(), threading.Event())._run()

    report = (tmp / "out" / "report.md").read_text(encoding="utf-8")
    assert report.startswith("# OCR reliability report")
    assert "## Suspicious — check against the original" in report
    assert "`lost.pdf` — missing pages: 3–4" in report               # причина тоже по-английски
    assert "`empty.pdf` — almost empty (0 chars)" in report
    assert "`lost.pdf` — 2 of 4 recognized; missing: 3–4" in report
    assert "`plain.pdf`" in report.split("### Not verified: 1")[1]
    # Кириллица — только в метке [неразборчиво], которую пишет сама OCR-модель
    assert not re.search("[А-Яа-яЁё]", report.replace("[неразборчиво]", ""))

    data = {d["source"]: d for d in json.loads((tmp / "out" / "report.json").read_text(encoding="utf-8"))}
    assert data["lost.pdf"]["level"] == "сомнительно"          # машинный код уровня не переводится
