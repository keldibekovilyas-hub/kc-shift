# Копирует общие модули Сверки в папку kc_shift (репозиторий отчёта за смену). Источник правды — Сверка,
# здесь копии: после правок в Сверке запускать заново и коммитить. Ключи вендорные копии берут из переменных
# окружения (GitHub Actions), а не из токены/.env.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Copy-Item "$root\adjoin.py", "$root\attribution.py", "$root\almaty.py", "$root\binotel_api.py" -Destination $PSScriptRoot -Force
Copy-Item "$root\Control\ИИ-панель Битрикс\kc_sheet.py" -Destination $PSScriptRoot -Force
Copy-Item "$root\automation\bx_users.json" -Destination $PSScriptRoot -Force
# binotel_api: ключи из окружения, если .env нет
$b = Get-Content "$PSScriptRoot\binotel_api.py" -Raw -Encoding UTF8
$b = $b -replace 'KEY, SEC = _ENV\.get\("BINOTEL_API_KEY"\), _ENV\.get\("BINOTEL_API_SECRET"\)', 'KEY, SEC = (os.environ.get("BINOTEL_API_KEY") or _ENV.get("BINOTEL_API_KEY")), (os.environ.get("BINOTEL_API_SECRET") or _ENV.get("BINOTEL_API_SECRET"))'
[IO.File]::WriteAllText("$PSScriptRoot\binotel_api.py", $b, (New-Object Text.UTF8Encoding $false))
# kc_sheet: кэш рядом с модулем, а не …/Сверка/.cache
$k = Get-Content "$PSScriptRoot\kc_sheet.py" -Raw -Encoding UTF8
$k = $k -replace 'CACHE_DIR = os\.path\.join\(os\.path\.dirname\(os\.path\.dirname\(HERE\)\), "\.cache"\)', 'CACHE_DIR = os.environ.get("KC_CACHE_DIR") or os.path.join(HERE, ".cache")'
[IO.File]::WriteAllText("$PSScriptRoot\kc_sheet.py", $k, (New-Object Text.UTF8Encoding $false))
Write-Host "модули скопированы в $PSScriptRoot"
