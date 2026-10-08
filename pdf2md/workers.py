"""Фоновые потоки GUI: конвертация (ConvertWorker), индексация (IndexWorker), поиск и ответ (SearchWorker)."""

from .compat import requests, np
import json
import time
import shutil
import threading
import traceback
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from .answerers import GeminiAnswerer, OllamaAnswerer
from .chunking import chunk_hash, chunk_markdown
from .constants import DEFAULT_DOC_LANGUAGE, MANIFEST_FILE
from .messages import route_label, tr
from .fileutils import collect_documents, file_content_hash, safe_filename, unique_name
from .imaging import preprocess_image_for_ocr, tiff_to_pdf
from .index import GeminiEmbedder, VectorIndex, collect_chunks_from_dir
from .ocr_cache import ocr_cache_get, ocr_cache_put
from .ocr_clients import QuotaExhaustedError, make_client
from .pages import (PAGES_OK, PAGES_PROBLEM, PAGES_UNVERIFIED, check_pages,
                    format_page_list, strip_page_markers)
from .pdf_native import extract_markdown_native, extract_markitdown, pdf_file_page_count, pdf_has_text_layer
from .quality import QA_CROSSCHECK_AGREE, _text_similarity, _write_html_diff, assess_markdown_quality

def _load_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

def _save_manifest(path: Path, manifest: dict) -> None:
    # Через временный файл: оборванная запись не испортит прежний манифест.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)

class ConvertWorker(threading.Thread):
    def __init__(self, input_paths, output_dir, service, api_key, options, msg_queue, cancel_event):
        super().__init__(daemon=True)
        # Принимаем как список путей, так и одиночный путь (обратная совместимость)
        if isinstance(input_paths, (str, Path)):
            input_paths = [input_paths]
        self.input_paths = [Path(p) for p in input_paths]
        self.output_dir = Path(output_dir)
        self.service = service; self.api_key = api_key
        self.options = options; self.q = msg_queue; self.cancel = cancel_event
        self._lock = threading.Lock(); self._done = 0

    def log(self, t): self.q.put(("log", t))
    def progress(self, c, t): self.q.put(("progress", (c, t)))
    def status(self, t): self.q.put(("status", t))
    def done(self, s): self.q.put(("done", s))
    def error(self, t): self.q.put(("error", t))

    def run(self):
        try: self._run()
        except Exception as e: self.error(tr("critical_error", e=e, tb=traceback.format_exc()))

    def _run(self):
        if requests is None:
            self.error(tr("no_requests_install"))
            return
        md_dir = self.output_dir / "markdown"
        chunks_dir = self.output_dir / "chunks"
        md_dir.mkdir(parents=True, exist_ok=True)
        if self.options.get("make_chunks"): chunks_dir.mkdir(parents=True, exist_ok=True)
        work_dir = self.output_dir / "_temp"; work_dir.mkdir(parents=True, exist_ok=True)
        self.status(tr("collecting"))
        self.log(tr("service", svc=self.service))
        self.log(tr("sources_count", n=len(self.input_paths)))

        # Один и тот же источник, добавленный дважды, обрабатываем один раз
        unique_inputs, seen_inputs = [], set()
        for ip in self.input_paths:
            k = str(ip.resolve()).lower()
            if k not in seen_inputs:
                seen_inputs.add(k); unique_inputs.append(ip)
        multi = len(unique_inputs) > 1

        # Собираем PDF и изображения из ВСЕХ источников
        all_docs = []
        taken_prefixes = set()
        for ip in unique_inputs:
            if not ip.exists():
                self.log(tr("source_missing", path=ip))
                continue
            self.log(tr("source", path=ip))
            try:
                got = collect_documents(ip, work_dir, self.log)
                n_pdf = sum(1 for *_, k in got if k == "pdf")
                n_img = sum(1 for *_, k in got if k in ("image", "tiff"))
                n_doc = sum(1 for *_, k in got if k == "doc")
                self.log(tr("found_counts", pdf=n_pdf, img=n_img, docs=n_doc))
                # Префикс пути для уникальности имён между источниками.
                # docs/ и docs.zip (или две папки docs) получат docs и docs_2.
                prefix = unique_name(safe_filename(ip.stem), taken_prefixes) if multi else ""
                for abs_p, rel, kind in got:
                    new_rel = f"{prefix}/{rel}" if prefix else rel
                    all_docs.append((abs_p, new_rel, kind))
            except Exception as e:
                self.log(tr("collect_error", path=ip, e=e))
                continue

        # Дедупликация по итоговому относительному пути
        seen = {}
        for abs_p, rel, kind in all_docs:
            seen.setdefault(rel, (abs_p, kind))
        docs = [(abs_p, rel, kind) for rel, (abs_p, kind) in seen.items()]

        if not docs:
            self.error(tr("no_docs")); return
        self.log(tr("total_to_process", n=len(docs)))
        doc_lang = self.options.get("doc_language", DEFAULT_DOC_LANGUAGE)
        # Язык влияет только на LlamaParse; для остальных держим в ключе кэша
        # прежнее "ru", чтобы смена языка не сбрасывала их кэш и не тратила квоту.
        cache_lang = doc_lang if self.service == "llamaparse" else DEFAULT_DOC_LANGUAGE
        try:
            client = make_client(self.service, self.api_key, doc_lang, self.options.get("scan_mode", True))
        except Exception as e:
            self.error(tr("client_error", e=e)); return
        total = len(docs); self._done = 0
        errors, processed, skipped = [], 0, 0
        self._assessments = []   # (src, route, level, reasons) для report.md
        self._doc_map = {}       # src -> (abs_path, kind, out_md) для сверки (часть B)
        self._page_checks = {}   # src -> результат check_pages (только PDF)
        assess_on = self.options.get("assess_quality", True)
        # Манифест: md-файл → хеш исходника, из которого он сделан. Нужен, чтобы
        # не считать готовым .md, исходник которого с тех пор изменился.
        manifest_path = self.output_dir / MANIFEST_FILE
        self._manifest = _load_manifest(manifest_path)
        tasks = []
        taken_md = set()  # защита от коллизии имён (scan.pdf и scan.png → scan.md)
        for abs_path, rel, kind in docs:
            rel_path = Path(rel)
            out_md = md_dir / rel_path.with_suffix(".md")
            key = out_md.as_posix().lower()
            if key in taken_md:
                ext = rel_path.suffix.lstrip(".")
                n = 1
                while key in taken_md:
                    suffix = f"_{ext}" if n == 1 else f"_{ext}_{n}"
                    out_md = md_dir / rel_path.with_name(f"{rel_path.stem}{suffix}.md")
                    key = out_md.as_posix().lower()
                    n += 1
                self.log(tr("name_conflict", name=out_md.name))
            taken_md.add(key)
            # JSON-чанки зеркалят имя итогового md-файла;
            # source — исходный путь с РОДНЫМ расширением (.pdf / .png / ...)
            out_json = chunks_dir / out_md.relative_to(md_dir).with_suffix(".json")
            src = rel_path.as_posix()
            self._doc_map[src] = (str(abs_path), kind, out_md)
            mkey = out_md.relative_to(md_dir).as_posix()
            try:
                src_hash = file_content_hash(abs_path)
            except OSError:
                src_hash = None
            ready = out_md.exists() and out_md.stat().st_size > 0
            if ready:
                recorded = self._manifest.get(mkey, {}).get("source_hash")
                if recorded is None:
                    # .md от версии без манифеста: считаем актуальным и запоминаем хеш,
                    # чтобы не переделывать весь архив (и не тратить квоту) при обновлении.
                    self._manifest[mkey] = {"source": src, "source_hash": src_hash}
                elif recorded != src_hash:
                    self.log(tr("source_changed", rel=rel))
                    ready = False
            if ready:
                skipped += 1
                self.log(tr("skip_ready", rel=rel))
                if self.options.get("make_chunks"):
                    self._chunks(out_md, out_json, src)
                if assess_on:
                    # оцениваем и готовые файлы, чтобы отчёт покрывал весь корпус
                    try:
                        level, reasons = self._assess(src, abs_path, kind, out_md.read_text(encoding="utf-8"))
                        self._assessments.append((src, "готов", level, reasons))
                    except Exception:
                        pass
                with self._lock:
                    self._done += 1; self.progress(self._done, total)
                continue
            tasks.append((kind, abs_path, out_md, out_json, src, mkey, src_hash))
        workers = max(1, min(8, int(self.options.get("workers", 2))))
        # Gemini free tier: 15 RPM. С глобальным throttle 4.5 сек и 2 потоков
        # — гарантированный запас. Больше = неизбежные 429.
        if self.service == "gemini" and workers > 2:
            self.log(tr("workers_reduced_gemini", n=workers))
            workers = 2
        elif self.service == "mistral" and workers > 3:
            self.log(tr("workers_reduced_mistral", n=workers))
            workers = 3
        self.log(tr("launch", files=len(tasks), workers=workers))

        # OCR-кэш: повторная обработка того же файла не тратит квоту
        cache_dir = None
        if self.options.get("use_ocr_cache", True):
            cache_dir = self.output_dir / "_ocr_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)

        def proc(args):
            kind, abs_path, out_md, out_json, src, mkey, src_hash = args
            if self.cancel.is_set(): return ("cancelled", src)
            try:
                self.status(tr("processing", src=src))
                cache_extra = f"{cache_lang}|scan={int(bool(self.options.get('scan_mode', True)))}"
                if kind == "image":
                    img_path = abs_path
                    if self.options.get("preprocess_images", True):
                        try:
                            img_path = preprocess_image_for_ocr(abs_path, work_dir / "_pre")
                        except Exception as e:
                            hint = tr("pillow_hint") if isinstance(e, ImportError) else ""
                            self.log(tr("preprocess_skipped", name=abs_path.name, e=e, hint=hint))
                            img_path = abs_path
                    # Кэш по исходному файлу (до предобработки) + сервис
                    cached = ocr_cache_get(cache_dir, abs_path, self.service, cache_extra)
                    if cached is not None:
                        md_text = cached
                        route = "кэш OCR"
                    else:
                        md_text = client.parse_image(img_path, cancel_event=self.cancel)
                        ocr_cache_put(cache_dir, abs_path, self.service, md_text, cache_extra)
                        route = "OCR+подготовка" if img_path is not abs_path else "OCR"
                elif kind == "doc":
                    # Office/web/data → MarkItDown (готовый текст, без OCR и квоты)
                    try:
                        md_text = extract_markitdown(abs_path)
                    except ImportError:
                        return ("error", tr("markitdown_missing", src=src))
                    route = "текст(office)"
                elif kind == "pdf" and self.options.get("auto_route", True) and pdf_has_text_layer(abs_path):
                    # Цифровой PDF — берём текст напрямую, без OCR и без квоты.
                    md_text = extract_markdown_native(abs_path)
                    route = "текст"
                    if len(strip_page_markers(md_text).strip()) < 20:
                        # слой оказался пустым/битым — подстраховываемся OCR
                        cached = ocr_cache_get(cache_dir, abs_path, self.service, cache_extra)
                        if cached is not None:
                            md_text = cached
                            route = "кэш OCR (слой пуст)"
                        else:
                            md_text = client.parse_pdf(abs_path, cancel_event=self.cancel)
                            ocr_cache_put(cache_dir, abs_path, self.service, md_text, cache_extra)
                            route = "OCR (слой пуст)"
                else:
                    # Скан-PDF или TIFF. Кэш — по исходному файлу (TIFF, а не временный PDF).
                    cached = ocr_cache_get(cache_dir, abs_path, self.service, cache_extra)
                    if cached is not None:
                        md_text = cached
                        route = "кэш OCR"
                    else:
                        md_text = client.parse_pdf(self._ocr_pdf(abs_path, kind, work_dir),
                                                   cancel_event=self.cancel)
                        ocr_cache_put(cache_dir, abs_path, self.service, md_text, cache_extra)
                        route = "OCR (TIFF)" if kind == "tiff" else "OCR"
                out_md.parent.mkdir(parents=True, exist_ok=True)
                out_md.write_text(md_text, encoding="utf-8")
                with self._lock:
                    self._manifest[mkey] = {"source": src, "source_hash": src_hash}
                if self.options.get("make_chunks"):
                    self._chunks(out_md, out_json, src)
                if self.options.get("assess_quality", True):
                    level, reasons = self._assess(src, abs_path, kind, md_text)
                    with self._lock:
                        self._assessments.append((src, route, level, reasons))
                return ("ok", f"{src} [{route_label(route)}]")
            except QuotaExhaustedError as e:
                # Дневная квота — нет смысла перебирать остаток пачки.
                self.cancel.set()
                return ("quota", str(e))
            except Exception as e:
                msg = str(e)[:250]
                if "SOCKS" in msg:
                    msg += tr("socks_hint")
                return ("error", f"{src}: {msg}")
            finally:
                with self._lock:
                    self._done += 1; self.progress(self._done, total)

        quota_hit = None
        if tasks:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futures = [ex.submit(proc, t) for t in tasks]
                for fut in as_completed(futures):
                    status, info = fut.result()
                    if status == "ok": processed += 1; self.log(tr("item_done", info=info))
                    elif status == "error": errors.append(info); self.log(tr("item_error", info=info))
                    elif status == "cancelled": self.log(tr("item_cancelled", info=info))
                    elif status == "quota":
                        quota_hit = info
                        self.log(tr("item_stop", info=info))
                    # Дневная квота или ручная отмена — прекращаем разбор очереди.
                    if self.cancel.is_set(): break
        try:
            _save_manifest(manifest_path, self._manifest)
        except Exception as e:
            self.log(tr("manifest_save_failed", e=e))
        # Часть B: сверка спорных вторым движком — ДО чистки work_dir
        # (нужны распакованные из ZIP файлы), и только если включена оценка.
        crosscheck = None
        if assess_on and self.options.get("crosscheck_service") and not self.cancel.is_set():
            try:
                crosscheck = self._cross_check(self.output_dir, work_dir)
            except Exception as e:
                self.log(tr("cc_failed", e=e))
        try: shutil.rmtree(work_dir, ignore_errors=True)
        except Exception: pass
        summary = {"total": total, "processed": processed, "skipped": skipped,
                   "errors": errors, "output_dir": str(self.output_dir)}
        if quota_hit:
            summary["quota_stop"] = quota_hit
        if assess_on and self._assessments:
            qa = self._write_quality_report(self._assessments, self.output_dir, crosscheck)
            summary["quality"] = qa
            if self._page_checks:
                statuses = [c["status"] for c in self._page_checks.values()]
                summary["pages"] = {"ok": statuses.count(PAGES_OK),
                                    "problem": statuses.count(PAGES_PROBLEM),
                                    "unverified": statuses.count(PAGES_UNVERIFIED)}
            if crosscheck:
                summary["crosscheck"] = {k: crosscheck[k] for k in ("checked", "agree", "disagree", "service")}
        self.done(summary)

    def _cross_check(self, out_root, work_dir):
        """Часть B: спорные страницы (не «надёжно») прогоняем вторым движком и
        сравниваем. Находит РАСХОЖДЕНИЕ, а не правоту — где модели не сошлись,
        пишем side-by-side diff для глаз человека."""
        sec = self.options.get("crosscheck_service")
        key = self.options.get("crosscheck_key", "")
        flagged = [(s, lv, rs) for (s, r, lv, rs) in self._assessments if lv != "надёжно"]
        if not flagged:
            self.log(tr("cc_nothing")); return None
        if not key:
            self.log(tr("cc_no_key", svc=sec)); return None
        try:
            sec_client = make_client(sec, key, self.options.get("doc_language", DEFAULT_DOC_LANGUAGE),
                                     self.options.get("scan_mode", True))
        except Exception as e:
            self.log(tr("cc_client_failed", svc=sec, e=e)); return None

        self.log(tr("cc_start", svc=sec, n=len(flagged)))
        diffs_dir = out_root / "report_diffs"
        pre2 = work_dir / "_pre2"
        results = []; agree = disagree = 0
        for src, lv, rs in flagged:
            if self.cancel.is_set():
                self.log(tr("cc_interrupted")); break
            info = self._doc_map.get(src)
            if not info:
                continue
            abs_path, kind, out_md = info
            if kind == "doc":
                continue  # office-документ — это готовый текст, OCR-сверка к нему неприменима
            ap = Path(abs_path)
            if not ap.exists():
                self.log(tr("cc_file_missing", src=src)); continue
            self.status(tr("cc_status", src=src))
            try:
                if kind == "image":
                    img = ap
                    if self.options.get("preprocess_images", True):
                        try: img = preprocess_image_for_ocr(ap, pre2)
                        except Exception: img = ap
                    second = sec_client.parse_image(img, cancel_event=self.cancel)
                else:
                    second = sec_client.parse_pdf(self._ocr_pdf(ap, kind, work_dir),
                                                  cancel_event=self.cancel)
            except QuotaExhaustedError as e:
                self.log(tr("cc_stopped", e=e)); break
            except Exception as e:
                self.log(tr("cc_item_error", src=src, e=str(e)[:150])); continue
            first = out_md.read_text(encoding="utf-8") if out_md.exists() else ""
            sim = _text_similarity(first, second)
            if sim >= QA_CROSSCHECK_AGREE:
                agree += 1
                results.append((src, sim, "согласны", None))
                self.log(tr("cc_agree", src=src, sim=sim))
            else:
                disagree += 1
                diffs_dir.mkdir(parents=True, exist_ok=True)
                dname = safe_filename(src.replace("/", "_").replace("\\", "_")) + ".html"
                try:
                    _write_html_diff(first, second, diffs_dir / dname, sec)
                except Exception as e:
                    self.log(tr("cc_diff_failed", src=src, e=e)); dname = None
                results.append((src, sim, "расходятся", dname))
                self.log(tr("cc_disagree", src=src, sim=sim) + (f" → report_diffs/{dname}" if dname else ""))
        return {"checked": len(results), "agree": agree, "disagree": disagree,
                "service": sec, "details": results}

    @staticmethod
    def _ocr_pdf(abs_path, kind, work_dir):
        """PDF для OCR: сам файл, а TIFF — сконвертированный во временный PDF."""
        if kind == "tiff":
            return tiff_to_pdf(Path(abs_path), work_dir / "_tiff")
        return Path(abs_path)

    def _assess(self, src, abs_path, kind, md_text):
        """Эвристическая оценка текста + сверка числа страниц для PDF.
        Пропавшая или пустая страница — это потеря текста, поэтому документ
        сразу «сомнительно» (и попадает на сверку вторым движком)."""
        level, reasons = assess_markdown_quality(md_text)
        if kind not in ("pdf", "tiff"):
            return level, reasons
        # PyMuPDF открывает и PDF, и TIFF: у TIFF страница = кадр
        n = pdf_file_page_count(Path(abs_path))
        if not n:
            return level, reasons
        check = check_pages(md_text, n)
        with self._lock:
            self._page_checks[src] = check
        if check["status"] == PAGES_PROBLEM:
            level = "сомнительно"
            if check["missing"]:
                reasons = reasons + [f"нет страниц: {format_page_list(check['missing'])}"]
            if check["empty"]:
                reasons = reasons + [f"пустые страницы: {format_page_list(check['empty'])}"]
        return level, reasons

    def _page_report_lines(self):
        """Раздел report.md о сверке числа страниц PDF."""
        checks = self._page_checks
        if not checks:
            return []
        problem = sorted((s, c) for s, c in checks.items() if c["status"] == PAGES_PROBLEM)
        unverified = sorted(s for s, c in checks.items() if c["status"] == PAGES_UNVERIFIED)
        ok = sum(1 for c in checks.values() if c["status"] == PAGES_OK)
        lines = [
            "", "## Сверка страниц PDF",
            f"PDF: {len(checks)} · все страницы на месте {ok} · "
            f"расхождения {len(problem)} · не проверено {len(unverified)}",
            "Сверяется число страниц исходника с размеченными страницами результата "
            "(метки <!-- page N --> в .md). Пустая страница — это, например, вклеенный "
            "скан без текстового слоя или страница, которую OCR не распознал.",
        ]
        if problem:
            lines += ["", "### Расхождения — проверьте по оригиналу"]
            for src, c in problem:
                parts = [f"распознано {c['found']} из {c['source']}"]
                if c["missing"]:
                    parts.append(f"нет: {format_page_list(c['missing'])}")
                if c["empty"]:
                    parts.append(f"пустые: {format_page_list(c['empty'])}")
                lines.append(f"- `{src}` — " + "; ".join(parts))
        if unverified:
            lines += ["", f"### Не проверено: {len(unverified)}",
                      "В результате нет разметки страниц: LlamaParse и GLM-OCR её не дают, "
                      "Gemini мог не выполнить инструкцию, либо .md сделан прошлой версией "
                      "или взят из OCR-кэша."]
            shown = unverified[:30]
            lines += [f"- `{s}`" for s in shown]
            if len(unverified) > len(shown):
                lines.append(f"- … и ещё {len(unverified) - len(shown)}")
        return lines

    def _write_quality_report(self, assessments, out_root, crosscheck=None):
        """Пишет report.md (для человека) и report.json (для машины).
        Возвращает счётчики уровней для итоговой сводки."""
        red = sorted((a for a in assessments if a[2] == "сомнительно"), key=lambda a: a[0])
        yel = sorted((a for a in assessments if a[2] == "проверить"), key=lambda a: a[0])
        grn = [a for a in assessments if a[2] == "надёжно"]
        lines = [
            "# Отчёт о достоверности распознавания", "",
            f"Всего: {len(assessments)} · надёжно {len(grn)} · "
            f"проверить {len(yel)} · сомнительно {len(red)}", "",
            "Оценка эвристическая: ловит явный мусор (пусто, метки [неразборчиво], "
            "искажённые слова), но НЕ «гладко выглядящую ошибку». "
            "Помеченное ниже стоит сверить с оригиналом.",
        ]
        if red:
            lines += ["", "## Сомнительно — проверьте по оригиналу"]
            for src, route, _, reasons in red:
                why = "; ".join(reasons) if reasons else "высокий шум"
                lines.append(f"- `{src}` — {why}")
        if yel:
            lines += ["", "## Стоит глянуть"]
            for src, route, _, reasons in yel:
                why = "; ".join(reasons) if reasons else "умеренный шум"
                lines.append(f"- `{src}` — {why}")
        if not red and not yel:
            lines += ["", "Подозрительных страниц не найдено."]
        lines += self._page_report_lines()

        if crosscheck and crosscheck.get("details"):
            disagree = [d for d in crosscheck["details"] if d[2] == "расходятся"]
            agree = [d for d in crosscheck["details"] if d[2] == "согласны"]
            lines += [
                "", f"## Сверка двух движков (второй: {crosscheck['service']})",
                f"Сверено {crosscheck['checked']}: согласны {len(agree)}, расходятся {len(disagree)}.",
                "Сверка показывает РАСХОЖДЕНИЕ, а не правоту. Где модели не сошлись — "
                "откройте diff и сверьте с оригиналом. Где сошлись — вероятно ок, но если "
                "обе ошиблись одинаково, это здесь не видно.",
            ]
            if disagree:
                lines += ["", "### Расходятся — откройте diff"]
                for src, sim, _, dname in sorted(disagree, key=lambda d: d[1]):
                    link = f" → report_diffs/{dname}" if dname else ""
                    lines.append(f"- `{src}` — сходство {sim:.0%}{link}")
            if agree:
                lines += ["", f"### Согласны (вероятно ок): {len(agree)}"]
                for src, sim, _, _ in sorted(agree, key=lambda d: d[0]):
                    lines.append(f"- `{src}` — {sim:.0%}")
        try:
            (out_root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            (out_root / "report.json").write_text(json.dumps(
                [{"source": s, "route": r, "level": lv, "reasons": rs,
                  "pages": self._page_checks.get(s)}
                 for s, r, lv, rs in assessments], ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as e:
            self.log(tr("report_write_failed", e=e))
        return {"reliable": len(grn), "review": len(yel), "suspicious": len(red)}

    def _chunks(self, md_path, out_json, source):
        try:
            text = md_path.read_text(encoding="utf-8")
            chunks = chunk_markdown(text)
            records = [{"text": c["text"], "source": source, "headers": c["headers"], "chunk_index": i}
                       for i, c in enumerate(chunks)]
            out_json.parent.mkdir(parents=True, exist_ok=True)
            out_json.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            self.log(tr("chunking_error", name=md_path.name, e=e))

class IndexWorker(threading.Thread):
    def __init__(self, chunks_dir, index_dir, api_key, msg_queue, cancel_event):
        super().__init__(daemon=True)
        self.chunks_dir = Path(chunks_dir)
        self.index_dir = Path(index_dir)
        self.api_key = api_key
        self.q = msg_queue; self.cancel = cancel_event

    def log(self, t): self.q.put(("log", t))
    def progress(self, c, t): self.q.put(("progress", (c, t)))
    def status(self, t): self.q.put(("status", t))
    def done(self, s): self.q.put(("done", s))
    def error(self, t): self.q.put(("error", t))

    def run(self):
        try: self._run()
        except Exception as e: self.error(tr("index_error", e=e, tb=traceback.format_exc()))

    def _run(self):
        if requests is None: self.error(tr("no_requests")); return
        if np is None: self.error(tr("no_numpy_install")); return
        self.status(tr("collecting_chunks"))
        records = collect_chunks_from_dir(self.chunks_dir)
        if not records:
            self.error(tr("no_chunks", path=self.chunks_dir)); return
        self.log(tr("found_chunks", n=len(records)))

        # Загрузка существующего индекса (если есть) для идемпотентности
        index = VectorIndex(self.index_dir)
        existing_hashes = set()
        if index.exists():
            try:
                index.load()
                old_model = index.info.get("embedding_model")
                if old_model != GeminiEmbedder.MODEL:
                    # Векторы разных моделей несравнимы — смешивать нельзя.
                    self.log(tr("index_model_mismatch", old=old_model or "?", new=GeminiEmbedder.MODEL))
                    index = VectorIndex(self.index_dir)
                else:
                    existing_hashes = {m.get("hash", "") for m in index.meta}
                    self.log(tr("index_existing", n=len(index.meta)))
            except Exception as e:
                self.log(tr("index_load_failed", e=e))
                index = VectorIndex(self.index_dir)
                existing_hashes = set()

        # Отбираем только новые чанки
        new_records, seen_new = [], set()
        for r in records:
            h = chunk_hash(r["text"], r.get("source", ""))
            r["hash"] = h
            if h not in existing_hashes and h not in seen_new:
                seen_new.add(h)
                new_records.append(r)

        # Документ обновился → его старые чанки больше не соответствуют тексту.
        # Удаляем из индекса чанки тех источников, что есть в папке чанков, но
        # с хешами, которых там уже нет. Источники, пропавшие из папки целиком,
        # не трогаем: папку чанков могли просто сменить на другую.
        removed = 0
        if index.meta:
            current_sources = {r.get("source", "") for r in records}
            current_hashes = {r["hash"] for r in records}
            keep = [not (m.get("source", "") in current_sources and m.get("hash") not in current_hashes)
                    for m in index.meta]
            removed = keep.count(False)
            if removed:
                index.meta = [m for m, k in zip(index.meta, keep) if k]
                index.vectors = index.vectors[np.array(keep, dtype=bool)]
                self.log(tr("index_pruned", n=removed))

        if not new_records:
            if removed:
                if not self._save_index(index, GeminiEmbedder.MODEL):
                    return
            else:
                self.log(tr("index_up_to_date"))
            self.done({"total": len(records), "added": 0, "removed": removed,
                       "index_dir": str(self.index_dir)})
            return

        self.log(tr("index_new_chunks", n=len(new_records)))

        embedder = GeminiEmbedder(self.api_key)
        all_new_vectors = []
        all_new_meta = []
        batch_size = embedder.BATCH_SIZE
        total = len(new_records)
        processed = 0

        for start in range(0, total, batch_size):
            if self.cancel.is_set():
                self.log(tr("index_interrupted"))
                break
            batch = new_records[start:start + batch_size]
            texts = [r["text"][:8000] for r in batch]  # ограничим длину
            self.status(tr("embedding_status", start=start + 1, end=start + len(batch), total=total))
            try:
                vectors = embedder.embed_batch(texts, task_type="RETRIEVAL_DOCUMENT", cancel_event=self.cancel)
            except Exception as e:
                self.log(tr("batch_error", start=start, e=e))
                continue
            for r, v in zip(batch, vectors):
                all_new_meta.append({
                    "text": r["text"],
                    "source": r.get("source", ""),
                    "headers": r.get("headers", []),
                    "chunk_index": r.get("chunk_index", 0),
                    "hash": r["hash"],
                })
                all_new_vectors.append(v)
            processed += len(batch)
            self.progress(processed, total)
            time.sleep(0.5)  # вежливо к API

        if not all_new_vectors:
            self.error(tr("no_vectors"))
            return

        # Объединяем со старым индексом
        new_arr = np.array(all_new_vectors, dtype=np.float32)
        if index.vectors is not None and len(index.meta) > 0:
            index.vectors = np.vstack([index.vectors, new_arr])
            index.meta.extend(all_new_meta)
        else:
            index.vectors = new_arr
            index.meta = all_new_meta

        if not self._save_index(index, embedder.MODEL):
            return
        self.log(tr("index_saved", total=len(index.meta), added=len(all_new_meta)))
        self.done({"total": len(records), "added": len(all_new_meta), "removed": removed,
                   "index_dir": str(self.index_dir)})

    def _save_index(self, index, model):
        """Сохраняет индекс; при ошибке сообщает в GUI и возвращает False."""
        dim = int(index.vectors.shape[1]) if index.vectors is not None and index.vectors.ndim == 2 else 0
        index.info = {
            "total_chunks": len(index.meta),
            "embedding_model": model,
            "dim": dim,
            "updated_at": datetime.now().isoformat(),
        }
        try:
            index.save()
        except Exception as e:
            self.error(tr("index_save_failed", e=e))
            return False
        return True

class SearchWorker(threading.Thread):
    def __init__(self, question, index_dir, embed_api_key, provider, provider_cfg, top_k, msg_queue, cancel_event):
        super().__init__(daemon=True)
        self.question = question
        self.index_dir = Path(index_dir)
        self.embed_api_key = embed_api_key
        self.provider = provider
        self.provider_cfg = provider_cfg
        self.top_k = top_k
        self.q = msg_queue; self.cancel = cancel_event

    def log(self, t): self.q.put(("log", t))
    def status(self, t): self.q.put(("status", t))
    def answer(self, text, sources): self.q.put(("answer", (text, sources)))
    def error(self, t): self.q.put(("error", t))

    def run(self):
        try: self._run()
        except Exception as e: self.error(tr("search_error", e=e, tb=traceback.format_exc()))

    def _run(self):
        if requests is None: self.error(tr("no_requests")); return
        if np is None: self.error(tr("no_numpy")); return
        index = VectorIndex(self.index_dir)
        if not index.exists():
            self.error(tr("index_not_found")); return
        try:
            index.load()
        except Exception as e:
            self.error(tr("index_load_error", e=e)); return
        if index.info.get("embedding_model") != GeminiEmbedder.MODEL:
            self.error(tr("index_outdated", old=index.info.get("embedding_model") or "?")); return
        self.log(tr("index_size", n=len(index.meta)))

        # Эмбеддинг запроса
        self.status(tr("embedding_query"))
        embedder = GeminiEmbedder(self.embed_api_key)
        try:
            q_vec = embedder.embed_query(self.question, cancel_event=self.cancel)
        except Exception as e:
            self.error(tr("embed_query_error", e=e)); return

        # Поиск
        self.status(tr("searching"))
        results = index.search(q_vec, top_k=self.top_k)
        if not results:
            self.error(tr("nothing_found")); return
        self.log(tr("top_found", n=len(results)))
        for meta, score in results:
            self.log(f"  [{score:.3f}] {meta.get('source', '?')}: {meta.get('text', '')[:80]}...")

        # Генерация ответа
        self.status(tr("generating", provider=self.provider))
        try:
            if self.provider == "gemini":
                answerer = GeminiAnswerer(self.provider_cfg.get("api_key", ""))
            elif self.provider == "ollama":
                answerer = OllamaAnswerer(
                    model=self.provider_cfg.get("model", "llama3.2"),
                    url=self.provider_cfg.get("url"),
                )
            else:
                self.error(tr("unknown_provider", provider=self.provider)); return
            answer_text = answerer.answer(self.question, results, cancel_event=self.cancel)
        except Exception as e:
            self.error(tr("answer_error", e=e)); return

        sources = []
        seen = set()
        for meta, score in results:
            src = meta.get("source", "")
            if src not in seen:
                sources.append({"source": src, "score": float(score), "snippet": meta.get("text", "")[:200]})
                seen.add(src)
        self.answer(answer_text, sources)


# ============================================================
# GUI
# ============================================================
