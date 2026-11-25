#!/usr/bin/env bash
# ============================================================
# bootstrap.sh — точка входа для Linux (win-x64 / linux-x64).
#
# Печатает перечень компонентов полного комплекта. Установка идёт ТОЛЬКО
# по явному режиму --full: без него скрипт показывает перечень и ждёт
# подтверждения пользователя (exit 4), НИЧЕГО не скачивая.
#
# В режиме --full: скачивает python-build-standalone (pinned-релиз), сверяет
# SHA-256 с зафиксированным пином, распаковывает в каталог-КАНДИДАТ
# (<PY_DIRNAME>.new) и создаёт venv (изоляция) в кандидате, затем вызывает
# bootstrap.py на этом интерпретаторе — зависимости, format-agent
# (upstream, пиннутый коммит) и grilling (upstream, пиннутый коммит, MIT).
# Рабочий версионный каталог НЕ трогается: bootstrap.py замещает его
# кандидатом только после успешной валидации, а прежний переносит в
# .staging/previous-* (не удаляет). Провал загрузки/сборки оставляет
# действующий рантайм и манифест без изменений.
#
# Запуск:  bash bootstrap.sh [--plan] [--full] [--no-grilling]
#   --plan        — показать перечень компонентов и выйти
#   --full        — установить ПОЛНЫЙ комплект (рекомендуется)
#   --no-grilling — режим ОСОЗНАННОГО ОТКАЗА: комплект без grilling
#                   (самопроверка Шага 2 недоступна, АНАЛИТИКА НЕПОЛНОЦЕННА)
#
# Пины НИЖЕ ДОЛЖНЫ совпадать с bootstrap.py (PBS_RELEASE / PY_VERSION /
# SHA-256 linux-x64), а перечень компонентов — с components.ru.md.
# Дублирование намеренное: скрипт работает до появления Python и не может
# читать bootstrap.py.
# ============================================================
set -euo pipefail

PLAN=""
MODE=""
for arg in "$@"; do
    case "$arg" in
        --plan)        PLAN=1 ;;
        --full)        MODE="--full" ;;
        --no-grilling) MODE="--no-grilling" ;;
        *) echo "[FAIL] неизвестный аргумент: $arg (см. --help в шапке)" >&2; exit 1 ;;
    esac
done

# --- пины (должны совпадать с bootstrap.py) ---
PBS_RELEASE="20261124"
PY_VERSION="3.11.18"
PY_DIRNAME="py31118-${PBS_RELEASE}"
ARCHIVE="cpython-${PY_VERSION}+${PBS_RELEASE}-x86_64-unknown-linux-gnu-install_only.tar.gz"
SHA256="ef0764e884b5e123692281b91bf388f8ebfd0afb41d6a212bb4f2779e51abf0e"
PBS_BASE="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_RELEASE}/"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP_PY="${SCRIPT_DIR}/bootstrap.py"
PLAN_FILE="${SCRIPT_DIR}/components.ru.md"

show_plan() { cat "$PLAN_FILE"; }

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
# Каталог-КАНДИДАТ: сборка идёт здесь, рабочий $VER_DIR не трогается до
# успешной валидации (bootstrap.py замещает его кандидатом и уносит
# прежний рабочий каталог в .staging — не удаляя).
BUILD_DIR="${VER_DIR}.new"
PY_DIR="${BUILD_DIR}/python"
VENV_PY="${VER_DIR}/venv/bin/python3"
STAGING="${RUNTIME_ROOT}/.staging"
ARC="${STAGING}/${ARCHIVE}"

echo "== BOOTSTRAP tz-rezultat-hz (sh) =="
echo "runtime_root: ${RUNTIME_ROOT}"

if [ -n "$PLAN" ]; then show_plan; exit 0; fi

# --- рантайм уже готов ПОЛНЫМ комплектом? ---
if [ -x "$VENV_PY" ]; then
    "$VENV_PY" "$BOOTSTRAP_PY" --root "$RUNTIME_ROOT" --check && exit 0
fi

# --- режим не задан → показать перечень и ЖДАТЬ подтверждения ---
if [ -z "$MODE" ]; then
    show_plan
    echo "[ОЖИДАНИЕ] подтверждение пользователя: повторите запуск с --full (полный комплект, рекомендуется)"
    exit 4
fi
if [ "$MODE" = "--no-grilling" ]; then
    echo "[ВНИМАНИЕ] осознанный отказ от обязательного компонента: установка БЕЗ grilling."
    echo "           самопроверка Шага 2 («прожарка») недоступна, АНАЛИТИКА НЕПОЛНОЦЕННА;"
    echo "           это НЕ полноценная установка (штатный режим: bootstrap.sh --full)"
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

# --- распаковка в СВЕЖИЙ каталог-кандидат ---
# Архив PBS содержит в корне папку python/, поэтому распаковка в
# $BUILD_DIR даёт $BUILD_DIR/python/bin/python3 (как в bootstrap.py).
# Каталог-кандидат — НЕ рабочий: рабочий $VER_DIR не трогается до
# успешной валидации (bootstrap.py замещает его кандидатом и уносит
# прежний рабочий каталог в .staging — не удаляя).
if [ -d "$BUILD_DIR" ]; then
    # Прежний незавершённый кандидат — ПЕРЕНОСИМ в корзину (не удаляем).
    PREV="${STAGING}/failed-$(date +%Y%m%d-%H%M%S)"
    echo "  прежний незавершённый кандидат сохранён: ${PREV}"
    mv "$BUILD_DIR" "$PREV"
fi
mkdir -p "$BUILD_DIR"
tar -xzf "$ARC" -C "$BUILD_DIR"

# --- изоляция: venv в каталоге-кандидате (bootstrap.py перенесёт его в
# --- рабочий каталог и отремонтирует после замещения) ---
"${PY_DIR}/bin/python3" -m venv "${BUILD_DIR}/venv"
echo "  изоляция (venv, кандидат): ${BUILD_DIR}/venv/bin/python3"

# --- делегируем bootstrap.py (pip + format-agent + grilling + validate + manifest) ---
# Запускаем на интерпретаторе КАНДИДАТА (venv в $BUILD_DIR): bootstrap.py
# собирает в кандидате, валидирует и ТОЛЬКО после этого замещает рабочий
# каталог (прежний — в .staging/previous-*), ремонтируя venv после переноса.
# Провал оставляет действующий рантайм и манифест без изменений.
"${BUILD_DIR}/venv/bin/python3" "$BOOTSTRAP_PY" --root "$RUNTIME_ROOT" --assume-python "$MODE"