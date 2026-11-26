# -*- coding: utf-8 -*-
"""Регрессионные тесты контракта Harness в preflight.py.

Запуск: python tests/test_preflight_harness.py
"""
import contextlib
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.abspath(os.path.join(
    HERE, "..", ".zcode", "skills", "tz-rezultat-hz"))
sys.path.insert(0, SKILL_DIR)

import preflight  # noqa: E402


def capture(harness):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        preflight.check_harness(harness)
    return output.getvalue()


def run(name, condition):
    print(f"[{'PASS' if condition else 'FAIL'}] {name}")
    return bool(condition)


results = []

zcode = capture("zcode")
results.append(run(
    "ZCode is WARN, never a false OK",
    "[WARN] харнесс:" in zcode and "[OK  ] харнесс:" not in zcode))
results.append(run(
    "ZCode requires live main-agent tool verification",
    "AskUserQuestion" in zcode and "ОСНОВНОГО агента" in zcode))
results.append(run(
    "ZCode blocks text fallback and requires auto-resolution OFF",
    "текстовый fallback запрещён" in zcode
    and "askUserQuestionAutoResolutionEnabled выключен" in zcode))

claude = capture("claude-code")
results.append(run(
    "Claude Code retains its interactive-tool status",
    "[OK  ] харнесс:" in claude and "вопросы инструментом" in claude))

codex = capture("codex")
results.append(run(
    "Codex retains its documented text-question route",
    "[OK  ] харнесс:" in codex and "вопросы ТОЛЬКО текстом" in codex))

unknown = capture("unknown")
results.append(run(
    "Unknown harness remains a failure",
    "[FAIL] харнесс:" in unknown))

failed = [index for index, passed in enumerate(results, 1) if not passed]
print(f"\nИТОГ: {'PASS' if not failed else 'FAIL'} "
      f"({len(results) - len(failed)}/{len(results)})")
sys.exit(1 if failed else 0)
