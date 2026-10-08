#!/usr/bin/env bash
# PDF2MD для macOS — двойной клик в Finder.
# Это тонкая обёртка: вся логика в PDF2MD.sh (запускается через bash,
# поэтому +x на .sh не обязателен).
cd "$(dirname "$0")" || exit 1
exec bash "./PDF2MD.sh"
