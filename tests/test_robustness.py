"""Тесты на исправления по внешнему ревью:
1. Gemini: оборванный ответ (finishReason=MAX_TOKENS) не принимается молча.
2. Изменённый исходник переделывается; индекс чистит устаревшие чанки.
3. Длинные абзацы и таблицы делятся по лимиту без потери текста.
4. GUI: задачи не запускаются одновременно, сообщения не путаются.

Сеть не нужна: API и OCR-клиенты подменяются заглушками.
"""
import json
import queue
import re
import shutil
import threading
import types

import pytest

KEY = "SECRET-TEST-KEY"


@pytest.fixture()
def tmp(tmp_path):
    yield tmp_path
    shutil.rmtree(tmp_path, ignore_errors=True)


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code
        self.text = json.dumps(data)

    def json(self):
        return self._data


def _respond_with(session, response):
    session.post = lambda url, **kw: response


def _gemini_resp(text, reason="STOP"):
    return FakeResponse({"candidates": [{"content": {"parts": [{"text": text}]},
                                         "finishReason": reason}]})


def _make_pdf(path, n_pages):
    import fitz
    doc = fitz.open()
    for i in range(1, n_pages + 1):
        doc.new_page().insert_text((72, 72), f"PAGE-{i:03d}")
    doc.save(str(path))
    doc.close()


def _pdf_page_labels(data):
    import fitz
    with fitz.open(stream=data, filetype="pdf") as doc:
        return [doc[i].get_text("text").strip() for i in range(doc.page_count)]


def _drain(q):
    msgs = []
    while not q.empty():
        msgs.append(q.get_nowait())
    return msgs


# ---------- 1. Gemini: оборванный ответ ----------

def test_gemini_max_tokens_is_error_not_result(monkeypatch):
    from pdf2md.ocr_clients import GeminiClient, GeminiTruncatedError

    monkeypatch.setattr(GeminiClient, "MIN_INTERVAL_SEC", 0)
    client = GeminiClient(KEY)
    _respond_with(client.session, _gemini_resp("половина текс", "MAX_TOKENS"))
    with pytest.raises(GeminiTruncatedError):
        client._call_api(b"%PDF")
    _respond_with(client.session, _gemini_resp("", "SAFETY"))
    with pytest.raises(RuntimeError, match="SAFETY"):
        client._call_api(b"%PDF")
    _respond_with(client.session, _gemini_resp("полный текст"))
    assert client._call_api(b"%PDF") == "полный текст"


def test_gemini_truncated_pdf_is_split_until_it_fits(tmp, monkeypatch):
    from pdf2md.ocr_clients import GeminiClient, GeminiTruncatedError

    p = tmp / "long.pdf"
    _make_pdf(p, 5)
    client = GeminiClient(KEY)

    def call(data, cancel_event=None):
        labels = _pdf_page_labels(data)
        if len(labels) > 2:                      # «ответ не влезает» для >2 страниц
            raise GeminiTruncatedError("cut")
        return " ".join(labels)

    monkeypatch.setattr(client, "_call_api", call)
    found = re.findall(r"PAGE-\d+", client.parse_pdf(p))
    assert found == [f"PAGE-{i:03d}" for i in range(1, 6)]   # всё, по порядку, без повторов


def test_gemini_truncated_single_page_and_image_fail(tmp, monkeypatch):
    from pdf2md.ocr_clients import GeminiClient, GeminiTruncatedError

    p = tmp / "one.pdf"
    _make_pdf(p, 1)
    img = tmp / "a.png"
    img.write_bytes(b"png")
    client = GeminiClient(KEY)

    def always_cut(data, mime=None, cancel_event=None):
        raise GeminiTruncatedError("cut")

    monkeypatch.setattr(client, "_call_api", always_cut)
    with pytest.raises(GeminiTruncatedError):
        client.parse_pdf(p)
    with pytest.raises(GeminiTruncatedError):
        client.parse_image(img)


def test_gemini_answer_marks_truncation():
    from pdf2md.answerers import GeminiAnswerer

    ans = GeminiAnswerer(KEY)
    _respond_with(ans.session, _gemini_resp("Начало ответа", "MAX_TOKENS"))
    out = ans.answer("вопрос?", [({"text": "t", "source": "s"}, 0.9)])
    assert out.startswith("Начало ответа") and "обрезан" in out


# ---------- 2. Устаревшие результаты ----------

def _convert_once(tmp, monkeypatch, src_dir, calls):
    from pdf2md import workers

    class FakeClient:
        def parse_pdf(self, path, cancel_event=None):
            calls.append(path.name)
            return f"# OCR {path.read_bytes().decode()}"

    monkeypatch.setattr(workers, "make_client", lambda *a: FakeClient())
    q = queue.Queue()
    workers.ConvertWorker([src_dir], tmp / "out", "mistral", KEY,
                          {"auto_route": False, "make_chunks": False, "assess_quality": False,
                           "use_ocr_cache": False, "workers": 1}, q, threading.Event())._run()
    assert not [m for m in _drain(q) if m[0] == "error"]


def test_changed_source_is_reconverted(tmp, monkeypatch):
    src = tmp / "src"
    src.mkdir()
    (src / "a.pdf").write_bytes(b"v1")
    calls = []
    _convert_once(tmp, monkeypatch, src, calls)
    _convert_once(tmp, monkeypatch, src, calls)           # без изменений — пропуск
    assert calls == ["a.pdf"]
    (src / "a.pdf").write_bytes(b"v2")
    _convert_once(tmp, monkeypatch, src, calls)           # исходник изменился — переделка
    assert calls == ["a.pdf", "a.pdf"]
    assert (tmp / "out" / "markdown" / "a.md").read_text(encoding="utf-8") == "# OCR v2"


def test_legacy_output_without_manifest_is_adopted(tmp, monkeypatch):
    from pdf2md.constants import MANIFEST_FILE

    src = tmp / "src"
    src.mkdir()
    (src / "a.pdf").write_bytes(b"v1")
    md = tmp / "out" / "markdown"
    md.mkdir(parents=True)
    (md / "a.md").write_text("# старый результат", encoding="utf-8")   # от прошлой версии
    calls = []
    _convert_once(tmp, monkeypatch, src, calls)
    assert calls == []                                    # не переделываем весь архив
    manifest = json.loads((tmp / "out" / MANIFEST_FILE).read_text(encoding="utf-8"))
    assert "a.md" in manifest
    (src / "a.pdf").write_bytes(b"v2")                    # дальше изменения уже ловятся
    _convert_once(tmp, monkeypatch, src, calls)
    assert calls == ["a.pdf"]


def test_reindex_removes_outdated_chunks_of_updated_doc(tmp, monkeypatch):
    from pdf2md.index import GeminiEmbedder, VectorIndex
    from pdf2md.workers import IndexWorker
    from pdf2md import workers

    monkeypatch.setattr(workers.time, "sleep", lambda s: None)
    monkeypatch.setattr(GeminiEmbedder, "embed_batch",
                        lambda self, texts, **kw: [[0.5] * self.DIM for _ in texts])
    chunks = tmp / "chunks"
    chunks.mkdir()

    def write(name, texts):
        (chunks / f"{name}.json").write_text(json.dumps(
            [{"text": t, "source": f"{name}.pdf"} for t in texts], ensure_ascii=False),
            encoding="utf-8")

    def run():
        q = queue.Queue()
        IndexWorker(chunks, tmp / "index", KEY, q, threading.Event())._run()
        assert not [m for m in _drain(q) if m[0] == "error"]
        vi = VectorIndex(tmp / "index")
        vi.load()
        assert len(vi.meta) == vi.vectors.shape[0]
        return sorted((m["source"], m["text"]) for m in vi.meta)

    write("a", ["старая версия"])
    write("b", ["другой документ"])
    run()
    write("a", ["новая версия", "добавленный раздел"])
    assert run() == [("a.pdf", "добавленный раздел"), ("a.pdf", "новая версия"),
                     ("b.pdf", "другой документ")]
    write("a", ["новая версия"])                          # раздел удалён — только чистка
    assert run() == [("a.pdf", "новая версия"), ("b.pdf", "другой документ")]


# ---------- 3. Длинные абзацы и таблицы ----------

def test_long_paragraph_split_within_limit_without_loss():
    from pdf2md.chunking import chunk_markdown
    from pdf2md.constants import MAX_CHARS

    no_punct = "# H\n\n" + " ".join(f"слово{i}" for i in range(2500))
    sentences = "# H\n## S\n\n" + " ".join(f"Пункт {i} договора." for i in range(800))
    for md in (no_punct, sentences):
        chunks = chunk_markdown(md)
        assert len(chunks) > 1
        assert max(len(c["text"]) for c in chunks) <= MAX_CHARS
        joined = " ".join(c["text"] for c in chunks)
        body = md.split("\n\n", 1)[1]
        assert set(re.findall(r"\w+", body)) <= set(re.findall(r"\w+", joined))


def test_long_table_split_with_header_repeated():
    from pdf2md.chunking import chunk_markdown
    from pdf2md.constants import MAX_CHARS

    rows_in = [f"| 2024-01-{i:04d} | {i} руб. |" for i in range(600)]
    table = "| Дата | Сумма |\n|---|---|\n" + "\n".join(rows_in)
    chunks = chunk_markdown("# Т\n\n" + table)
    assert len(chunks) > 1
    assert max(len(c["text"]) for c in chunks) <= MAX_CHARS
    assert all("| Дата | Сумма |" in c["text"] for c in chunks)
    rows = [l for c in chunks for l in c["text"].split("\n") if l.startswith("| 2024")]
    assert rows == rows_in                                # каждая строка ровно раз, по порядку


# ---------- 4. GUI: задачи не смешиваются ----------

def test_tagged_queue_routes_to_own_handler():
    from pdf2md.gui import _TaggedQueue

    main = queue.Queue()
    got = []
    _TaggedQueue(main, lambda k, p: got.append(("convert", k, p))).put(("log", "a"))
    _TaggedQueue(main, lambda k, p: got.append(("search", k, p))).put(("log", "b"))
    while not main.empty():
        handler, (kind, payload) = main.get_nowait()
        handler(kind, payload)
    assert got == [("convert", "log", "a"), ("search", "log", "b")]


def test_busy_blocks_second_task(monkeypatch):
    from pdf2md import gui

    shown = []
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a: shown.append(a))
    alive = types.SimpleNamespace(worker=types.SimpleNamespace(is_alive=lambda: True))
    idle = types.SimpleNamespace(worker=types.SimpleNamespace(is_alive=lambda: False))
    assert gui.App._busy(alive) is True and len(shown) == 1
    assert gui.App._busy(idle) is False
    assert gui.App._busy(types.SimpleNamespace(worker=None)) is False
