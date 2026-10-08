"""Пакетный ввод: архивы RAR/7z (и вложенные), многотомные RAR, TIFF-сканы.
Без сети. Тест с 7z пропускается, если 7-Zip не установлен."""
import queue
import shutil
import subprocess
import threading
import zipfile

import pytest

KEY = "SECRET-TEST-KEY"


@pytest.fixture()
def tmp(tmp_path):
    yield tmp_path
    shutil.rmtree(tmp_path, ignore_errors=True)


def _make_tiff(path, n_pages):
    from PIL import Image, ImageDraw
    frames = []
    for i in range(n_pages):
        im = Image.new("1", (620, 877), 1)
        ImageDraw.Draw(im).text((50, 50), f"PAGE {i + 1}", fill=0)
        frames.append(im)
    frames[0].save(path, save_all=True, append_images=frames[1:], compression="group4")


def _rels(docs):
    return sorted((rel, kind) for _, rel, kind in docs)


def test_document_kinds():
    from pathlib import Path
    from pdf2md.fileutils import document_kind, is_archive, is_extra_volume

    assert [document_kind(Path(n)) for n in ("a.PDF", "b.tif", "c.TIFF", "d.jpg", "e.docx", "f.exe")] == \
        ["pdf", "tiff", "tiff", "image", "doc", None]
    assert all(is_archive(Path(n)) for n in ("a.zip", "b.RAR", "c.7z"))
    assert not is_extra_volume(Path("дело.part1.rar"))
    assert is_extra_volume(Path("дело.part2.rar")) and is_extra_volume(Path("дело.part010.rar"))


def test_multipage_tiff_to_pdf(tmp):
    import fitz
    from pdf2md.imaging import tiff_to_pdf

    src = tmp / "скан.tif"
    _make_tiff(src, 3)
    pdf = tiff_to_pdf(src, tmp / "out")
    with fitz.open(str(pdf)) as doc:
        assert doc.page_count == 3


def test_7z_with_nested_zip_is_collected(tmp):
    from pdf2md.archives import find_7zip
    from pdf2md.fileutils import collect_documents

    seven = find_7zip()
    if not seven:
        pytest.skip("7-Zip не установлен")
    content = tmp / "content"
    (content / "акты").mkdir(parents=True)
    (content / "договор.pdf").write_bytes(b"%PDF-1")
    (content / "акты" / "скан.tif").write_bytes(b"II*")
    with zipfile.ZipFile(content / "вложение.zip", "w") as zf:
        zf.writestr("письмо.pdf", b"%PDF-2")
    src = tmp / "src"
    src.mkdir()
    subprocess.run([seven, "a", "-bd", str(src / "дело.7z"), "."], cwd=content,
                   check=True, capture_output=True, stdin=subprocess.DEVNULL)

    docs = collect_documents(src, tmp / "work", log_fn=lambda s: None)
    assert _rels(docs) == [("дело/акты/скан.tif", "tiff"),
                           ("дело/вложение/письмо.pdf", "pdf"),
                           ("дело/договор.pdf", "pdf")]


def test_broken_archive_does_not_stop_batch(tmp):
    from pdf2md.fileutils import collect_documents

    src = tmp / "src"
    src.mkdir()
    (src / "битый.rar").write_bytes(b"not a rar at all")
    (src / "дело.part2.rar").write_bytes(b"volume 2")
    (src / "a.pdf").write_bytes(b"%PDF")
    logs = []
    docs = collect_documents(src, tmp / "work", log_fn=logs.append)
    assert _rels(docs) == [("a.pdf", "pdf")]              # остальное собрано
    assert any("битый.rar" in m for m in logs)            # ошибка архива — в логе, не падение
    assert any("дело.part2.rar" in m for m in logs)       # лишний том пропущен с пояснением


def test_no_archive_tool_gives_clear_hint(tmp, monkeypatch):
    from pdf2md import archives
    from pdf2md.fileutils import collect_documents

    monkeypatch.setattr(archives, "find_7zip", lambda: None)
    monkeypatch.setattr(archives, "find_bsdtar", lambda: None)
    (tmp / "дело.rar").write_bytes(b"Rar!")
    logs = []
    assert collect_documents(tmp / "дело.rar", tmp / "work", log_fn=logs.append) == []
    assert any("7-Zip" in m for m in logs)


def test_symlinks_inside_sources_are_skipped(tmp):
    from pdf2md.fileutils import collect_documents

    outside = tmp / "secret.pdf"
    outside.write_bytes(b"%PDF secret")
    src = tmp / "src"
    src.mkdir()
    (src / "a.pdf").write_bytes(b"%PDF")
    try:
        (src / "link.pdf").symlink_to(outside)
    except OSError:
        pytest.skip("нет прав на создание символических ссылок")
    docs = collect_documents(src, tmp / "work", log_fn=lambda s: None)
    assert _rels(docs) == [("a.pdf", "pdf")]


def test_tiff_goes_through_ocr_as_pdf_with_page_check(tmp, monkeypatch):
    import fitz
    import json
    from pdf2md import workers
    from pdf2md.pages import join_pages

    src = tmp / "src"
    src.mkdir()
    _make_tiff(src / "скан.tiff", 4)
    seen = []

    class FakeClient:
        def parse_pdf(self, path, cancel_event=None):
            with fitz.open(str(path)) as d:
                seen.append((path.suffix, d.page_count))
            return join_pages([f"Страница {i}" for i in range(1, 4)])   # OCR «потерял» 4-ю

    monkeypatch.setattr(workers, "make_client", lambda *a: FakeClient())
    q = queue.Queue()
    workers.ConvertWorker([src], tmp / "out", "mistral", KEY,
                          {"make_chunks": False, "assess_quality": True, "use_ocr_cache": False,
                           "workers": 1}, q, threading.Event())._run()
    assert seen == [(".pdf", 4)]                          # в OCR ушёл PDF на 4 страницы
    report = json.loads((tmp / "out" / "report.json").read_text(encoding="utf-8"))
    entry = report[0]
    assert entry["route"] == "OCR (TIFF)"
    assert entry["pages"]["missing"] == [4] and entry["level"] == "сомнительно"
