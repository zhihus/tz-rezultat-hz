@echo off
rem Сборка one-file бинарника tz-tool.exe (Windows) — v4 §16.
rem Кросс-компиляция ненадёжна: бинарник под Windows собирается на Windows (CI: два раннера).
python -m pip install nuitka ordered-set
python -m nuitka --onefile --windows-console-mode=force ^
    --include-module=extract_spec ^
    --include-module=build_from_spec ^
    --include-module=verify_template ^
    --output-filename=tz-tool.exe ^
    tz_tool.py
echo.
echo Готово: dist\tz-tool.exe (или tz-tool.dist/tz-tool.exe в зависимости от версии Nuitka)