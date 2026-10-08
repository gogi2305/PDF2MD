"""Регрессионные тесты на исправления:
1. Gemini: дорезка слишком большого куска PDF не задваивает документ.
2. API-ключ Google передаётся в заголовке x-goog-api-key, а не в URL.
3. Эмбеддинги на gemini-embedding-001; индекс старой модели пересоздаётся,
   а поиск по нему не запускается.

Сеть не нужна: HTTP-сессии подменяются заглушками.
"""
import json
import re
import queue
import shutil
import threading

import numpy as np
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


def _make_pdf(path, n_pages):
    import fitz
    doc = fitz.open()
    for i in range(1, n_pages + 1):
        doc.new_page().insert_text((72, 72), f"PAGE-{i:03d}")
    doc.save(str(path))
    doc.close()


def _pdf_page_labels(data):
    import fitz
    doc = fitz.open(stream=data, filetype="pdf")
    labels = [doc[i].get_text("text").strip() for i in range(doc.page_count)]
    doc.close()
    return labels


# ---------- 1. Разбивка больших PDF ----------

def test_split_pdf_accepts_bytes(tmp):
    from pdf2md.pdf_native import split_pdf_to_chunks

    p = tmp / "doc.pdf"
    _make_pdf(p, 10)
    chunks, total = split_pdf_to_chunks(p.read_bytes(), 3)
    assert total == 10
    assert [(s, e) for _, s, e in chunks] == [(1, 3), (4, 6), (7, 9), (10, 10)]
    assert _pdf_page_labels(chunks[1][0]) == ["PAGE-004", "PAGE-005", "PAGE-006"]


def test_gemini_oversized_chunk_not_duplicated(tmp, monkeypatch):
    from pdf2md import ocr_clients

    p = tmp / "big.pdf"
    _make_pdf(p, 25)
    client = ocr_clients.GeminiClient(KEY)
    # Любой кусок «слишком большой» — заставляем код дорезать каждый
    monkeypatch.setattr(client, "MAX_INLINE_MB", -1)
    monkeypatch.setattr(client, "PAGES_PER_CHUNK", 10)
    monkeypatch.setattr(ocr_clients.time, "sleep", lambda s: None)
    sent = []
    monkeypatch.setattr(client, "_call_api",
                        lambda data, cancel_event=None: sent.extend(_pdf_page_labels(data)) or "x")

    client.parse_pdf(p)
    # Каждая страница ушла ровно один раз и по порядку
    assert sent == [f"PAGE-{i:03d}" for i in range(1, 26)]


# ---------- 2. Ключ в заголовке, не в URL ----------

def _capture_post(session, response):
    calls = []

    def post(url, **kwargs):
        calls.append({"url": url, "headers": dict(session.headers), **kwargs})
        return response

    session.post = post
    return calls


def _assert_key_in_header_only(calls):
    assert calls, "запрос не был отправлен"
    for c in calls:
        assert KEY not in c["url"]
        assert "key=" not in c["url"]
        assert c["headers"].get("x-goog-api-key") == KEY


def test_gemini_ocr_key_in_header(monkeypatch):
    from pdf2md.ocr_clients import GeminiClient

    monkeypatch.setattr(GeminiClient, "MIN_INTERVAL_SEC", 0)
    client = GeminiClient(KEY)
    calls = _capture_post(client.session, FakeResponse(
        {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}))
    assert client._call_api(b"%PDF-fake") == "ok"
    _assert_key_in_header_only(calls)


def test_gemini_embedder_key_in_header_and_model():
    from pdf2md.index import GeminiEmbedder

    emb = GeminiEmbedder(KEY)
    calls = _capture_post(emb.session, FakeResponse(
        {"embeddings": [{"values": [0.1] * GeminiEmbedder.DIM}] * 2}))
    vectors = emb.embed_batch(["а", "б"])
    assert len(vectors) == 2
    _assert_key_in_header_only(calls)
    # 3. Новая модель и урезанная размерность
    assert GeminiEmbedder.MODEL == "gemini-embedding-001"
    assert "gemini-embedding-001" in calls[0]["url"]
    for req in calls[0]["json"]["requests"]:
        assert req["model"] == "models/gemini-embedding-001"
        assert req["outputDimensionality"] == GeminiEmbedder.DIM


def test_gemini_answerer_key_in_header():
    from pdf2md.answerers import GeminiAnswerer

    ans = GeminiAnswerer(KEY)
    calls = _capture_post(ans.session, FakeResponse(
        {"candidates": [{"content": {"parts": [{"text": "ответ"}]}}]}))
    assert ans.answer("вопрос?", [({"text": "t", "source": "s"}, 0.9)]) == "ответ"
    _assert_key_in_header_only(calls)


# ---------- 3. Индекс устаревшей модели ----------

def _write_old_index(index_dir):
    from pdf2md.index import VectorIndex

    vi = VectorIndex(index_dir)
    vi.vectors = np.ones((3, 768), dtype=np.float32)
    vi.meta = [{"text": f"старый {i}", "source": "old.pdf", "hash": f"h{i}"} for i in range(3)]
    vi.info = {"embedding_model": "text-embedding-004", "total_chunks": 3}
    vi.save()


def _drain(q):
    msgs = []
    while not q.empty():
        msgs.append(q.get_nowait())
    return msgs


def test_index_worker_rebuilds_old_model_index(tmp, monkeypatch):
    from pdf2md.index import GeminiEmbedder, VectorIndex
    from pdf2md.workers import IndexWorker
    from pdf2md import workers

    index_dir = tmp / "index"
    _write_old_index(index_dir)
    chunks_dir = tmp / "chunks"
    chunks_dir.mkdir()
    (chunks_dir / "new.json").write_text(json.dumps(
        [{"text": "новый чанк", "source": "new.pdf"}], ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(workers.time, "sleep", lambda s: None)
    monkeypatch.setattr(GeminiEmbedder, "embed_batch",
                        lambda self, texts, **kw: [[0.5] * self.DIM for _ in texts])

    q = queue.Queue()
    IndexWorker(chunks_dir, index_dir, KEY, q, threading.Event())._run()
    assert not [m for m in _drain(q) if m[0] == "error"]

    vi = VectorIndex(index_dir)
    vi.load()
    assert vi.info["embedding_model"] == "gemini-embedding-001"
    # Старые векторы выброшены, а не смешаны с новыми
    assert [m["source"] for m in vi.meta] == ["new.pdf"]
    assert vi.vectors.shape == (1, GeminiEmbedder.DIM)


def test_search_worker_refuses_old_model_index(tmp, monkeypatch):
    from pdf2md.index import GeminiEmbedder
    from pdf2md.workers import SearchWorker

    index_dir = tmp / "index"
    _write_old_index(index_dir)

    def no_network(*a, **kw):
        raise AssertionError("эмбеддинг не должен запрашиваться")

    monkeypatch.setattr(GeminiEmbedder, "embed_batch", no_network)

    q = queue.Queue()
    SearchWorker("вопрос?", index_dir, KEY, "gemini", {"api_key": KEY},
                 top_k=3, msg_queue=q, cancel_event=threading.Event())._run()
    errors = [m[1] for m in _drain(q) if m[0] == "error"]
    assert len(errors) == 1
    assert "Индексировать" in errors[0]


# ---------- 4. Язык: ответы и OCR ----------

def test_answer_prompt_follows_question_language():
    from pdf2md.answerers import build_answer_prompt

    prompt = build_answer_prompt("What is the contract number?",
                                 [({"text": "Договор № 42", "source": "a.pdf"}, 0.9)])
    assert "SAME LANGUAGE as the question" in prompt
    assert "русском" not in prompt
    assert "What is the contract number?" in prompt
    assert "[Source: a.pdf]" in prompt


def _run_convert(tmp, monkeypatch, service, doc_language):
    from pdf2md import workers

    src = tmp / "in"
    src.mkdir(exist_ok=True)
    (src / "scan.png").write_bytes(b"fake-png")
    made = []

    class FakeClient:
        def parse_image(self, path, cancel_event=None):
            return "# Распознанный текст документа"

    def fake_make_client(svc, key, language, scan_mode):
        made.append((svc, language))
        return FakeClient()

    monkeypatch.setattr(workers, "make_client", fake_make_client)
    opts = {"doc_language": doc_language, "preprocess_images": False,
            "make_chunks": False, "assess_quality": False, "workers": 1}
    out = tmp / f"out_{service}_{doc_language}"
    q = queue.Queue()
    workers.ConvertWorker([src], out, service, KEY, opts, q, threading.Event())._run()
    assert not [m for m in _drain(q) if m[0] == "error"]
    return made, src / "scan.png", out / "_ocr_cache"


def test_convert_passes_doc_language_to_client(tmp, monkeypatch):
    from pdf2md.ocr_cache import ocr_cache_get

    made, img, cache = _run_convert(tmp, monkeypatch, "llamaparse", "en")
    assert made == [("llamaparse", "en")]
    # Для LlamaParse язык — часть ключа кэша
    assert ocr_cache_get(cache, img, "llamaparse", "en|scan=1") is not None
    assert ocr_cache_get(cache, img, "llamaparse", "ru|scan=1") is None


def test_convert_cache_key_keeps_ru_for_other_services(tmp, monkeypatch):
    from pdf2md.ocr_cache import ocr_cache_get

    made, img, cache = _run_convert(tmp, monkeypatch, "gemini", "en")
    assert made == [("gemini", "en")]
    # Gemini язык игнорирует — старый кэш с "ru" должен оставаться валидным
    assert ocr_cache_get(cache, img, "gemini", "ru|scan=1") is not None


# ---------- 5. Mistral чистит за собой; совпадающие имена не теряются ----------

class _MistralFakeSession:
    def __init__(self, ocr_status=200):
        self.headers = {}
        self.deleted = []
        self.ocr_status = ocr_status

    def post(self, url, **kw):
        if url.endswith("/files"):
            return FakeResponse({"id": "file-123"})
        return FakeResponse({"pages": [{"markdown": "текст"}]} if self.ocr_status == 200
                            else {"error": "bad"}, self.ocr_status)

    def get(self, url, **kw):
        return FakeResponse({"url": "https://signed"})

    def delete(self, url, **kw):
        self.deleted.append(url)
        return FakeResponse({}, 200)


@pytest.mark.parametrize("ocr_status", [200, 400])
def test_mistral_deletes_uploaded_file(tmp, ocr_status):
    from pdf2md.ocr_clients import MistralOCRClient

    pdf = tmp / "a.pdf"
    pdf.write_bytes(b"%PDF-fake")
    client = MistralOCRClient(KEY)
    client.session = _MistralFakeSession(ocr_status)
    if ocr_status == 200:
        assert client.parse_pdf(pdf) == "<!-- page 1 -->\n\nтекст"
    else:
        with pytest.raises(RuntimeError):
            client.parse_pdf(pdf)
    # Удаляем и при успехе, и при ошибке OCR
    assert client.session.deleted == ["https://api.mistral.ai/v1/files/file-123"]


def _zip_with(path, files):
    import zipfile
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)


def test_collect_documents_zips_with_same_inner_names(tmp):
    from pdf2md.fileutils import collect_documents

    src = tmp / "src"
    (src / "sub").mkdir(parents=True)
    _zip_with(src / "a.zip", {"x.pdf": b"A"})
    _zip_with(src / "b.zip", {"x.pdf": b"B"})
    _zip_with(src / "sub" / "a.zip", {"x.pdf": b"C"})   # то же имя архива, другая папка
    (src / "scan.pdf").write_bytes(b"P")
    (src / "scan.png").write_bytes(b"I")

    docs = collect_documents(src, tmp / "work", log_fn=lambda s: None)
    rels = sorted(rel for _, rel, _ in docs)
    assert rels == ["a/x.pdf", "b/x.pdf", "scan.pdf", "scan.png", "sub/a/x.pdf"]
    # Каждый путь указывает на свой файл, архивы не смешались при распаковке
    by_rel = {rel: p.read_bytes() for p, rel, _ in docs}
    assert (by_rel["a/x.pdf"], by_rel["b/x.pdf"], by_rel["sub/a/x.pdf"]) == (b"A", b"B", b"C")


def test_collect_documents_renames_instead_of_dropping(tmp):
    from pdf2md.fileutils import collect_documents

    src = tmp / "src"
    (src / "a").mkdir(parents=True)
    (src / "a" / "x.pdf").write_bytes(b"folder")
    _zip_with(src / "a.zip", {"x.pdf": b"zip"})       # тоже даёт a/x.pdf

    logs = []
    docs = collect_documents(src, tmp / "work", log_fn=logs.append)
    contents = sorted(p.read_bytes() for p, _, _ in docs)
    assert contents == [b"folder", b"zip"]
    assert sorted(rel for _, rel, _ in docs) == ["a/x.pdf", "a/x_2.pdf"]
    assert any("a/x_2.pdf" in m for m in logs)


def _convert_sources(tmp, monkeypatch, sources):
    from pdf2md import workers

    class FakeClient:
        def parse_pdf(self, path, cancel_event=None):
            return f"# OCR {path.read_bytes().decode()}"

    monkeypatch.setattr(workers, "make_client", lambda *a: FakeClient())
    opts = {"auto_route": False, "make_chunks": False, "assess_quality": False,
            "use_ocr_cache": False, "workers": 1}
    out = tmp / "out"
    q = queue.Queue()
    workers.ConvertWorker(sources, out, "mistral", KEY, opts, q, threading.Event())._run()
    done = [m[1] for m in _drain(q) if m[0] == "done"]
    md = {p.relative_to(out / "markdown").as_posix(): p.read_text(encoding="utf-8")
          for p in (out / "markdown").rglob("*.md")}
    return done[0], md


def test_convert_sources_with_same_name_both_processed(tmp, monkeypatch):
    folder = tmp / "x" / "docs"
    folder.mkdir(parents=True)
    (folder / "a.pdf").write_bytes(b"folder")
    _zip_with(tmp / "docs.zip", {"a.pdf": b"zip"})

    summary, md = _convert_sources(tmp, monkeypatch, [folder, tmp / "docs.zip"])
    assert summary["processed"] == 2
    assert md == {"docs/a.md": "# OCR folder", "docs_2/a.md": "# OCR zip"}


def test_convert_same_source_twice_processed_once(tmp, monkeypatch):
    folder = tmp / "docs"
    folder.mkdir()
    (folder / "a.pdf").write_bytes(b"one")

    summary, md = _convert_sources(tmp, monkeypatch, [folder, folder])
    assert summary["processed"] == 1
    assert md == {"a.md": "# OCR one"}


# ---------- 6. Логи и ошибки по языку интерфейса ----------

@pytest.fixture()
def english():
    from pdf2md import messages
    messages.set_language("en")
    yield
    messages.set_language("ru")


def test_messages_catalog_consistent():
    import string
    from pdf2md.messages import MESSAGES

    ru, en = MESSAGES["ru"], MESSAGES["en"]
    assert set(ru) == set(en)
    fields = lambda s: {f for _, f, _, _ in string.Formatter().parse(s) if f}
    assert [k for k in ru if fields(ru[k]) != fields(en[k])] == []


def test_tr_language_switch_and_fallback(english):
    from pdf2md import messages

    assert messages.tr("found_chunks", n=3) == "Chunks found: 3"
    assert messages.route_label("кэш OCR") == "OCR cache"
    assert messages.tr("no-such-key") == "no-such-key"
    messages.set_language("xx")            # неизвестный язык → русский
    assert messages.tr("found_chunks", n=3) == "Найдено чанков: 3"
    assert messages.route_label("кэш OCR") == "кэш OCR"


def test_worker_errors_in_english(tmp, english):
    from pdf2md.workers import SearchWorker

    q = queue.Queue()
    SearchWorker("q?", tmp / "no_index", KEY, "gemini", {}, top_k=3,
                 msg_queue=q, cancel_event=threading.Event())._run()
    errors = [m[1] for m in _drain(q) if m[0] == "error"]
    assert errors == ["Index not found. Click Build index before searching."]


def test_client_errors_in_english(english):
    from pdf2md.ocr_clients import make_client, QuotaExhaustedError, GeminiClient
    from pdf2md import ocr_clients

    with pytest.raises(ValueError, match="Unknown service: nope"):
        make_client("nope", KEY, "ru", True)

    client = GeminiClient(KEY)
    ocr_clients.GeminiClient.MIN_INTERVAL_SEC, saved = 0, ocr_clients.GeminiClient.MIN_INTERVAL_SEC
    try:
        _capture_post(client.session, FakeResponse({"error": "GenerateRequestsPerDay"}, 429))
        with pytest.raises(QuotaExhaustedError, match="Gemini daily quota exhausted"):
            client._call_api(b"%PDF")
    finally:
        ocr_clients.GeminiClient.MIN_INTERVAL_SEC = saved


def test_convert_log_in_english(tmp, monkeypatch, english):
    from pdf2md import workers

    src = tmp / "in"
    src.mkdir()
    (src / "a.pdf").write_bytes(b"x")

    class FakeClient:
        def parse_pdf(self, path, cancel_event=None):
            return "# text"

    monkeypatch.setattr(workers, "make_client", lambda *a: FakeClient())
    q = queue.Queue()
    workers.ConvertWorker([src], tmp / "out", "mistral", KEY,
                          {"auto_route": False, "make_chunks": False, "assess_quality": False,
                           "use_ocr_cache": True, "workers": 1}, q, threading.Event())._run()
    logs = [m[1] for m in _drain(q) if m[0] == "log"]
    assert "Service: mistral" in logs
    assert "  Done: a.pdf [OCR]" in logs
    assert not any(re.search("[А-Яа-я]", m) for m in logs)
