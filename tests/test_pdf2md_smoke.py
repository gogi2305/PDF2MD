"""Дымовые тесты pdf2md: реально вызывают функции/классы каждого модуля,
без сети и без GUI. Не покрывают сами OCR-API (нужны ключи + сеть),
но ловят регрессии в роутинге, чанкинге, индексе и связке модулей.

Запуск:  pip install pytest && pytest tests/ -v
"""
import shutil
import threading
import zipfile
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture()
def tmp(tmp_path):
    yield tmp_path
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_chunk_markdown_splits_long_text():
    from pdf2md.chunking import chunk_markdown, chunk_hash

    md = "# Заголовок\n\n" + ("Текст абзаца. " * 300) + "\n\n## Раздел 2\n\n" + ("Ещё текст. " * 200)
    chunks = chunk_markdown(md)
    assert len(chunks) >= 2
    assert isinstance(chunk_hash(chunks[0], "src.md"), str)


def test_pdf_native_reads_text_layer(tmp):
    import fitz  # PyMuPDF
    from pdf2md.pdf_native import pdf_has_text_layer, extract_markdown_native

    pdf_path = tmp / "sample.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "The quick brown fox jumps over the lazy dog.")
    doc.save(str(pdf_path))
    doc.close()

    assert pdf_has_text_layer(pdf_path) is True
    assert "quick brown fox" in extract_markdown_native(pdf_path)


def test_fileutils_junk_names_and_paths():
    from pdf2md.fileutils import is_junk, safe_filename

    assert is_junk(Path("__MACOSX/foo")) is True
    assert is_junk(Path("normal.pdf")) is False
    assert safe_filename('a:b/c*d') == "a_b_c_d"


def test_zip_extraction_fixes_cyrillic_names(tmp):
    from pdf2md.fileutils import extract_zip_recursive

    zpath = tmp / "test.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("отчёт.txt", "содержимое")
        zf.writestr("__MACOSX/junk", "x")

    extracted = tmp / "extracted"
    extracted.mkdir()
    extract_zip_recursive(zpath, extracted, log_fn=lambda s: None)
    names = [p.name for p in extracted.rglob("*") if p.is_file()]
    assert "отчёт.txt" in names


def test_collect_documents_returns_list(tmp):
    from pdf2md.fileutils import collect_documents

    docs = collect_documents(tmp, tmp / "work", log_fn=lambda s: None)
    assert isinstance(docs, list)


def test_ocr_cache_roundtrip(tmp):
    from pdf2md.ocr_cache import ocr_cache_get, ocr_cache_put

    f = tmp / "img.bin"
    f.write_bytes(b"fake-image-bytes")
    cache_dir = tmp / "_ocr_cache"
    assert ocr_cache_get(cache_dir, f, "gemini") is None
    ocr_cache_put(cache_dir, f, "gemini", "# Распознанный текст")
    assert ocr_cache_get(cache_dir, f, "gemini") == "# Распознанный текст"


def test_assess_markdown_quality_levels():
    from pdf2md.quality import assess_markdown_quality

    level, _ = assess_markdown_quality("Нормальный связный текст документа без искажений.")
    assert level == "надёжно"

    level2, _ = assess_markdown_quality("[неразборчиво] [неразборчиво] xqzpr")
    assert level2 in ("сомнительно", "проверить")


def test_vector_index_save_load_search(tmp):
    from pdf2md.index import VectorIndex

    vi = VectorIndex(tmp / "index")
    vi.vectors = np.random.RandomState(0).rand(5, 8).astype("float32")
    vi.meta = [{"text": f"чанк {i}", "source": "doc.md"} for i in range(5)]
    vi.info = {"model": "test"}
    vi.save()

    vi2 = VectorIndex(tmp / "index")
    assert vi2.load() is True
    results = vi2.search(vi.vectors[2], top_k=3)
    assert len(results) == 3
    assert results[0][0]["text"] == "чанк 2"  # сам с собой -> макс. похожесть


def test_make_client_builds_all_services():
    from pdf2md.ocr_clients import make_client, LlamaParseClient, GeminiClient, MistralOCRClient, GlmOcrClient

    expected = {
        "llamaparse": LlamaParseClient, "gemini": GeminiClient,
        "mistral": MistralOCRClient, "glm": GlmOcrClient,
    }
    for svc, cls in expected.items():
        client = make_client(svc, api_key="dummy-key", language="ru", scan_mode=True)
        assert isinstance(client, cls)


def test_answerer_constructors():
    from pdf2md.answerers import GeminiAnswerer, OllamaAnswerer

    GeminiAnswerer(api_key="dummy")
    OllamaAnswerer(model="llama3.2")


def test_worker_constructors(tmp):
    import queue
    from pdf2md.workers import ConvertWorker, IndexWorker, SearchWorker

    q, ev = queue.Queue(), threading.Event()
    options = {"scan_mode": True, "auto_route": True, "preprocess": True,
               "assess": True, "crosscheck": None, "make_chunks": True, "workers": 2}

    assert isinstance(ConvertWorker([tmp], tmp / "out", "gemini", "dummy", options, q, ev), threading.Thread)
    assert isinstance(IndexWorker(tmp / "chunks", tmp / "index2", "dummy", q, ev), threading.Thread)
    assert isinstance(
        SearchWorker("вопрос?", tmp / "index2", "dummy", "gemini", {}, top_k=5, msg_queue=q, cancel_event=ev),
        threading.Thread,
    )


def test_config_store_roundtrip(tmp, monkeypatch):
    from pdf2md import config_store

    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp / "cfgdir")
    monkeypatch.setattr(config_store, "CONFIG_FILE", tmp / "cfgdir" / "config.json")

    config_store.save_config({"language": "en", "api_keys": {"gemini": "x"}})
    loaded = config_store.load_config()
    assert loaded["language"] == "en"
    assert loaded["api_keys"]["gemini"] == "x"
