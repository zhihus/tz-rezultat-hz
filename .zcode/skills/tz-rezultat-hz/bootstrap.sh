#!/usr/bin/env bash
# ============================================================
# bootstrap.sh — точка входа для Linux (ВРЕМЕННО ОТКЛЮЧЕНА).
#
# ВРЕМЕННОЕ ОГРАНИЧЕНИЕ: публикуемая версия tz-rezultat-hz поддерживает
# ТОЛЬКО Windows. Этот скрипт завершается сразу, ничего не скачивая, не
# создавая каталогов и не изменяя рантайм. Linux-код ниже СОХРАНЁН для
# последующей доработки — заблокировано только исполнение.
#
# Замысел (для будущей доработки): печатает перечень компонентов полного
# комплекта; установка идёт ТОЛЬКО по явному режиму --full: без него скрипт
# показывает перечень и ждёт подтверждения пользователя (exit 4), НИЧЕГО
# не скачивая. В режиме --full: скачивает python-build-standalone
# (pinned-релиз), сверяет SHA-256 с зафиксированным пином, распаковывает,
# создаёт venv (изоляция), затем вызывает bootstrap.py на свежем
# интерпретаторе — зависимости, format-agent (upstream, пиннутый коммит)
# и grilling (upstream, пиннутый коммит, MIT). Прежний рабочий каталог НЕ
# удаляется: он переносится в корзину .staging/previous-*.
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

# --- ВРЕМЕННАЯ БЛОКИРОВКА Linux: выход ДО любых действий --------------------
# Порядок важен: ни одной загрузки, ни одного mkdir, ни одного изменения
# рантайма до этого места (проверки платформы/аргументов здесь НЕ выполняются,
# чтобы исключить любые побочные эффекты).
{
    echo "[НЕ ПОДДЕРЖИВАЕТСЯ] tz-rezultat-hz: установка на Linux временно недоступна."
    echo "                     Поддерживается ТОЛЬКО Windows: powershell -ExecutionPolicy"
    echo "                     Bypass -File bootstrap.ps1 -Full (см. README.md)."
    echo "                     Linux-поддержка будет добавлена позднее."
    echo "                     Ничего не скачано, каталогов не создано, рантайм не изменён."
} >&2
exit 1

# ===========================================================================
# НИЖЕ — код для будущей Linux-поддержки (сейчас недостижим по замыслу).
# ===========================================================================

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
PY_DIR="${VER_DIR}/python"
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

# --- распаковка в свежий конечный версионный каталог ---
# Архив PBS содержит в корне папку python/, поэтому распаковка в
# $VER_DIR даёт $VER_DIR/python/bin/python3 (как в bootstrap.py).
# На Linux сборка идёт в КОНЕЧНЫЙ каталог: venv создаётся только по
# конечному пути и не переносится (см. _isolate в bootstrap.py), поэтому
# каталог-кандидат здесь неприменим. Прежний рабочий каталог НЕ удаляем —
# переносим в корзину .staging (сетевые компоненты уже скачаны и сверены
# выше, поэтому сбой загрузки/сверки сюда не доходит).
if [ -d "$VER_DIR" ]; then
    PREV="${STAGING}/previous-$(date +%Y%m%d-%H%M%S)"
    echo "  прежний рантайм сохранён: ${PREV}"
    mv "$VER_DIR" "$PREV"
fi
mkdir -p "$VER_DIR"
tar -xzf "$ARC" -C "$VER_DIR"

# --- изоляция: venv в конечном версионном каталоге (не переносим) ---
"${PY_DIR}/bin/python3" -m venv "${VER_DIR}/venv"
echo "  изоляция (venv): ${VENV_PY}"

# --- делегируем bootstrap.py (pip + format-agent + grilling + validate + manifest) ---
"$VENV_PY" "$BOOTSTRAP_PY" --root "$RUNTIME_ROOT" --assume-python "$MODE"
