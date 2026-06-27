# GitHub Actions secrets for VPS deploy.
# Usage:
#   $env:VPS_HOST = '1.2.3.4'
#   $env:VPS_USER = 'root'   # optional, default root
#   .\scripts\setup_github_secrets.ps1

$ErrorActionPreference = "Stop"

$Gh = "C:\Program Files\GitHub CLI\gh.exe"
if (-not (Test-Path $Gh)) {
  $Gh = "gh"
}

$Repo = "Spen-dev/TradingBot_tinkoff"
$VpsHost = $env:VPS_HOST
if (-not $VpsHost) {
  Write-Error "Set VPS_HOST, e.g.: `$env:VPS_HOST = '1.2.3.4'"
}

$VpsUser = $env:VPS_USER
if (-not $VpsUser) {
  $VpsUser = "root"
}

$KeyPath = Join-Path $env:USERPROFILE ".ssh\github_actions_tradingbot"
if (-not (Test-Path $KeyPath)) {
  $KeyPath = Join-Path $env:USERPROFILE ".ssh\id_ed25519"
}

$Description = "MOEX portfolio rebalancer: Tinkoff Invest API, OpenRouter LLM, macro news, Telegram, Docker"

function Invoke-Gh {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
  & $Gh @Args
  if ($LASTEXITCODE -ne 0) {
    throw "gh failed: $($Args -join ' ')"
  }
}

if (-not (Get-Command $Gh -ErrorAction SilentlyContinue) -and -not (Test-Path $Gh)) {
  Write-Error "GitHub CLI not found. Install: winget install GitHub.cli"
}

& $Gh auth status 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
  Write-Host "GitHub login (browser will open)..." -ForegroundColor Cyan
  Start-Process "https://github.com/login/device"
  Invoke-Gh auth login -h github.com -p https -w -s repo,workflow
}

if (-not (Test-Path $KeyPath)) {
  Write-Error "SSH key not found: $KeyPath"
}

Write-Host "Setting secrets in $Repo ..." -ForegroundColor Cyan
Invoke-Gh secret set VPS_HOST -b $VpsHost -R $Repo
Invoke-Gh secret set VPS_USER -b $VpsUser -R $Repo
Invoke-Gh secret set VPS_SSH_KEY --body-file $KeyPath -R $Repo

Write-Host "Updating repository description ..." -ForegroundColor Cyan
Invoke-Gh repo edit $Repo --description $Description

Write-Host "Done." -ForegroundColor Green
Invoke-Gh secret list -R $Repo
