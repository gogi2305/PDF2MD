"""Провайдеры ответов по найденным чанкам: облачный Gemini и локальная Ollama."""

from .compat import requests
from .messages import tr
import json
import time

def build_answer_prompt(question, context_chunks):
    """Общий промпт для Gemini и Ollama.

    Нейтральный (английский) каркас + явное «отвечай на языке вопроса» в самом
    конце: иначе русский промпт тянет модель отвечать по-русски на любой вопрос,
    а инструкция в конце лучше слушается малыми локальными моделями.
    """
    context_text = "\n\n---\n\n".join(
        f"[Source: {c.get('source', 'unknown')}]\n{c.get('text', '')}"
        for c, _ in context_chunks
    )
    return (
        "Answer the question STRICTLY based on the documents below. "
        "If the answer is not in the documents, say so honestly. "
        "Do not invent anything and do not add general knowledge. "
        "At the end, list the sources (file names) you relied on.\n\n"
        f"=== DOCUMENTS ===\n{context_text}\n\n"
        f"=== QUESTION ===\n{question}\n\n"
        "Answer concisely, in the SAME LANGUAGE as the question."
    )

class GeminiAnswerer:
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, api_key, model="gemini-2.5-flash"):
        self.api_key = api_key
        self.model = model
        self.session = requests.Session()
        # Ключ — в заголовке, не в URL: URL попадает в тексты сетевых ошибок и лог.
        self.session.headers.update({"x-goog-api-key": api_key})

    def answer(self, question, context_chunks, cancel_event=None):
        prompt = build_answer_prompt(question, context_chunks)
        url = f"{self.BASE}/models/{self.model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4000},
        }
        for attempt in range(5):
            if cancel_event and cancel_event.is_set(): raise RuntimeError(tr("cancelled"))
            r = self.session.post(url, json=payload, timeout=180)
            if r.status_code in (401, 403):
                raise RuntimeError(tr("google_bad_key", code=r.status_code))
            if r.status_code == 429:
                time.sleep(20 + attempt * 20); continue
            if r.status_code >= 500:
                time.sleep(10 + attempt * 10); continue
            if r.status_code >= 400:
                raise RuntimeError(f"Gemini answer HTTP {r.status_code}: {r.text[:300]}")
            break
        else:
            raise RuntimeError(tr("answer_rate_limit"))
        data = r.json()
        try:
            cand = data["candidates"][0]
            text = cand["content"]["parts"][0]["text"]
            if cand.get("finishReason") == "MAX_TOKENS":
                text += "\n\n" + tr("answer_truncated")
            return text
        except (KeyError, IndexError):
            return tr("answer_unparsed", data=json.dumps(data)[:200])

class OllamaAnswerer:
    DEFAULT_URL = "http://localhost:11434"

    def __init__(self, model="llama3.2", url=None):
        self.model = model or "llama3.2"
        self.url = (url or self.DEFAULT_URL).rstrip("/")
        self.session = requests.Session()

    def check(self):
        try:
            r = self.session.get(f"{self.url}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def answer(self, question, context_chunks, cancel_event=None):
        if not self.check():
            raise RuntimeError(tr("ollama_unreachable", url=self.url, model=self.model))
        prompt = build_answer_prompt(question, context_chunks)
        payload = {"model": self.model, "prompt": prompt, "stream": False, "options": {"temperature": 0.2}}
        try:
            r = self.session.post(f"{self.url}/api/generate", json=payload, timeout=300)
        except requests.RequestException as e:
            raise RuntimeError(tr("ollama_request_failed", e=e))
        if r.status_code >= 400:
            raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        return data.get("response", tr("empty_answer"))


# ============================================================
# Оценка достоверности OCR (грубый триаж, без обращений к API)
# ============================================================

# Пороги — это триажная эвристика (важнее поймать плохое, чем не задеть хорошее),
# а не истина в последней инстанции. Меняются здесь.
