"""Сборка Windows-версии в один файл dist/PDF2MD.exe (PyInstaller).

    pip install -r requirements.txt -r requirements-optional.txt pyinstaller
    python build_exe.py [папка_сборки]

По умолчанию сборка идёт в build/ и dist/ рядом со скриптом. Если проект
лежит в OneDrive/Dropbox, укажите папку вне них — иначе облако начнёт
синхронизировать тысячи промежуточных файлов. После сборки запускает самопроверку собранного .exe (--selftest): если в
сборку не попал PyMuPDF, MarkItDown или Tkinter, скрипт завершится ошибкой.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent

ARGS = [
    str(ROOT / "app.py"),
    "--name", "PDF2MD",
    "--onefile",
    "--windowed",                      # без консольного окна
    "--noconfirm", "--clean",
    # PyMuPDF и pymupdf4llm: данные и подмодули, которые не находятся автоматически
    "--collect-all", "pymupdf4llm",
    "--collect-all", "pymupdf",
    # MarkItDown (офисные форматы) и его модель определения типа файла
    "--collect-all", "markitdown",
    "--collect-data", "magika",
    "--hidden-import", "socks",        # PySocks — для работы через SOCKS-прокси/VPN
    # Тяжёлое и ненужное в рантайме
    "--exclude-module", "pytest",
    "--exclude-module", "matplotlib",
]


def main() -> int:
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT
    paths = ["--distpath", str(out / "dist"), "--workpath", str(out / "build"), "--specpath", str(out)]
    subprocess.run([sys.executable, "-m", "PyInstaller", *ARGS, *paths], cwd=ROOT, check=True)
    exe = out / "dist" / ("PDF2MD.exe" if sys.platform == "win32" else "PDF2MD")
    report = Path(tempfile.gettempdir()) / "pdf2md_selftest.json"
    report.unlink(missing_ok=True)
    rc = subprocess.run([str(exe), "--selftest", str(report)], timeout=300).returncode
    result = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {"ok": False}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    size_mb = exe.stat().st_size / 1024 / 1024
    print(f"{exe} — {size_mb:.0f} МБ, самопроверка: {'OK' if rc == 0 and result.get('ok') else 'ОШИБКА'}")
    return 0 if rc == 0 and result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
