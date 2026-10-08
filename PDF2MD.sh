#!/usr/bin/env bash
# PDF2MD — запуск под Linux и macOS.
# Находит Python 3, при первом запуске создаёт .venv и ставит зависимости,
# затем запускает app.py. Запуск: ./PDF2MD.sh  (или: bash PDF2MD.sh)
set -u

# Перейти в папку скрипта (важно для двойного клика на macOS)
cd "$(dirname "$0")" || { echo "Не удалось перейти в папку скрипта"; exit 1; }

pause_exit() { echo; read -r -p "Нажмите Enter для выхода..." _; exit "${1:-1}"; }

if [ ! -f "app.py" ]; then
    echo "ОШИБКА: app.py не найден рядом со скриптом."
    echo "Положите все файлы PDF2MD в одну папку."
    pause_exit 1
fi

# --- Поиск Python 3.10+ ---
PY=""
for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then
        if "$c" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)' >/dev/null 2>&1; then
            PY="$c"; break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo "Python 3.10+ не найден."
    echo "  macOS:  brew install python      (или скачайте с https://www.python.org/downloads/)"
    echo "  Linux:  sudo apt install python3 python3-venv python3-pip   (Debian/Ubuntu)"
    echo "          sudo dnf install python3 python3-pip               (Fedora)"
    pause_exit 1
fi
echo "Python: $($PY --version 2>&1)  ($(command -v "$PY"))"

VENV=".venv"
VPY="$VENV/bin/python"
DEPS_MARK="$VENV/.deps_v3"   # повышаем номер при изменении requirements → переустановка
# pip без системного SOCKS/VPN-прокси (чтобы дотянуться до PyPI напрямую)
PIP_NOPROXY="env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy"

# --- Создать окружение, если его ещё нет ---
if [ ! -x "$VPY" ]; then
    echo "Первый запуск: создаю виртуальное окружение..."
    if ! "$PY" -m venv "$VENV"; then
        echo "Не удалось создать виртуальное окружение."
        echo "  Linux: возможно нужен пакет python3-venv:  sudo apt install python3-venv"
        pause_exit 1
    fi
    $PIP_NOPROXY "$VPY" -m pip install --upgrade pip --disable-pip-version-check
fi

# --- Зависимости: ядро обязательно, офисные форматы — по возможности ---
# Маркер — подсказка, но решает реальный импорт: окружение могло сломаться.
CORE_CHECK="import requests, pypdf, numpy, pymupdf4llm, PIL, socks"
if [ ! -f "$DEPS_MARK" ] || ! "$VPY" -c "$CORE_CHECK" >/dev/null 2>&1; then
    echo "Устанавливаю зависимости (VPN/прокси временно в обход), подождите..."
    if ! $PIP_NOPROXY "$VPY" -m pip install -r requirements.txt --disable-pip-version-check; then
        echo "Не удалось установить ядро зависимостей. Если включён VPN/прокси — выключите на время установки."
        pause_exit 1
    fi
    echo "Ставлю поддержку office-форматов (Word/Excel/PPTX) — необязательно..."
    if ! $PIP_NOPROXY "$VPY" -m pip install -r requirements-optional.txt --disable-pip-version-check; then
        echo
        echo "ПРИМЕЧАНИЕ: office-форматы не установились (часто: на Python 3.14 нет сборки onnxruntime)."
        echo "Приложение всё равно работает для PDF, сканов и картинок."
        echo "Для Word/Excel поставьте Python 3.12 или 3.13 и запустите снова."
        echo
    fi
    touch "$DEPS_MARK"
    echo "Зависимости готовы."
fi

# --- Проверка GUI (tkinter) ---
if ! "$VPY" -c 'import tkinter' >/dev/null 2>&1; then
    echo
    echo "ВНИМАНИЕ: в Python нет модуля tkinter — графический интерфейс не запустится."
    echo "  macOS:  brew install python-tk     (или поставьте Python с python.org — там tkinter уже встроен)"
    echo "  Linux:  sudo apt install python3-tk        (Debian/Ubuntu)"
    echo "          sudo dnf install python3-tkinter   (Fedora)"
    echo "После установки просто запустите этот файл снова."
    read -r -p "Всё равно попробовать запуск сейчас? Enter — да, Ctrl+C — выход " _
fi

echo "Запуск PDF2MD..."
echo
"$VPY" app.py
RC=$?
if [ "$RC" -ne 0 ]; then
    echo
    echo "Программа завершилась с кодом $RC"
    pause_exit "$RC"
fi
