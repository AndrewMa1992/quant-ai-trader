# Set Tiger credentials as GitHub Actions repository secrets (local machine only).
# Cloud agents cannot write secrets (token is read-only).
#
# Usage (PowerShell, from anywhere with gh auth):
#   .\scripts\set_github_tiger_secrets.ps1
# Or with an existing PEM:
#   .\scripts\set_github_tiger_secrets.ps1 -PemPath C:\quant-ai-trader\certs\tiger_private_key.pem

param(
    [string]$Repo = "AndrewMa1992/quant-ai-trader",
    [string]$PemPath = "",
    [string]$TigerId = "20159337",
    [string]$TigerAccount = "21837535188693626",
    [string]$TigerLicense = ""
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "Install GitHub CLI: https://cli.github.com/ then run: gh auth login"
}

$ghAuth = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Not logged in. Run: gh auth login"
}

# Resolve PEM body
$keyBody = $null
if ($PemPath -and (Test-Path $PemPath)) {
    $keyBody = (Get-Content -Raw $PemPath).Trim()
    Write-Host "Using PEM from $PemPath"
} elseif (Test-Path "certs/tiger_private_key.pem") {
    $keyBody = (Get-Content -Raw "certs/tiger_private_key.pem").Trim()
    Write-Host "Using PEM from certs/tiger_private_key.pem"
} else {
    Write-Host "Paste RSA private key (PEM or raw base64), then Ctrl+Z Enter (Windows) / Ctrl+D (Unix):"
    $keyBody = [Console]::In.ReadToEnd().Trim()
}

if ([string]::IsNullOrWhiteSpace($keyBody)) {
    throw "Empty private key — abort"
}

# Strip accidental quotes/newlines at ends only for size check
Write-Host "Key length: $($keyBody.Length) chars"

gh secret set TIGER_PRIVATE_KEY -R $Repo --body $keyBody
Write-Host "OK: TIGER_PRIVATE_KEY"

gh secret set TIGER_ID -R $Repo --body $TigerId
Write-Host "OK: TIGER_ID=$TigerId"

gh secret set TIGER_ACCOUNT -R $Repo --body $TigerAccount
Write-Host "OK: TIGER_ACCOUNT=$TigerAccount"

if (-not [string]::IsNullOrWhiteSpace($TigerLicense)) {
    gh secret set TIGER_LICENSE -R $Repo --body $TigerLicense
    Write-Host "OK: TIGER_LICENSE"
} else {
    Write-Host "SKIP: TIGER_LICENSE (empty) — set later if SDK requires it"
}

Write-Host ""
Write-Host "Verify: https://github.com/$Repo/settings/secrets/actions"
Write-Host "Next: merge PR / run workflow 'CD - Lightsail Windows Paper Deploy'"
