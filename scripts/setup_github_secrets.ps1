# Настройка GitHub Actions secrets и описания репозитория.
# Запуск: .\scripts\setup_github_secrets.ps1

$ErrorActionPreference = "Stop"
$Gh = "C:\Program Files\GitHub CLI\gh.exe"
if (-not (Test-Path $Gh)) {
  $Gh = "gh"
}

$Repo = "Spen-dev/TradingBot_tinkoff"
$VpsHost = "YOUR_VPS_IP"
$VpsUser = "root"
$KeyPath = Join-Path $env:USERPROFILE ".ssh\github_actions_tradingbot"
if (-not (Test-Path $KeyPath)) {
  $KeyPath = Join-Path $env:USERPROFILE ".ssh\id_ed25519"
}
$Description = "MOEX portfolio rebalancer: Tinkoff Invest API, OpenRouter LLM, macro news, Telegram, Docker"

function Invoke-Gh {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
  & $Gh @Args
  if ($LASTEXITCODE -ne 0) { throw "gh failed: $($Args -join ' ')" }
}

if (-not (Get-Command $Gh -ErrorAction SilentlyContinue) -and -not (Test-Path $Gh)) {
  Write-Error "GitHub CLI не найден. Установите: winget install GitHub.cli"
}

& $Gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Вход в GitHub (откроется браузер)..." -ForegroundColor Cyan
  Start-Process "https://github.com/login/device"
  Invoke-Gh auth login -h github.com -p https -w -s repo,admin:repo_hook,workflow
}

if (-not (Test-Path $KeyPath)) {
  Write-Error "SSH-ключ не найден: $KeyPath"
}

Write-Host "Добавляю secrets в $Repo ..." -ForegroundColor Cyan
Invoke-Gh secret set VPS_HOST -b $VpsHost -R $Repo
Invoke-Gh secret set VPS_USER -b $VpsUser -R $Repo
Get-Content -Raw $KeyPath | Invoke-Gh secret set VPS_SSH_KEY -R $Repo

Write-Host "Обновляю описание репозитория ..." -ForegroundColor Cyan
Invoke-Gh repo edit $Repo --description $Description

Write-Host "Готово." -ForegroundColor Green
Invoke-Gh secret list -R $Repo
