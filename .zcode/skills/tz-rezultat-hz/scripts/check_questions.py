# -*- coding: utf-8 -*-
"""check_questions.py — гейт журнала вопросов ДО гейта §6
(question-necessity-gate, 2026-11-22).

Валидирует `вопросы_ответы_<КОД>.md` (Шаг 2, п.3в):
  1. КАЖДЫЙ содержательный вопрос несёт метку класса в строке вопроса:
     [ANSWERABLE] (снят выгрузкой/Unica/исследованием — источник указан)
     | [USER-ONLY] (знание только у аналитика) | [DIVERGENT] (несколько
     решений — chosen/alternative); организационные вопросы Шага 3 —
     [ORG]. Без метки → FAIL.
  2. Ответ закрыт только при строке «Источник:» → без неё FAIL.
  3. Кросс-сверка с выгрузкой: [USER-ONLY]/[DIVERGENT]-вопрос, чей текст
     упоминает объект выгрузки («Вид.Имя» или camelCase/underscore-id,
     найденный в cf/cfe через _config_lookup) → FAIL «снимается
     выгрузкой — вернуться к исследованию». Нет --config →
     [ПРЕДУПРЕЖДЕНИЕ], не FAIL (бизнес-проект без связки не блокируется).
  4. Дубликаты: два вопроса с одинаковым нормализованным текстом → FAIL.
  5. Сводка по классам для финального отчёта.
  6. Глубина absence-claim: [USER-ONLY]/[DIVERGENT]-ответ с «не найдено в
     конфигурации» без упоминания расширения (cfe) или caller-based поиска
     (ОткрытьФорму/обработчики) → [ПРЕДУПРЕЖДЕНИЕ] «ответ поверхностный —
     дожать исследование» (non-blocking, не блокирует гейт §6).

Код возврата 1 при нарушениях, 0 если чисто (пустой журнал тоже 0 —
вопросов могло не быть).

Вызов: python check_questions.py <журнал.md> --spec <spec.json>
       [--config ext=<cfe>] [--config main=<cf>]
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lint_draft import _config_lookup, _KIND_DIRS  # единая правда по выгрузке

_CLASSES = ("ANSWERABLE", "USER-ONLY", "DIVERGENT", "ORG")
_CLASS_RE = re.compile(r"\[(" + "|".join(_CLASSES) + r")\]", re.IGNORECASE)
_Q_RE = re.compile(r"^[^«\"]*[Вв]опрос[^«\"]*:")
_KINDS_RU = sorted(_KIND_DIRS.keys())
_QUALIFIED_RE = re.compile(
    r"(?:" + "|".join(_KINDS_RU) + r")\.[А-Яа-яёЁA-Za-z0-9_]+")
# bare-id: ≥4 символа, внутренняя заглавная (camelCase) или «_» —
# отсекает обычные русские слова («Какая», «периодичность»)
_BARE_RE = re.compile(r"[А-Яа-яёЁA-Za-z0-9_]{4,}")
# absence-claim: ответ утверждает, что объект не найден в конфигурации
_ABSENCE_RE = re.compile(
    r"не\s+найдено\s+в\s+конфигурации|не\s+нашёл|отсутствует\s+в\s+конфигурации"
    r"|не\s+обнаружено", re.IGNORECASE)
# depth-markers: ответ ссылается на расширение (cfe) или на caller-based
# поиск (ОткрытьФорму / обработчики) → absence-claim считается глубоким
_DEPTH_RE = re.compile(r"cfe|расширение|ОткрытьФорму|обработчик",
                       re.IGNORECASE)


def _bare_candidates(text):
    out = []
    for tok in _BARE_RE.findall(text):
        core = tok[1:]
        if "_" in tok or any(c.isupper() for c in core):
            out.append(tok)
    return sorted(set(out))


def _in_export(config_paths, token):
    """Токен найден в выгрузке (по любому виду) → источник/label."""
    for kind in _KINDS_RU:
        hit = _config_lookup(config_paths, f"{kind}.{token}", None)
        if hit:
            return hit
    return None


def parse_ledger(text):
    """→ список вопросов: dict(line_no, text, cls, has_source, answer)."""
    questions = []
    cur = None
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if _Q_RE.search(line) and "?" in line:
            m = _CLASS_RE.search(line)
            cur = {"line_no": i, "text": line, "cls": m.group(1).upper()
                   if m else None, "has_source": False, "answer": ""}
            questions.append(cur)
        elif cur is not None and re.match(r"^Источник\s*:", line,
                                          re.IGNORECASE):
            cur["has_source"] = True
        elif cur is not None and re.match(r"^Ответ\s*:", line,
                                          re.IGNORECASE):
            cur["answer"] = line
        elif cur is not None and _Q_RE.search(line):
            cur = None
    return questions


def check_questions(ledger_path, config_paths):
    problems, warnings = [], []
    with open(ledger_path, encoding="utf-8") as fh:
        text = fh.read()
    questions = parse_ledger(text)
    counts = {c: 0 for c in _CLASSES}
    if not questions:
        print("[ВОПРОСЫ] журнал без вопросов (вопросов не было) — чисто.")
        return problems, warnings, counts

    seen = {}
    for q in questions:
        if q["cls"] is None:
            problems.append(
                f"[ВОПРОСЫ] строка {q['line_no']}: вопрос без метки класса "
                f"{list(_CLASSES)} → поставить метку; без метки гейт §6 не "
                f"проходится.")
        else:
            counts[q["cls"]] += 1
            if q["cls"] != "ORG" and not q["has_source"]:
                problems.append(
                    f"[ВОПРОСЫ] строка {q['line_no']}: вопрос закрыт без "
                    f"«Источник:» → записать источник ответа (аналитик/"
                    f"выгрузка/Unica).")
            if q["cls"] in ("USER-ONLY", "DIVERGENT"):
                qualified = _QUALIFIED_RE.findall(q["text"])
                for token in qualified + _bare_candidates(q["text"]):
                    hit = (_config_lookup(config_paths, token, None)
                           if "." in token else _in_export(config_paths, token))
                    if hit:
                        problems.append(
                            f"[ВОПРОСЫ] строка {q['line_no']}: вопрос "
                            f"[{q['cls']}] упоминает «{token}», найденный в "
                            f"выгрузке «{hit['source']}» → ответ снимается "
                            f"выгрузкой: вернуться к исследованию, вопрос "
                            f"задавать НЕ нужно.")
                        break
                # depth check: absence-claim без доказательной глубины
                # (расширение cfe или caller-based поиск) → non-blocking
                # [ПРЕДУПРЕЖДЕНИЕ] в сводке
                if (q["answer"] and _ABSENCE_RE.search(q["answer"])
                        and not _DEPTH_RE.search(q["answer"])):
                    warnings.append(
                        f"[ПРЕДУПРЕЖДЕНИЕ] строка {q['line_no']}: ответ "
                        f"[{q['cls']}] — absence-claim без упоминания "
                        f"расширения (cfe) или caller-based поиска "
                        f"(ОткрытьФорму/обработчики) → ответ поверхностный — "
                        f"дожать исследование (non-blocking, гейт §6 не "
                        f"блокируется).")
        # тело вопроса = после первого «:» (отбрасывает «Вопрос N [класс]:»)
        body = q["text"].split(":", 1)[-1]
        norm = re.sub(r"\[[^\]]+\]|[^а-яёa-z0-9 ]", "",
                      body.lower())
        norm = " ".join(norm.split())
        if norm and norm in seen:
            problems.append(
                f"[ВОПРОСЫ] строка {q['line_no']}: повтор вопроса из строки "
                f"{seen[norm]} → не переспрашивать (EVPI-lite).")
        else:
            seen[norm] = q["line_no"]

    if not config_paths:
        warnings.append("[ПРЕДУПРЕЖДЕНИЕ] выгрузка не передана (--config): "
                        "кросс-сверка «снимается выгрузкой» недоступна — "
                        "для тех-ТЗ связка обязательна (§5 question-packs).")
    return problems, warnings, counts


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("ledger", help="вопросы_ответы_<КОД>.md")
    ap.add_argument("--spec", default=None)
    ap.add_argument("--config", action="append", default=[],
                    help="выгрузка 1С «метка=путь» (ext|main); расширение — ПЕРВЫМ")
    ap.add_argument("--progress", default=None,
                    help="прогресс.json — записать вердикт шага 2 при коде 0")
    args = ap.parse_args()
    config_paths = []
    for c in args.config:
        label, _, path = c.partition("=")
        config_paths.append((label or "main", path))
    problems, warnings, counts = check_questions(args.ledger, config_paths)
    for w in warnings:
        print(w)
    if problems:
        for p in problems:
            print(p)
    total = sum(counts.values())
    print(f"[сводка] вопросов: {total} "
          f"(ANSWERABLE: {counts['ANSWERABLE']}, USER-ONLY: {counts['USER-ONLY']}, "
          f"DIVERGENT: {counts['DIVERGENT']}, ORG: {counts['ORG']})")
    if problems:
        print("[ИТОГ] журнал вопросов не чист → выполнить предписания; гейт §6 "
              "не проходится, пока check_questions не вернёт код 0.")
        sys.exit(1)
    print("[ИТОГ] журнал вопросов чист → гейт §6 разрешён.")
    # process-flow: шаг 2 закрыт записью гейта в прогресс.json (не моделью)
    from tz_common import record_progress
    record_progress(args.progress, "2", "check_questions", "PASS", [args.ledger])


if __name__ == "__main__":
    main()
