"""Сообщения логов и ошибок (воркеры, OCR-клиенты, распаковка, индекс) на RU/EN.

Язык задаёт GUI через set_language() — при старте и при переключении языка
интерфейса. Глобальная настройка, а не параметр: сообщения рождаются глубоко
в клиентах и утилитах, протаскивать язык через каждый конструктор неудобно.
Тексты самих окон (кнопки, подписи) — в i18n.UI.
"""

MESSAGES = {
    "ru": {
        # --- ConvertWorker ---
        "critical_error": "Критическая ошибка: {e}\n{tb}",
        "no_requests_install": "requests не установлен. Запустите PDF2MD.bat для установки.",
        "collecting": "Сбор файлов...",
        "service": "Сервис: {svc}",
        "sources_count": "Источников: {n}",
        "source_missing": "  Пропускаю (не существует): {path}",
        "source": "  Источник: {path}",
        "found_counts": "    найдено: PDF {pdf}, изображений и TIFF {img}, офисных {docs}",
        "collect_error": "    ОШИБКА сбора из {path}: {e}",
        "no_docs": "В источниках не найдено ни одного поддерживаемого документа",
        "total_to_process": "Всего к обработке: {n}",
        "client_error": "Клиент: {e}",
        "name_conflict": "  Конфликт имён, сохраняю как: {name}",
        "skip_ready": "Пропуск (готов): {rel}",
        "source_changed": "Исходник изменился, переделываю: {rel}",
        "manifest_save_failed": "  Не удалось сохранить манифест результатов: {e}",
        "workers_reduced_gemini": "Снижаю потоки с {n} до 2 (бесплатный тир Gemini = 15 RPM)",
        "workers_reduced_mistral": "Снижаю потоки с {n} до 3 (бесплатный тир Mistral)",
        "launch": "Запуск: {files} файлов, {workers} потоков",
        "processing": "Обработка: {src}",
        "pillow_hint": " — Pillow не установлен, перезапустите PDF2MD.bat",
        "preprocess_skipped": "  Предобработка пропущена ({name}): {e}{hint}",
        "markitdown_missing": "{src}: office-формат требует MarkItDown, а он не установлен "
                              "(на Python 3.14 он пока недоступен — поставьте Python 3.12/3.13). "
                              "PDF, сканы и картинки работают и без него.",
        "socks_hint": " — у вас включён SOCKS-прокси/VPN, для него нужен пакет PySocks. "
                      "Обновите PDF2MD и перезапустите — он доустановится сам.",
        "item_done": "  Готово: {info}",
        "item_error": "  ОШИБКА: {info}",
        "item_cancelled": "  Отменён: {info}",
        "item_stop": "  СТОП: {info}",
        "cc_failed": "Сверка: сбой ({e})",
        "cc_nothing": "Сверка: сомнительных страниц нет — пропускаю",
        "cc_no_key": "Сверка: нет ключа второго движка ({svc}) — пропускаю",
        "cc_client_failed": "Сверка: второй движок ({svc}) не создан: {e}",
        "cc_start": "Сверка спорных вторым движком [{svc}]: {n} стр.",
        "cc_interrupted": "  Сверка прервана",
        "cc_file_missing": "  Сверка пропущена (файл недоступен): {src}",
        "cc_status": "Сверка: {src}",
        "cc_stopped": "  Сверка остановлена: {e}",
        "cc_item_error": "  Сверка {src}: {e}",
        "cc_agree": "  {src}: движки согласны ({sim:.0%})",
        "cc_disagree": "  {src}: РАСХОДЯТСЯ ({sim:.0%})",
        "cc_diff_failed": "  diff {src}: {e}",
        "report_write_failed": "  Не удалось записать отчёт достоверности: {e}",
        "chunking_error": "  Чанкинг {name}: {e}",
        # --- IndexWorker ---
        "index_error": "Индексация: {e}\n{tb}",
        "no_requests": "requests не установлен",
        "no_numpy_install": "numpy не установлен. Запустите PDF2MD.bat для переустановки зависимостей.",
        "collecting_chunks": "Собираю чанки...",
        "no_chunks": "В {path} нет JSON-чанков. Сначала сконвертируйте PDF.",
        "found_chunks": "Найдено чанков: {n}",
        "index_model_mismatch": "Индекс построен моделью {old}, нужна {new}. Пересоздаю.",
        "index_existing": "Существующий индекс: {n} чанков (буду добавлять новые)",
        "index_load_failed": "Не удалось загрузить старый индекс: {e}. Пересоздаю.",
        "index_up_to_date": "Все чанки уже в индексе, делать нечего",
        "index_pruned": "Удалено устаревших чанков обновлённых документов: {n}",
        "index_new_chunks": "Новых чанков для индексации: {n}",
        "index_interrupted": "Прерывание по запросу. Сохраняю то, что успел.",
        "embedding_status": "Эмбеддинг {start}-{end} из {total}",
        "batch_error": "Ошибка батча {start}: {e}. Пропускаю.",
        "no_vectors": "Не удалось получить ни одного вектора",
        "index_save_failed": "Не удалось сохранить индекс: {e}",
        "index_saved": "Индекс сохранён: {total} чанков всего, добавлено {added}",
        # --- SearchWorker ---
        "search_error": "Поиск: {e}\n{tb}",
        "no_numpy": "numpy не установлен",
        "index_not_found": "Индекс не найден. Нажмите «Индексировать» перед поиском.",
        "index_load_error": "Не удалось загрузить индекс: {e}",
        "index_outdated": "Индекс построен устаревшей моделью эмбеддингов ({old}). "
                          "Нажмите «Индексировать» — он пересоздастся.",
        "index_size": "Индекс: {n} чанков",
        "embedding_query": "Получаю эмбеддинг вопроса...",
        "embed_query_error": "Эмбеддинг запроса: {e}",
        "searching": "Ищу релевантные чанки...",
        "nothing_found": "Ничего не найдено в индексе",
        "top_found": "Найдено топ-{n} чанков:",
        "generating": "Генерирую ответ через {provider}...",
        "unknown_provider": "Неизвестный провайдер: {provider}",
        "answer_error": "Генерация ответа: {e}",
        # --- fileutils ---
        "zip_suspicious": "  Пропускаю подозрительный путь в архиве: {name}",
        "zip_extract_failed": "  Не удалось извлечь {name}: {e}",
        "zip_nested_failed": "  Не удалось распаковать вложенный {name}: {e}",
        "unpacking": "Распаковываю архив: {name}",
        "unsupported_file": "Неподдерживаемый файл: {name}",
        "unpack_error": "Ошибка распаковки {name}: {e}",
        "path_collision": "  Совпадение пути, сохраняю как: {rel}",
        "archive_warning": "  Архив {name} распакован с предупреждениями (часть файлов могла не извлечься): {details}",
        "archive_failed": "не удалось распаковать: {details}",
        "archive_no_tool": "для RAR и 7z нужен 7-Zip (https://www.7-zip.org) — установите его и запустите снова",
        "archive_volume_skipped": "  {name} — следующий том многотомного архива, распакуется вместе с первым",
        # --- OCR-клиенты ---
        "cancelled": "Отменено",
        "timeout": "Таймаут",
        "llama_bad_key": "Неверный API-ключ LlamaParse (401)",
        "llama_no_credits": "Закончились кредиты LlamaParse (402)",
        "llama_no_job": "Нет job_id: {text}",
        "llama_failed": "Провал: {status}",
        "network": "Сеть: {e}",
        "google_bad_key": "Неверный API-ключ Google ({code})",
        "gemini_daily_quota": "Дневная квота Gemini исчерпана (сброс в полночь по тихоокеанскому времени). "
                              "Перезапустите завтра — готовые файлы пропустятся, "
                              "либо смените сервис на Mistral/LlamaParse.",
        "gemini_empty": "Пустой ответ Gemini: {feedback}",
        "gemini_strange": "Странный ответ Gemini: {data} ({e})",
        "gemini_truncated": "Ответ Gemini оборван по лимиту токенов (MAX_TOKENS) — распознавание неполное",
        "gemini_blocked": "Gemini не завершил распознавание (finishReason={reason}) — текст неполный или отсутствует",
        "answer_truncated": "[Ответ обрезан по лимиту длины]",
        "mistral_no_file_id": "Mistral: нет file_id",
        "glm_network": "Сеть GLM-OCR: {e}",
        "glm_auth": "GLM-OCR auth {code} (проверьте ключ z.ai)",
        "glm_not_json": "GLM-OCR: ответ не JSON: {text}",
        "glm_no_markdown": "GLM-OCR: не нашёл Markdown в ответе — пришлите эту строку, поправлю парсер. "
                           "Сырой ответ: {raw}",
        "unknown_service": "Неизвестный сервис: {svc}",
        "need_pypdf": "Для больших PDF нужен pypdf или PyMuPDF.\nУстановите: pip install pypdf",
        # --- эмбеддинги и ответы ---
        "embed_network": "Сеть при эмбеддинге: {e}",
        "embed_bad_key": "Неверный API-ключ Google для эмбеддингов ({code})",
        "embed_rate_limit": "Rate limit при эмбеддингах",
        "embed_count_mismatch": "Получено {got} векторов вместо {expected}",
        "install_numpy": "Установите numpy: pip install numpy",
        "answer_rate_limit": "Rate limit при генерации ответа",
        "answer_unparsed": "[Не удалось получить ответ: {data}]",
        "ollama_unreachable": "Ollama не отвечает на {url}.\n"
                              "Установите с https://ollama.com и запустите.\n"
                              "Затем выполните в командной строке: ollama pull {model}",
        "ollama_request_failed": "Не удалось обратиться к Ollama: {e}",
        "empty_answer": "[пустой ответ]",
        # --- report.md и причины пометок ---
        "rep_title": "# Отчёт о достоверности распознавания",
        "rep_summary": "Всего: {total} · надёжно {reliable} · проверить {review} · сомнительно {suspicious}",
        "rep_disclaimer": "Оценка эвристическая: ловит явный мусор (пусто, метки [неразборчиво], "
                          "искажённые слова), но НЕ «гладко выглядящую ошибку». "
                          "Помеченное ниже стоит сверить с оригиналом.",
        "rep_suspicious": "## Сомнительно — проверьте по оригиналу",
        "rep_review": "## Стоит глянуть",
        "rep_none": "Подозрительных страниц не найдено.",
        "rep_pages_title": "## Сверка страниц PDF",
        "rep_pages_summary": "PDF: {total} · все страницы на месте {ok} · расхождения {problem} · не проверено {unverified}",
        "rep_pages_note": "Сверяется число страниц исходника с размеченными страницами результата "
                          "(метки `<!-- page N -->` в .md). Пустая страница — это, например, вклеенный "
                          "скан без текстового слоя или страница, которую OCR не распознал.",
        "rep_pages_problems": "### Расхождения — проверьте по оригиналу",
        "rep_pages_found": "распознано {found} из {total}",
        "rep_pages_missing": "нет: {pages}",
        "rep_pages_empty": "пустые: {pages}",
        "rep_pages_unverified": "### Не проверено: {n}",
        "rep_pages_unverified_note": "В результате нет разметки страниц: LlamaParse и GLM-OCR её не дают, "
                                     "Gemini мог не выполнить инструкцию, либо .md сделан прошлой версией "
                                     "или взят из OCR-кэша.",
        "rep_more": "- … и ещё {n}",
        "rep_cc_title": "## Сверка двух движков (второй: {svc})",
        "rep_cc_summary": "Сверено {checked}: согласны {agree}, расходятся {disagree}.",
        "rep_cc_note": "Сверка показывает РАСХОЖДЕНИЕ, а не правоту. Где модели не сошлись — "
                       "откройте diff и сверьте с оригиналом. Где сошлись — вероятно ок, но если "
                       "обе ошиблись одинаково, это здесь не видно.",
        "rep_cc_disagree": "### Расходятся — откройте diff",
        "rep_cc_similarity": "сходство {sim:.0%}",
        "rep_cc_agree": "### Согласны (вероятно ок): {n}",
        "q_almost_empty": "почти пусто ({n} симв.)",
        "q_garbled": "искажённых слов {share:.0%}",
        "q_illegible": "меток [неразборчиво] {share:.0%}",
        "q_replacement": "символов-замен {n}",
        "q_high_noise": "высокий шум",
        "q_moderate_noise": "умеренный шум",
        "q_missing_pages": "нет страниц: {pages}",
        "q_empty_pages": "пустые страницы: {pages}",
        "diff_engine1": "Движок 1 (основной)",
        "diff_engine2": "Движок 2 ({svc})",
        # --- сообщения GUI в логе и статусе ---
        "gui_intro_digital": "Цифровые PDF берутся из текстового слоя напрямую (без OCR), сканы и картинки — через OCR.",
        "gui_intro_office": "Word/Excel/PPTX/HTML/CSV/EPUB и т.п. конвертируются напрямую через MarkItDown (без OCR).",
        "gui_intro_embed": "Эмбеддинги берутся через Google Gemini — ключ нужен на вкладке «Конвертация».",
        "gui_filter_all_supported": "Все поддерживаемые",
        "gui_filter_archives": "Архивы (ZIP/RAR/7z)",
        "gui_filter_docs": "Документы (Word/Excel/HTML/…)",
        "gui_filter_pdf_img": "PDF и изображения",
        "gui_filter_all": "Все",
        "gui_missing_paths": "Внимание: {n} путей не существует, они будут пропущены",
        "gui_launch": "Запуск через {svc}, источников: {n}",
        "gui_ollama_ok": "Ollama доступна на {url}",
        "gui_ollama_down": "Ollama не отвечает на {url}.\n\n"
                           "Скачайте с https://ollama.com\n"
                           "После установки выполните в командной строке:\n"
                           "ollama pull {model}",
        "gui_indexing": "Индексация: {src} → {dst}",
        "gui_question": "Вопрос: {q}",
        "gui_error_log": "ОШИБКА: {msg}",
        "gui_error_status": "Ошибка",
        "gui_convert_done_status": "Готово: {processed} обработано, {skipped} пропущено, {errors} ошибок",
        "gui_convert_summary": "ИТОГ: всего {total}, обработано {processed}, пропущено {skipped}, ошибок {errors}",
        "gui_quality_summary": "Достоверность: надёжно {reliable}, проверить {review}, "
                               "сомнительно {suspicious} — подробности в report.md",
        "gui_pages_summary": "Страницы PDF: все на месте {ok}, расхождения {problem}, "
                             "не проверено {unverified} — подробности в report.md",
        "gui_cc_summary": "Сверка [{svc}]: сверено {checked}, согласны {agree}, "
                          "расходятся {disagree} — diff в report_diffs/",
        "gui_quota_status": "Остановлено: дневная квота Gemini исчерпана",
        "gui_quota_title": "PDF2MD — квота исчерпана",
        "gui_index_progress": "Индексация: {cur} / {tot}",
        "gui_index_status": "Индекс: добавлено {added} из {total}",
        "gui_index_done_log": "Индексация завершена: {summary}",
        "gui_index_done_box": "Готово! В индекс добавлено {added} чанков.\nТеперь можно задавать вопросы.",
        "gui_done": "Готово",
        "gui_busy": "Уже идёт другая задача (конвертация, индексация или поиск).\n"
                    "Дождитесь её окончания или остановите.",
        "gui_answer_received": "Ответ получен",
    },
    "en": {
        # --- ConvertWorker ---
        "critical_error": "Critical error: {e}\n{tb}",
        "no_requests_install": "requests is not installed. Run PDF2MD.bat to install it.",
        "collecting": "Collecting files...",
        "service": "Service: {svc}",
        "sources_count": "Sources: {n}",
        "source_missing": "  Skipping (does not exist): {path}",
        "source": "  Source: {path}",
        "found_counts": "    found: {pdf} PDF, {img} images/TIFF, {docs} office files",
        "collect_error": "    ERROR collecting from {path}: {e}",
        "no_docs": "No supported documents found in the sources",
        "total_to_process": "Total to process: {n}",
        "client_error": "Client: {e}",
        "name_conflict": "  Name conflict, saving as: {name}",
        "skip_ready": "Skipping (already done): {rel}",
        "source_changed": "Source changed, redoing: {rel}",
        "manifest_save_failed": "  Could not save the results manifest: {e}",
        "workers_reduced_gemini": "Reducing workers from {n} to 2 (Gemini free tier = 15 RPM)",
        "workers_reduced_mistral": "Reducing workers from {n} to 3 (Mistral free tier)",
        "launch": "Starting: {files} files, {workers} workers",
        "processing": "Processing: {src}",
        "pillow_hint": " — Pillow is not installed, restart PDF2MD.bat",
        "preprocess_skipped": "  Preprocessing skipped ({name}): {e}{hint}",
        "markitdown_missing": "{src}: office formats require MarkItDown, which is not installed "
                              "(not yet available on Python 3.14 — use Python 3.12/3.13). "
                              "PDFs, scans and images work without it.",
        "socks_hint": " — a SOCKS proxy/VPN is active and needs the PySocks package. "
                      "Update PDF2MD and restart — it will be installed automatically.",
        "item_done": "  Done: {info}",
        "item_error": "  ERROR: {info}",
        "item_cancelled": "  Cancelled: {info}",
        "item_stop": "  STOP: {info}",
        "cc_failed": "Cross-check: failed ({e})",
        "cc_nothing": "Cross-check: no suspicious pages — skipping",
        "cc_no_key": "Cross-check: no key for the second engine ({svc}) — skipping",
        "cc_client_failed": "Cross-check: could not create the second engine ({svc}): {e}",
        "cc_start": "Cross-checking disputed pages with second engine [{svc}]: {n} pages",
        "cc_interrupted": "  Cross-check interrupted",
        "cc_file_missing": "  Cross-check skipped (file unavailable): {src}",
        "cc_status": "Cross-check: {src}",
        "cc_stopped": "  Cross-check stopped: {e}",
        "cc_item_error": "  Cross-check {src}: {e}",
        "cc_agree": "  {src}: engines agree ({sim:.0%})",
        "cc_disagree": "  {src}: DISAGREE ({sim:.0%})",
        "cc_diff_failed": "  diff {src}: {e}",
        "report_write_failed": "  Could not write the quality report: {e}",
        "chunking_error": "  Chunking {name}: {e}",
        # --- IndexWorker ---
        "index_error": "Indexing: {e}\n{tb}",
        "no_requests": "requests is not installed",
        "no_numpy_install": "numpy is not installed. Run PDF2MD.bat to reinstall dependencies.",
        "collecting_chunks": "Collecting chunks...",
        "no_chunks": "No JSON chunks in {path}. Convert some PDFs first.",
        "found_chunks": "Chunks found: {n}",
        "index_model_mismatch": "Index was built with model {old}, {new} is required. Rebuilding.",
        "index_existing": "Existing index: {n} chunks (will add new ones)",
        "index_load_failed": "Could not load the old index: {e}. Rebuilding.",
        "index_up_to_date": "All chunks are already indexed, nothing to do",
        "index_pruned": "Removed outdated chunks of updated documents: {n}",
        "index_new_chunks": "New chunks to index: {n}",
        "index_interrupted": "Interrupted on request. Saving what is done so far.",
        "embedding_status": "Embedding {start}-{end} of {total}",
        "batch_error": "Batch {start} failed: {e}. Skipping.",
        "no_vectors": "Could not get a single vector",
        "index_save_failed": "Could not save the index: {e}",
        "index_saved": "Index saved: {total} chunks in total, {added} added",
        # --- SearchWorker ---
        "search_error": "Search: {e}\n{tb}",
        "no_numpy": "numpy is not installed",
        "index_not_found": "Index not found. Click Build index before searching.",
        "index_load_error": "Could not load the index: {e}",
        "index_outdated": "The index was built with an outdated embedding model ({old}). "
                          "Click Build index — it will be rebuilt.",
        "index_size": "Index: {n} chunks",
        "embedding_query": "Embedding the question...",
        "embed_query_error": "Query embedding: {e}",
        "searching": "Searching for relevant chunks...",
        "nothing_found": "Nothing found in the index",
        "top_found": "Top {n} chunks found:",
        "generating": "Generating the answer with {provider}...",
        "unknown_provider": "Unknown provider: {provider}",
        "answer_error": "Answer generation: {e}",
        # --- fileutils ---
        "zip_suspicious": "  Skipping suspicious path in archive: {name}",
        "zip_extract_failed": "  Could not extract {name}: {e}",
        "zip_nested_failed": "  Could not unpack nested archive {name}: {e}",
        "unpacking": "Unpacking archive: {name}",
        "unsupported_file": "Unsupported file: {name}",
        "unpack_error": "Error unpacking {name}: {e}",
        "path_collision": "  Path collision, saving as: {rel}",
        "archive_warning": "  Archive {name} unpacked with warnings (some files may be missing): {details}",
        "archive_failed": "could not unpack: {details}",
        "archive_no_tool": "RAR and 7z need 7-Zip (https://www.7-zip.org) — install it and run again",
        "archive_volume_skipped": "  {name} is a later volume of a multi-volume archive, unpacked with the first one",
        # --- OCR clients ---
        "cancelled": "Cancelled",
        "timeout": "Timeout",
        "llama_bad_key": "Invalid LlamaParse API key (401)",
        "llama_no_credits": "LlamaParse credits exhausted (402)",
        "llama_no_job": "No job_id: {text}",
        "llama_failed": "Failed: {status}",
        "network": "Network: {e}",
        "google_bad_key": "Invalid Google API key ({code})",
        "gemini_daily_quota": "Gemini daily quota exhausted (resets at midnight Pacific Time). "
                              "Restart tomorrow — finished files will be skipped, "
                              "or switch the service to Mistral/LlamaParse.",
        "gemini_empty": "Empty Gemini response: {feedback}",
        "gemini_strange": "Unexpected Gemini response: {data} ({e})",
        "gemini_truncated": "Gemini response was cut off by the token limit (MAX_TOKENS) — recognition is incomplete",
        "gemini_blocked": "Gemini did not finish recognition (finishReason={reason}) — text is incomplete or missing",
        "answer_truncated": "[Answer truncated by the length limit]",
        "mistral_no_file_id": "Mistral: no file_id",
        "glm_network": "GLM-OCR network: {e}",
        "glm_auth": "GLM-OCR auth {code} (check your z.ai key)",
        "glm_not_json": "GLM-OCR: response is not JSON: {text}",
        "glm_no_markdown": "GLM-OCR: no Markdown found in the response — send this line so the parser can be fixed. "
                           "Raw response: {raw}",
        "unknown_service": "Unknown service: {svc}",
        "need_pypdf": "Large PDFs require pypdf or PyMuPDF.\nInstall: pip install pypdf",
        # --- embeddings and answers ---
        "embed_network": "Network error while embedding: {e}",
        "embed_bad_key": "Invalid Google API key for embeddings ({code})",
        "embed_rate_limit": "Rate limit while embedding",
        "embed_count_mismatch": "Got {got} vectors instead of {expected}",
        "install_numpy": "Install numpy: pip install numpy",
        "answer_rate_limit": "Rate limit while generating the answer",
        "answer_unparsed": "[Could not get an answer: {data}]",
        "ollama_unreachable": "Ollama is not responding at {url}.\n"
                              "Install it from https://ollama.com and start it.\n"
                              "Then run in a terminal: ollama pull {model}",
        "ollama_request_failed": "Could not reach Ollama: {e}",
        "empty_answer": "[empty answer]",
        # --- report.md and reasons ---
        "rep_title": "# OCR reliability report",
        "rep_summary": "Total: {total} · reliable {reliable} · review {review} · suspicious {suspicious}",
        "rep_disclaimer": "The assessment is heuristic: it catches obvious garbage (empty output, "
                          "[неразборчиво] (illegible) marks, garbled words), but NOT a plausible-looking "
                          "misreading. Check the documents listed below against the originals.",
        "rep_suspicious": "## Suspicious — check against the original",
        "rep_review": "## Worth a look",
        "rep_none": "No suspicious documents found.",
        "rep_pages_title": "## PDF page check",
        "rep_pages_summary": "PDFs: {total} · all pages present {ok} · mismatches {problem} · not verified {unverified}",
        "rep_pages_note": "The source's page count is compared with the marked pages of the result "
                          "(`<!-- page N -->` markers in the .md). An empty page is, for example, a scan "
                          "pasted into a digital PDF without a text layer, or a page OCR failed to read.",
        "rep_pages_problems": "### Mismatches — check against the original",
        "rep_pages_found": "{found} of {total} recognized",
        "rep_pages_missing": "missing: {pages}",
        "rep_pages_empty": "empty: {pages}",
        "rep_pages_unverified": "### Not verified: {n}",
        "rep_pages_unverified_note": "The result has no page markers: LlamaParse and GLM-OCR do not provide them, "
                                     "Gemini may have ignored the instruction, or the .md comes from a previous "
                                     "version or the OCR cache.",
        "rep_more": "- … and {n} more",
        "rep_cc_title": "## Two-engine cross-check (second engine: {svc})",
        "rep_cc_summary": "Checked {checked}: agree {agree}, disagree {disagree}.",
        "rep_cc_note": "The cross-check shows DISAGREEMENT, not which engine is right. Where they disagree, "
                       "open the diff and compare with the original. Where they agree it is probably fine, "
                       "but if both made the same mistake, it does not show here.",
        "rep_cc_disagree": "### Disagree — open the diff",
        "rep_cc_similarity": "similarity {sim:.0%}",
        "rep_cc_agree": "### Agree (probably fine): {n}",
        "q_almost_empty": "almost empty ({n} chars)",
        "q_garbled": "garbled words {share:.0%}",
        "q_illegible": "[неразборчиво] (illegible) marks {share:.0%}",
        "q_replacement": "replacement characters {n}",
        "q_high_noise": "high noise",
        "q_moderate_noise": "moderate noise",
        "q_missing_pages": "missing pages: {pages}",
        "q_empty_pages": "empty pages: {pages}",
        "diff_engine1": "Engine 1 (primary)",
        "diff_engine2": "Engine 2 ({svc})",
        # --- GUI log and status messages ---
        "gui_intro_digital": "Digital PDFs are read from the text layer directly (no OCR); scans and images go through OCR.",
        "gui_intro_office": "Word/Excel/PPTX/HTML/CSV/EPUB etc. are converted directly via MarkItDown (no OCR).",
        "gui_intro_embed": "Embeddings use Google Gemini — the key is set on the Convert tab.",
        "gui_filter_all_supported": "All supported",
        "gui_filter_archives": "Archives (ZIP/RAR/7z)",
        "gui_filter_docs": "Documents (Word/Excel/HTML/…)",
        "gui_filter_pdf_img": "PDF and images",
        "gui_filter_all": "All",
        "gui_missing_paths": "Warning: {n} paths do not exist and will be skipped",
        "gui_launch": "Starting with {svc}, sources: {n}",
        "gui_ollama_ok": "Ollama is available at {url}",
        "gui_ollama_down": "Ollama is not responding at {url}.\n\n"
                           "Download it from https://ollama.com\n"
                           "After installing, run in a terminal:\n"
                           "ollama pull {model}",
        "gui_indexing": "Indexing: {src} → {dst}",
        "gui_question": "Question: {q}",
        "gui_error_log": "ERROR: {msg}",
        "gui_error_status": "Error",
        "gui_convert_done_status": "Done: {processed} processed, {skipped} skipped, {errors} errors",
        "gui_convert_summary": "SUMMARY: total {total}, processed {processed}, skipped {skipped}, errors {errors}",
        "gui_quality_summary": "Reliability: reliable {reliable}, review {review}, "
                               "suspicious {suspicious} — details in report.md",
        "gui_pages_summary": "PDF pages: complete {ok}, mismatches {problem}, "
                             "unverified {unverified} — details in report.md",
        "gui_cc_summary": "Cross-check [{svc}]: checked {checked}, agree {agree}, "
                          "disagree {disagree} — diffs in report_diffs/",
        "gui_quota_status": "Stopped: Gemini daily quota exhausted",
        "gui_quota_title": "PDF2MD — quota exhausted",
        "gui_index_progress": "Indexing: {cur} / {tot}",
        "gui_index_status": "Index: {added} of {total} added",
        "gui_index_done_log": "Indexing finished: {summary}",
        "gui_index_done_box": "Done! {added} chunks added to the index.\nYou can ask questions now.",
        "gui_done": "Done",
        "gui_busy": "Another task is already running (conversion, indexing or search).\n"
                    "Wait for it to finish or stop it.",
        "gui_answer_received": "Answer received",
    },
}

# Маршруты обработки хранятся по-русски (их пишет report.json), в лог — переводим.
ROUTE_LABELS = {
    "en": {
        "готов": "already done",
        "кэш OCR": "OCR cache",
        "OCR+подготовка": "OCR+preprocessing",
        "текст(office)": "text (office)",
        "текст": "text layer",
        "кэш OCR (слой пуст)": "OCR cache (empty text layer)",
        "OCR (слой пуст)": "OCR (empty text layer)",
    },
}

_lang = "ru"


def set_language(lang: str) -> None:
    """Задать язык сообщений ("ru"/"en"). Неизвестный язык → русский."""
    global _lang
    _lang = lang if lang in MESSAGES else "ru"


def get_language() -> str:
    return _lang


def tr(key: str, **kwargs) -> str:
    """Текст сообщения на текущем языке; нет перевода — русский, нет ключа — сам ключ."""
    s = MESSAGES[_lang].get(key) or MESSAGES["ru"].get(key) or key
    return s.format(**kwargs) if kwargs else s


def route_label(route: str) -> str:
    """Название маршрута обработки для лога на текущем языке."""
    return ROUTE_LABELS.get(_lang, {}).get(route, route)
