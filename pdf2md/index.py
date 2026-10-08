"""Эмбеддинги Gemini и простой векторный индекс на numpy (косинусная близость)."""

from .compat import requests, np
import json
import time
from pathlib import Path
from .messages import tr
from .constants import INDEX_INFO_FILE, INDEX_META_FILE, INDEX_VEC_FILE

class GeminiEmbedder:
    """Эмбеддинги через Gemini gemini-embedding-001 (бесплатный тир).
    text-embedding-004 Google вывел из эксплуатации — индексы на нём нужно пересоздать."""
    BASE = "https://generativelanguage.googleapis.com/v1beta"
    MODEL = "gemini-embedding-001"
    BATCH_SIZE = 100  # лимит Gemini batch endpoint
    DIM = 768  # модель отдаёт 3072, урезаем через outputDimensionality — индекс в 4 раза меньше

    def __init__(self, api_key):
        self.api_key = api_key
        self.session = requests.Session()
        # Ключ — в заголовке, не в URL: URL попадает в тексты сетевых ошибок и лог.
        self.session.headers.update({"x-goog-api-key": api_key})

    def embed_batch(self, texts, task_type="RETRIEVAL_DOCUMENT", cancel_event=None):
        if not texts:
            return []
        url = f"{self.BASE}/models/{self.MODEL}:batchEmbedContents"
        payload = {
            "requests": [
                {
                    "model": f"models/{self.MODEL}",
                    "content": {"parts": [{"text": t}]},
                    "taskType": task_type,
                    "outputDimensionality": self.DIM,
                }
                for t in texts
            ]
        }
        for attempt in range(6):
            if cancel_event and cancel_event.is_set():
                raise RuntimeError(tr("cancelled"))
            try:
                r = self.session.post(url, json=payload, timeout=120)
            except requests.RequestException as e:
                if attempt == 5:
                    raise RuntimeError(tr("embed_network", e=e))
                time.sleep(5 + attempt * 5); continue
            if r.status_code in (401, 403):
                raise RuntimeError(tr("embed_bad_key", code=r.status_code))
            if r.status_code == 429:
                time.sleep(30 + attempt * 30); continue
            if r.status_code >= 500:
                time.sleep(10 + attempt * 10); continue
            if r.status_code >= 400:
                raise RuntimeError(f"Embeddings HTTP {r.status_code}: {r.text[:300]}")
            break
        else:
            raise RuntimeError(tr("embed_rate_limit"))
        data = r.json()
        result = []
        for emb in data.get("embeddings", []):
            values = emb.get("values", [])
            result.append(values)
        if len(result) != len(texts):
            raise RuntimeError(tr("embed_count_mismatch", got=len(result), expected=len(texts)))
        return result

    def embed_query(self, query, cancel_event=None):
        return self.embed_batch([query], task_type="RETRIEVAL_QUERY", cancel_event=cancel_event)[0]

class VectorIndex:
    """Простой векторный индекс: numpy массив + JSON метаданные."""

    def __init__(self, index_dir):
        self.dir = Path(index_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta = []
        self.vectors = None
        self.info = {}

    def exists(self):
        return (self.dir / INDEX_VEC_FILE).exists() and (self.dir / INDEX_META_FILE).exists()

    def load(self):
        if not self.exists():
            return False
        if np is None:
            raise RuntimeError(tr("install_numpy"))
        self.vectors = np.load(self.dir / INDEX_VEC_FILE)
        self.meta = json.loads((self.dir / INDEX_META_FILE).read_text(encoding="utf-8"))
        try:
            self.info = json.loads((self.dir / INDEX_INFO_FILE).read_text(encoding="utf-8"))
        except Exception:
            self.info = {}
        return True

    def save(self):
        if np is None:
            raise RuntimeError(tr("install_numpy"))
        np.save(self.dir / INDEX_VEC_FILE, self.vectors)
        (self.dir / INDEX_META_FILE).write_text(
            json.dumps(self.meta, ensure_ascii=False), encoding="utf-8"
        )
        (self.dir / INDEX_INFO_FILE).write_text(
            json.dumps(self.info, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def search(self, query_vector, top_k=5):
        if self.vectors is None or len(self.meta) == 0:
            return []
        q = np.asarray(query_vector, dtype=np.float32)
        # Нормализация
        q_norm = np.linalg.norm(q)
        if q_norm == 0:
            return []
        q = q / q_norm
        # Нормализуем векторы базы, если ещё не нормализованы
        norms = np.linalg.norm(self.vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normed = self.vectors / norms
        sims = normed @ q
        top_k = min(top_k, len(sims))
        top_idx = np.argpartition(-sims, top_k - 1)[:top_k]
        top_idx = top_idx[np.argsort(-sims[top_idx])]
        return [(self.meta[i], float(sims[i])) for i in top_idx]

def collect_chunks_from_dir(chunks_dir):
    """Собирает все JSON-чанки из директории."""
    chunks_dir = Path(chunks_dir)
    if not chunks_dir.exists():
        return []
    records = []
    for jp in sorted(chunks_dir.rglob("*.json")):
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
            for rec in data:
                if not isinstance(rec, dict) or "text" not in rec:
                    continue
                rec.setdefault("source", str(jp.stem))
                records.append(rec)
        except Exception:
            continue
    return records


# ============================================================
# LLM для ответов
# ============================================================
