"""Работа с файловой системой: фильтрация мусора, распаковка ZIP (с починкой кириллических имён), определение типа файла, сбор документов для конвертации."""

import shutil
import zipfile
import re
import hashlib
from pathlib import Path
from .messages import tr
from .constants import IMAGE_EXTENSIONS, IMAGE_MIME, JUNK_NAMES, JUNK_PREFIXES, MARKITDOWN_EXTENSIONS

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

def extract_zip_recursive(zip_path: Path, dest: Path, log_fn=None) -> None:
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

    for nested in list(dest.rglob("*.zip")):
        if is_junk(nested):
            continue
        sub_dest = nested.with_suffix("")
        sub_dest.mkdir(exist_ok=True)
        try:
            extract_zip_recursive(nested, sub_dest, log_fn)
            nested.unlink()
        except Exception as e:
            if log_fn:
                log_fn(tr("zip_nested_failed", name=nested.name, e=e))

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
    """Собирает PDF, изображения и офисные документы из файла / папки / ZIP.

    Возвращает список кортежей (абсолютный_путь, относительный_путь, kind),
    где kind — "pdf", "image" или "doc" (office/web/data — через MarkItDown).
    """
    docs: list = []

    def _scan(root: Path, prefix: str = ""):
        """Рекурсивно добавляет PDF, картинки и офисные документы.
        `prefix` — путь архива внутри папки, чтобы x.pdf из a.zip и b.zip не совпали."""
        for item in root.rglob("*"):
            if is_junk(item) or not item.is_file():
                continue
            ext = item.suffix.lower()
            rel = str(item.relative_to(root))
            if prefix:
                rel = f"{prefix}/{rel}"
            if ext == ".pdf":
                docs.append((item, rel, "pdf"))
            elif is_image_file(item):
                docs.append((item, rel, "image"))
            elif is_markitdown_file(item):
                docs.append((item, rel, "doc"))

    if input_path.is_file():
        ext = input_path.suffix.lower()
        if ext == ".zip":
            log_fn(tr("unpacking", name=input_path.name))
            extract_dir = _unique_dir(work_dir / safe_filename(input_path.stem))
            extract_dir.mkdir(parents=True, exist_ok=True)
            extract_zip_recursive(input_path, extract_dir, log_fn)
            _scan(extract_dir)
        elif ext == ".pdf":
            docs.append((input_path, input_path.name, "pdf"))
        elif is_image_file(input_path):
            docs.append((input_path, input_path.name, "image"))
        elif is_markitdown_file(input_path):
            docs.append((input_path, input_path.name, "doc"))
        else:
            log_fn(tr("unsupported_file", name=input_path.name))
    elif input_path.is_dir():
        for item in input_path.rglob("*"):
            if is_junk(item) or not item.is_file():
                continue
            ext = item.suffix.lower()
            if ext == ".zip":
                log_fn(tr("unpacking", name=item.name))
                extract_dir = _unique_dir(work_dir / safe_filename(item.stem))
                extract_dir.mkdir(parents=True, exist_ok=True)
                try:
                    extract_zip_recursive(item, extract_dir, log_fn)
                    # sub/a.zip → файлы идут как sub/a/...
                    _scan(extract_dir, item.relative_to(input_path).with_suffix("").as_posix())
                except Exception as e:
                    log_fn(tr("unpack_error", name=item.name, e=e))
            elif ext == ".pdf":
                docs.append((item, str(item.relative_to(input_path)), "pdf"))
            elif is_image_file(item):
                docs.append((item, str(item.relative_to(input_path)), "image"))
            elif is_markitdown_file(item):
                docs.append((item, str(item.relative_to(input_path)), "doc"))

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
