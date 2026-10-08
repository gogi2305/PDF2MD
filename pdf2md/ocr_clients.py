"""HTTP-клиенты OCR-сервисов (LlamaParse, Gemini, Mistral, GLM) — без SDK, на чистом requests, чтобы код был стабилен на любом Python 3.10+, включая 3.14."""

from .compat import requests
import json
import time
import base64
import threading
import re
from .fileutils import image_mime
from .messages import tr
from .pages import page_marker, shift_page_markers
from .pdf_native import pdf_page_count, split_pdf_to_chunks

class QuotaExhaustedError(RuntimeError):
    """Дневная квота API исчерпана — повторять сегодня бессмысленно.
    Сигнал воркеру остановить всю пачку, а не перебирать файлы впустую."""
    pass

class GeminiTruncatedError(RuntimeError):
    """Gemini оборвал ответ по лимиту токенов (finishReason=MAX_TOKENS).
    Для PDF — сигнал поделить кусок на меньшие и повторить."""
    pass

def _parse_gemini_retry_delay(text: str):
    """Достаёт retryDelay (секунды) из тела 429-ответа Gemini, если он есть."""
    m = re.search(r'"retryDelay"\s*:\s*"(\d+)(?:\.\d+)?s"', text or "")
    return int(m.group(1)) if m else None

def _is_gemini_daily_quota(text: str) -> bool:
    """True, если 429 — это суточный лимит (PerDay), а не минутный."""
    return "PerDay" in (text or "")

class LlamaParseClient:
    LLAMA_API_BASE = "https://api.cloud.llamaindex.ai/api/v1/parsing"
    POLL_INTERVAL = 3
    POLL_TIMEOUT = 600

    def __init__(self, api_key, language="ru", scan_mode=True):
        self.api_key = api_key
        self.language = language
        self.parse_mode = "parse_page_with_agent" if scan_mode else "parse_page_with_lvm"
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    def parse_pdf(self, pdf_path, cancel_event=None):
        return self._parse_file(pdf_path, "application/pdf", cancel_event)

    def parse_image(self, image_path, cancel_event=None):
        return self._parse_file(image_path, image_mime(image_path), cancel_event)

    def _parse_file(self, file_path, mime, cancel_event=None):
        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, mime)}
            data = {"language": self.language, "parse_mode": self.parse_mode, "result_type": "markdown"}
            resp = self.session.post(f"{self.LLAMA_API_BASE}/upload", files=files, data=data, timeout=120)
        if resp.status_code == 401: raise RuntimeError(tr("llama_bad_key"))
        if resp.status_code == 402: raise RuntimeError(tr("llama_no_credits"))
        if resp.status_code == 429: raise RuntimeError("Rate limit LlamaParse (429)")
        if resp.status_code >= 400: raise RuntimeError(f"LlamaParse HTTP {resp.status_code}: {resp.text[:200]}")
        job_id = resp.json().get("id") or resp.json().get("job_id")
        if not job_id: raise RuntimeError(tr("llama_no_job", text=resp.text[:200]))
        start = time.time()
        while True:
            if cancel_event and cancel_event.is_set(): raise RuntimeError(tr("cancelled"))
            if time.time() - start > self.POLL_TIMEOUT: raise RuntimeError(tr("timeout"))
            time.sleep(self.POLL_INTERVAL)
            r = self.session.get(f"{self.LLAMA_API_BASE}/job/{job_id}", timeout=30)
            if r.status_code >= 400: raise RuntimeError(f"Status HTTP {r.status_code}")
            status = r.json().get("status", "")
            if status == "SUCCESS": break
            if status in ("ERROR", "FAILED", "CANCELLED"): raise RuntimeError(tr("llama_failed", status=status))
        r = self.session.get(f"{self.LLAMA_API_BASE}/job/{job_id}/result/markdown", timeout=60)
        if r.status_code >= 400: raise RuntimeError(f"Result HTTP {r.status_code}")
        result = r.json()
        return result.get("markdown") or result.get("result") or ""

class GeminiClient:
    BASE = "https://generativelanguage.googleapis.com/v1beta"
    MAX_INLINE_MB = 18
    PAGES_PER_CHUNK = 25
    # Глобальный rate limiter — общий для всех экземпляров класса и всех потоков.
    # Бесплатный тир Gemini = 15 запросов/мин, поэтому держим минимум 4.5 сек между вызовами.
    MIN_INTERVAL_SEC = 4.5
    _rate_lock = threading.Lock()
    _last_call_ts = 0.0

    PROMPT = (
        "Transcribe this document to clean Markdown EXACTLY as written. "
        "This is a legal/evidentiary document — literal accuracy matters more than readability.\n"
        "Rules:\n"
        "- Transcribe ALL text VERBATIM in the ORIGINAL language. Do NOT correct, paraphrase, "
        "translate, summarize, or complete anything.\n"
        "- If text is unreadable or you are unsure, write [неразборчиво]. NEVER guess names, "
        "numbers, dates, sums, or case/contract numbers.\n"
        "- Reproduce numbers, dates, names and document numbers character-for-character.\n"
        "- Use # ## ### for headers based on visual hierarchy.\n"
        "- Format tables as Markdown tables with | separators.\n"
        "- Mark non-text elements: [печать: …], [подпись], [рукописная пометка: …].\n"
        "- Keep bullet/numbered lists. Preserve **bold**/*italic* only if clearly emphasized.\n"
        "- Start EVERY page with its own line <!-- page N -->, where N is the page number "
        "in this file (1, 2, 3, ...). Emit it even for a blank page.\n"
        "- Output ONLY the Markdown content, no commentary, no code fences."
    )

    def __init__(self, api_key, language="ru", model="gemini-2.5-flash"):
        self.api_key = api_key
        self.model = model
        self.session = requests.Session()
        # Ключ — в заголовке, не в URL: URL попадает в тексты сетевых ошибок и лог.
        self.session.headers.update({"x-goog-api-key": api_key})

    @classmethod
    def _throttle(cls):
        """Гарантирует минимальный интервал между запросами через все потоки."""
        with cls._rate_lock:
            now = time.monotonic()
            wait = cls.MIN_INTERVAL_SEC - (now - cls._last_call_ts)
            if wait > 0:
                time.sleep(wait)
            cls._last_call_ts = time.monotonic()

    def _call_api(self, file_bytes, mime="application/pdf", cancel_event=None):
        b64 = base64.b64encode(file_bytes).decode("ascii")
        url = f"{self.BASE}/models/{self.model}:generateContent"
        payload = {
            "contents": [{"parts": [
                {"inline_data": {"mime_type": mime, "data": b64}},
                {"text": self.PROMPT},
            ]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 65000},
        }
        for attempt in range(6):
            if cancel_event and cancel_event.is_set(): raise RuntimeError(tr("cancelled"))
            # Глобальная пауза перед каждым запросом — защита от 15 RPM
            self._throttle()
            try:
                resp = self.session.post(url, json=payload, timeout=600)
            except requests.RequestException as e:
                if attempt == 5: raise RuntimeError(tr("network", e=e))
                time.sleep(10 + attempt * 10); continue
            if resp.status_code in (401, 403): raise RuntimeError(tr("google_bad_key", code=resp.status_code))
            if resp.status_code == 429:
                body = resp.text or ""
                # Суточный лимит — повторять сегодня бесполезно, падаем сразу.
                if _is_gemini_daily_quota(body):
                    raise QuotaExhaustedError(tr("gemini_daily_quota"))
                # Минутный лимит: слушаем retryDelay от API, иначе обычный бэкофф.
                delay = _parse_gemini_retry_delay(body)
                if delay is None:
                    delay = 30 + attempt * 30
                else:
                    delay = min(delay + 1, 90)  # подушка +1с, но не ждём вечность
                time.sleep(delay); continue
            if resp.status_code >= 500: time.sleep(15 + attempt * 15); continue
            if resp.status_code >= 400: raise RuntimeError(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")
            break
        else:
            raise RuntimeError("Rate limit Gemini")
        data = resp.json()
        try:
            candidates = data["candidates"]
            if not candidates:
                raise RuntimeError(tr("gemini_empty", feedback=data.get("promptFeedback", {})))
            cand = candidates[0]
            reason = cand.get("finishReason", "STOP")
            # MAX_TOKENS = ответ оборван на середине. Принять его — значит молча
            # потерять конец документа, поэтому это ошибка, а не результат.
            if reason == "MAX_TOKENS":
                raise GeminiTruncatedError(tr("gemini_truncated"))
            # SAFETY / RECITATION / OTHER и т.п. — текст неполный или отсутствует.
            if reason not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
                raise RuntimeError(tr("gemini_blocked", reason=reason))
            parts = cand["content"]["parts"]
            return "\n".join(p.get("text", "") for p in parts if p.get("text"))
        except (KeyError, IndexError) as e:
            raise RuntimeError(tr("gemini_strange", data=json.dumps(data)[:300], e=e))

    def parse_pdf(self, pdf_path, cancel_event=None):
        size_mb = pdf_path.stat().st_size / (1024 * 1024)
        if size_mb <= self.MAX_INLINE_MB:
            pieces = [(pdf_path.read_bytes(), 1)]
        else:
            chunks, _ = split_pdf_to_chunks(pdf_path, self.PAGES_PER_CHUNK)
            pieces = [(d, start) for d, start, _ in chunks]
        return "\n\n".join(self._parse_pdf_piece(d, first, cancel_event) for d, first in pieces)

    def _parse_pdf_piece(self, data, first_page=1, cancel_event=None):
        """Распознаёт кусок PDF, начинающийся со страницы `first_page` документа.
        Если он не влезает в лимит запроса или ответ оборвался по MAX_TOKENS —
        делит кусок пополам и распознаёт половины. Одна страница, которая
        всё равно обрывается, — ошибка файла."""
        if cancel_event and cancel_event.is_set(): raise RuntimeError(tr("cancelled"))
        pages = pdf_page_count(data)
        too_big = len(data) / (1024 * 1024) > self.MAX_INLINE_MB
        if not too_big or pages <= 1:
            try:
                # Модель нумерует страницы куска с 1 — переводим в номера документа
                return shift_page_markers(self._call_api(data, cancel_event=cancel_event), first_page - 1)
            except GeminiTruncatedError:
                if pages <= 1:
                    raise
        halves, _ = split_pdf_to_chunks(data, (pages + 1) // 2)
        return "\n\n".join(self._parse_pdf_piece(h, first_page + start - 1, cancel_event)
                           for h, start, _ in halves)

    def parse_image(self, image_path, cancel_event=None):
        # Картинку дробить нельзя: оборванный ответ (GeminiTruncatedError) — ошибка файла.
        return self._call_api(image_path.read_bytes(),
                              mime=image_mime(image_path), cancel_event=cancel_event)

class MistralOCRClient:
    BASE = "https://api.mistral.ai/v1"

    def __init__(self, api_key, language="ru"):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    def parse_pdf(self, pdf_path, cancel_event=None):
        with open(pdf_path, "rb") as f:
            files = {"file": (pdf_path.name, f, "application/pdf")}
            r = self.session.post(f"{self.BASE}/files", files=files, data={"purpose": "ocr"}, timeout=300)
        if r.status_code == 401: raise RuntimeError("Mistral 401")
        if r.status_code >= 400: raise RuntimeError(f"Mistral upload {r.status_code}: {r.text[:300]}")
        file_id = r.json().get("id")
        if not file_id: raise RuntimeError(tr("mistral_no_file_id"))
        try:
            if cancel_event and cancel_event.is_set(): raise RuntimeError(tr("cancelled"))
            r = self.session.get(f"{self.BASE}/files/{file_id}/url", timeout=60)
            if r.status_code >= 400: raise RuntimeError(f"Mistral url {r.status_code}")
            signed_url = r.json().get("url")
            return self._run_ocr({"type": "document_url", "document_url": signed_url}, cancel_event)
        finally:
            self._delete_file(file_id)

    def _delete_file(self, file_id):
        """Удаляет загруженный PDF из хранилища Mistral — иначе там копятся
        копии всех документов. Best-effort: сбой удаления не роняет OCR."""
        try:
            self.session.delete(f"{self.BASE}/files/{file_id}", timeout=30)
        except Exception:
            pass

    def parse_image(self, image_path, cancel_event=None):
        # Картинку Mistral OCR принимает прямо как base64 data-URI —
        # загрузка в /files и подписанная ссылка не нужны.
        b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        data_uri = f"data:{image_mime(image_path)};base64,{b64}"
        return self._run_ocr({"type": "image_url", "image_url": data_uri}, cancel_event)

    def _run_ocr(self, document, cancel_event=None):
        payload = {"model": "mistral-ocr-latest", "document": document}
        for attempt in range(5):
            if cancel_event and cancel_event.is_set(): raise RuntimeError(tr("cancelled"))
            r = self.session.post(f"{self.BASE}/ocr", json=payload, timeout=900)
            if r.status_code == 429: time.sleep(30 + attempt * 30); continue
            if r.status_code in (401, 403): raise RuntimeError(f"Mistral auth {r.status_code}")
            if r.status_code >= 500: time.sleep(15 + attempt * 15); continue
            if r.status_code >= 400: raise RuntimeError(f"Mistral OCR {r.status_code}: {r.text[:300]}")
            break
        else:
            raise RuntimeError("Mistral rate limit")
        pages = r.json().get("pages", [])
        # Mistral отдаёт страницы списком с index (с 0) — ставим метки для сверки.
        return "\n\n".join(
            f"{page_marker(p.get('index', i) + 1)}\n\n{(p.get('markdown') or '').strip()}".rstrip()
            for i, p in enumerate(pages))

def _glm_extract_markdown(obj):
    """Достаёт Markdown из ответа z.ai layout_parsing.

    Точную структуру ответа z.ai явно не публикует, поэтому ищем текст в
    нескольких вероятных местах (страницы, одиночное поле, конверт data,
    стиль chat-completions). Если ничего — вызывающий код залогирует сырой ответ.
    """
    def _join_pages(pages):
        return "\n\n".join(
            (p.get("markdown") or p.get("md") or p.get("text") or "")
            for p in pages if isinstance(p, dict)
        ).strip()

    candidates = [obj]
    if isinstance(obj, dict) and isinstance(obj.get("data"), (dict, list)):
        candidates.append(obj["data"])
    for c in candidates:
        if isinstance(c, dict):
            pages = c.get("pages")
            if isinstance(pages, list) and pages:
                md = _join_pages(pages)
                if md:
                    return md
            for key in ("markdown_result", "markdown", "md", "result", "content", "text"):
                v = c.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        elif isinstance(c, list) and c:
            md = _join_pages(c)
            if md:
                return md
    try:
        ch = obj["choices"][0]["message"]["content"]
        if isinstance(ch, str) and ch.strip():
            return ch.strip()
    except Exception:
        pass
    return ""

class GlmOcrClient:
    """GLM-OCR от Z.ai (Zhipu). Облачный layout_parsing, принимает data-URI.
    Зеркалит MistralOCRClient: тот же base64-путь для PDF и картинок."""
    BASE = "https://api.z.ai/api/paas/v4"
    MODEL = "glm-ocr"

    def __init__(self, api_key, language="ru"):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    def parse_pdf(self, pdf_path, cancel_event=None):
        b64 = base64.b64encode(pdf_path.read_bytes()).decode("ascii")
        return self._parse(f"data:application/pdf;base64,{b64}", cancel_event)

    def parse_image(self, image_path, cancel_event=None):
        b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return self._parse(f"data:{image_mime(image_path)};base64,{b64}", cancel_event)

    def _parse(self, file_uri, cancel_event=None):
        payload = {"model": self.MODEL, "file": file_uri}
        for attempt in range(5):
            if cancel_event and cancel_event.is_set(): raise RuntimeError(tr("cancelled"))
            try:
                r = self.session.post(f"{self.BASE}/layout_parsing", json=payload, timeout=900)
            except requests.RequestException as e:
                if attempt == 4: raise RuntimeError(tr("glm_network", e=e))
                time.sleep(10 + attempt * 10); continue
            if r.status_code == 429: time.sleep(30 + attempt * 30); continue
            if r.status_code in (401, 403): raise RuntimeError(tr("glm_auth", code=r.status_code))
            if r.status_code >= 500: time.sleep(15 + attempt * 15); continue
            if r.status_code >= 400: raise RuntimeError(f"GLM-OCR HTTP {r.status_code}: {r.text[:300]}")
            break
        else:
            raise RuntimeError("GLM-OCR rate limit")
        try:
            data = r.json()
        except Exception:
            raise RuntimeError(tr("glm_not_json", text=r.text[:200]))
        md = _glm_extract_markdown(data)
        if not md:
            raise RuntimeError(tr("glm_no_markdown", raw=json.dumps(data, ensure_ascii=False)[:400]))
        return md

def make_client(service, api_key, language, scan_mode):
    if service == "llamaparse": return LlamaParseClient(api_key, language, scan_mode)
    if service == "gemini": return GeminiClient(api_key, language)
    if service == "mistral": return MistralOCRClient(api_key, language)
    if service == "glm": return GlmOcrClient(api_key, language)
    raise ValueError(tr("unknown_service", svc=service))


# ============================================================
# Чанкинг Markdown
# ============================================================
