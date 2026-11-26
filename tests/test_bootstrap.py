# -*- coding: utf-8 -*-
"""Тесты механизмов Bootstrap (bootstrap.py) для публичного репозитория.

Покрытие (уточнение E): реальные механизмы установки, атомарности и
восстановления — без тестовой инфраструктуры в дистрибутиве навыка
(тесты лежат в корне репозитория, вне `.zcode/skills/tz-rezultat-hz/`).

Негативы (отказы):
  * чужой живой замок → busy, STEAL запрещён, чужой замок не тронут;
  * мёртвый замок → stale БЕЗ автоудаления (ручное удаление);
  * нечитаемый замок → отказ;
  * SHA-256 ≠ пин → отказ сборки (действующий рантайм не тронут);
  * сбой записи манифеста → прежний манифест цел;
  * сетевой отказ загрузки → build_candidate (False, err) без исключения,
    main() → exit 1 с [FAIL]/[ОСТАНОВ] (без traceback), частичный .part-архив
    не считается готовым (повторная попытка перекачивает), прежний манифест цел.
Позитивы:
  * свежий захват / повторный вход / релиз;
  * атомарная запись манифеста; fallback runtime_root в кэш ОС;
  * коды возврата main(): busy → 2, stale → 3.

Транзакционная сборка (Windows + Linux, обе платформы):
  * сборка идёт в каталог-кандидат (`<PY_DIRNAME>.new`) на ОБЕИХ
    платформах — рабочий версионный каталог не трогается до валидации;
  * замещение: прежний рабочий каталог ПЕРЕНОСИТСЯ в `.staging/previous-*`
    (не удаляется), кандидат становится рабочим;
  * откат при сбое замещения: сломанный кандидат удаляется, прежний рабочий
    каталог возвращается на место;
  * восстановление после прерванного замещения: если рабочий каталог
    пропал, прежний рабочий каталог возвращается из `.staging/previous-*`;
  * ремонт venv (Linux): после переноса каталога абсолютные пути venv
    обновляются через `python -m venv --upgrade`, venv работает.

Запуск: `python tests/test_bootstrap.py` (или `py -3 tests/test_bootstrap.py`
на Windows). Выход 0 — все тесты прошли.
"""
import contextlib
import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.abspath(os.path.join(HERE, "..", ".zcode", "skills",
                                         "tz-rezultat-hz"))
sys.path.insert(0, SKILL_DIR)

import bootstrap  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

results = []


def run(name, cond):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")


def fresh_root():
    return tempfile.mkdtemp(prefix="bootstrap-test-")


def write_lock(root, pid, host=None):
    """Чужой замок: pid + чужой token (не наш процесс)."""
    host = host or "foreign-host-never-matches"
    d = bootstrap._lock_dir(root)
    os.makedirs(d, exist_ok=True)
    with open(bootstrap._lock_path(root), "w", encoding="utf-8") as f:
        json.dump({"pid": pid, "hostname": host,
                   "start_time": 0, "token": "foreign" * 2}, f)


def spawn_live():
    return subprocess.Popen([sys.executable, "-c",
                             "import time; time.sleep(300)"])


def _settle():
    """Короткая пауза перед операциями, которые переименовывают только что
    созданные каталоги. В реальной сборке кандидат строится секунды (загрузки,
    pip install), поэтому замещение никогда не гонится со сканированием свежих
    файлов; тест создаёт каталог и сразу его переносит, и на Windows антивирус
    может на мгновение удерживать ручку на новом каталоге (WinError 5).
    Пауза имитирует естественную задержку реального потока."""
    time.sleep(0.4)


# --- SHA-256 -----------------------------------------------------------------

p = tempfile.mkdtemp(prefix="bootstrap-sha-")
fp = os.path.join(p, "known.bin")
with open(fp, "wb") as f:
    f.write(b"tz-rezultat-hz")
run("sha256_file: known hash",
    bootstrap._sha256_file(fp) == hashlib.sha256(b"tz-rezultat-hz").hexdigest())

# --- SHA-256 ≠ пин → отказ сборки (негатив) ---
root = fresh_root()
staging = os.path.join(root, ".staging")
os.makedirs(staging)
arc = os.path.join(staging, bootstrap.PINS["win-x64"]["archive"])
with open(arc, "wb") as f:
    f.write(b"this is not a real archive")
ok, detail = bootstrap.build_candidate(root, "win-x64")
run("sha256 mismatch: build refused",
    (not ok) and detail.startswith("SHA-256"))

# --- замок: чужой ЖИВОЙ pid → busy, STEAL запрещён (негатив) ---
root = fresh_root()
child = spawn_live()
try:
    write_lock(root, child.pid, host=platform.node())
    before = open(bootstrap._lock_path(root), "rb").read()
    ok, reason = bootstrap.acquire_lock(root)
    after = open(bootstrap._lock_path(root), "rb").read()
    run("lock: foreign live pid → busy (no STEAL)",
        (not ok) and reason.startswith("busy"))
    run("lock: foreign lock untouched", before == after)
finally:
    child.kill()
    child.wait()

# --- замок: мёртвый pid → stale, БЕЗ автоудаления (негатив) ---
DEAD_PID = 2 ** 31 - 1
root = fresh_root()
write_lock(root, DEAD_PID, host=platform.node())
ok, reason = bootstrap.acquire_lock(root)
run("lock: dead pid → stale, manual delete",
    (not ok) and reason.startswith("stale") and "вручную" in reason)
run("lock: stale lock NOT auto-deleted",
    os.path.isfile(bootstrap._lock_path(root)))

# --- замок: нечитаемый → отказ (негатив) ---
root = fresh_root()
os.makedirs(bootstrap._lock_dir(root), exist_ok=True)
with open(bootstrap._lock_path(root), "wb") as f:
    f.write(b"\xff\xfe not json")
ok, reason = bootstrap.acquire_lock(root)
run("lock: unreadable → refused", (not ok) and reason.startswith("stale"))

# --- замок: свежий захват, повторный вход, релиз (позитив) ---
root = fresh_root()
ok1, _ = bootstrap.acquire_lock(root)
ok2, reason2 = bootstrap.acquire_lock(root)
run("lock: fresh acquire", ok1)
run("lock: reentrant", ok2 and reason2 == "reentrant")
bootstrap.release_lock(root)
run("lock: release removes own lock",
    not os.path.isfile(bootstrap._lock_path(root)))

# --- release_lock НЕ чужой замок (негатив) ---
root = fresh_root()
write_lock(root, 99999, host=platform.node())  # мёртвый, но не наш
bootstrap.release_lock(root)
run("release_lock: foreign lock untouched",
    os.path.isfile(bootstrap._lock_path(root)))

# --- манифест: атомарность (сбой → прежний цел) + позитивная запись ---
root = fresh_root()
old = {"schema": 1, "active": {"python": bootstrap.PY_DIRNAME}}
bootstrap.write_manifest_atomic(root, old)
real_replace = os.replace
try:
    def boom(*a, **k):
        raise OSError("simulated crash")
    os.replace = boom
    try:
        bootstrap.write_manifest_atomic(root, {"schema": 2})
        crashed = False
    except OSError:
        crashed = True
finally:
    os.replace = real_replace
m = bootstrap.read_manifest(root)
run("manifest: crash during write → exception", crashed)
run("manifest: prior manifest intact after crash", m == old)
tmp_left = bootstrap._manifest_path(root) + ".tmp"
if os.path.isfile(tmp_left):
    os.remove(tmp_left)
bootstrap.write_manifest_atomic(root, {"schema": 1, "active": {"python": "x"}})
run("manifest: atomic write ok",
    bootstrap.read_manifest(root) == {"schema": 1, "active": {"python": "x"}})
with open(bootstrap._manifest_path(root), "w", encoding="utf-8") as f:
    f.write("{not json")
run("manifest: corrupted → None", bootstrap.read_manifest(root) is None)

# --- runtime_root: override / default / fallback в кэш ОС ---
run("root: override wins",
    bootstrap._resolve_root("/tmp/anywhere") == os.path.abspath("/tmp/anywhere"))
run("root: default = skill/runtime",
    bootstrap._resolve_root(None) == os.path.join(bootstrap._SKILL_DIR, "runtime"))
real_isdir = os.path.isdir
real_writable = bootstrap._is_writable
os.path.isdir = lambda p: False
bootstrap._is_writable = lambda d: False
try:
    fb = bootstrap._resolve_root(None)
finally:
    os.path.isdir = real_isdir
    bootstrap._is_writable = real_writable
if platform.system() == "Windows":
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
else:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
run("root: fallback to OS cache",
    os.path.abspath(fb) == os.path.abspath(os.path.join(base, "tz-rezultat-hz", "runtime")))

# --- платформа: обе x64-платформы поддерживаются (негатив: гейт) ---
run("platform: both win-x64 and linux-x64 supported",
    bootstrap._SUPPORTED_TARGETS == ("win-x64", "linux-x64"))
run("platform: current host resolves to a supported target",
    bootstrap._target() in bootstrap._SUPPORTED_TARGETS)

# --- транзакционная сборка: каталог-кандидат на обеих платформах ---
root = fresh_root()
cand = bootstrap._candidate_dir(root)
run("candidate dir: <PY_DIRNAME>.new",
    os.path.normpath(cand) == os.path.normpath(
        os.path.join(root, bootstrap.PY_DIRNAME + ".new")))
run("build dir (win-x64) = candidate (рабочий каталог не трогается)",
    os.path.normpath(bootstrap._build_dir(root, "win-x64")) == os.path.normpath(cand))
run("build dir (linux-x64) = candidate (рабочий каталог не трогается)",
    os.path.normpath(bootstrap._build_dir(root, "linux-x64")) == os.path.normpath(cand))
run("build dir != final version dir (обе платформы)",
    os.path.normpath(bootstrap._build_dir(root, "win-x64"))
    != os.path.normpath(os.path.join(root, bootstrap.PY_DIRNAME))
    and os.path.normpath(bootstrap._build_dir(root, "linux-x64"))
    != os.path.normpath(os.path.join(root, bootstrap.PY_DIRNAME)))


def _mk_dir_with(root, name, marker):
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "marker.txt"), "w", encoding="utf-8") as f:
        f.write(marker)
    return d


def _read_marker(d):
    """Читает marker.txt в каталоге d (d — полный путь)."""
    with open(os.path.join(d, "marker.txt"), encoding="utf-8") as f:
        return f.read()


# --- замещение: рабочий каталог → .staging/previous-*, кандидат → рабочий ---
root = fresh_root()
ver_dir = _mk_dir_with(root, bootstrap.PY_DIRNAME, "OLD")
cand_dir = _mk_dir_with(root, bootstrap.PY_DIRNAME + ".new", "NEW")
_settle()
prev = bootstrap._swap_candidate(root, "win-x64", "full")
run("swap: working dir preserved in .staging/previous-* (не удалён)",
    prev is not None and os.path.isdir(prev)
    and _read_marker(prev) == "OLD")
run("swap: candidate becomes working dir",
    _read_marker(os.path.join(root, bootstrap.PY_DIRNAME)) == "NEW")
run("swap: candidate dir gone after swap",
    not os.path.isdir(cand_dir))

# --- замещение: НОВОЕ (без прежнего) — previous = None ---
root = fresh_root()
_mk_dir_with(root, bootstrap.PY_DIRNAME + ".new", "FIRST")
_settle()
prev = bootstrap._swap_candidate(root, "win-x64", "full")
run("swap: fresh install → previous is None", prev is None)
run("swap: fresh install → working dir present",
    _read_marker(os.path.join(root, bootstrap.PY_DIRNAME)) == "FIRST")

# --- замещение: ОТКАТ при сбое (кандидат отсутствует → rename падает) ---
root = fresh_root()
ver_dir = _mk_dir_with(root, bootstrap.PY_DIRNAME, "OLD")
_settle()
try:
    bootstrap._swap_candidate(root, "win-x64", "full")
    raised = False
except Exception:
    raised = True
run("swap: failed swap raises", raised)
run("swap: rollback restores previous working dir",
    os.path.isdir(ver_dir) and _read_marker(ver_dir) == "OLD")
run("swap: rollback leaves no candidate",
    not os.path.isdir(os.path.join(root, bootstrap.PY_DIRNAME + ".new")))
# прежний каталог перенесён в .staging и возвращён — в staging previous-*
# после успешного отката быть не должно (он переименован обратно)
staging = os.path.join(root, ".staging")
leftover = [n for n in os.listdir(staging)] if os.path.isdir(staging) else []
run("swap: rollback consumes the staged previous (no leftover previous-*)",
    not any(n.startswith("previous-") for n in leftover))

# --- восстановление после прерванного замещения ---
# Симуляция: рабочий каталог пропал (прервано между переносом прежнего и
# переименованием кандидата), остаточный кандидат есть, прежний в staging.
root = fresh_root()
prev_dir = os.path.join(root, ".staging", "previous-20260101-000000")
_mk_dir_with(root, "x", "dummy")  # чтобы .staging существовал
os.makedirs(prev_dir, exist_ok=True)
with open(os.path.join(prev_dir, "marker.txt"), "w", encoding="utf-8") as f:
    f.write("PREV")
_mk_dir_with(root, bootstrap.PY_DIRNAME + ".new", "CAND")
_settle()
rec, detail = bootstrap._recover_interrupted(root, "win-x64")
run("recover: interrupted swap → previous restored", rec is True)
run("recover: working dir back with previous content",
    os.path.isdir(os.path.join(root, bootstrap.PY_DIRNAME))
    and _read_marker(os.path.join(root, bootstrap.PY_DIRNAME)) == "PREV")
run("recover: residual candidate quarantined (not left as .new)",
    not os.path.isdir(os.path.join(root, bootstrap.PY_DIRNAME + ".new")))

# --- восстановление: рабочий каталог на месте → нечего восстанавливать ---
root = fresh_root()
_mk_dir_with(root, bootstrap.PY_DIRNAME, "OK")
rec, detail = bootstrap._recover_interrupted(root, "win-x64")
run("recover: working dir present → no-op", rec is False and detail == "ok")

# --- восстановление: нет ни рабочего, ни previous → no-previous ---
root = fresh_root()
rec, detail = bootstrap._recover_interrupted(root, "win-x64")
run("recover: no previous available → no-previous",
    rec is False and detail == "no-previous")

# --- ремонт venv (Linux): после переноса абсолютные пути обновляются ---
if platform.system() == "Linux":
    root = fresh_root()
    ver = os.path.join(root, bootstrap.PY_DIRNAME)
    pybin = os.path.join(ver, "python", "bin")
    os.makedirs(pybin)
    base_py = os.path.join(pybin, "python3")
    shutil.copy2(sys.executable, base_py)
    os.chmod(base_py, 0o755)
    venv_dir = os.path.join(ver, "venv")
    subprocess.run([base_py, "-m", "venv", venv_dir], check=True)

    def _home(cfg):
        for line in cfg.splitlines():
            if line.startswith("home"):
                return line.split("=", 1)[1].strip()
        return None

    with open(os.path.join(venv_dir, "pyvenv.cfg"), encoding="utf-8") as f:
        cfg_before = f.read()
    run("venv: before move, home points to original location",
        _home(cfg_before) == os.path.join(ver, "python", "bin"))
    # перенос каталога (симуляция замещения) — пути в venv становятся устаревшими
    ver2 = os.path.join(root, bootstrap.PY_DIRNAME + ".moved")
    os.rename(ver, ver2)
    bootstrap._repair_venv(ver2)
    with open(os.path.join(ver2, "venv", "pyvenv.cfg"), encoding="utf-8") as f:
        cfg_after = f.read()
    run("venv repair: home updated to final location after move",
        _home(cfg_after) == os.path.join(ver2, "python", "bin"))
    vpy = os.path.join(ver2, "venv", "bin", "python3")
    r = subprocess.run([vpy, "-c", "print(1)"], capture_output=True, text=True)
    run("venv repair: repaired venv python works", r.returncode == 0)
else:
    print("[SKIP] venv repair (Linux-only mechanism; on Windows venv не используется)")

# --- коды возврата main(): busy → 2, stale → 3 (end-to-end) ---
# --full обязателен: без флага режима main() возвращает 4 (ожидание
# подтверждения) ДО проверки замка; с --full поток доходит до acquire_lock.
root = fresh_root()
child = spawn_live()
argv = sys.argv
try:
    write_lock(root, child.pid, host=platform.node())
    sys.argv = ["bootstrap.py", "--full", "--root", root]
    code = bootstrap.main()
    run("main: busy lock → exit 2", code == 2)
    child.kill()
    child.wait()
    write_lock(root, DEAD_PID, host=platform.node())
    code = bootstrap.main()
    run("main: stale lock → exit 3", code == 3)
finally:
    sys.argv = argv

# --- сетевой отказ: build_candidate → (False, err) без исключения ---
# _download имитирует срыв сети: оставляет .part-черновик, финальный архив
# НЕ создаёт. Ожидаемые типы исключений: RuntimeError (curl) и OSError
# (subprocess.run / os.replace). Провал НЕ трогает действующий рантайм.
target = bootstrap._target()
root = fresh_root()
real_download = bootstrap._download
def _boom_download(url, dst):
    with open(dst + ".part", "wb") as f:
        f.write(b"partial")
    raise RuntimeError("curl: (7) Failed to connect (simulated)")
bootstrap._download = _boom_download
try:
    try:
        ok, detail = bootstrap.build_candidate(root, target, force=True,
                                               mode="no-grilling")
        raised = False
    except Exception:
        raised = True
        ok, detail = None, None
finally:
    bootstrap._download = real_download
run("net-fail: build_candidate → (False, err), без исключения",
    (not ok) and (not raised) and detail is not None
    and detail.startswith("скачивание Python"))
# частичный архив: финальный архив НЕ создан → .part-черновик не считается
# готовым, следующая попытка перекачает
arc = os.path.join(root, ".staging", bootstrap.PINS[target]["archive"])
run("net-fail: финальный архив не создан (частичный .part не 'готов')",
    not os.path.isfile(arc))
# повторная попытка: _download вызывается снова (архив не считается готовым)
calls = []
def _count_download(url, dst):
    calls.append(1)
    raise RuntimeError("curl: (7) still down (simulated)")
bootstrap._download = _count_download
try:
    bootstrap.build_candidate(root, target, force=False, mode="no-grilling")
finally:
    bootstrap._download = real_download
run("net-fail: повторная попытка снова ходит за архивом", len(calls) == 1)

# --- сетевой отказ end-to-end: main() → exit 1, [FAIL]/[ОСТАНОВ], без traceback ---
root = fresh_root()
os.makedirs(root, exist_ok=True)
prior = {"schema": 2, "active": {"python": bootstrap.PY_DIRNAME}}
bootstrap.write_manifest_atomic(root, prior)
real_stage_gr = bootstrap.stage_grilling
bootstrap.stage_grilling = lambda r: (True, "grilling: staged (test)",
                                       os.path.join(r, ".staging", "grilling-src"))
bootstrap._download = _boom_download
buf = io.StringIO()
argv = sys.argv
try:
    sys.argv = ["bootstrap.py", "--full", "--rebuild", "--root", root]
    with contextlib.redirect_stdout(buf):
        code = bootstrap.main()
finally:
    sys.argv = argv
    bootstrap.stage_grilling = real_stage_gr
    bootstrap._download = real_download
out = buf.getvalue()
run("net-fail: main() → exit 1", code == 1)
run("net-fail: main() печатает [FAIL] и [ОСТАНОВ]",
    "[FAIL]" in out and "[ОСТАНОВ]" in out)
run("net-fail: main() без traceback", "Traceback" not in out)
run("net-fail: прежний манифест цел",
    bootstrap.read_manifest(root) == prior)

# --- bootstrap.sh: платформенный предохранитель (только Linux) --------------
BASH = shutil.which("bash")
SH_CANON = os.path.join(SKILL_DIR, "bootstrap.sh")


def _run_sh(stub, args=()):
    """Копия bootstrap.sh в temp + PATH-заглушки (uname/curl): рабочий
    скилл и действующий runtime не затрагиваются."""
    run_dir = tempfile.mkdtemp(prefix="bsh-run-")
    sh = os.path.join(run_dir, "bootstrap.sh")
    with open(SH_CANON, "rb") as f:
        data = f.read()
    with open(sh, "wb") as f:
        f.write(data)
    comp = os.path.join(SKILL_DIR, "components.ru.md")
    if os.path.isfile(comp):  # нужен режиму --plan (show_plan читает его)
        shutil.copy2(comp, os.path.join(run_dir, "components.ru.md"))
    stub_dir = tempfile.mkdtemp(prefix="bsh-stub-")
    for name, body in stub.items():
        p = os.path.join(stub_dir, name)
        with open(p, "w", newline="\n") as f:
            f.write(body)
        os.chmod(p, 0o755)
    env = dict(os.environ)
    env["PATH"] = stub_dir + os.pathsep + os.environ.get("PATH", "")
    r = subprocess.run([BASH, sh, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    return r, (r.stdout or "") + (r.stderr or "")


if BASH:
    r_win, out_win = _run_sh({"uname": "#!/bin/sh\necho MINGW64_NT-10.0\n"})
    run("sh: вне Linux → отказ (код ≠ 0)", r_win.returncode != 0)
    run("sh: вне Linux → понятное сообщение",
        "только Linux" in out_win and "bootstrap.ps1" in out_win)

    r_lin, out_lin = _run_sh({"uname": "#!/bin/sh\necho Linux\n",
                              "curl": "#!/bin/sh\nexit 1\n"}, args=["--plan"])
    run("sh: на Linux предохранитель не срабатывает",
        "только Linux" not in out_lin and r_lin.returncode == 0)
else:
    print("[SKIP] bootstrap.sh guard: bash отсутствует")

# --- bootstrap.py: детектор чужой платформенной раскладки (§5) ---------------
vroot = tempfile.mkdtemp(prefix="bsl-layout-")
py_base = os.path.join(vroot, "python")
os.makedirs(os.path.join(py_base, "bin"))
open(os.path.join(py_base, "bin", "python3"), "w").close()  # Unix-раскладка
try:
    bootstrap._isolate(win=True, py_base=py_base, target="win-x64",
                       ver_dir=vroot)
    detected = False
except Exception as e:
    detected = "python.exe" in str(e)
run("py: Unix-раскладка на win-x64 → диагностическая ошибка", detected)

fails = [n for n, ok in results if not ok]
print(f"\nИТОГ: {'PASS' if not fails else 'FAIL'} ({len(results) - len(fails)}/{len(results)})")
if fails:
    print("Падения:")
    for n in fails:
        print("  - %s" % n)
sys.exit(1 if fails else 0)