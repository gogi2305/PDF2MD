"""Работа с файловой системой: фильтрация мусора, распаковка ZIP / RAR / 7z (с починкой кириллических имён в ZIP), определение типа файла, сбор документов для конвертации."""

import shutil
import zipfile
import re
import hashlib
from pathlib import Path
from .archives import extract_with_tool
from .messages import tr
from .constants import (ARCHIVE_EXTENSIONS, IMAGE_EXTENSIONS, IMAGE_MIME, JUNK_NAMES, JUNK_PREFIXES,
                        MARKITDOWN_EXTENSIONS, TIFF_EXTENSIONS)

# Тома многотомного RAR: name.part2.rar, name.part03.rar ... Распаковывается
# только первый том (7-Zip сам подхватит остальные), прочие пропускаем.
_EXTRA_RAR_VOLUME = re.compile(r"\.part0*(?:[2-9]|[1-9]\d+)\.rar$", re.IGNORECASE)

def is_junk(path: Path) -> bool:
    if path.name in JUNK_NAMES:
        return True
    if any(path.name.startswith(p) for p in JUNK_PREFIXES):
        return True
    if any(part in JUNK_NAMES for part in path.parts):
        return True
    return False

def safe_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name)

def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS

def is_markitdown_file(path: Path) -> bool:
    return path.suffix.lower() in MARKITDOWN_EXTENSIONS

def is_archive(path: Path) -> bool:
    return path.suffix.lower() in ARCHIVE_EXTENSIONS

def is_extra_volume(path: Path) -> bool:
    return bool(_EXTRA_RAR_VOLUME.search(path.name))

def document_kind(path: Path):
    """Тип документа по расширению: "pdf" / "tiff" / "image" / "doc" или None."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in TIFF_EXTENSIONS:
        return "tiff"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in MARKITDOWN_EXTENSIONS:
        return "doc"
    return None

def image_mime(path: Path) -> str:
    return IMAGE_MIME.get(path.suffix.lower(), "image/jpeg")


# ============================================================
# OCR-кэш (экономия квоты и времени)
# ============================================================
# Кэш лежит в output/_ocr_cache/. Ключ = sha256(содержимое файла) + сервис + режим.
# При повторной конвертации того же файла/страницы OCR не вызывается.

def file_content_hash(path: Path, chunk_size: int = 1 << 20) -> str:
    """SHA-256 содержимого файла (не пути)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()

def _fix_zip_name(name: str) -> str:
    """Чинит имя файла из ZIP, если оно закодировано не в UTF-8.

    ZIP-формат до 2007 года использовал CP437 как кодировку имён.
    Windows-архиваторы пишут CP866/CP1251 без флага кодировки.
    Python декодирует это как CP437 — получаются 'кракозябры'.
    Этот метод пробует несколько кодировок и выбирает читаемую.
    """
    # Если строка содержит русские буквы кириллицы — уже UTF-8 (поле имеет флаг 0x800)
    if any('\u0400' <= ch <= '\u04ff' for ch in name):
        return name

    # Преобразуем обратно в байты так, как Python их получил из ZIP
    try:
        raw = name.encode("cp437")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name

    # Пробуем популярные русские кодировки в порядке распространённости в RU-ZIP
    for enc in ("utf-8", "cp866", "cp1251"):
        try:
            decoded = raw.decode(enc)
            # Проверяем: получились ли русские буквы и разумные символы
            if any('\u0400' <= ch <= '\u04ff' for ch in decoded):
                return decoded
        except UnicodeDecodeError:
            continue
    return name

def _extract_zip(zip_path: Path, dest: Path, log_fn=None) -> None:
    """Распаковывает ZIP, попутно чиня имена файлов в кириллице (Windows-zip)."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            # Чиним имя
            fixed_name = _fix_zip_name(info.filename)
            # Нормализуем разделители: ZIP всегда использует /
            fixed_name = fixed_name.replace("\\", "/")
            # Защита от путей вверх (zip slip)
            target_path = (dest / fixed_name).resolve()
            try:
                target_path.relative_to(dest.resolve())
            except ValueError:
                if log_fn:
                    log_fn(tr("zip_suspicious", name=info.filename))
                continue
            # Каталог
            if info.is_dir() or fixed_name.endswith("/"):
                target_path.mkdir(parents=True, exist_ok=True)
                continue
            # Файл
            target_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with zf.open(info, "r") as src, open(target_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            except Exception as e:
                if log_fn:
                    log_fn(tr("zip_extract_failed", name=fixed_name, e=e))
                continue

def extract_archive_recursive(archive: Path, dest: Path, log_fn=None) -> None:
    """Распаковывает ZIP / RAR / 7z в `dest`, затем — вложенные архивы любого
    из этих типов (каждый в папку со своим именем, сам архив удаляется)."""
    if archive.suffix.lower() == ".zip":
        _extract_zip(archive, dest, log_fn)
    else:
        extract_with_tool(archive, dest, log_fn)

    for nested in list(dest.rglob("*")):
        if (not is_archive(nested) or is_junk(nested) or nested.is_symlink()
                or not nested.is_file() or is_extra_volume(nested)):
            continue
        sub_dest = _unique_dir(nested.with_suffix(""))
        sub_dest.mkdir(parents=True, exist_ok=True)
        try:
            extract_archive_recursive(nested, sub_dest, log_fn)
            nested.unlink()
        except Exception as e:
            if log_fn:
                log_fn(tr("zip_nested_failed", name=nested.name, e=e))

# Прежнее имя — для обратной совместимости
extract_zip_recursive = extract_archive_recursive

def unique_name(name: str, taken: set) -> str:
    """Возвращает `name`, а если оно занято — `name_2`, `name_3`, ...
    Сравнение без учёта регистра (Windows). Добавляет результат в `taken`."""
    candidate, n = name, 2
    while candidate.lower() in taken:
        candidate = f"{name}_{n}"; n += 1
    taken.add(candidate.lower())
    return candidate

def unique_rel(rel: str, taken: set) -> str:
    """Как unique_name, но для пути к файлу: номер ставится перед расширением
    (dir/x.pdf → dir/x_2.pdf). scan.pdf и scan.png — разные пути, не конфликт."""
    p = Path(rel)
    candidate, n = p.as_posix(), 2
    while candidate.lower() in taken:
        candidate = p.with_name(f"{p.stem}_{n}{p.suffix}").as_posix(); n += 1
    taken.add(candidate.lower())
    return candidate

def _unique_dir(base: Path) -> Path:
    """Свободная папка для распаковки: два архива с одним именем
    не должны сваливаться в одну папку и смешиваться."""
    candidate, n = base, 2
    while candidate.exists():
        candidate = base.with_name(f"{base.name}_{n}"); n += 1
    return candidate

def collect_documents(input_path: Path, work_dir: Path, log_fn) -> list:
    """Собирает документы из файла / папки / архива (ZIP, RAR, 7z), рекурсивно.

    Возвращает список кортежей (абсолютный_путь, относительный_путь, kind),
    где kind — "pdf", "tiff", "image" или "doc" (office/web/data — через MarkItDown).
    """
    docs: list = []

    def _add(item: Path, rel: str):
        kind = document_kind(item)
        if kind:
            docs.append((item, rel, kind))

    def _unpack(archive: Path, prefix: str):
        """Распаковывает архив во work_dir и добавляет его документы под `prefix`
        (sub/a.zip → sub/a/...), чтобы x.pdf из a.zip и b.rar не совпали."""
        if is_extra_volume(archive):
            log_fn(tr("archive_volume_skipped", name=archive.name))
            return
        log_fn(tr("unpacking", name=archive.name))
        extract_dir = _unique_dir(work_dir / safe_filename(archive.stem))
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            extract_archive_recursive(archive, extract_dir, log_fn)
        except Exception as e:
            log_fn(tr("unpack_error", name=archive.name, e=e))
            return
        _scan(extract_dir, prefix)

    def _scan(root: Path, prefix: str = ""):
        for item in root.rglob("*"):
            # Символическая ссылка из архива может указывать на чужой файл на диске
            if is_junk(item) or item.is_symlink() or not item.is_file():
                continue
            rel = str(item.relative_to(root))
            _add(item, f"{prefix}/{rel}" if prefix else rel)

    if input_path.is_file():
        if is_archive(input_path):
            _unpack(input_path, "")
        elif document_kind(input_path):
            _add(input_path, input_path.name)
        else:
            log_fn(tr("unsupported_file", name=input_path.name))
    elif input_path.is_dir():
        for item in input_path.rglob("*"):
            if is_junk(item) or item.is_symlink() or not item.is_file():
                continue
            rel = item.relative_to(input_path)
            if is_archive(item):
                _unpack(item, rel.with_suffix("").as_posix())
            else:
                _add(item, str(rel))

    # Совпадение относительных путей — это разные файлы (например, папка a/
    # рядом с a.zip), поэтому не выбрасываем, а переименовываем с пометкой в логе.
    result, taken = [], set()
    for abs_p, rel, kind in docs:
        rel = Path(rel).as_posix()
        new_rel = unique_rel(rel, taken)
        if new_rel != rel:
            log_fn(tr("path_collision", rel=new_rel))
        result.append((abs_p, new_rel, kind))
    return result
