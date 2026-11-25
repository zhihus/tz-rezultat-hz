# ============================================================
# bootstrap.ps1 — первый запуск tz-rezultat-hz БЕЗ Python (Windows).
#
# Печатает перечень компонентов полного комплекта. Установка идёт ТОЛЬКО
# по явному режиму -Full: без него скрипт показывает перечень и ждёт
# подтверждения пользователя (exit 4), НИЧЕГО не скачивая.
#
# В режиме -Full: скачивает python-build-standalone (pinned-релиз), сверяет
# SHA-256 с зафиксированным пином, распаковывает, ставит изоляцию
# (python311._pth + DLL pywin32), затем вызывает bootstrap.py на свежем
# интерпретаторе — зависимости, format-agent (upstream, пиннутый коммит)
# и grilling (upstream, пиннутый коммит, MIT).
#
# Пины НИЖЕ ДОЛЖНЫ совпадать с bootstrap.py (PBS_RELEASE / PY_VERSION /
# SHA-256 win-x64), а перечень компонентов — с components.ru.md.
# Дублирование намеренное: скрипт работает до появления Python и не может
# читать bootstrap.py. Файл сохранён в UTF-8 С BOM — Windows PowerShell 5.1
# иначе читает русский текст как ANSI (кракозябры в выводе).
#
# Запуск:  powershell -ExecutionPolicy Bypass -File bootstrap.ps1 [-Plan] [-Full] [-NoGrilling]
#   -Plan        — показать перечень компонентов и выйти
#   -Full        — установить ПОЛНЫЙ комплект (рекомендуется)
#   -NoGrilling  — НЕ рекомендуется: без grilling (аналитика будет неполноценной)
# ============================================================
param(
    [switch]$Plan,
    [switch]$Full,
    [switch]$NoGrilling
)
$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

# --- пины (должны совпадать с bootstrap.py) ---
$PBS_RELEASE = "20261124"
$PY_VERSION  = "3.11.18"
$PY_DIRNAME  = "py31118-$PBS_RELEASE"
$ARCHIVE     = "cpython-$PY_VERSION+$PBS_RELEASE-x86_64-pc-windows-msvc-install_only.tar.gz"
$SHA256      = "3e4a35e3c238e5090d36bf95c041d9052bc82d6e298cb912ba7f70f6c66cf81a"
$PBS_BASE    = "https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_RELEASE/"

$SkillDir    = $PSScriptRoot
$BootstrapPy = Join-Path $SkillDir "bootstrap.py"
$PlanFile    = Join-Path $SkillDir "components.ru.md"

function Show-Plan {
    Get-Content -Encoding UTF8 -Path $PlanFile
}

# --- runtime_root (скилл → кэш ОС) ---
function Test-Writable([string]$dir) {
    try {
        $probe = Join-Path $dir ".bootstrap_wtest"
        [System.IO.File]::WriteAllText($probe, "x")
        Remove-Item $probe -Force
        return $true
    } catch { return $false }
}
$SkillRuntime = Join-Path $SkillDir "runtime"
if ((Test-Path $SkillRuntime -PathType Container) -or (Test-Writable $SkillDir)) {
    $RuntimeRoot = $SkillRuntime
} else {
    $base = $env:LOCALAPPDATA
    if (-not $base) { $base = $env:USERPROFILE }
    $RuntimeRoot = Join-Path $base "tz-rezultat-hz\runtime"
}
New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

$VerDir  = Join-Path $RuntimeRoot $PY_DIRNAME
$PyDir   = Join-Path $VerDir "python"
$PyExe   = Join-Path $PyDir "python.exe"
$Staging = Join-Path $RuntimeRoot ".staging"
$Arc     = Join-Path $Staging $ARCHIVE

Write-Host "== BOOTSTRAP tz-rezultat-hz (ps1) =="
Write-Host "runtime_root: $RuntimeRoot"

if ($Plan) { Show-Plan; exit 0 }

# --- рантайм уже готов ПОЛНЫМ комплектом? ---
if (Test-Path $PyExe) {
    & $PyExe $BootstrapPy --root $RuntimeRoot --check
    if ($LASTEXITCODE -eq 0) { exit 0 }
}

# --- режим не задан → показать перечень и ЖДАТЬ подтверждения ---
if (-not $Full -and -not $NoGrilling) {
    Show-Plan
    Write-Host "[ОЖИДАНИЕ] подтверждение пользователя: повторите запуск с -Full (полный комплект, рекомендуется)"
    exit 4
}
if ($NoGrilling) {
    Write-Host "[ВНИМАНИЕ] установка БЕЗ grilling: самопроверка Шага 2 недоступна, АНАЛИТИКА НЕПОЛНОЦЕННА"
}

# --- скачивание (curl.exe; .part → rename) ---
New-Item -ItemType Directory -Force -Path $Staging | Out-Null
if (-not (Test-Path $Arc)) {
    Write-Host "  скачиваю $ARCHIVE …"
    & curl.exe -sSL --fail --retry 3 --max-time 600 -o "$Arc.part" "$PBS_BASE$ARCHIVE"
    if ($LASTEXITCODE -ne 0) { throw "curl: скачивание не удалось" }
    Move-Item "$Arc.part" $Arc -Force
}

# --- проверка SHA-256 с пином ---
$got = (Get-FileHash -Algorithm SHA256 -Path $Arc).Hash.ToLower()
if ($got -ne $SHA256) {
    throw "SHA-256 не совпадает: получен $got, пин $SHA256"
}
Write-Host "  SHA-256 сверен с пином"

# --- распаковка в версионный каталог (свежий) ---
# Архив PBS содержит в корне папку python/, поэтому распаковка в
# $VerDir даёт $VerDir/python/python.exe (как в bootstrap.py).
# tar берём из System32 (bsdtar): tar из PATH может оказаться MSYS/Git-Bash
# и не понять путь «C:\…» («Cannot connect to C: resolve failed»).
$TarExe = Join-Path $env:SystemRoot "System32\tar.exe"
if (-not (Test-Path $TarExe)) { $TarExe = "tar" }
if (Test-Path $VerDir) { Remove-Item $VerDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $VerDir | Out-Null
& $TarExe -xzf $Arc -C $VerDir
if ($LASTEXITCODE -ne 0) { throw "tar: распаковка не удалась" }

# --- изоляция: python311._pth + DLL pywin32 ---
$pth = Join-Path $PyDir "python311._pth"
@(
    "Lib",
    "DLLs",
    "Lib\site-packages",
    "Lib\site-packages\win32",
    "Lib\site-packages\win32\lib"
) | Set-Content -Path $pth -Encoding ascii
foreach ($dll in @("pythoncom311.dll", "pywintypes311.dll")) {
    $src = Join-Path $PyDir "Lib\site-packages\pywin32_system32\$dll"
    if (Test-Path $src) { Copy-Item $src $PyDir -Force }
}
Write-Host "  изоляция: $PyExe"

# --- делегируем bootstrap.py (pip + format-agent + grilling + validate + manifest) ---
$modeArg = if ($Full) { "--full" } else { "--no-grilling" }
& $PyExe $BootstrapPy --root $RuntimeRoot --assume-python $modeArg
exit $LASTEXITCODE
