"""Общие константы: имя приложения, путь к конфигу с API-ключами, поддерживаемые расширения файлов, имена файлов индекса."""

import os
from pathlib import Path

APP_NAME = "pdf2md"

CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME

CONFIG_FILE = CONFIG_DIR / "config.json"

JUNK_NAMES = {"__MACOSX", ".DS_Store", "Thumbs.db", "desktop.ini"}

JUNK_PREFIXES = ("~$", "._")

MAX_CHARS = 1200

OVERLAP_CHARS = 150

# Изображения, которые умеют распознавать ВСЕ три бэкенда (LlamaParse,
# Gemini, Mistral OCR) без дополнительных зависимостей. Намеренно держим
# только универсально поддерживаемый набор: иначе файл может молча пройти
# на одном сервисе и упасть на другом. bmp/tiff/gif сюда не входят — их
# нужно сначала пересохранить в png/jpeg.

IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

IMAGE_EXTENSIONS = set(IMAGE_MIME)

# TIFF (часто многостраничный — стандарт сканеров и электронных архивов)
# не все OCR-сервисы принимают, поэтому перед OCR он конвертируется в PDF.
TIFF_EXTENSIONS = {".tif", ".tiff"}

# Архивы: ZIP распаковывается встроенно, RAR и 7z — через 7-Zip / bsdtar (см. archives.py)
ARCHIVE_EXTENSIONS = {".zip", ".rar", ".7z"}

# Текстовые/офисные форматы, которые отдаём MarkItDown (готовый текст, без OCR).
# Намеренно НЕ включаем zip (распаковывается отдельно), картинки и pdf
# (у них свои, лучшие пути), а также аудио (другой движок).

MARKITDOWN_EXTENSIONS = {
    ".docx", ".pptx", ".xlsx", ".xls",
    ".html", ".htm", ".xml", ".csv", ".json", ".txt",
    ".epub", ".msg",
}

SERVICES = ["llamaparse", "gemini", "mistral", "glm"]

SERVICE_KEY_URLS = {
    "llamaparse": "https://cloud.llamaindex.ai",
    "gemini": "https://aistudio.google.com/apikey",
    "mistral": "https://console.mistral.ai/api-keys",
    "glm": "https://z.ai/manage-apikey/apikey-list",
}

# Язык документов для OCR (коды LlamaParse). Остальные сервисы определяют язык сами.
# Не путать с языком интерфейса: английский UI не значит английские документы.

DOC_LANGUAGES = {
    "ru": "Русский",
    "en": "English",
    "uk": "Українська",
    "de": "Deutsch",
    "fr": "Français",
    "es": "Español",
}

DEFAULT_DOC_LANGUAGE = "ru"

ANSWER_PROVIDERS = ["gemini", "ollama"]

INDEX_META_FILE = "index_metadata.json"

INDEX_VEC_FILE = "index_vectors.npy"

INDEX_INFO_FILE = "index_info.json"

# В папке результатов: какой md из исходника с каким хешем сделан
MANIFEST_FILE = "_manifest.json"

# ============================================================
# UI strings (RU / EN)
# ============================================================
