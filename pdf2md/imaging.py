"""Подготовка фото/сканов перед OCR: авто-поворот по EXIF, ресайз, лёгкий автоконтраст."""

import uuid
from pathlib import Path

def tiff_to_pdf(src: Path, dest_dir: Path) -> Path:
    """Конвертирует TIFF (в т.ч. многостраничный) в PDF — одна страница на кадр.

    PDF принимают все OCR-сервисы, а TIFF — не все. Дальше файл идёт как
    скан-PDF: OCR, деление на куски, сверка числа страниц. Изображение
    встраивается без пересжатия качества (PyMuPDF), запасной путь — Pillow.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{uuid.uuid4().hex}.pdf"
    try:
        import fitz
        with fitz.open(str(src)) as doc:
            out.write_bytes(doc.convert_to_pdf())
        return out
    except ImportError:
        pass
    from PIL import Image, ImageSequence
    with Image.open(src) as img:
        frames = [f.convert("RGB") if f.mode not in ("1", "L", "RGB") else f.copy()
                  for f in ImageSequence.Iterator(img)]
    frames[0].save(out, format="PDF", save_all=True, append_images=frames[1:], resolution=300)
    return out

def preprocess_image_for_ocr(src: Path, dest_dir: Path, max_edge: int = 2000) -> Path:
    """Лёгкая подготовка фото/скана под VLM-OCR.

    Делаем только то, что современным OCR-моделям помогает и ничего не теряет:
    авто-ориентация по EXIF, разумный размер (телефонные 4000px → 2000px),
    мягкий автоконтраст. Цвет СОХРАНЯЕМ — печати/подписи/правки часто цветные.
    НЕ бинаризуем и НЕ правим перекос: VLM-OCR это вредит, а кроп может срезать
    содержимое. Возвращает путь к подготовленному .jpg во временной папке.
    """
    from PIL import Image, ImageOps, ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True   # пережить обрезанный/битый JPEG
    Image.MAX_IMAGE_PIXELS = None            # не падать на огромных сканах (это свои документы)
    img = Image.open(src)
    img.load()                               # форсируем декод здесь, чтобы поймать битость
    try:
        img = ImageOps.exif_transpose(img)   # развернуть по EXIF-ориентации
    except Exception:
        pass                                 # кривой EXIF — не повод падать
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > max_edge:                      # ужать гигантские фото
        s = max_edge / max(w, h)
        img = img.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
    img = ImageOps.autocontrast(img, cutoff=1)    # мягко вытянуть бледные сканы
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{uuid.uuid4().hex}.jpg"
    img.save(out, format="JPEG", quality=90)
    return out
