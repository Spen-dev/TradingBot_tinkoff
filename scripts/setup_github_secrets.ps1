# Настройка GitHub Actions secrets и описания репозитория.
# Требуется: gh auth login (один раз)
# Запуск: .\scripts\setup_github_secrets.ps1

$ErrorActionPreference = "Stop"
$Repo = "Spen-dev/TradingBot_tinkoff"
$VpsHost = "YOUR_VPS_IP"
$VpsUser = "root"
$KeyPath = Join-Path $env:USERPROFILE ".ssh\id_ed25519"
$Description = "MOEX portfolio rebalancer: Tinkoff Invest API, OpenRouter LLM, macro news, Telegram, Docker"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
  Write-Error "GitHub CLI (gh) не найден. Установите: winget install GitHub.cli"
}

gh auth status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Сначала выполните: gh auth login" -ForegroundColor Yellow
  exit 1
}

if (-not (Test-Path $KeyPath)) {
  Write-Error "SSH-ключ не найден: $KeyPath"
}

Write-Host "Добавляю secrets в $Repo ..."
gh secret set VPS_HOST -b $VpsHost -R $Repo
gh secret set VPS_USER -b $VpsUser -R $Repo
Get-Content -Raw $KeyPath | gh secret set VPS_SSH_KEY -R $Repo

Write-Host "Обновляю описание репозитория ..."
gh repo edit $Repo --description $Description

Write-Host "Готово. Secrets: VPS_HOST, VPS_USER, VPS_SSH_KEY" -ForegroundColor Green
gh secret list -R $Repo
