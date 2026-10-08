"""
PDF2MD — конвертер PDF в Markdown + RAG-поиск по документам.

Вкладка 1 «Конвертация»:
  PDF / изображения (JPG, PNG, WEBP) / ZIP / папка → Markdown + JSON-чанки
  через LlamaParse / Gemini / Mistral / GLM-OCR.
  Цифровые PDF — из текстового слоя (без OCR). Office — через MarkItDown.
  OCR-результаты кэшируются (output/_ocr_cache/) — повтор не тратит квоту.

Вкладка 2 «Поиск»:
  1. Индексация чанков через эмбеддинги Gemini (gemini-embedding-001).
  2. Поиск top-k чанков по запросу.
  3. Ответ через Gemini API или локальную Ollama, со ссылками на источники.

Все коммуникации — через HTTP REST, никаких SDK с pydantic, чтобы код
оставался стабильным на любом Python 3.10+, включая 3.14.

Это тонкая точка входа: вся логика разложена по модулям в pdf2md/
(clients, chunking, index, workers, gui — см. README.txt).
"""

from pdf2md.gui import main

if __name__ == "__main__":
    main()
