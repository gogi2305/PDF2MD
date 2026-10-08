# PDF2MD — document converter and search

Desktop app (Tkinter, Windows / Linux / macOS) that turns PDFs, scans, photos and
office files into Markdown, checks the result for lost or garbled text, and lets
you ask questions about your documents with answers that cite their sources.

*Русская версия: [README.txt](README.txt)*

## What it does

1. **Converts to Markdown**
   - Scanned PDFs and images (JPG/PNG/WEBP) — via OCR: LlamaParse, Google Gemini, Mistral OCR or GLM-OCR
   - Digital PDFs — straight from the text layer (no OCR, no quota)
   - Word / Excel / PowerPoint / HTML / CSV / JSON / EPUB / Outlook `.msg` — via MarkItDown (no OCR)
2. **Checks the result** — a report of suspicious documents and a page-count check for every PDF
3. **Indexes** the Markdown chunks into a local vector index
4. **Answers questions** using only the retrieved chunks, with source citations

The interface, logs and error messages are available in English and Russian.

## Getting started

1. Install Python 3.10+ from <https://www.python.org/downloads/>
   (on Windows, tick **Add Python to PATH**).
   Office formats (Word/Excel/PPTX) need Python 3.12 or 3.13 — MarkItDown does not
   install on 3.14 yet. PDFs, scans and images work on any supported version.
2. Launch:
   - **Windows:** double-click `PDF2MD.bat`
   - **Linux:** `bash PDF2MD.sh`
   - **macOS:** `chmod +x PDF2MD.command`, then double-click it. If macOS blocks it the
     first time, right-click → Open, or run `xattr -d com.apple.quarantine PDF2MD.command`.

   If dependencies are missing, the launcher installs them (2–3 minutes).
3. A window with two tabs opens. Switch the interface language at the top.

If the GUI does not start (no tkinter): `sudo apt install python3-tk python3-venv` on
Linux, `brew install python-tk` on macOS. To diagnose the environment, run
`DIAGNOSE.bat` (Windows) or `bash DIAGNOSE.sh` (macOS/Linux).

## Convert tab

- Add files, folders or ZIP archives — several at once; PDFs and images can be mixed
- Pick a service — LlamaParse / Gemini / Mistral / GLM — and paste its API key once (it is saved)
- **Document language** — used by LlamaParse only (default: Russian); the other services
  detect the language themselves. Independent of the interface language.
- Digital PDFs are read from the text layer; scans and images go through OCR (cached)
- Photos are prepared before OCR: auto-rotation, resizing, contrast
- Optional: **cross-check** disputed documents with a second OCR engine (needs that service's key)
- **START** → Markdown in `output/markdown/`, chunks in `output/chunks/`
- Finished files are skipped; files whose source has changed are converted again

### Quality report — `output/report.md`

| Section | What it shows |
|---|---|
| Suspicious / Worth a look | Documents with signs of garbage — empty output, `[неразборчиво]` (illegible) marks, garbled words — or with lost pages |
| PDF page check | Documents where fewer pages were recognized than the source has, and which pages came out empty |
| Two-engine cross-check | Where the second OCR engine read the text differently (side-by-side diffs in `report_diffs/`) |

`report.json` has the same data in machine-readable form.

> **"Reliable" means "no obvious garbage found", not "accurate".** A misread figure or
> name that looks plausible will pass this check. Verify key details against the original.

> The report itself is currently written in Russian, regardless of the interface language.

#### How the page check works

Every page in the `.md` file starts with a hidden marker `<!-- page N -->` — invisible in
Markdown viewers and stripped from search chunks. The report compares the source's page
count with these markers and lists missing and empty pages, e.g. a scanned page pasted into
a digital PDF, or a page OCR failed to read. Such documents are flagged as suspicious right
away (and get cross-checked if that is enabled).

| Route | Page check |
|---|---|
| Digital PDF (text layer) | Reliable |
| Mistral OCR | Reliable — the API returns pages as a list |
| Gemini | Relies on the model following the instruction to emit markers |
| LlamaParse, GLM-OCR | Not verified yet |
| Images, office files | Not applicable |

## Search tab

**Step 1 — Indexing**
- Chunks folder: `output/chunks`, index folder: `output/index`
- **Build index** creates vectors with Gemini embeddings (`gemini-embedding-001`; uses the
  Gemini key from the Convert tab)
- Re-running adds new chunks and removes outdated chunks of updated documents. Documents
  whose chunk files were deleted entirely stay in the index — delete the index folder to start over.

**Step 2 — Questions**
- Answered by Gemini (cloud) or Ollama (local)
- Answers use **only** the retrieved chunks and list their sources
- The answer is in the language of the question; an answer cut off by the length limit is marked as such

Only one task runs at a time: while conversion, indexing or search is in progress, another one cannot be started.

## Where things are stored

| What | Where |
|---|---|
| API keys and settings | `%APPDATA%\pdf2md\config.json` (Windows), `~/pdf2md/config.json` (Linux/macOS) |
| Markdown | `output/markdown/` (with `<!-- page N -->` markers) |
| JSON chunks | `output/chunks/` |
| Vector index | `output/index/` |
| OCR cache | `output/_ocr_cache/` — re-processing the same file does not spend quota |
| Manifest | `output/_manifest.json` — source hashes, so a changed document is converted again |
| Report | `output/report.md`, `output/report.json`, `output/report_diffs/` |

## API keys

| Service | Get a key |
|---|---|
| Google Gemini (recommended) | <https://aistudio.google.com/apikey> |
| LlamaParse | <https://cloud.llamaindex.ai> |
| Mistral | <https://console.mistral.ai/api-keys> |
| GLM (Z.ai) | <https://z.ai/manage-apikey/apikey-list> |
| Ollama (local, no key) | <https://ollama.com> |

The Google key is sent in the `x-goog-api-key` header, never in the URL, so it does not end
up in logs. Mistral deletes uploaded PDFs from its storage after recognition.

## What's new in 1.2

The main theme: the output can no longer *look* finished when part of the text was lost or is out of date.

- **PDF page check** in the report (see above).
- **Gemini truncation is no longer accepted as a result.** If a response hits the token
  limit (`MAX_TOKENS`), the PDF piece is split in half and recognized again. If even a single
  page or image is cut off, the file is reported as an error instead of a result with a missing ending.
- **Changed documents are updated.** The manifest tracks source hashes, so changed sources are
  converted again, and re-indexing removes the outdated chunks of updated documents.
- **Files with the same name are no longer lost.** `x.pdf` inside `a.zip` and `b.zip`,
  sources `docs/` and `docs.zip`, two archives with the same name — all are processed;
  collisions are renamed (`x_2.pdf`) and logged. A source added twice is processed once.
- **Large PDFs are no longer duplicated in Gemini output** — only the oversized piece is re-split.
- **New embedding model `gemini-embedding-001`.** Google shut down `text-embedding-004`.
  An old index is rebuilt automatically on **Build index**; search refuses to run on it.
- **Chunks stay within the size limit.** Long paragraphs are split by sentences (an
  over-long sentence by words), large tables by rows with the header repeated.
  Previously a paragraph could become one 15,000-character chunk instead of 1,200.
- **Language:** logs and errors follow the interface language; answers follow the question
  language; new *Document language* setting.
- **Robustness:** the Google key moved to a header; Mistral cleans up uploads; two tasks can no
  longer run at once; launchers check that dependencies actually import instead of relying on a
  marker file, so a copied folder installs them on a clean machine.
- **Tests:** 51 instead of 12.

### Upgrading from 1.1

- Rebuild the index once with **Build index** (spends embedding requests on all chunks).
- Existing `.md` files are not re-converted: on the first run their source hashes are recorded,
  and changes are tracked from then on.
- Files from ZIPs inside a folder now keep the archive name in their path
  (`markdown/a/x.md` instead of `markdown/x.md`), so they are converted again — the OCR cache
  saves the quota. Old `.md` files at the previous paths can be deleted.
- `.md` files from the previous version and results from the OCR cache have no page markers,
  so they show as *not verified* in the page check.

## Project structure

```
app.py                  Entry point (started by the launchers)
pdf2md/
  constants.py          Paths, extensions, document languages, file names
  i18n.py               Window texts RU/EN (buttons, labels), service labels
  messages.py           Log and error texts RU/EN, language selection
  compat.py             Optional dependencies (requests/numpy)
  config_store.py       config.json (API keys, language, settings)
  fileutils.py          ZIPs/folders/junk files, file types, unique names
  ocr_cache.py          OCR cache keyed by content hash
  imaging.py            Photo preparation before OCR
  pages.py              Page markers and page-count check
  chunking.py           Markdown chunking (with splitting of long blocks)
  pdf_native.py         PDF text layer, PDF splitting, MarkItDown
  ocr_clients.py        LlamaParse / Gemini / Mistral / GLM clients
  index.py              Embeddings + vector index (numpy)
  answerers.py          Gemini / Ollama answers from chunks
  quality.py            Quality assessment + engine cross-check
  workers.py            Convert / Index / Search workers, manifest, report
  gui.py                Tkinter interface (tabs, handlers)
tests/                  51 pytest tests, no network or API keys needed
  test_pdf2md_smoke.py    smoke tests for every module
  test_fixes.py           key in header, embeddings, language, file names, Mistral
  test_robustness.py      Gemini truncation, document updates, chunks, GUI
  test_pages.py           page markers and the report's page check
```

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

The tests never call the real OCR APIs — service responses are replaced with stubs.

## Roadmap

1. Page markers for LlamaParse and GLM-OCR (needs a sample of their responses)
2. Option to cross-check *all* documents with a second engine, not only suspicious ones
3. Page numbers in answer sources (the markers are already in the `.md` files)
4. Replace the numpy index with sqlite-vec or FAISS for large collections
5. English quality report; screenshots
6. Optional local `marker` backend (`--disable_ocr`) for complex multi-column digital PDFs — no API key needed

## License

MIT — see [LICENSE](LICENSE).
