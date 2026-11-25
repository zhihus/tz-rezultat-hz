#!/usr/bin/env bash
# ============================================================
# bootstrap.sh — первый запуск tz-rezultat-hz БЕЗ Python (Linux).
#
# Скачивает python-build-standalone (pinned-релиз), сверяет SHA-256
# с зафиксированным пином, распаковывает, создаёт venv (изоляция),
# затем вызывает bootstrap.py на свежем интерпретаторе для
# зависимостей и format-agent.
#
# Пины НИЖЕ ДОЛЖНЫ совпадать с bootstrap.py (PBS_RELEASE /
# PY_VERSION / SHA-256 linux-x64). Это намеренное дублирование:
# скрипт работает до появления Python и не может читать bootstrap.py.
#
# Запуск:  bash bootstrap.sh
# ============================================================
set -euo pipefail

# --- пины (должны совпадать с bootstrap.py) ---
PBS_RELEASE="20261124"
PY_VERSION="3.11.18"
PY_DIRNAME="py31118-${PBS_RELEASE}"
ARCHIVE="cpython-${PY_VERSION}+${PBS_RELEASE}-x86_64-unknown-linux-gnu-install_only.tar.gz"
SHA256="ef0764e884b5e123692281b91bf388f8ebfd0afb41d6a212bb4f2779e51abf0e"
PBS_BASE="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_RELEASE}/"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP_PY="${SCRIPT_DIR}/bootstrap.py"

# --- runtime_root (скилл → кэш ОС) ---
is_writable() {
    local probe="$1/.bootstrap_wtest"
    if ( : > "$probe" ) 2>/dev/null; then rm -f "$probe"; return 0; fi
    return 1
}
SKILL_RUNTIME="${SCRIPT_DIR}/runtime"
if [ -d "$SKILL_RUNTIME" ] || is_writable "$SCRIPT_DIR"; then
    RUNTIME_ROOT="$SKILL_RUNTIME"
else
    CACHE="${XDG_CACHE_HOME:-$HOME/.cache}"
    RUNTIME_ROOT="${CACHE}/tz-rezultat-hz/runtime"
fi
mkdir -p "$RUNTIME_ROOT"

VER_DIR="${RUNTIME_ROOT}/${PY_DIRNAME}"
PY_DIR="${VER_DIR}/python"
VENV_PY="${VER_DIR}/venv/bin/python3"
STAGING="${RUNTIME_ROOT}/.staging"
ARC="${STAGING}/${ARCHIVE}"

echo "== BOOTSTRAP tz-rezultat-hz (sh) =="
echo "runtime_root: ${RUNTIME_ROOT}"

# --- рантайм уже готов? ---
if [ -x "$VENV_PY" ]; then
    "$VENV_PY" "$BOOTSTRAP_PY" --root "$RUNTIME_ROOT" --check && exit 0
    echo "[WARN] активный рантайм не валиден — пересобираю"
fi

# --- скачивание (curl; .part → rename) ---
mkdir -p "$STAGING"
if [ ! -f "$ARC" ]; then
    echo "  скачиваю ${ARCHIVE} …"
    curl -sSL --fail --retry 3 --max-time 600 -o "${ARC}.part" "${PBS_BASE}${ARCHIVE}"
    mv "${ARC}.part" "$ARC"
fi

# --- проверка SHA-256 с пином ---
got="$(sha256sum "$ARC" | awk '{print $1}')"
if [ "$got" != "$SHA256" ]; then
    echo "[FAIL] SHA-256 не совпадает: получен $got, пин $SHA256" >&2
    exit 1
fi
echo "  SHA-256 сверен с пином"

# --- распаковка в версионный каталог (свежий) ---
# Архив PBS содержит в корне папку python/, поэтому распаковка в
# $VER_DIR даёт $VER_DIR/python/bin/python3 (как в bootstrap.py).
if [ -d "$VER_DIR" ]; then rm -rf "$VER_DIR"; fi
mkdir -p "$VER_DIR"
tar -xzf "$ARC" -C "$VER_DIR"

# --- изоляция: venv в конечном версионном каталоге (не переносим) ---
"${PY_DIR}/bin/python3" -m venv "${VER_DIR}/venv"
echo "  изоляция (venv): ${VENV_PY}"

# --- делегируем bootstrap.py (pip + format-agent + validate + manifest) ---
"$VENV_PY" "$BOOTSTRAP_PY" --root "$RUNTIME_ROOT" --assume-python