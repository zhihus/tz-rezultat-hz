# -*- coding: utf-8 -*-
"""bootstrap.py — установка/обновление версионного рантайма скилла tz-rezultat-hz.

Оркестратор: скачивает python-build-standalone (pinned-релиз), сверяет
SHA-256 с зафиксированным пином, строит версионный каталог-кандидат
(изоляция по ОС: Windows — python311._pth, Linux — venv), ставит
зависимости, скачивает 33-файловый набор format-agent из upstream по
пиннутому коммиту (сверяя точный состав и контент-хэш), валидирует
кандидата и атомарно переключает manifest.json.

Защита от параллельного запуска — замок {pid, hostname, start_time, token}:
чужая живая блокировка → отказ; устаревший замок НЕ удаляется автоматически
(безопасность удаления не подтверждена) → отказ с инструкцией; STEAL запрещён.

Запуск:  <любой Python 3.8+> bootstrap.py [--rebuild] [--root <путь>] [--check]
  --rebuild  — пересобрать рантайм даже если активный валиден
  --root     — переопределить runtime_root (тесты)
  --check    — только проверить активный рантайм, ничего не скачивать

Коды возврата: 0 — готово/валиден; 1 — ошибка; 2 — чужой живой замок;
3 — устаревший замок (удалить вручную).
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
_REQS = os.path.join(_SKILL_DIR, "scripts", "requirements.txt")

MANIFEST_SCHEMA = 1


# --- утилиты ----------------------------------------------------------------

def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _target():
    """Платформенный таргет: win-x64 | linux-x64 | None (неподдерживается)."""
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

def _fa_normalized_sha256(path):
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
        h.update(_fa_normalized_sha256(fp).encode())
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


def fetch_format_agent(root, ver_dir, downloader=None, files=None, pin=None,
                       url=None):
    """Приобрести format-agent из upstream строго по пиннутому коммиту:
    скачать архив коммита, распаковать, сверить ТОЧНЫЙ состав и
    контент-хэш, скопировать в <ver_dir>/format-agent. Идемпотентно: уже
    установленный и сверенный набор не скачивается. Без сети — понятная
    ошибка с именем коммита (без traceback). Возвращает (ok, detail)."""
    files = FA_FILES if files is None else files
    pin = FA_CONTENT_SHA256 if pin is None else pin
    url = FA_ARCHIVE_URL if url is None else url
    dst = os.path.join(ver_dir, "format-agent")
    if os.path.isdir(dst):
        ok, _ = verify_format_agent(dst, files, pin, ignore_pycache=True)
        if ok:
            return True, ("format-agent уже установлен и сверен "
                          "(commit %s)" % FA_COMMIT[:12])
    staging = os.path.join(root, ".staging")
    os.makedirs(staging, exist_ok=True)
    tarball = os.path.join(staging, "format-agent-%s.tar.gz" % FA_COMMIT)
    try:
        if not os.path.isfile(tarball):
            print("  скачиваю format-agent (commit %s) …" % FA_COMMIT[:12])
            (downloader or _fa_download)(url, tarball)
        src = os.path.join(staging, "fa-src")
        if os.path.isdir(src):
            shutil.rmtree(src)
        os.makedirs(src)
        with tarfile.open(tarball, "r:gz") as t:
            t.extractall(src, filter="data")
        ok, detail = verify_format_agent(_fa_top(src), files, pin)
        if not ok:
            return False, "format-agent: %s" % detail
        copy_format_agent(_fa_top(src), dst, files, pin)
        return True, "format-agent установлен (commit %s)" % FA_COMMIT[:12]
    except Exception as e:
        return False, ("format-agent: не удалось получить из upstream "
                       "(commit %s): %s" % (FA_COMMIT, str(e)[:160]))


# --- интерпретатор -----------------------------------------------------------

def _py_exe(ver_dir, target):
    """Путь к активному интерпретатору в версионном каталоге."""
    py = os.path.join(ver_dir, "python")
    if target == "win-x64":
        return os.path.join(py, "python.exe")
    return os.path.join(py, "bin", "python3")


def _venv_python(ver_dir):
    """Linux: venv создаётся в конечном версионном каталоге (не переносим)."""
    return os.path.join(ver_dir, "venv", "bin", "python3")


def _isolate(win, py_base, target, ver_dir):
    """Изоляция: Windows — python311._pth + DLL pywin32; Linux — venv."""
    if target == "win-x64":
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


def build_candidate(root, target, force=False, assume_python=False):
    """Собирает версионный каталог-кандидат. Возвращает (ok, detail).
    assume_python=True — интерпретатор уже распакован/изолирован (сделали
    bootstrap.ps1/.sh); пропускаем download/extract/isolate."""
    pin = PINS[target]
    ver_dir = os.path.join(root, PY_DIRNAME)
    staging = os.path.join(root, ".staging")
    os.makedirs(staging, exist_ok=True)
    arc = os.path.join(staging, pin["archive"])
    try:
        if assume_python:
            py_base = os.path.join(ver_dir, "python")
            if not os.path.isdir(py_base):
                return False, "assume_python: нет %s (сначала распакуйте)" % py_base
            active_py = (_py_exe(ver_dir, target) if target == "win-x64"
                         else _venv_python(ver_dir))
            if not os.path.isfile(active_py):
                return False, "assume_python: нет изолированного интерпретатора"
            print("  интерпретатор уже готов (assume_python)")
        else:
            if not os.path.isfile(arc) or force:
                print("  скачиваю %s …" % pin["archive"])
                _download(_PBS_BASE + pin["archive"], arc)
            got = _sha256_file(arc)
            if got != pin["sha256"]:
                return False, ("SHA-256 не совпадает: получен %s, пин %s" % (got, pin["sha256"]))
            print("  SHA-256 сверен с пином")
            # распаковка в версионный каталог (свежий). Архив PBS содержит в
            # корне папку python/ (python/python.exe, python/Lib, …), поэтому
            # распаковываем в ver_dir — папка python/ из архива становится
            # ver_dir/python/.
            if os.path.isdir(ver_dir):
                shutil.rmtree(ver_dir)
            os.makedirs(ver_dir)
            with tarfile.open(arc, "r:gz") as t:
                t.extractall(ver_dir, filter="data")
            py_base = os.path.join(ver_dir, "python")
            active_py = _isolate(win=(target == "win-x64"), py_base=py_base,
                                 target=target, ver_dir=ver_dir)
            print("  изоляция: %s" % active_py)
        _install_deps(active_py, _REQS)
        print("  зависимости установлены")
        fok, fdetail = fetch_format_agent(root, ver_dir)
        if not fok:
            return False, fdetail
        print("  %s" % fdetail)
        return True, ver_dir
    except Exception as e:
        return False, "сборка не удалась: %s" % str(e)[:200]


def validate_candidate(root, target):
    """Валидация кандидата: интерпретатор работает, импорты, набор на месте."""
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
        mods = "import docx, lxml, pymupdf"
        if target == "win-x64":
            mods += ", win32com.client"
        r = subprocess.run([py, "-c", mods], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return False, "импорты не прошли: %s" % (r.stderr or "")[:120]
        fa = os.path.join(ver_dir, "format-agent")
        vok, vdetail = verify_format_agent(fa, ignore_pycache=True)
        if not vok:
            return False, "format-agent: %s" % vdetail
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
    ap.add_argument("--rebuild", action="store_true", help="пересобрать даже если валиден")
    ap.add_argument("--root", default=None, help="переопределить runtime_root")
    ap.add_argument("--check", action="store_true", help="только проверить, не скачивать")
    ap.add_argument("--assume-python", action="store_true",
                    help="интерпретатор уже распакован/изолирован "
                         "(сделали bootstrap.ps1/.sh); пропускаем download/extract/isolate")
    args = ap.parse_args()

    target = _target()
    if target is None:
        print("[FAIL] неподдерживаемая платформа: %s/%s (только win-x64, linux-x64)"
              % (platform.system(), platform.machine()))
        return 1
    root = _resolve_root(args.root)
    print("== BOOTSTRAP tz-rezultat-hz ==")
    print("платформа: %s" % target)
    print("runtime_root: %s" % root)

    if args.check:
        ok, detail = check_active(root)
        print("[%s] %s" % ("OK  " if ok else "FAIL", detail))
        return 0 if ok else 1

    ok, reason = acquire_lock(root)
    if not ok:
        print("[FAIL] %s" % reason)
        code = 2 if reason.startswith("busy") else 3
        return code
    try:
        if not args.rebuild:
            ok, detail = check_active(root)
            if ok:
                print("[OK  ] %s — ничего не скачиваю" % detail)
                return 0
            print("[WARN] активный рантайм не валиден (%s) — собираю" % detail)
        ok, detail = build_candidate(root, target, force=args.rebuild,
                             assume_python=args.assume_python)
        if not ok:
            print("[FAIL] %s" % detail)
            return 1
        ok, detail = validate_candidate(root, target)
        if not ok:
            print("[FAIL] кандидат не прошёл валидацию: %s" % detail)
            return 1
        # атомарный сдвиг манифеста
        m = read_manifest(root) or {}
        m["schema"] = MANIFEST_SCHEMA
        m["active"] = {"python": PY_DIRNAME, "format_agent": FA_CONTENT_SHA256}
        m["python"] = {"release": PBS_RELEASE, "version": PY_VERSION,
                       "platform": target, "archive": PINS[target]["archive"],
                       "sha256": PINS[target]["sha256"]}
        m["format_agent"] = {"upstream": FA_UPSTREAM, "commit": FA_COMMIT,
                             "files": 33, "content_sha256": FA_CONTENT_SHA256}
        m["updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        write_manifest_atomic(root, m)
        print("[OK  ] рантайм готов: %s" % PY_DIRNAME)
        print("интерпретатор: %s" % active_python(root, m))
        return 0
    finally:
        release_lock(root)


if __name__ == "__main__":
    sys.exit(main())