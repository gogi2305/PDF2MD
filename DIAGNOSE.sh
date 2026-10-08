#!/usr/bin/env bash
# PDF2MD — диагностика окружения (Linux/macOS).
cd "$(dirname "$0")" 2>/dev/null || true

echo
echo "=== PDF2MD — Диагностика ==="
echo "Папка: $(pwd)"
echo "ОС:    $(uname -s) $(uname -m)"
echo

echo "--- Файлы ---"
for f in app.py requirements.txt PDF2MD.sh; do
    if [ -f "$f" ]; then echo "  OK  $f"; else echo "  --  $f ОТСУТСТВУЕТ"; fi
done
echo

echo "--- Поиск Python ---"
found=""
for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then
        ver="$("$c" --version 2>&1)"
        path="$(command -v "$c")"
        if "$c" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)' >/dev/null 2>&1; then
            echo "  OK  $c → $ver ($path)"
            found="$c"
        else
            echo "  !!  $c → $ver — слишком старый (нужен 3.10+)"
        fi
    else
        echo "  --  $c не найден"
    fi
done
echo

if [ -n "$found" ]; then
    echo "--- Модули в найденном Python ---"
    "$found" -c 'import tkinter' >/dev/null 2>&1 \
        && echo "  OK  tkinter (GUI)" \
        || echo "  !!  tkinter ОТСУТСТВУЕТ — GUI не запустится (Linux: sudo apt install python3-tk; macOS: brew install python-tk)"
    "$found" -c 'import venv'   >/dev/null 2>&1 \
        && echo "  OK  venv" \
        || echo "  !!  venv ОТСУТСТВУЕТ (Linux: sudo apt install python3-venv)"
fi
echo

if [ -x ".venv/bin/python" ]; then
    echo "--- Окружение .venv ---"
    echo "  есть: $(.venv/bin/python --version 2>&1)"
    echo "  (чтобы переустановить зависимости — удалите папку .venv и запустите PDF2MD.sh заново)"
else
    echo "--- Окружение .venv ещё не создано (создастся при первом запуске PDF2MD.sh) ---"
fi

echo
echo "=== Конец ==="
read -r -p "Нажмите Enter для выхода..." _
