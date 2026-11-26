# -*- coding: utf-8 -*-
"""bootstrap.py — установка/обновление версионного рантайма скилла tz-rezultat-hz.

Оркестратор: скачивает python-build-standalone (pinned-релиз), сверяет
SHA-256 с зафиксированным пином, строит версионный каталог-кандидат
(изоляция по ОС: Windows — python311._pth, Linux — venv), ставит
зависимости, скачивает 33-файловый набор format-agent из upstream по
пиннутому коммиту (сверяя точный состав и контент-хэш), скачивает
2-файловый скилл grilling из upstream по пиннутому коммиту (MIT),
валидирует кандидата и атомарно переключает manifest.json.

КОМПОНЕНТЫ: полный комплект (Python + библиотеки, format-agent,
tz-1c-style, grilling) — ОСНОВНОЙ и РЕКОМЕНДУЕМЫЙ сценарий установки.
Все компоненты обязательны для полноценной работы: без grilling
самопроверка Шага 2 («прожарка») недоступна и АНАЛИТИКА НЕПОЛНОЦЕННА.
При первом запуске (нет валидного рантайма) скрипт печатает перечень
компонентов и НЕ ставит ничего, ожидая подтверждения пользователя
(exit 4); установка идёт только по явному режиму. Если скачать или
сверить обязательный компонент не удалось — установка НЕ имитируется:
[FAIL] и остановка, манифест не меняется.

ЦЕЛОСТНОСТЬ (не разрушать рабочий рантайм): все сетевые компоненты
(архив Python, format-agent, grilling) скачиваются и сверяются ДО сборки
каталога; на Windows сборка идёт в каталог-кандидат <PY_DIRNAME>.new, а
рабочий каталог замещается кандидатом ТОЛЬКО после успешной валидации —
прежний уносится в .staging/previous-* (переносится, не удаляется).
Провал загрузки, сверки или сборки оставляет действующий рантайм и
манифест без изменений. На Linux сборка идёт в конечный каталог: venv
создаётся только по конечному пути и не переносится, поэтому сетевые
компоненты там приобретаются до разрушительных шагов, а сбой локального
шага пересборки требует повторного запуска.

Защита от параллельного запуска — замок {pid, hostname, start_time, token}:
чужая живая блокировка → отказ; устаревший замок НЕ удаляется автоматически
(безопасность удаления не подтверждена) → отказ с инструкцией; STEAL запрещён.

Запуск:  <любой Python 3.8+> bootstrap.py [режим] [--rebuild] [--root <путь>]
  --plan         — показать перечень компонентов и выйти (ничего не скачивать)
  --full         — установить ПОЛНЫЙ комплект (рекомендуется; включает grilling)
  --no-grilling  — режим ОСОЗНАННОГО ОТКАЗА: ставит комплект без grilling.
                   Последствия: самопроверка Шага 2 («прожарка») недоступна,
                   АНАЛИТИКА НЕПОЛНОЦЕННА. Это не полноценная установка и
                   не рекомендуемый сценарий; штатный режим — --full.
  --rebuild      — пересобрать рантайм даже если активный валиден
  --root         — переопределить runtime_root (тесты)
  --check        — только проверить активный рантайм и компоненты
  --assume-python — интерпретатор уже распакован/изолирован (bootstrap.ps1/.sh)
  Без режима: валидный полный рантайм → [OK] и выход 0; иначе — перечень
  компонентов и ожидание подтверждения (exit 4), ничего не скачивается.

СИГНАЛЫ О КОМПОНЕНТЕ grilling ([WARN] и [FAIL] не взаимозаменяемы):
  [FAIL] — комплект заявлен полным (манифест install.mode = full), но
           grilling отсутствует или повреждён; либо загрузка/сверка
           обязательного компонента сорвалась при полной установке.
  [WARN] — явный отказ пользователя (--no-grilling) либо комплект
           неизвестен (манифест прежнего формата без сведений об
           установке): работа возможна, но аналитика неполноценна.

ПЛАТФОРМЫ: поддерживаются Windows (win-x64) и Linux (linux-x64) — обе
полноправные. На других платформах (arm64, macOS) скрипт завершается с
[НЕ ПОДДЕРЖИВАЕТСЯ] ДО любых изменений: ни загрузок, ни создания каталогов
рантайма, ни записи манифеста. Ограничение действует и при прямом запуске
bootstrap.py (гейт в main() до _resolve_root). Точки входа: bootstrap.ps1
(Windows) и bootstrap.sh (Linux); обе собирают транзакционно (каталог-
кандидат → валидация → замещение, прежний рабочий каталог в .staging).

Коды возврата: 0 — готово/валиден; 1 — ошибка (в т.ч. неподдерживаемая
платформа); 2 — чужой живой замок; 3 — устаревший замок (удалить вручную);
4 — нужно подтверждение режима установки (пользователь ещё не выбрал;
ничего не скачано).
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

# Обязательные импорты рантайма — единый источник (scripts/tz_common.py):
# validate_candidate и check_active проверяют по нему наличие зависимостей.
_SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
from tz_common import required_imports_probe  # noqa: E402

# ---------------------------------------------------------------------------
# ПИНЫ ВНЕШНИХ КОМПОНЕНТОВ (фиксированы в исходниках — источник подлинности).
# Вычисленный после загрузки хэш СРАВНИВАЕТСЯ с пином; сам по себе он
# подтверждением подлинности не является (правило проекта).
# ---------------------------------------------------------------------------
PBS_RELEASE = "20261124"
PY_VERSION = "3.11.18"
# Версионный каталог рантайма (имя = ф-я от пинов).
PY_DIRNAME = "py%s-%s" % (PY_VERSION.replace(".", ""), PBS_RELEASE)

# Платформенные архивы + опубликованные SHA-256 (из SHA256SUMS релиза).
_PBS_BASE = ("https://github.com/astral-sh/python-build-standalone/"
             "releases/download/%s/" % PBS_RELEASE)
PINS = {
    "win-x64": {
        "archive": "cpython-%s+%s-x86_64-pc-windows-msvc-install_only.tar.gz"
                   % (PY_VERSION, PBS_RELEASE),
        "sha256": "3e4a35e3c238e5090d36bf95c041d9052bc82d6e298cb912ba7f70f6c66cf81a",
    },
    "linux-x64": {
        "archive": "cpython-%s+%s-x86_64-unknown-linux-gnu-install_only.tar.gz"
                   % (PY_VERSION, PBS_RELEASE),
        "sha256": "ef0764e884b5e123692281b91bf388f8ebfd0afb41d6a212bb4f2779e51abf0e",
    },
}

# format-agent: 33-файловый минимальный набор (main.py + 31 core/*.py +
# requirements.txt). Источник — официальный upstream, СТРОГО по пиннутому
# коммиту (не ветка, не latest): URL выводится из коммита. Контент-SHA-256
# набора зафиксирован пином и вычисляется с нормализацией переводов строк
# CRLF→LF, поэтому инвариантен к переводам строк checkout'а (локальный
# бандл — CRLF, upstream-архив — LF; оба дают один хэш). Состав набора —
# ЯВНЫЙ список 33 путей (без динамического листинга).
FA_UPSTREAM = "https://github.com/KaguraNanaga/format-agent-skill"
FA_COMMIT = "8dd726caba43953579d386339765b9613ca6bd58"
FA_ARCHIVE_URL = FA_UPSTREAM + "/archive/" + FA_COMMIT + ".tar.gz"
FA_CONTENT_SHA256 = "218ee326c08fee9bbd46519bdb50df9f66e34b0e6742822f1e69e91096c8ff7f"
FA_FILES = [
    "main.py",
    "requirements.txt",
    "core/__init__.py",
    "core/academic_fields.py",
    "core/agent.py",
    "core/apply.py",
    "core/com_conversion_worker.py",
    "core/com_pdf_worker.py",
    "core/effective_props.py",
    "core/executor.py",
    "core/extract.py",
    "core/field_refresh.py",
    "core/history.py",
    "core/input_conversion.py",
    "core/label_roles.py",
    "core/legal_features.py",
    "core/llm.py",
    "core/numbering.py",
    "core/preflight.py",
    "core/profiles.py",
    "core/render.py",
    "core/report_docx.py",
    "core/rules_from_template.py",
    "core/rules_from_text.py",
    "core/safe_output.py",
    "core/schema.py",
    "core/style_packs.py",
    "core/style_set.py",
    "core/technical_features.py",
    "core/text_integrity.py",
    "core/thesis_structure.py",
    "core/track_changes.py",
    "core/verify_visual.py",
]  # 33 файла (main.py + 31 core/*.py + requirements.txt)

_SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
# Локальный бандл format-agent — БОЛЬШЕ НЕ источник установки (источник —
# upstream по пиннутому коммиту). Остаётся доверенным артефактом для
# кросс-сверки контент-хэша в тестах; в публичном репо отсутствует
# (git-ignored).
_BUNDLE_FA = os.path.join(_SKILL_DIR, "bundle", "format-agent-skill")
_BUNDLE_STYLE = os.path.join(_SKILL_DIR, "bundle", "tz-1c-style")
_REQS = os.path.join(_SKILL_DIR, "scripts", "requirements.txt")

# grilling: сторонний скилл (MIT, © 2026 Matt Pocock) из ОФИЦИАЛЬНОГО
# upstream (плагин mattpocock-skills официального маркетплейса). Ставится
# СТРОГО по пиннутому коммиту (не ветка, не latest). Пути в GR_FILES —
# относительно КОРНЯ репозитория upstream (как FA_FILES), поэтому
# контент-хэш воспроизводим независимо от места установки; локально файлы
# кладутся БЕЗ префикса GR_PREFIX (SKILL.md, agents/openai.yaml).
GR_UPSTREAM = "https://github.com/mattpocock/skills"
GR_COMMIT = "7739eaed7f8f3915437a8def198a6d0d7206dbc7"
GR_PREFIX = "skills/productivity/grilling/"
GR_FILES = [
    "skills/productivity/grilling/SKILL.md",
    "skills/productivity/grilling/agents/openai.yaml",
]
GR_CONTENT_SHA256 = "2c29822897e0da69c46ef26bda242eb3229c7509745472be0fe58935a281ce46"
GR_LICENSE = "MIT"
GR_RAW_BASE = ("https://raw.githubusercontent.com/mattpocock/skills/"
               + GR_COMMIT + "/")

MANIFEST_SCHEMA = 2

# ПОДДЕРЖИВАЕМЫЕ ПЛАТФОРМЫ: Windows и Linux (обе — x64). Гейт в main()
# срабатывает ДО любых изменений файлов (в т.ч. до _resolve_root, который
# пишет пробный файл), поэтому неподдерживаемую платформу нельзя обойти
# прямым запуском bootstrap.py.
_SUPPORTED_TARGETS = ("win-x64", "linux-x64")
_PLATFORM_NOTICE = ("поддерживаются Windows (win-x64) и Linux (linux-x64); "
                    "другие платформы не поддерживаются")

# Перечень компонентов — единый текст (печатается на первом запуске).
# Один источник для bootstrap.py и (до появления Python) bootstrap.ps1 /
# bootstrap.sh: файл читается явным UTF-8, поэтому русский текст не зависит
# от кодировки, в которой интерпретируется сам скрипт.
PLAN_FILE = os.path.join(_SKILL_DIR, "components.ru.md")


def print_plan():
    """Напечатать перечень компонентов полного комплекта (файл поставки)."""
    try:
        with open(PLAN_FILE, encoding="utf-8") as f:
            sys.stdout.write(f.read())
    except OSError as e:
        print("[WARN] перечень компонентов недоступен (%s): %s" % (PLAN_FILE, e))
        print("Компоненты полного комплекта: Python + библиотеки, format-agent, "
              "tz-1c-style, grilling (полный комплект — основной сценарий).")


# --- утилиты ----------------------------------------------------------------

def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _target():
    """Платформенный таргет: win-x64 | linux-x64 | None.

    Оба таргета поддерживаются (входят в _SUPPORTED_TARGETS); гейт в main()
    останавливает только неподдерживаемые платформы."""
    sysname, machine = platform.system(), platform.machine()
    if sysname == "Windows" and machine in ("AMD64", "x86_64"):
        return "win-x64"
    if sysname == "Linux" and machine in ("x86_64", "AMD64"):
        return "linux-x64"
    return None


def _is_writable(d):
    try:
        probe = os.path.join(d, ".bootstrap_wtest")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return True
    except Exception:
        return False


def _resolve_root(override=None):
    """runtime_root: папка скилла (если запись возможна), иначе кэш ОС."""
    if override:
        return os.path.abspath(override)
    skill_runtime = os.path.join(_SKILL_DIR, "runtime")
    if os.path.isdir(skill_runtime) or _is_writable(_SKILL_DIR):
        return skill_runtime
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "tz-rezultat-hz", "runtime")
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "tz-rezultat-hz", "runtime")


# --- манифест ----------------------------------------------------------------

def _manifest_path(root):
    return os.path.join(root, "manifest.json")


def read_manifest(root):
    p = _manifest_path(root)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def write_manifest_atomic(root, manifest):
    """Атомарная запись: tmp → os.replace. При сбое прежний манифест цел."""
    p = _manifest_path(root)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, p)


# --- блокировка --------------------------------------------------------------

def _lock_dir(root):
    return os.path.join(root, ".lock")


def _lock_path(root):
    return os.path.join(_lock_dir(root), "lock.json")


def _pid_alive(pid, host):
    """Жив ли PID на этом host. Консервативно: неопределённость → False."""
    if host != socket.gethostname():
        return False  # чужой host — не наш процесс
    try:
        if platform.system() == "Windows":
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32")
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int,
                                             ctypes.c_uint32]
            PROCESS_QUERY = 0x1000  # PROCESS_QUERY_INFORMATION
            h = kernel32.OpenProcess(PROCESS_QUERY, False, pid)
            if not h:
                return False
            kernel32.CloseHandle(h)
            return True
        else:
            os.kill(pid, 0)  # сигнал 0 — только проверка существования
            return True
    except Exception:
        return False


def acquire_lock(root):
    """Захват замка. Возвращает (ok, reason). reason — код/сообщение.
    ok=True → замок наш; ok=False → причина отказа (не удаляем чужой замок)."""
    os.makedirs(_lock_dir(root), exist_ok=True)
    lp = _lock_path(root)
    me = {
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "start_time": int(time.time()),
        "token": hashlib.sha256(
            (str(os.getpid()) + socket.gethostname() + str(int(time.time()))).encode()
        ).hexdigest()[:16],
    }
    if not os.path.isfile(lp):
        tmp = lp + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(me, f)
        os.replace(tmp, lp)
        return True, "acquired"
    try:
        with open(lp, encoding="utf-8") as f:
            owner = json.load(f)
    except Exception:
        # нечитаемый замок — безопасность удаления не подтверждена → отказ
        return False, ("stale: замок не читается (%s) — удалите его вручную" % lp)
    # повторный вход того же процесса
    if owner.get("token") == me["token"] and owner.get("pid") == me["pid"]:
        return True, "reentrant"
    # чужой владелец жив?
    if _pid_alive(owner.get("pid", -1), owner.get("hostname", "")):
        return False, ("busy: идёт другой bootstrap (pid=%s host=%s) — "
                      "дождитесь завершения; STEAL запрещён"
                      % (owner.get("pid"), owner.get("hostname")))
    # владелец мёртв / чужой host → устаревший замок; НЕ удаляем автоматически
    return False, ("stale: замок устарел (pid=%s host=%s), но безопасность "
                  "удаления не подтверждена — удалите вручную: %s"
                  % (owner.get("pid"), owner.get("hostname"), lp))


def release_lock(root):
    """Отпустить замок — только если он наш (по pid+token)."""
    lp = _lock_path(root)
    try:
        with open(lp, encoding="utf-8") as f:
            owner = json.load(f)
        if owner.get("pid") == os.getpid():
            os.remove(lp)
    except Exception:
        pass


# --- format-agent (upstream, пиннутый коммит) --------------------------------

def _normalized_sha256(path):
    """SHA-256 содержимого файла с нормализацией CRLF→LF (только для хэша)."""
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _fa_content_sha256(src_dir, files=None):
    """Контент-SHA-256 набора: по каждому файлу — относительный путь +
    содержимое с нормализацией CRLF→LF. Нормализация применяется ТОЛЬКО
    при хэшировании; на диск файлы пишутся байт-в-байт."""
    files = FA_FILES if files is None else files
    h = hashlib.sha256()
    for rel in files:
        fp = os.path.join(src_dir, rel.replace("/", os.sep))
        h.update(rel.encode())
        h.update(_normalized_sha256(fp).encode())
    return h.hexdigest()


def _fa_scan(src_dir, ignore_pycache=False):
    """Фактический набор относительных путей в области минимального набора:
    корневые .py, requirements.txt и всё под core/ (рекурсивно). Файлы
    upstream вне набора (docs/, examples/, references/, LICENSE, README*,
    SKILL.md) в область не входят.

    ignore_pycache=True — не считать байткод-кэш Python
    (`core/__pycache__/*.pyc`, появляется при ИСПОЛНЕНИИ установленного
    набора). Для СКАЧАННОГО набора проверка строгая (any лишний файл →
    отказ); для проверок рантайма кэш байткода — не часть набора."""
    found = set()
    for f in os.listdir(src_dir):
        p = os.path.join(src_dir, f)
        if os.path.isfile(p) and (f.endswith(".py") or f == "requirements.txt"):
            found.add(f)
    core = os.path.join(src_dir, "core")
    if os.path.isdir(core):
        for dp, dn, fns in os.walk(core):
            if ignore_pycache:
                dn[:] = [d for d in dn if d != "__pycache__"]
            for f in fns:
                rel = os.path.relpath(os.path.join(dp, f), src_dir)
                found.add(rel.replace(os.sep, "/"))
    return found


def verify_format_agent(src_dir, files=None, pin=None, ignore_pycache=False):
    """Сверить набор: ТОЧНЫЙ состав путей + контент-хэш (CRLF→LF).
    Возвращает (ok, detail). Отсутствующий или лишний файл → отказ.
    ignore_pycache — см. `_fa_scan` (для проверок рантайма)."""
    files = FA_FILES if files is None else files
    pin = FA_CONTENT_SHA256 if pin is None else pin
    if not os.path.isdir(src_dir):
        return False, "нет каталога %s" % src_dir
    expected = set(files)
    found = _fa_scan(src_dir, ignore_pycache)
    missing = sorted(expected - found)
    if missing:
        return False, "отсутствует: %s" % ", ".join(missing[:6])
    extra = sorted(found - expected)
    if extra:
        return False, "лишний: %s" % ", ".join(extra[:6])
    got = _fa_content_sha256(src_dir, files)
    if got != pin:
        return False, "контент-хэш %s ≠ пин %s" % (got, pin)
    return True, got


def _fa_top(src_dir):
    """Корень дерева в распакованном архиве (единственная верхняя папка)."""
    entries = [d for d in os.listdir(src_dir)
               if os.path.isdir(os.path.join(src_dir, d))]
    return os.path.join(src_dir, entries[0]) if len(entries) == 1 else src_dir


def _fa_download(url, dst):
    """Скачивание архива format-agent (curl; .part → rename)."""
    tmp = dst + ".part"
    r = subprocess.run(
        ["curl", "-sSL", "--fail", "--retry", "3", "--max-time", "300",
         "-o", tmp, url], capture_output=True)
    if r.returncode != 0 or not os.path.isfile(tmp):
        raise RuntimeError("%s" % (r.stderr or b"").decode(errors="replace")[:160])
    os.replace(tmp, dst)


def copy_format_agent(src_dir, dst_dir, files=None, pin=None):
    """Скопировать пиннутый набор из src_dir в dst_dir БАЙТ-В-БАЙТ и
    повторно сверить контент-хэш. Возвращает хэш; расхождение → RuntimeError."""
    files = FA_FILES if files is None else files
    pin = FA_CONTENT_SHA256 if pin is None else pin
    os.makedirs(dst_dir, exist_ok=True)
    for rel in files:
        src = os.path.join(src_dir, rel.replace("/", os.sep))
        dst = os.path.join(dst_dir, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    got = _fa_content_sha256(dst_dir, files)
    if got != pin:
        raise RuntimeError("format-agent: контент-хэш %s ≠ пин %s" % (got, pin))
    return got


def stage_format_agent(root, downloader=None, files=None, pin=None, url=None):
    """Скачать архив пиннутого коммита и СВЕРИТЬ набор, не трогая рантайм:
    результат кладётся в .staging/fa-src. Выполняется ДО сборки каталога —
    провал загрузки/сверки не разрушает действующий рантайм.
    Идемпотентно: уже скачанный и сверенный staging не перекачивается.
    Возвращает (ok, detail, staged_src|None)."""
    files = FA_FILES if files is None else files
    pin = FA_CONTENT_SHA256 if pin is None else pin
    url = FA_ARCHIVE_URL if url is None else url
    staging = os.path.join(root, ".staging")
    src = os.path.join(staging, "fa-src")
    top = _fa_top(src) if os.path.isdir(src) else None
    if top and verify_format_agent(top, files, pin)[0]:
        return True, ("format-agent: скачан и сверен раньше (staging, "
                      "commit %s)" % FA_COMMIT[:12]), top
    os.makedirs(staging, exist_ok=True)
    tarball = os.path.join(staging, "format-agent-%s.tar.gz" % FA_COMMIT)
    try:
        if not os.path.isfile(tarball):
            print("  скачиваю format-agent (commit %s) …" % FA_COMMIT[:12])
            (downloader or _fa_download)(url, tarball)
        if os.path.isdir(src):
            shutil.rmtree(src)
        os.makedirs(src)
        with tarfile.open(tarball, "r:gz") as t:
            t.extractall(src, filter="data")
        top = _fa_top(src)
        ok, detail = verify_format_agent(top, files, pin)
        if not ok:
            return False, "format-agent: %s" % detail, None
        return True, ("format-agent скачан и сверен (commit %s)"
                      % FA_COMMIT[:12]), top
    except Exception as e:
        return False, ("format-agent: не удалось получить из upstream "
                       "(commit %s): %s" % (FA_COMMIT, str(e)[:160])), None


def fetch_format_agent(root, ver_dir, downloader=None, files=None, pin=None,
                       url=None):
    """Приобрести format-agent из upstream строго по пиннутому коммиту и
    положить в <ver_dir>/format-agent. Идемпотентно: уже установленный и
    сверенный набор не скачивается. Без сети — понятная ошибка с именем
    коммита (без traceback). Возвращает (ok, detail)."""
    files = FA_FILES if files is None else files
    pin = FA_CONTENT_SHA256 if pin is None else pin
    dst = os.path.join(ver_dir, "format-agent")
    if os.path.isdir(dst):
        ok, _ = verify_format_agent(dst, files, pin, ignore_pycache=True)
        if ok:
            return True, ("format-agent уже установлен и сверен "
                          "(commit %s)" % FA_COMMIT[:12])
    ok, detail, src = stage_format_agent(root, downloader, files, pin, url)
    if not ok:
        return False, detail
    try:
        copy_format_agent(src, dst, files, pin)
    except Exception as e:
        return False, "format-agent: %s" % str(e)[:160]
    return True, "format-agent установлен (commit %s)" % FA_COMMIT[:12]


# --- grilling (upstream, пиннутый коммит, MIT) -------------------------------

def _gr_local(rel):
    """Путь в наборе (от корня upstream) → локальный путь в каталоге скилла."""
    return rel[len(GR_PREFIX):] if rel.startswith(GR_PREFIX) else rel


def _gr_content_sha256(base_dir):
    """Контент-SHA-256 набора grilling: путь от корня upstream + содержимое
    с нормализацией CRLF→LF. base_dir — каталог скилла (SKILL.md, agents/)."""
    h = hashlib.sha256()
    for rel in GR_FILES:
        fp = os.path.join(base_dir, _gr_local(rel).replace("/", os.sep))
        h.update(rel.encode())
        h.update(_normalized_sha256(fp).encode())
    return h.hexdigest()


def _gr_scan(base_dir):
    """Фактический состав каталога скилла (относительные пути, без байткода)."""
    found = set()
    for dirpath, dirnames, filenames in os.walk(base_dir):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for f in filenames:
            rel = os.path.relpath(os.path.join(dirpath, f), base_dir)
            found.add(rel.replace(os.sep, "/"))
    return found


def verify_grilling(base_dir, files=None, pin=None):
    """Сверить набор grilling: ТОЧНЫЙ состав путей + контент-хэш (CRLF→LF).
    Возвращает (ok, detail). Отсутствующий/лишний файл → отказ."""
    files = GR_FILES if files is None else files
    pin = GR_CONTENT_SHA256 if pin is None else pin
    if not os.path.isdir(base_dir):
        return False, "нет каталога %s" % base_dir
    expected = {_gr_local(r) for r in files}
    found = _gr_scan(base_dir)
    missing = sorted(expected - found)
    if missing:
        return False, "отсутствует: %s" % ", ".join(missing[:6])
    extra = sorted(found - expected)
    if extra:
        return False, "лишний: %s" % ", ".join(extra[:6])
    got = _gr_content_sha256(base_dir)
    if got != pin:
        return False, "контент-хэш %s ≠ пин %s" % (got, pin)
    return True, got


def _gr_download(url, dst):
    """Скачивание одного файла grilling (curl; .part → rename)."""
    tmp = dst + ".part"
    r = subprocess.run(
        ["curl", "-sSL", "--fail", "--retry", "3", "--max-time", "120",
         "-o", tmp, url], capture_output=True)
    if r.returncode != 0 or not os.path.isfile(tmp):
        raise RuntimeError("%s" % (r.stderr or b"").decode(errors="replace")[:160])
    os.replace(tmp, dst)


def stage_grilling(root, downloader=None, url_base=None):
    """Скачать 2 файла grilling по пиннутому коммиту в staging и СВЕРИТЬ
    состав и контент-хэш. Выполняется ДО пересборки версионного каталога:
    провал не трогает рабочий рантайм (установка не имитируется).
    Идемпотентно: уже скачанный и сверенный staging не перекачивается.
    Возвращает (ok, detail, staged_dir|None)."""
    url_base = GR_RAW_BASE if url_base is None else url_base
    staging = os.path.join(root, ".staging", "grilling-src")
    if os.path.isdir(staging) and verify_grilling(staging)[0]:
        return True, "grilling: скачан и сверен раньше (staging)", staging
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    os.makedirs(staging)
    try:
        for rel in GR_FILES:
            dst = os.path.join(staging, _gr_local(rel).replace("/", os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            print("  скачиваю grilling: %s …" % _gr_local(rel))
            (downloader or _gr_download)(url_base + rel, dst)
    except Exception as e:
        return False, ("grilling: не удалось скачать из upstream (commit %s): %s"
                       % (GR_COMMIT, str(e)[:160])), None
    ok, detail = verify_grilling(staging)
    if not ok:
        return False, "grilling: %s" % detail, None
    return True, "grilling скачан и сверен (commit %s)" % GR_COMMIT[:12], staging


def copy_grilling(src_dir, dst_dir, files=None, pin=None):
    """Скопировать сверенный набор grilling в dst_dir БАЙТ-В-БАЙТ и
    повторно сверить контент-хэш. Возвращает хэш; расхождение → RuntimeError."""
    files = GR_FILES if files is None else files
    pin = GR_CONTENT_SHA256 if pin is None else pin
    os.makedirs(dst_dir, exist_ok=True)
    for rel in files:
        src = os.path.join(src_dir, _gr_local(rel).replace("/", os.sep))
        dst = os.path.join(dst_dir, _gr_local(rel).replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    got = _gr_content_sha256(dst_dir)
    if got != pin:
        raise RuntimeError("grilling: контент-хэш %s ≠ пин %s" % (got, pin))
    return got


def grilling_dir(root, manifest=None):
    """Каталог установленного grilling в активном рантайме (или None)."""
    m = manifest if manifest is not None else read_manifest(root)
    ver = (m.get("active") or {}).get("python") if m else None
    if not ver:
        return None
    return os.path.join(root, ver, "grilling")


def grilling_status(root, manifest=None):
    """Состояние компонента grilling: 'ok' | 'absent' | 'invalid' | 'none'."""
    d = grilling_dir(root, manifest)
    if not d:
        return "none", "нет активного рантайма"
    if not os.path.isdir(d):
        return "absent", "grilling не установлен"
    ok, detail = verify_grilling(d)
    return ("ok", detail) if ok else ("invalid", detail)


def install_mode(manifest):
    """Режим установки по манифесту: 'full' | 'no-grilling' | 'unknown'.

    'unknown' — манифест прежнего формата (schema 1) без ключа install:
    комплект НЕ подтверждён как полный и должен трактоваться как
    неизвестный/неполный (не как эквивалент осознанного отказа)."""
    inst = (manifest or {}).get("install")
    if isinstance(inst, dict) and inst.get("mode") in ("full", "no-grilling"):
        return inst["mode"]
    return "unknown"


def grilling_verdict(root, manifest=None):
    """Вердикт по обязательному компоненту grilling: (severity, текст).

    severity: 'ok'   — компонент установлен и сверен;
              'fail' — комплект заявлен ПОЛНЫМ (install.mode = full), но
                       компонент отсутствует или повреждён → останавливаем;
              'warn' — явный отказ (--no-grilling) либо комплект неизвестен
                       (манифест прежнего формата) → работа возможна, но
                       аналитика неполноценна."""
    m = manifest if manifest is not None else read_manifest(root)
    state, detail = grilling_status(root, m)
    if state == "ok":
        return "ok", detail
    mode = install_mode(m)
    what = "повреждён" if state == "invalid" else "не установлен"
    if mode == "full":
        return "fail", ("компонент полного комплекта grilling %s: %s"
                        % (what, detail))
    if mode == "no-grilling":
        return "warn", ("установка выполнена БЕЗ grilling (осознанный отказ) — "
                        "самопроверка Шага 2 недоступна, АНАЛИТИКА НЕПОЛНОЦЕННА")
    return "warn", ("сведения об установке отсутствуют (манифест прежнего "
                    "формата) — комплект неизвестен/неполон; grilling %s (%s) — "
                    "самопроверка Шага 2 недоступна, АНАЛИТИКА НЕПОЛНОЦЕННА"
                    % (what, detail))


# --- интерпретатор -----------------------------------------------------------

def _py_exe(ver_dir, target):
    """Путь к активному интерпретатору в версионном каталоге."""
    py = os.path.join(ver_dir, "python")
    if target == "win-x64":
        return os.path.join(py, "python.exe")
    return os.path.join(py, "bin", "python3")


def _venv_python(ver_dir):
    """Linux: venv в версионном каталоге (кандидате при сборке; после
    замещения — в конечном каталоге, где venv ремонтируется — см.
    _repair_venv и _swap_candidate)."""
    return os.path.join(ver_dir, "venv", "bin", "python3")


def _isolate(win, py_base, target, ver_dir):
    """Изоляция: Windows — python311._pth + DLL pywin32; Linux — venv в
    версионном каталоге (кандидате при сборке; после замещения venv
    ремонтируется — см. _repair_venv)."""
    if target == "win-x64":
        # Детектор чужой платформенной раскладки: на win-x64 обязан быть
        # python.exe. Unix-раскладка (bin/python3) означает, что распакован
        # не тот архив (Linux) — молчаливая подмена дала бы необъяснимые
        # «нет интерпретатора».
        if not os.path.isfile(os.path.join(py_base, "python.exe")):
            hint = (" — похоже, распакован Linux-архив"
                    if os.path.isfile(os.path.join(py_base, "bin", "python3"))
                    else "")
            raise RuntimeError(
                "неверная платформенная раскладка: нет python.exe в %s%s"
                % (py_base, hint))
        pth = os.path.join(py_base, "python311._pth")
        lines = ["Lib", "DLLs", "Lib\\site-packages",
                 "Lib\\site-packages\\win32", "Lib\\site-packages\\win32\\lib"]
        with open(pth, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        # DLL pywin32 рядом с exe (LoadLibrary ищет в каталоге exe)
        for dll in ("pythoncom311.dll", "pywintypes311.dll"):
            src = os.path.join(py_base, "Lib", "site-packages",
                               "pywin32_system32", dll)
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(py_base, dll))
        return _py_exe(ver_dir, "win-x64")
    else:
        base_py = os.path.join(py_base, "bin", "python3")
        venv_dir = os.path.join(ver_dir, "venv")
        subprocess.run([base_py, "-m", "venv", venv_dir], check=True)
        return _venv_python(ver_dir)


def _install_deps(py_exe_path, reqs):
    subprocess.run([py_exe_path, "-m", "pip", "install",
                    "--disable-pip-version-check", "-r", reqs], check=True)


# --- сборка кандидата --------------------------------------------------------

def _download(url, dst):
    """Скачивание через curl (надёжнее urllib на редиректах GitHub→CDN и
    прокси). Атомарно: .part → rename."""
    tmp = dst + ".part"
    r = subprocess.run(
        ["curl", "-sSL", "--fail", "--retry", "3", "--max-time", "600",
         "-o", tmp, url],
        capture_output=True)
    if r.returncode != 0 or not os.path.isfile(tmp):
        raise RuntimeError("curl: %s" % (r.stderr or b"").decode(errors="replace")[:160])
    os.replace(tmp, dst)


def _candidate_dir(root):
    """Каталог-кандидат (Windows): сборка идёт здесь, рабочий версионный
    каталог не трогается до успешной валидации и замещения."""
    return os.path.join(root, PY_DIRNAME + ".new")


def _build_dir(root, target):
    """Где идёт сборка: каталог-кандидат на обеих платформах. Рабочий
    версионный каталог не трогается до успешной валидации и замещения
    (_swap_candidate). Linux: venv создаётся в кандидате, а после переноса
    в конечный каталог ремонтируется (_repair_venv) — см. _swap_candidate."""
    return _candidate_dir(root)


def _quarantine(root, bdir, ver_dir):
    """Неудачная сборка: перенести каталог сборки в .staging (корзина).
    Рабочий версионный каталог не трогаем."""
    if os.path.normpath(bdir) == os.path.normpath(ver_dir) or not os.path.isdir(bdir):
        return
    trash = os.path.join(root, ".staging")
    dst = os.path.join(trash, "failed-%s" % time.strftime("%Y%m%d-%H%M%S"))
    try:
        os.makedirs(trash, exist_ok=True)
        os.rename(bdir, dst)
    except Exception:
        pass


def _repair_venv(ver_dir):
    """Linux: после переноса каталога-кандидата в конечный venv содержит
    абсолютные пути (pyvenv.cfg home, bin/python* → base), которые стали
    недействительны. Сломанные симлинки bin/python* мешают `venv --upgrade`
    (он не может последовать за ними и прерывается), поэтому сначала
    удаляем их, а затем пересоздаём venv-структуру через
    `python -m venv --upgrade` от КОНЕЧНОГО base-интерпретатора: site-packages
    сохраняются, пути и симлинки обновляются. Windows — нет venv, ничего не
    делаем."""
    base_py = os.path.join(ver_dir, "python", "bin", "python3")
    venv_dir = os.path.join(ver_dir, "venv")
    if os.path.isfile(base_py) and os.path.isdir(venv_dir):
        vbin = os.path.join(venv_dir, "bin")
        if os.path.isdir(vbin):
            for name in os.listdir(vbin):
                p = os.path.join(vbin, name)
                # только симлинки python* (python, python3, python3.11) —
                # они сломаны переносом; скрипты (pip, activate) не трогаем
                if name.startswith("python") and os.path.islink(p):
                    os.remove(p)
        subprocess.run([base_py, "-m", "venv", "--upgrade", venv_dir], check=True)


def _swap_candidate(root, target, mode):
    """Заместить рабочий каталог кандидатом (Windows и Linux). Прежний рабочий
    каталог ПЕРЕНОСИТСЯ в .staging/previous-* (не удаляется). Linux: после
    переноса ремонтируется venv (абсолютные пути) и кандидат пере-валидируется
    в конечном каталоге. При любом сбое — откат: сломанный кандидат удаляется,
    прежний рабочий каталог возвращается на место. Возвращает путь прежнего
    каталога (или None)."""
    ver_dir = os.path.join(root, PY_DIRNAME)
    new_dir = _candidate_dir(root)
    prev = None
    if os.path.isdir(ver_dir):
        trash = os.path.join(root, ".staging")
        prev = os.path.join(trash, "previous-%s" % time.strftime("%Y%m%d-%H%M%S"))
        os.makedirs(trash, exist_ok=True)
        os.rename(ver_dir, prev)
    try:
        os.rename(new_dir, ver_dir)
        if target == "linux-x64":
            _repair_venv(ver_dir)
            ok, detail = validate_candidate(root, target, mode=mode,
                                            ver_dir=ver_dir)
            if not ok:
                raise RuntimeError("venv после переноса не валиден: %s" % detail)
    except Exception:
        # откат: сломанный кандидат (артефакт сборки) удаляется, прежний
        # рабочий каталог возвращается на место; манифест при этом не тронут
        if prev:
            try:
                if os.path.isdir(ver_dir):
                    shutil.rmtree(ver_dir)
                os.rename(prev, ver_dir)
            except Exception:
                pass
        raise
    return prev


def _recover_interrupted(root, target):
    """Восстановление после прерванного замещения: если конечный версионный
    каталог отсутствует (процесс прерван между переносом прежнего каталога
    и переименованием кандидата), возвращаем прежний рабочий каталог из
    .staging/previous-* — предыдущая рабочая версия снова доступна.
    Остаточный кандидат уносим в корзину. Возвращает (восстановлено_ли, detail)."""
    ver_dir = os.path.join(root, PY_DIRNAME)
    if os.path.isdir(ver_dir):
        return False, "ok"  # рабочий каталог на месте — восстанавливать нечего
    staging = os.path.join(root, ".staging")
    cand = _candidate_dir(root)
    if os.path.isdir(cand):  # остаточный кандидат от прерванной сборки
        _quarantine(root, cand, ver_dir)
    prevs = []
    if os.path.isdir(staging):
        for name in os.listdir(staging):
            if name.startswith("previous-"):
                prevs.append(os.path.join(staging, name))
    if not prevs:
        return False, "no-previous"
    prevs.sort()  # previous-YYYYMMDD-HHMMSS: лексиграфически = по времени
    newest = prevs[-1]
    try:
        os.rename(newest, ver_dir)
        return True, newest
    except Exception as e:
        return False, "restore-failed: %s" % str(e)[:80]


def build_candidate(root, target, force=False, assume_python=False, mode="full"):
    """Собирает каталог-кандидат рантайма. Возвращает (ok, detail), где
    detail при ok — путь каталога сборки.
    mode — 'full' (полный комплект: включая grilling) | 'no-grilling'.
    assume_python=True — интерпретатор уже распакован/изолирован (сделали
    bootstrap.ps1/.sh) в каталоге сборки; пропускаем download/extract/isolate.
    ЭТАП 1 (сеть и сверка) — до любых разрушительных действий: поставка
    tz-1c-style, grilling, архив Python, format-agent. Провал здесь НЕ
    трогает действующий рантайм и не имитирует успешную установку."""
    pin = PINS[target]
    ver_dir = os.path.join(root, PY_DIRNAME)
    bdir = _build_dir(root, target)
    staging = os.path.join(root, ".staging")
    os.makedirs(staging, exist_ok=True)
    arc = os.path.join(staging, pin["archive"])

    # tz-1c-style — компонент поставки: без него полный комплект неполон.
    if not os.path.isfile(os.path.join(_BUNDLE_STYLE, "SKILL.md")):
        return False, ("компонент tz-1c-style отсутствует в поставке: %s — "
                       "восстановите bundle/tz-1c-style/" % _BUNDLE_STYLE)
    # grilling: приобрести и СВЕРИТЬ до сборки каталога.
    staged_gr = None
    if mode == "full":
        gok, gdetail, staged_gr = stage_grilling(root)
        if not gok:
            return False, gdetail
        print("  %s" % gdetail)
    else:
        # не понижать уже установленный компонент: если он валиден — унести
        # в staging (сборка заменяет версионный каталог)
        existing = os.path.join(ver_dir, "grilling")
        if os.path.isdir(existing) and verify_grilling(existing)[0]:
            staged_gr = os.path.join(staging, "grilling-keep")
            copy_grilling(existing, staged_gr)

    if not assume_python:
        if not os.path.isfile(arc) or force:
            print("  скачиваю %s …" % pin["archive"])
            try:
                _download(_PBS_BASE + pin["archive"], arc)
            except (RuntimeError, OSError) as e:
                # Провал сети/диска на этапе загрузки — штатный отказ:
                # действующий рантайм и манифест не тронуты (архив ещё не
                # создан, .part-черновик не считается готовым).
                return False, "скачивание Python: %s" % str(e)[:160]
        got = _sha256_file(arc)
        if got != pin["sha256"]:
            return False, ("SHA-256 не совпадает: получен %s, пин %s"
                           % (got, pin["sha256"]))
        print("  SHA-256 сверен с пином")

    fok, fdetail, fa_src = stage_format_agent(root)
    if not fok:
        return False, fdetail
    print("  %s" % fdetail)

    try:
        if assume_python:
            py_base = os.path.join(bdir, "python")
            if not os.path.isdir(py_base):
                return False, ("assume_python: нет %s (сначала распакуйте "
                               "интерпретатор в каталог сборки)" % py_base)
            active_py = (_py_exe(bdir, target) if target == "win-x64"
                         else _venv_python(bdir))
            if not os.path.isfile(active_py):
                return False, ("assume_python: нет изолированного "
                               "интерпретатора %s" % active_py)
            print("  интерпретатор уже готов (assume_python)")
        else:
            # распаковка в каталог сборки (свежий). Архив PBS содержит в
            # корне папку python/ (python/python.exe, python/Lib, …), поэтому
            # распаковываем в каталог сборки — python/ из архива становится
            # <bdir>/python/.
            if os.path.isdir(bdir):
                shutil.rmtree(bdir)
            os.makedirs(bdir)
            with tarfile.open(arc, "r:gz") as t:
                t.extractall(bdir, filter="data")
            py_base = os.path.join(bdir, "python")
            active_py = _isolate(win=(target == "win-x64"), py_base=py_base,
                                 target=target, ver_dir=bdir)
            print("  изоляция: %s" % active_py)
        _install_deps(active_py, _REQS)
        print("  зависимости установлены")
        copy_format_agent(fa_src, os.path.join(bdir, "format-agent"))
        print("  format-agent установлен (commit %s)" % FA_COMMIT[:12])
        if staged_gr:
            copy_grilling(staged_gr, os.path.join(bdir, "grilling"))
            print("  grilling установлен (commit %s)" % GR_COMMIT[:12])
        return True, bdir
    except Exception as e:
        _quarantine(root, bdir, ver_dir)
        return False, "сборка не удалась: %s" % str(e)[:200]


def validate_candidate(root, target, mode="full", ver_dir=None):
    """Валидация кандидата: интерпретатор работает, импорты, наборы на месте.
    mode='full' → обязателен и сверен компонент grilling.
    ver_dir=None → конечный версионный каталог (Linux/уже замещённый)."""
    if ver_dir is None:
        ver_dir = os.path.join(root, PY_DIRNAME)
    pin = PINS[target]
    if target == "win-x64":
        py = _py_exe(ver_dir, "win-x64")
    else:
        py = _venv_python(ver_dir)
    if not os.path.isfile(py):
        return False, "интерпретатор не найден: %s" % py
    try:
        v = subprocess.run([py, "--version"], capture_output=True, text=True, timeout=60)
        ver = (v.stdout + v.stderr).strip()
        if PY_VERSION not in ver:
            return False, "неверная версия Python: %s" % ver
        mods = required_imports_probe(target)
        r = subprocess.run([py, "-c", mods], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return False, "импорты не прошли: %s" % (r.stderr or "")[:120]
        fa = os.path.join(ver_dir, "format-agent")
        vok, vdetail = verify_format_agent(fa, ignore_pycache=True)
        if not vok:
            return False, "format-agent: %s" % vdetail
        gr = os.path.join(ver_dir, "grilling")
        if mode == "full":
            gok, gdetail = verify_grilling(gr)
            if not gok:
                return False, "grilling: %s" % gdetail
        elif os.path.isdir(gr) and not verify_grilling(gr)[0]:
            return False, "grilling: %s" % verify_grilling(gr)[1]
        return True, ver
    except Exception as e:
        return False, "валидация не удалась: %s" % str(e)[:120]


def active_python(root, manifest):
    """Путь к активному интерпретатору по манифесту (или None)."""
    if not manifest:
        return None
    ver = (manifest.get("active") or {}).get("python")
    if not ver:
        return None
    ver_dir = os.path.join(root, ver)
    target = _target()
    if target == "win-x64":
        py = _py_exe(ver_dir, "win-x64")
    elif target == "linux-x64":
        py = _venv_python(ver_dir)
    else:
        return None
    return py if os.path.isfile(py) else None


# --- главный поток -----------------------------------------------------------

def check_active(root):
    """Проверка активного рантайма по манифесту. Возвращает (ok, detail)."""
    m = read_manifest(root)
    if not m:
        return False, "нет manifest.json"
    py = active_python(root, m)
    if not py:
        return False, "активный интерпретатор не найден"
    try:
        v = subprocess.run([py, "--version"], capture_output=True, text=True, timeout=60)
        if PY_VERSION not in (v.stdout + v.stderr):
            return False, "версия Python не та"
        r = subprocess.run([py, "-c", required_imports_probe(_target())],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return False, ("обязательные импорты не прошли: %s"
                           % ((r.stderr or "").strip()[:120]))
        fa = os.path.join(root, (m.get("active") or {}).get("python"), "format-agent")
        vok, vdetail = verify_format_agent(fa, ignore_pycache=True)
        if vok:
            return True, "runtime OK (%s)" % (m.get("active") or {}).get("python")
        return False, "format-agent не валиден: %s" % vdetail
    except Exception as e:
        return False, "проверка не удалась: %s" % str(e)[:120]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true",
                    help="показать перечень компонентов и выйти")
    ap.add_argument("--full", action="store_true",
                    help="установить ПОЛНЫЙ комплект (рекомендуется)")
    ap.add_argument("--no-grilling", action="store_true",
                    help="режим ОСОЗНАННОГО ОТКАЗА от обязательного компонента: "
                         "комплект без grilling. Последствия: самопроверка Шага 2 "
                         "(«прожарка») недоступна, АНАЛИТИКА НЕПОЛНОЦЕННА — это НЕ "
                         "полноценная установка и НЕ рекомендуемый сценарий "
                         "(штатный режим — --full)")
    ap.add_argument("--rebuild", action="store_true", help="пересобрать даже если валиден")
    ap.add_argument("--root", default=None, help="переопределить runtime_root")
    ap.add_argument("--check", action="store_true", help="только проверить, не скачивать")
    ap.add_argument("--assume-python", action="store_true",
                    help="интерпретатор уже распакован/изолирован "
                         "(сделал bootstrap.ps1); пропускаем download/extract/isolate")
    args = ap.parse_args()
    if args.full and args.no_grilling:
        print("[FAIL] --full и --no-grilling взаимоисключающие")
        return 1
    mode = "full" if args.full else ("no-grilling" if args.no_grilling else None)

    target = _target()
    # ГЕЙТ ПЛАТФОРМЫ — раньше любых действий: он стоит ДО _resolve_root
    # (та пишет пробный файл), до мытья каталогов, загрузок и манифеста.
    if target not in _SUPPORTED_TARGETS:
        print("[НЕ ПОДДЕРЖИВАЕТСЯ] %s" % _PLATFORM_NOTICE)
        print("[FAIL] платформа: %s/%s (таргет %s; поддерживается: %s)"
              % (platform.system(), platform.machine(), target or "нет",
                 ", ".join(_SUPPORTED_TARGETS)))
        print("[ОСТАНОВ] до любых изменений: ничего не скачано, каталоги рантайма "
              "и манифест не тронуты")
        print("[ДЕЙСТВИЕ] Windows: powershell -ExecutionPolicy Bypass "
              "-File bootstrap.ps1 -Full")
        return 1
    root = _resolve_root(args.root)
    print("== BOOTSTRAP tz-rezultat-hz ==")
    print("платформа: %s" % target)
    print("runtime_root: %s" % root)

    if args.plan:
        print_plan()
        return 0

    m = read_manifest(root)
    if args.check:
        ok, detail = check_active(root)
        if not ok:
            print("[FAIL] runtime: %s" % detail)
            return 1
        sev, msg = grilling_verdict(root, m)
        if sev == "ok":
            print("[OK  ] %s + grilling — полный комплект" % detail)
            return 0
        if sev == "fail":
            print("[FAIL] grilling: %s" % msg)
            print("[ДЕЙСТВИЕ] восстановить компонент полного комплекта: "
                  "bootstrap --full")
            return 1
        print("[OK  ] %s" % detail)
        print("[WARN] %s" % msg)
        print("[ДЕЙСТВИЕ] полный комплект: bootstrap --full")
        return 0

    if mode is None:
        # Режим не задан: валидный и полный рантайм → ничего не делать;
        # иначе — показать перечень и ЖДАТЬ подтверждения (ничего не качать).
        ok, detail = check_active(root)
        if ok:
            sev, msg = grilling_verdict(root, m)
            if sev == "ok":
                print("[OK  ] %s + grilling — рантайм валиден, ничего не скачиваю"
                      % detail)
                return 0
            if sev == "warn":
                print("[OK  ] %s" % detail)
                print("[WARN] %s" % msg)
                print("[ДЕЙСТВИЕ] полный комплект: bootstrap --full")
                return 0
        print_plan()
        print("[ОЖИДАНИЕ] подтверждение пользователя: повторите запуск в режиме "
              "полного комплекта — bootstrap.ps1 -Full (Windows) / "
              "bootstrap.py --full")
        return 4

    ok, reason = acquire_lock(root)
    if not ok:
        print("[FAIL] %s" % reason)
        code = 2 if reason.startswith("busy") else 3
        return code
    try:
        # Восстановление после прерванного замещения: если конечный каталог
        # пропал, возвращаем прежний рабочий (предыдущая версия доступна).
        rec, rec_detail = _recover_interrupted(root, target)
        if rec:
            print("  восстановление прежнего рабочего каталога: %s" % rec_detail)
        if not args.rebuild:
            ok, detail = check_active(root)
            gstate = grilling_status(root, read_manifest(root))[0] if ok else "none"
            if ok and (gstate == "ok" or mode != "full"):
                print("[OK  ] %s — ничего не скачиваю" % detail)
                return 0
            if ok:
                print("[WARN] компонент grilling не готов (%s) — доустанавливаю" % gstate)
            else:
                print("[WARN] активный рантайм не валиден (%s) — собираю" % detail)
        ok, detail = build_candidate(root, target, force=args.rebuild,
                                     assume_python=args.assume_python, mode=mode)
        if not ok:
            print("[FAIL] %s" % detail)
            print("[ОСТАНОВ] установка комплекта прервана — действующий рантайм "
                  "не изменён, манифест не записан; устраните причину и повторите")
            return 1
        bdir = detail  # каталог сборки (Windows — <PY_DIRNAME>.new)
        ok, vdetail = validate_candidate(root, target, mode=mode, ver_dir=bdir)
        if not ok:
            _quarantine(root, bdir, os.path.join(root, PY_DIRNAME))
            print("[FAIL] кандидат не прошёл валидацию: %s" % vdetail)
            print("[ОСТАНОВ] действующий рантайм не изменён (манифест прежний)")
            return 1
        # Полный комплект без установленного grilling записан быть не может.
        gr_ok = verify_grilling(os.path.join(bdir, "grilling"))[0]
        if mode == "full" and not gr_ok:
            _quarantine(root, bdir, os.path.join(root, PY_DIRNAME))
            print("[FAIL] установка заявлена полной, но grilling не установлен")
            print("[ОСТАНОВ] действующий рантайм не изменён, манифест не записан")
            return 1
        # Замещение рабочего каталога (Windows и Linux): только после
        # валидации; прежний рабочий рантайм переносится в .staging (не
        # удаляется). Linux: venv ремонтируется и пере-валидируется; при сбое
        # — откат к прежнему рабочему каталогу.
        try:
            prev = _swap_candidate(root, target, mode)
        except Exception as e:
            print("[FAIL] не удалось заместить рабочий каталог: %s" % str(e)[:160])
            print("[ОСТАНОВ] манифест прежний — повторите запуск")
            return 1
        if prev:
            print("  прежний рабочий рантайм сохранён: %s" % prev)
        # атомарный сдвиг манифеста
        m = read_manifest(root) or {}
        m["schema"] = MANIFEST_SCHEMA
        m["active"] = {"python": PY_DIRNAME, "format_agent": FA_CONTENT_SHA256}
        m["python"] = {"release": PBS_RELEASE, "version": PY_VERSION,
                       "platform": target, "archive": PINS[target]["archive"],
                       "sha256": PINS[target]["sha256"]}
        m["format_agent"] = {"upstream": FA_UPSTREAM, "commit": FA_COMMIT,
                             "files": 33, "content_sha256": FA_CONTENT_SHA256}
        m["grilling"] = ({"upstream": GR_UPSTREAM, "commit": GR_COMMIT,
                          "files": len(GR_FILES), "license": GR_LICENSE,
                          "content_sha256": GR_CONTENT_SHA256} if gr_ok else None)
        m["install"] = {"mode": "full" if gr_ok else "no-grilling",
                        "requested": mode,
                        "components": ["python", "deps", "format-agent",
                                       "tz-1c-style"]
                                      + (["grilling"] if gr_ok else [])}
        m["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_manifest_atomic(root, m)
        print("[OK  ] рантайм готов: %s" % PY_DIRNAME)
        print("интерпретатор: %s" % active_python(root, m))
        if not gr_ok:
            print("[WARN] установлено БЕЗ grilling (осознанный отказ) — "
                  "самопроверка Шага 2 недоступна, АНАЛИТИКА НЕПОЛНОЦЕННА; "
                  "это НЕ полноценная установка (штатный режим: --full)")
        elif mode != "full":
            print("  grilling сохранён из прежнего рантайма — комплект полный")
        return 0
    finally:
        release_lock(root)


if __name__ == "__main__":
    sys.exit(main())