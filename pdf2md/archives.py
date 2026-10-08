"""Распаковка RAR и 7z внешними инструментами (ZIP распаковывает fileutils сам).

Без новых pip-зависимостей: под свежий Python они собираются не всегда.
Порядок попыток:
  1. 7-Zip (7z / 7zz / 7za в PATH или в Program Files) — RAR и 7z, основной путь;
  2. bsdtar (tar в Windows 10+ и macOS) — RAR; 7z только если tar собран с LZMA
     (в Windows — нет, в macOS — да);
  3. py7zr, если установлен, — только 7z.
"""

import os
import shutil
import subprocess
from pathlib import Path
from .messages import tr

TOOL_TIMEOUT = 1800                                   # сек; защита от зависания на битом архиве
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # без мелькания консоли из GUI в Windows
_tar_is_bsdtar = {}


def find_7zip():
    for name in ("7z", "7zz", "7za"):
        p = shutil.which(name)
        if p:
            return p
    for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base and (Path(base) / "7-Zip" / "7z.exe").exists():
            return str(Path(base) / "7-Zip" / "7z.exe")
    return None


def find_bsdtar():
    """tar, умеющий RAR/7z, — это bsdtar (libarchive). GNU tar в Linux не умеет."""
    for name in ("bsdtar", "tar"):
        p = shutil.which(name)
        if not p:
            continue
        if p not in _tar_is_bsdtar:
            try:
                r = _run([p, "--version"], timeout=15)
                text = (r.stdout + r.stderr).lower()
                _tar_is_bsdtar[p] = "bsdtar" in text or "libarchive" in text
            except Exception:
                _tar_is_bsdtar[p] = False
        if _tar_is_bsdtar[p]:
            return p
    return None


def _run(cmd, timeout=TOOL_TIMEOUT):
    # stdin закрыт: архив с паролем не повиснет в ожидании ввода, а завершится ошибкой
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          stdin=subprocess.DEVNULL, timeout=timeout, creationflags=_NO_WINDOW)


def _tail(r) -> str:
    lines = [l.strip() for l in (r.stderr or r.stdout or "").splitlines() if l.strip()]
    return " | ".join(lines[-2:])[:200]


def _reset(dest: Path):
    """Убрать остатки неудачной попытки, чтобы следующий инструмент начал с чистой папки."""
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)


def extract_with_tool(archive: Path, dest: Path, log_fn=None) -> str:
    """Распаковывает .rar/.7z в `dest`. Возвращает имя сработавшего инструмента.
    Если не сработал ни один — RuntimeError с причинами всех попыток."""
    dest.mkdir(parents=True, exist_ok=True)
    errors = []

    seven = find_7zip()
    if seven:
        try:
            r = _run([seven, "x", "-y", "-bd", f"-o{dest}", str(archive)])
            if r.returncode == 0:
                return "7-Zip"
            if r.returncode == 1:             # 7-Zip: «предупреждение», часть файлов могла не извлечься
                if log_fn:
                    log_fn(tr("archive_warning", name=archive.name, details=_tail(r)))
                return "7-Zip"
            errors.append(f"7-Zip ({r.returncode}): {_tail(r)}")
        except subprocess.TimeoutExpired:
            errors.append("7-Zip: timeout")
        _reset(dest)

    tar = find_bsdtar()
    if tar:
        try:
            r = _run([tar, "-xf", str(archive), "-C", str(dest)])
            if r.returncode == 0:
                return "tar"
            errors.append(f"tar ({r.returncode}): {_tail(r)}")
        except subprocess.TimeoutExpired:
            errors.append("tar: timeout")
        _reset(dest)

    if archive.suffix.lower() == ".7z":
        try:
            import py7zr
            with py7zr.SevenZipFile(archive, mode="r") as z:
                z.extractall(path=dest)
            return "py7zr"
        except ImportError:
            pass
        except Exception as e:
            errors.append(f"py7zr: {e}")
            _reset(dest)

    if errors:
        raise RuntimeError(tr("archive_failed", details="; ".join(errors)))
    raise RuntimeError(tr("archive_no_tool"))
