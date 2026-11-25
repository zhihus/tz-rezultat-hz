#!/bin/sh
# Сборка one-file бинарника tz-tool (Linux) — v4 §16.
# Кросс-компиляция ненадёжна: бинарник под Linux собирается на Linux (CI: два раннера).
set -e
python3 -m pip install nuitka ordered-set
python3 -m nuitka --onefile \
    --include-module=extract_spec \
    --include-module=build_from_spec \
    --include-module=verify_template \
    --output-filename=tz-tool \
    tz_tool.py
echo "Готово: dist/tz-tool (или tz-tool.dist/tz-tool в зависимости от версии Nuitka)"