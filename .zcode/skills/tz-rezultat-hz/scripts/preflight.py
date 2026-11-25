# -*- coding: utf-8 -*-
"""preflight.py — Шаг 1 скилла tz-rezultat-hz одним вызовом.

Скрипт делает все проверки окружения сам и печатает плоский отчёт:
OK/FAIL по каждой позиции + готовые действия. Модель читает отчёт и
действует по строкам «ДЕЙСТВИЕ:». Ничего не спрашивает, интерактив —
нет (контракт слабой модели).

Использование:
  python preflight.py --work <рабочая папка> --harness zcode|claude-code|codex|other

Код возврата: 0 — отчёт напечатан (даже при FAIL: отчёт и есть результат).
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request

_SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_OK = "OK  "
_FAIL = "FAIL"
_WARN = "WARN"


def _line(status, name, detail=""):
    line = f"[{status}] {name}: {detail}" if detail else f"[{status}] {name}"
    print(line)
    return line


_HARNESS = {
    "zcode": "ZCode — инструмент вопросов + documents:visual-judge доступны",
    "claude-code": "Claude Code — вопросы инструментом, визуальная приёмка постранично",
    "codex": "Codex — вопросы ТОЛЬКО текстом в конце ответа, приёмка постранично",
    "other": "другой: вопросы ТОЛЬКО текстом в конце ответа, визуальная приёмка постранично",
}


def check_harness(harness):
    detail = _HARNESS.get(harness)
    if detail is None:
        line = _line(_FAIL, "харнесс", "неизвестное значение --harness: %s"
                     " (Unica: zcode|claude-code|codex, или other)" % harness)
    else:
        line = _line(_OK, "харнесс", detail)
    return line or ""


def check_runtime():
    """Активный рантайм — из манифеста Bootstrap. Preflight НЕ ставит
    Python/библиотеки сам: при отсутствии валидного рантайма указывает
    запустить Bootstrap (bootstrap.ps1 / bootstrap.sh / bootstrap.py)."""
    sys.path.insert(0, _SKILL_DIR)
    import bootstrap
    root = bootstrap._resolve_root()
    m = bootstrap.read_manifest(root)
    py = bootstrap.active_python(root, m)
    if not py:
        _line(_FAIL, "runtime", "валидный рантайм отсутствует (нет манифеста/интерпретатора)")
        _line("ДЕЙСТВИЕ", "",
              "агент: запустите Bootstrap — bootstrap.ps1 (Windows) / bootstrap.sh (Linux)")
        return
    # Импорты проверяем в АКТИВНОМ интерпретаторе (не в host-питоне).
    mods = "import docx, lxml, pymupdf"
    if bootstrap._target() == "win-x64":
        mods += ", win32com.client"
    try:
        r = subprocess.run([py, "-c", mods], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            _line(_FAIL, "runtime", "импорты не прошли в активном интерпретаторе")
            _line("ДЕЙСТВИЕ", "", "агент: запустите Bootstrap --rebuild")
            return
    except Exception as e:
        _line(_FAIL, "runtime", "проверка не удалась: %s" % str(e)[:120])
        _line("ДЕЙСТВИЕ", "", "агент: запустите Bootstrap --rebuild")
        return
    _line(_OK, "runtime", py)


def check_word_com():
    try:
        import win32com.client  # noqa: F401
        have_pywin32 = True
    except ImportError:
        have_pywin32 = False
    if not have_pywin32:
        _line(_WARN, "Word COM", "pywin32 не установлен — проверить Word не могу")
        _line("ДЕЙСТВИЕ", "", "агент: проверить Word вручную (COM-рендер) или продолжить с LibreOffice")
        return
    try:
        import win32com.client
        word = win32com.client.DispatchEx("Word.Application")
        word.Quit()
        _line(_OK, "Word COM", "запуск/закрытие Word.Application прошёл")
    except Exception as e:
        _line(_WARN, "Word COM", "не запустился: %s" % str(e)[:120])
        _line("ДЕЙСТВИЕ", "", "агент: проверить LibreOffice; отсутствие И Word, И LibreOffice — доложить")


def _soffice_candidates():
    """Те же кандидаты, что у рендера (verify_template.render_to_pdf):
    TZ_SOFFICE → PATH → portable/libreoffice рядом с проектом."""
    cands = []
    env = os.environ.get("TZ_SOFFICE")
    if env:
        cands.append(env)
    cands.append("soffice")
    root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    for rel in (os.path.join("portable", "libreoffice", "program", "soffice.exe"),
                os.path.join("portable", "libreoffice", "soffice")):
        p = os.path.join(root, rel)
        if os.path.exists(p):
            cands.append(p)
    return cands


def check_libreoffice():
    """Наличие + ЖИВОЙ headless-конверт DOCX→PDF (присутствие ≠ работоспособность)."""
    soffice = None
    for cand in _soffice_candidates():
        found = cand if os.path.isfile(cand) else shutil.which(cand)
        if found:
            soffice = found
            break
    if not soffice:
        # НЕ проблема (правило Шага 1 п.3): докладывать только в паре с отсутствием Word
        return [_line(_WARN, "LibreOffice",
                      "не найден — НЕ проблема при живом Word (запасной "
                      "рендер): конверт DOCX→PDF недоступен"),
                _line("ДЕЙСТВИЕ", "", "агент: рендер — только Word COM")]
    # живой конверт: крошечный DOCX → PDF во временную папку
    import tempfile
    tmp = tempfile.mkdtemp(prefix="lo-check-")
    try:
        from docx import Document
        tiny = os.path.join(tmp, "tiny.docx")
        d = Document(); d.add_paragraph("preflight"); d.save(tiny)
        r = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, tiny],
            capture_output=True, timeout=120)
        pdf = os.path.join(tmp, "tiny.pdf")
        if os.path.exists(pdf):
            return [_line(_OK, "LibreOffice", f"конверт DOCX→PDF прошёл ({soffice})")]
        return [_line(_WARN, "LibreOffice", f"конверт не удался (exit {r.returncode})"),
                _line("ДЕЙСТВИЕ", "", "агент: полагаться на Word COM; запасной рендер сломан")]
    except Exception as e:
        return [_line(_WARN, "LibreOffice", f"конверт не удался: {str(e)[:120]}"),
                _line("ДЕЙСТВИЕ", "", "агент: полагаться на Word COM; запасной рендер сломан")]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_format_agent(work):
    """Развернуть format-agent в рабочую папку ИЗ РАНТАЙМА (не из локального
    бандла): источник — <runtime>/<версия>/format-agent, установленный
    Bootstrap'ом по пиннутому коммиту upstream."""
    dst = os.path.join(work, "format-agent-skill")
    if os.path.isdir(dst):
        _line(_OK, "format-agent", dst)
        return
    sys.path.insert(0, _SKILL_DIR)
    import bootstrap
    root = bootstrap._resolve_root()
    m = bootstrap.read_manifest(root)
    ver = (m.get("active") or {}).get("python") if m else None
    src = os.path.join(root, ver, "format-agent") if ver else None
    if not src or not bootstrap.verify_format_agent(src, ignore_pycache=True)[0]:
        _line(_FAIL, "format-agent", "набор в рантайме не готов (нет в манифесте/не сверен)")
        _line("ДЕЙСТВИЕ", "", "агент: запустите Bootstrap — bootstrap.ps1 (Windows) / bootstrap.sh (Linux)")
        return
    try:
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
        _line(_OK, "format-agent", "скопирован из рантайма в %s" % dst)
    except Exception as e:
        _line(_FAIL, "format-agent", "копирование не удалось: %s" % str(e)[:120])
        _line("ДЕЙСТВИЕ", "", "агент: скопировать %s → %s вручную" % (src, dst))


BIZ_NAME = "_ТЗ_"          # бизнес-ТЗ: «Заказчик_ТЗ_{КОД}_V{ВЕРСИЯ}»
TECH_NAME = "Приложение к ТЗ "  # тех-ТЗ: «Приложение к ТЗ {КОД}_V{ВЕРСИЯ}»


def _sample_kind(name):
    if name.startswith("~$"):
        return None  # lock-файл Word
    if name.startswith(TECH_NAME):
        return "tech"
    if BIZ_NAME in name:
        return "biz"
    return "unknown"


def check_samples_layout(work):
    """Классификация образцов по типу (урок 2026-11-20, sess_54d8495b:
    бизнес и тех-образцы вперемешку → модель «тупила»). Эталон (обе
    подпапки, имена маленькими буквами): references/business/ — ТОЛЬКО
    бизнес-образцы, references/tech/ — ТОЛЬКО тех. Исправимое (не в
    своём каталоге) скрипт переносит сам."""
    refs = os.path.join(work, "references")
    if not os.path.isdir(refs):
        return []
    biz = os.path.join(refs, "business")
    tech = os.path.join(refs, "tech")
    out = []
    moves = []  # (src, kind)
    for dirpath, _dirs, files in os.walk(refs):
        for f in files:
            kind = _sample_kind(f)
            if kind is None:
                continue
            here_tech = os.path.normpath(dirpath).lower().endswith(
                os.path.normpath(tech).lower())
            here_biz = os.path.normpath(dirpath).lower().endswith(
                os.path.normpath(biz).lower())
            if kind == "tech" and not here_tech:
                moves.append((os.path.join(dirpath, f), "tech"))
            elif kind == "biz" and not here_biz:
                moves.append((os.path.join(dirpath, f), "biz"))
            elif kind == "unknown":
                out.append(_line(_WARN, "образцы",
                                 f"{os.path.relpath(os.path.join(dirpath, f), work)} — "
                                 f"не образец по шаблону имени; проверить"))
    if moves:
        os.makedirs(tech, exist_ok=True)
        os.makedirs(biz, exist_ok=True)
        for src, kind in moves:
            dst = tech if kind == "tech" else biz
            try:
                import shutil
                shutil.move(src, os.path.join(dst, os.path.basename(src)))
                out.append(_line("ИСПРАВЛЕНО", "образцы",
                                 f"{os.path.basename(src)} → "
                                 f"{os.path.relpath(dst, work)}/ "
                                 f"({'тех-ТЗ (приложение к ТЗ)' if kind == 'tech' else 'бизнес-ТЗ'})"))
            except Exception as e:
                out.append(_line(_FAIL, "образцы",
                                 f"{src}: перенос не удался: {str(e)[:100]}"))
        out.append(_line("ДЕЙСТВИЕ", "",
                         "образцы разложены: references/business/ — "
                         "бизнес-ТЗ (сами ТЗ), references/tech/ — тех-ТЗ "
                         "(приложения к ТЗ); переоценить список образцов "
                         "(Шаг 3) и перезапустить extract"))
    else:
        out.append(_line(_OK, "образцы",
                         "раскладка по типам чиста (references/business/ — "
                         "бизнес-ТЗ (сами ТЗ), references/tech/ — тех-ТЗ "
                         "(приложения к ТЗ))"))
    return out


def check_write(work):
    if not os.path.isdir(work):
        _line(_FAIL, "рабочая папка", "не существует: %s" % work)
        _line("ДЕЙСТВИЕ", "", "уточнить у пользователя путь к рабочей папке")
        return
    try:
        with tempfile.NamedTemporaryFile(dir=work, prefix=".pf_", delete=True):
            pass
        _line(_OK, "рабочая папка", "доступна для записи: %s" % work)
        return True
    except OSError as e:
        _line(_FAIL, "рабочая папка", "не записывается: %s" % str(e)[:120])
        _line("ДЕЙСТВИЕ", "", "вопрос пользователю (права/путь)")
        return False


def check_projects(work):
    from yaml import safe_load  # pyyaml идёт с lxml-окружением редко — защита ниже
    # манифест рядом с work ИЛИ в work/projects/ (обе раскладки встречаются)
    path = next((p for p in (os.path.join(work, "projects.yaml"),
                             os.path.join(work, "projects", "projects.yaml"))
                 if os.path.exists(p)), None)
    if path is None:
        _line(_WARN, "проект", "манифеста нет — проект появится после разбора образцов (Шаг 3)")
        return
    if not os.path.exists(path):
        _line(_WARN, "проект", "манифеста нет — проект появится после разбора образцов (Шаг 3)")
        return
    try:
        with open(path, encoding="utf-8") as f:
            data = safe_load(f) or {}
    except Exception as e:
        _line(_WARN, "проект", "манифест не читается: %s" % str(e)[:120])
        return
    projects = data.get("projects") or []
    names = [p.get("name") for p in projects if isinstance(p, dict) and p.get("name")]
    if not names:
        _line(_WARN, "проект", "манифест пуст — проект появится после разбора образцов")
    elif len(names) == 1:
        _line(_OK, "проект", "один в манифесте: «%s» → задать «Продолжаем проект %s?»" % (names[0], names[0]))
    else:
        _line(_OK, "проект", "несколько в манифесте: %s → показать перечень, выбрать с пользователем" % ", ".join(names))
    # Схема записи: name, customer, created, config{main,ext},
    # doc_type, pii_mode, sample_types — E-56-память проекта.
    # Неизвестные ключи → WARN (схема поплыла, как client/date).
    _KNOWN = {"name", "customer", "created", "config",
              "doc_type", "pii_mode", "sample_types"}
    # E-56: связка 1С и ответы пользователя живут в проекте, а не в
    # переписке; есть → НЕ переспрашивать ни в одной фазе. Мёртвый
    # путь связки → переспросить ОДИН раз (запись есть — папки нет).
    for p in projects:
        if not isinstance(p, dict):
            continue
        unknown = sorted(set(p) - _KNOWN)
        if unknown:
            _line(_WARN, "проект",
                  "«%s»: неизвестные ключи %s — привести к схеме (name, customer, "
                  "created, config{main,ext}, doc_type, pii_mode, sample_types)"
                  % (p.get("name"), ", ".join(unknown)))
        answers = [("doc_type", p.get("doc_type")), ("pii_mode", p.get("pii_mode"))]
        stated = [(k, v) for k, v in answers if v]
        if p.get("sample_types"):
            stated.append(("sample_types", ", ".join(map(str, p["sample_types"]))))
        if stated:
            _line(_OK, "проект", "«%s»: %s — НЕ переспрашивать"
                  % (p.get("name"), "; ".join("%s=%s" % kv for kv in stated)))
        cfg = p.get("config") or {}
        main, ext = cfg.get("main"), cfg.get("ext")
        if main or ext:
            missing = [v for v in (main, ext) if v and not os.path.isdir(v)]
            if missing:
                _line(_WARN, "связка 1С",
                      "проект «%s»: записана, но папки нет: %s → переспросить "
                      "ОДИН раз" % (p.get("name"), "; ".join(missing)))
            else:
                _line(_OK, "связка 1С",
                      "проект «%s»: ext=%s, main=%s (projects.yaml) — "
                      "НЕ переспрашивать" % (p.get("name"), ext, main))


def check_settings(work):
    """settings.yaml — пользовательские настройки (verify_report и др.).
    Нет файла → WARN с готовым содержимым; есть → печатаем состояние."""
    path = os.path.join(work, "settings.yaml")
    if not os.path.exists(path):
        return [_line(_WARN, "settings", "нет settings.yaml → создать в рабочей папке:"),
                _line("ДЕЙСТВИЕ", "", "записать: settings: { verify_report: off }")]
    try:
        from yaml import safe_load
        data = safe_load(open(path, encoding="utf-8")) or {}
        st = data.get("settings") or {}
        return [_line(_OK, "settings", "verify_report=%s (отчёт_проверки.md %s)"
                      % (st.get("verify_report", "off"),
                         "пишется" if st.get("verify_report") else "не пишется"))]
    except Exception as e:
        return [_line(_WARN, "settings", "не читается: %s" % str(e)[:120])]


def check_skills(work, extra_bases=None, bundle_dir=None):
    """Скиллы-зависимости, которые не входят в поставку скилла.
    tz-1c-style (база тона) — ОБЯЗАТЕЛЕН, разворачивается из bundle.
    grilling (самопрожарка Шага 2) — НЕОБЯЗАТЕЛЕН: сторонний скилл, не
    распространяется; отсутствие → WARN, а не FAIL (этап «прожарка»
    недоступен, основные шаги работают без него). Unica —
    MCP-плагин: диагностируется отдельно в check_unica (кэш, рантайм,
    сеть, handshake).
    Портативность (урок 2026-11-19): отсутствующий скилл разворачивается
    САМ из bundle скилла в первую базу (рабочую папку) — рабочая папка
    самодостаточна, глобальные установки не нужны."""
    if hasattr(sys.stdout, "reconfigure"):
        # печать «→» при разворачивании из bundle падает в cp1251-пайп
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if extra_bases:
        bases = list(extra_bases)  # изоляция теста: искать ТОЛЬКО в поданных базах
    else:
        home = os.path.expanduser("~")
        bases = [os.path.join(work, ".zcode", "skills"),
                 os.path.join(home, ".zcode", "skills"),
                 os.path.join(home, ".agents", "skills")]
    if bundle_dir is None:
        bundle_dir = os.path.join(_SKILL_DIR, "bundle")
    out = []
    for name in ("grilling", "tz-1c-style"):
        found = next((b for b in bases
                      if os.path.isfile(os.path.join(b, name, "SKILL.md"))), None)
        if found:
            out.append(_line(_OK, "skills", "%s: %s" % (name, found)))
            continue
        src = os.path.join(bundle_dir, name)
        if os.path.isdir(src):
            try:
                dst = os.path.join(bases[0], name)
                shutil.copytree(src, dst)
                out.append(_line("ИСПРАВЛЕНО", "skills",
                                 "%s: развёрнут из bundle → %s" % (name, dst)))
            except Exception as e:
                out.append(_line(_FAIL, "skills",
                                 "%s: копирование из bundle не удалось: %s"
                                 % (name, str(e)[:120])))
                out.append(_line("ДЕЙСТВИЕ", "",
                                 "агент: скопировать %s → %s вручную" % (src, bases[0])))
            continue
        if name == "grilling":
            out.append(_line(_WARN, "skills",
                             "grilling не установлен и нет в bundle — этап "
                             "«прожарка» (Шаг 2) недоступен; основные шаги "
                             "работают без него"))
            out.append(_line("ДЕЙСТВИЕ", "",
                             "агент: сообщить пользователю, что этап «прожарка» "
                             "недоступен, и продолжить без него"))
            continue
        out.append(_line(_FAIL, "skills",
                         "%s: не найден ни в одной установке (.zcode/skills, "
                         "~/.zcode/skills, ~/.agents/skills) и нет в bundle" % name))
        out.append(_line("ДЕЙСТВИЕ", "",
                         "агент: установить скилл %s (папкой в .zcode/skills или "
                         "~/.agents/skills) до Шага 2" % name))
    return out


# --- Unica (MCP-плагин): диагностика кэша, рантайма, сети, handshake ------
# Пути кэша — механика окружения (не признаки образцов), хардкод допустим;
# версии и состав артефактов — ТОЛЬКО из runtime-manifest.json (не из памяти).

_UNICA_PLUGIN_BASE = os.path.join("~", ".zcode", "cli", "plugins", "cache", "unica", "unica")
_UNICA_RUNTIME_BASE = os.path.join("~", ".zcode", "cli", "plugins", "data", "unica@unica", "runtimes")


def _unica_target():
    """Платформенный таргет артефактов рантайма (win-x64 | linux-x64 | darwin-arm64)."""
    import platform
    sysname, machine = platform.system(), platform.machine()
    if sysname == "Windows":
        return "win-x64"
    if sysname == "Linux":
        return "linux-x64" if machine in ("x86_64", "AMD64") else None
    if sysname == "Darwin":
        return "darwin-arm64" if machine == "arm64" else None
    return None


def _unica_plugin_root(plugin_base=None):
    """Кэш плагина + runtime-manifest.json. Версия — из каталогов (не хардкод).
    Возвращает (plugin_root, manifest_dict); (None, None) — кэша нет."""
    base = os.path.expanduser(plugin_base or _UNICA_PLUGIN_BASE)
    if not os.path.isdir(base):
        return None, None
    versions = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))]
    if not versions:
        return None, None

    def _verkey(v):
        return [int(x) for x in v.split(".") if x.isdigit()] or [0]
    versions.sort(key=_verkey)
    root = os.path.join(base, versions[-1])
    mpath = os.path.join(root, "runtime-manifest.json")
    if not os.path.isfile(mpath):
        return root, None
    try:
        with open(mpath, encoding="utf-8") as f:
            return root, json.load(f)
    except Exception:
        return root, None


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _proxy_host_port(proxy):
    p = proxy
    for pre in ("http://", "https://"):
        if p.lower().startswith(pre):
            p = p[len(pre):]
    host, _, port = p.partition(":")
    try:
        port = int(port)
    except ValueError:
        port = 443
    return host, port


def _check_unica_network(timeout=8):
    """Сеть/прокси: прямой HTTPS → при падении поиск прокси (env, реестр
    Windows) → тест прокси. Возвращает (proxy_url_or_None, [строки отчёта]).
    proxy возвращается, если он найден и TCP-достижим (bootstrap докачает
    через него даже если urllib-тест не подтвердил TLS)."""
    lines = []
    probe = "https://github.com"
    try:
        urllib.request.urlopen(probe, timeout=timeout)
        lines.append(_line(_OK, "Unica network", "прямой HTTPS работает — прокси не нужен"))
        return None, lines
    except Exception as e:
        # В3: прямой HTTPS при рабочем прокси — НЕ блокер (handshake через
        # прокси достаточен для Юники); FAIL вводил в заблуждение
        lines.append(_line(_WARN, "Unica network",
                           "прямой HTTPS заблокирован (не блокер, если handshake через прокси): %s" % str(e)[:60]))
    proxy, src = None, None
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        v = os.environ.get(var)
        if v:
            proxy, src = v, "env %s" % var
            break
    if proxy is None:
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                               r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
            ps = winreg.QueryValueEx(k, "ProxyServer")[0]
            if ps:
                proxy, src = "http://" + ps, "реестр ProxyServer"
        except Exception:
            pass
    if proxy is None:
        lines.append(_line(_FAIL, "Unica network", "прокси не найден (env и реестр)"))
        return None, lines
    host, port = _proxy_host_port(proxy)
    tcp_ok = False
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        tcp_ok = True
    except Exception:
        pass
    https_ok = False
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler(
            {"http": proxy, "https": proxy}))
        op.open(probe, timeout=timeout)
        https_ok = True
    except Exception:
        pass
    if https_ok:
        lines.append(_line(_OK, "Unica network", "прокси жив: %s (%s)" % (proxy, src)))
    elif tcp_ok:
        lines.append(_line(_WARN, "Unica network",
                           "прокси TCP-достижим, TLS не подтверждён: %s (%s)" % (proxy, src)))
    else:
        # Прокси не отвечает даже по TCP — состояние СРЕДЫ, не блокер:
        # шаблон ТЗ строится из локальных образцов, сеть нужна только
        # для докачки рантайма Unica (отдельный шаг со своим отчётом).
        lines.append(_line(_WARN, "Unica network",
                           "прокси недоступен: %s (%s) — не блокер для сборки "
                           "шаблона" % (proxy, src)))
        return None, lines
    return proxy, lines


def _unica_bootstrap(plugin_root, target):
    exe = "unica-bootstrap.exe" if target == "win-x64" else "unica-bootstrap"
    return os.path.join(plugin_root, "bootstrap", "bin", target, exe)


def _unica_prefetch(plugin_root, target, proxy, timeout=300):
    """Докачка рантайма: bootstrap prefetch с прокси в окружении subprocess.
    Возвращает True, если bootstrap завершился с кодом 0."""
    boot = _unica_bootstrap(plugin_root, target)
    if not os.path.isfile(boot):
        return False
    env = dict(os.environ)
    if proxy:
        for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
            env[k] = proxy
    try:
        r = subprocess.run([boot, "prefetch", "--plugin-root", plugin_root],
                           capture_output=True, timeout=timeout, env=env)
        return r.returncode == 0
    except Exception:
        return False


def _check_unica_handshake(plugin_root, target, timeout=45):
    """Живой handshake MCP-сервера: bootstrap run + initialize (таймаут,
    preflight не должен вешаться). Возвращает [строки отчёта]."""
    boot = _unica_bootstrap(plugin_root, target)
    if not os.path.isfile(boot):
        return [_line(_FAIL, "Unica handshake", "bootstrap-бинарник отсутствует")]
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                 "clientInfo": {"name": "preflight", "version": "1.0"}}})
    try:
        import threading
        proc = subprocess.Popen([boot, "run", "--plugin-root", plugin_root],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        first = []

        def _read():
            line = proc.stdout.readline()
            if line:
                first.append(line)
        proc.stdin.write((req + "\n").encode("utf-8"))
        proc.stdin.flush()
        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout=timeout)
        proc.stdin.close()
        proc.terminate()
        if first:
            try:
                resp = json.loads(first[0].decode("utf-8"))
                si = (resp.get("result") or {}).get("serverInfo")
                if si:
                    return [_line(_OK, "Unica handshake",
                                  "initialize OK: %s v%s" % (si.get("name"), si.get("version")))]
                return [_line(_FAIL, "Unica handshake", "ответ без serverInfo")]
            except Exception as e:
                return [_line(_FAIL, "Unica handshake", "ответ не распарсен: %s" % str(e)[:80])]
        return [_line(_FAIL, "Unica handshake", "нет ответа за %d с" % timeout)]
    except Exception as e:
        return [_line(_FAIL, "Unica handshake", "запуск не удался: %s" % str(e)[:80])]


def _unica_index_verdict(msg):
    """Вердикт по ответу пробы: OK — результат; WARN — ошибка RPC или
    invalid_state (невалидный v8project.yaml — 2026-11-22). Ответ есть,
    но это НЕ «индекс готов»."""
    txt = ""
    if "error" in msg:
        return ("WARN",
                "проба вернула ошибку: %s" % json.dumps(msg["error"], ensure_ascii=False)[:120])
    for c in (msg.get("result", {}) or {}).get("content", []) or []:
        if isinstance(c, dict):
            txt += c.get("text", "")
    if "invalid_state" in txt or "is present but invalid" in txt:
        return ("WARN", "конфигурация проекта невалидна (invalid_state)")
    return ("OK", "")


def _check_unica_index(plugin_root, target, work, timeout=120):
    """В1: прогрев индекса Юники с гейтом готовности. initialize + первый
    unica_search (частый дедлайн на свежей рабочей папке — индекс строится
    минуты). Готово → [OK]; не готово за таймаут → [WARN] + штатный
    фолбэк «скан по выгрузке с пометкой». Preflight не вешается."""
    exe = os.path.join(plugin_root, "bootstrap", "bin", target,
                       "unica-bootstrap.exe"
                       if target == "win-x64" else "unica-bootstrap")
    init_req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2024-11-05",
                                      "capabilities": {},
                                      "clientInfo": {"name": "preflight",
                                                     "version": "1.0"}}})
    search_req = json.dumps({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "unica.search",  # канонический профиль bootstrap (v0.13)
                   "arguments": {"query": "Конфигурация", "limit": 1}}})
    try:
        import threading
        proc = subprocess.Popen(
            [exe, "run", "--plugin-root", plugin_root],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=work)
        resp = {}

        def _read(want_id):
            for line in proc.stdout:
                try:
                    msg = json.loads(line.decode("utf-8"))
                except Exception:
                    continue
                if msg.get("id") == want_id:
                    resp[want_id] = msg
                    return

        proc.stdin.write((init_req + "\n").encode("utf-8"))
        proc.stdin.flush()
        t1 = threading.Thread(target=_read, args=(1,), daemon=True)
        t1.start()
        t1.join(timeout=timeout)
        if 1 not in resp:
            proc.stdin.close(); proc.terminate()
            return [_line(_WARN, "Unica index",
                          "initialize не ответил за %d с — фолбэк: скан по выгрузке (cf/cfe) с пометкой в отчёте версии" % timeout)]
        proc.stdin.write((search_req + "\n").encode("utf-8"))
        proc.stdin.flush()
        t2 = threading.Thread(target=_read, args=(2,), daemon=True)
        t2.start()
        t2.join(timeout=timeout)
        proc.stdin.close()
        proc.terminate()
        if 2 in resp:
            status, why = _unica_index_verdict(resp[2])
            if status == "OK":
                return [_line(_OK, "Unica index",
                              "индекс готов — первый unica_search отвечает")]
            return [_line(_WARN, "Unica index", why + " — фолбэк: скан по выгрузке (cf/cfe) с пометкой в отчёте версии")]
        return [_line(_WARN, "Unica index",
                      "индекс ещё строится (первый unica_search не ответил за %d с) — скан НЕ начинать; фолбэк: скан по выгрузке (cf/cfe) с пометкой в отчёте версии" % timeout)]
    except Exception as e:
        return [_line(_WARN, "Unica index",
                      "прогрев не удался: %s — фолбэк: скан по выгрузке (cf/cfe) с пометкой" % str(e)[:80])]


def _check_unica_v8project(work):
    """v8project.yaml в рабочей папке: наличие + валидность путей cf/cfe."""
    path = os.path.join(work, "v8project.yaml")
    if not os.path.isfile(path):
        return [_line(_WARN, "Unica v8project", "нет v8project.yaml — создаст find_config (Шаг 1 п.4)")]
    try:
        from yaml import safe_load
        data = safe_load(open(path, encoding="utf-8")) or {}
    except Exception as e:
        return [_line(_WARN, "Unica v8project", "не читается: %s" % str(e)[:120])]
    out = []
    abs_paths = {}  # name -> абсолютный путь
    for ss in (data.get("source-set") or []):
        if not isinstance(ss, dict):
            continue
        p = ss.get("path")
        if not p:
            continue
        # относительный путь — от каталога v8project.yaml (рабочая папка)
        full = p if os.path.isabs(p) else os.path.normpath(os.path.join(work, p))
        abs_paths[ss.get("name")] = full
        if not os.path.isdir(full):
            out.append(_line(_FAIL, "Unica v8project",
                             "%s: путь не существует: %s" % (ss.get("name"), p)))
    if not out:
        # run-59 (Часть E): готовая строка копипаста для find_config
        out.append(_line(_OK, "Unica v8project",
                         "пути cf/cfe валидны; копипаст: "
                         "--config ext=%s --config main=%s"
                         % (abs_paths.get("cfe", ""), abs_paths.get("main", ""))))
    return out


def _check_unica_plugin_link(plugin_base=None, config_path=None):
    """preflight-restart-check (2026-11-22): связка плагин unica ↔ клиент
    ZCode — скриптовый вердикт о перезапуске. Единственная легитимная
    причина рестарта — FAIL связки (не подключён / версия кэша ≠
    заявленной). Возвращает (lines, ok)."""
    import json as _json
    lines = []
    if plugin_base and not config_path:
        # инъекция (тесты/подмена кэша без своего config.json) — связка
        # с реальным config.json не проверяется: сравнение было бы
        # ложным FAIL. Полная проверка — plugin_base=None (прод) или
        # config_path задан явно (тест связки).
        return [], True
    cfg_path = config_path or os.path.join(
        "~", ".zcode", "cli", "config.json")
    cfg_path = os.path.expanduser(cfg_path)
    base = os.path.expanduser(plugin_base or _UNICA_PLUGIN_BASE)
    declared_version = None
    enabled = False
    try:
        cfg = _json.load(open(cfg_path, encoding="utf-8"))
    except Exception as e:
        lines.append(_line(_FAIL, "Unica link",
                           "config.json клиента не читается: %s" % str(e)[:100]))
        lines.append(_line("ДЕЙСТВИЕ", "", "перезапусти ZCode после установки плагина"))
        return lines, False
    blob = _json.dumps(cfg, ensure_ascii=False)

    bs = chr(92)
    # класс [\/] — в charclass бэкслеш должен быть экранирован (bs+bs):
    # bs + "/]" даёт [\/] = {/} и НЕ матчит разделитель (дефект найден тестом)
    ver_re = re.compile("unica[" + bs + bs + "/](" + bs + "d+" + bs + "."
                        + bs + "d+" + bs + "." + bs + "d+)")
    def _walk(o):
        nonlocal declared_version, enabled
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "unica@unica":
                    enabled = True
                    if isinstance(v, dict):
                        declared_version = v.get("version") or declared_version
                if k == "command" and isinstance(v, str):
                    m = ver_re.search(v)
                    if m:
                        declared_version = m.group(1)
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)
    _walk(cfg)
    if not enabled:
        lines.append(_line(_FAIL, "Unica link",
                           "плагин unica не подключён в config.json клиента"))
        lines.append(_line("ДЕЙСТВИЕ", "", "перезапусти ZCode после установки"))
        return lines, False

    versions = [d for d in (os.listdir(base) if os.path.isdir(base) else [])
                if os.path.isdir(os.path.join(base, d))]
    cache_version = max(versions, key=lambda v: [int(x) for x in v.split(".") if x.isdigit()]) if versions else None
    if cache_version and declared_version and cache_version != declared_version:
        lines.append(_line(_FAIL, "Unica link",
                           "обновление не применено: кэш v%s, заявлено v%s"
                           % (cache_version, declared_version)))
        lines.append(_line("ДЕЙСТВИЕ", "", "перезапусти ZCode"))
        return lines, False
    lines.append(_line(_OK, "Unica link",
                       "плагин подключён (v%s) — перезапуск не требуется — работать"
                       % (cache_version or "?")))
    return lines, True


def check_unica(work, plugin_base=None, runtime_base=None, proxy=None,
                do_handshake=True, network=None):
    """Диагностика Unica (MCP-плагин) одним вызовом: кэш плагина, кэш
    рантайма (целостность + рассинхрон .ready.json), v8project.yaml,
    сеть/прокси, живой handshake. Авто-исправление: рантайм отсутствует и
    есть живой прокси → докачка через него (bootstrap prefetch). Плоский
    отчёт [OK]/[FAIL]/[ДЕЙСТВИЕ]/[ИСПРАВЛЕНО]; интерактив — нет."""
    lines = []
    link_lines, _link_ok = _check_unica_plugin_link(plugin_base)
    lines.extend(link_lines)
    plugin_root, manifest = _unica_plugin_root(plugin_base)
    if plugin_root is None:
        lines.append(_line(_FAIL, "Unica", "кэш плагина не найден: %s" % os.path.expanduser(_UNICA_PLUGIN_BASE)))
        lines.append(_line("ДЕЙСТВИЕ", "", "агент: установить плагин Unica (marketplace) и перезапустить сессию"))
        return lines
    target = _unica_target()
    version = (manifest or {}).get("pluginVersion", "?")
    lines.append(_line(_OK, "Unica", "кэш плагина: %s (v%s, target %s)"
                       % (plugin_root, version, target)))
    if manifest is None:
        lines.append(_line(_FAIL, "Unica", "runtime-manifest.json не читается"))
        lines.append(_line("ДЕЙСТВИЕ", "", "агент: переустановить плагин Unica"))
        return lines
    # компоненты кэша плагина
    for comp, desc in ((".mcp.json", "MCP-конфиг"), ("bootstrap", "bootstrap"),
                       ("runtime-manifest.json", "манифест")):
        p = os.path.join(plugin_root, comp)
        if os.path.exists(p):
            lines.append(_line(_OK, "Unica plugin", "%s: %s" % (desc, p)))
        else:
            lines.append(_line(_FAIL, "Unica plugin", "%s отсутствует: %s" % (desc, p)))
    boot = _unica_bootstrap(plugin_root, target)
    if os.path.isfile(boot):
        lines.append(_line(_OK, "Unica bootstrap", boot))
    else:
        lines.append(_line(_FAIL, "Unica bootstrap", "бинарник для %s отсутствует: %s" % (target, boot)))
        lines.append(_line("ДЕЙСТВИЕ", "", "агент: переустановить плагин Unica"))
        return lines
    # кэш рантайма: бинарники по манифесту + целостность + рассинхрон
    rbase = os.path.expanduser(runtime_base or _UNICA_RUNTIME_BASE)
    missing = []
    for artifact, art in (manifest.get("artifacts") or {}).items():
        t = (art.get("targets") or {}).get(target)
        if not t:
            continue
        ver = art.get("version")
        sha = (t.get("asset") or {}).get("sha256")
        art_dir = os.path.join(rbase, artifact, "%s--%s" % (ver, sha), target)
        ready = os.path.join(art_dir, ".ready.json")
        bad = None
        for f in (t.get("files") or []):
            fp = os.path.join(art_dir, f["path"])
            if not os.path.isfile(fp):
                bad = ("рассинхрон: .ready.json заявляет готовность, но %s нет" % f["path"]
                       if os.path.exists(ready) else "%s отсутствует" % f["path"])
                break
            if _sha256(fp) != f.get("sha256"):
                bad = "%s: хеш не совпадает" % f["path"]
                break
        if bad:
            missing.append(artifact)
            lines.append(_line(_FAIL, "Unica runtime", "%s: %s" % (artifact, bad)))
        else:
            lines.append(_line(_OK, "Unica runtime",
                               "%s v%s: %d файл(ов) проверено" % (artifact, ver, len(t.get("files") or []))))
    # незавершённые докачки (.partial с содержимым)
    partial = os.path.join(rbase, ".partial")
    if os.path.isdir(partial):
        for sub in sorted(os.listdir(partial)):
            sp = os.path.join(partial, sub)
            if os.path.isdir(sp) and os.listdir(sp):
                lines.append(_line(_WARN, "Unica runtime",
                                   "незавершённая докачка: .partial/%s" % sub))
    # v8project.yaml
    lines.extend(_check_unica_v8project(work))
    # сеть/прокси
    if network is not None:
        proxy, net_lines = network
    else:
        proxy, net_lines = _check_unica_network()
    lines.extend(net_lines)
    # авто-исправление: рантайм отсутствует + живой прокси → докачка
    if missing:
        if proxy:
            lines.append(_line("ДЕЙСТВИЕ", "",
                               "докачиваю рантайм через прокси %s (bootstrap prefetch)…" % proxy))
            if _unica_prefetch(plugin_root, target, proxy):
                lines.append(_line("ИСПРАВЛЕНО", "Unica runtime",
                                   "рантайм докачан через прокси %s" % proxy))
            else:
                lines.append(_line(_FAIL, "Unica runtime", "докачка через прокси не удалась"))
                lines.append(_line("ДЕЙСТВИЕ", "", "агент: доложить пользователю (прокси не докачал)"))
        else:
            lines.append(_line("ДЕЙСТВИЕ", "",
                               "агент: рантайм отсутствует, живого прокси нет — доложить пользователю"))
    # живой handshake (финальная проверка «Unica работает»)
    if do_handshake:
        lines.extend(_check_unica_handshake(plugin_root, target))
    # В1: прогрев индекса с гейтом готовности — при живом v8project.yaml
    if os.path.isfile(os.path.join(work, "v8project.yaml")):
        lines.extend(_check_unica_index(plugin_root, target, work))
    return lines


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, help="рабочая папка проекта пользователя")
    ap.add_argument("--harness", default="zcode", choices=["zcode", "claude-code", "codex", "other"])
    args = ap.parse_args()

    print("== PREFLIGHT tz-rezultat-hz ==")
    check_harness(args.harness)
    check_runtime()
    check_word_com()
    check_libreoffice()
    ok = check_write(args.work)
    if ok:
        check_settings(args.work)
        check_skills(args.work)
        # В2: find_config ДО проверки Юники — если v8project.yaml создан
        # (exit 42, нужен перезапуск), ни один вызов Unica не тратится:
        # полный потерянный круг «preflight → unica → перезапуск» исключён
        fc = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "find_config.py")
        fc_args = [sys.executable, "-I", fc, "--path", args.work,
                   "--work", args.work, "--harness", args.harness]
        try:
            r = subprocess.run(fc_args, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=120)
            if (r.stdout or "").strip():
                print(r.stdout.strip())
            if (r.stderr or "").strip():
                print(r.stderr.strip(), file=sys.stderr)
            if r.returncode == 42:
                sys.exit(42)
        except Exception as e:
            print("[ДЕЙСТВИЕ] find_config не выполнен: %s — Шаг 1 п.4 запустит его сам" % str(e)[:80])
        check_unica(args.work)
        check_format_agent(args.work)
        check_projects(args.work)
        # раскладка образцов: строки уже напечатаны внутри (_line печатает
        # сразу); раньше здесь было обращение к несуществующему OUT —
        # NameError в конце отчёта (дефект 2026-11-20, живой прогон)
        check_samples_layout(args.work)
        # раскладка проектов (урок 2026-11-19): исправимое скрипт делает сам
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import check_layout
        if os.path.exists(os.path.join(args.work, "projects")):
            check_layout.OUT.clear()
            for name in sorted(os.listdir(os.path.join(args.work, "projects"))):
                p = os.path.join(args.work, "projects", name)
                if os.path.isdir(p):
                    check_layout.check_project(p, args.work)
            for _ln in check_layout.OUT:
                print(_ln)
    print("== КОНЕЦ ОТЧЁТА: действуй по строкам [FAIL]/[ДЕЙСТВИЕ]; "
          "все устранимые — сам, остальные — вопрос пользователю; "
          "итоговый отчёт — в первом сообщении ==")


if __name__ == "__main__":
    main()
