# Set Tiger credentials as GitHub Environment secrets (recommended).
# Environment name used by CD: "private key"
#
# Usage:
#   .\scripts\set_github_tiger_secrets.ps1
#   .\scripts\set_github_tiger_secrets.ps1 -PemPath C:\path\to\key.pem

param(
    [string]$Repo = "AndrewMa1992/quant-ai-trader",
    [string]$Environment = "private key",
    [string]$PemPath = "",
    [string]$TigerId = "20159337",
    [string]$TigerAccount = "21837535188693626",
    [string]$TigerLicense = "",
    [string]$SecretName = "TIGER_PRIVATE_KEY"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "Install GitHub CLI: https://cli.github.com/ then run: gh auth login"
}

$ghAuth = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Not logged in. Run: gh auth login"
}

$keyBody = $null
if ($PemPath -and (Test-Path $PemPath)) {
    $keyBody = (Get-Content -Raw $PemPath).Trim()
    Write-Host "Using PEM from $PemPath"
} elseif (Test-Path "certs/tiger_private_key.pem") {
    $keyBody = (Get-Content -Raw "certs/tiger_private_key.pem").Trim()
    Write-Host "Using PEM from certs/tiger_private_key.pem"
} else {
    Write-Host "Paste RSA private key (PEM or raw base64), then Ctrl+Z Enter (Windows):"
    $keyBody = [Console]::In.ReadToEnd().Trim()
}

if ([string]::IsNullOrWhiteSpace($keyBody)) {
    throw "Empty private key — abort"
}

Write-Host "Key length: $($keyBody.Length) chars"
Write-Host "Target environment: $Environment"

gh api -X PUT "repos/$Repo/environments/$([uri]::EscapeDataString($Environment))" 2>$null | Out-Null

gh secret set $SecretName -R $Repo --env $Environment --body $keyBody
Write-Host "OK: $SecretName (env=$Environment)"

gh secret set TIGER_ID -R $Repo --env $Environment --body $TigerId
Write-Host "OK: TIGER_ID=$TigerId"

gh secret set TIGER_ACCOUNT -R $Repo --env $Environment --body $TigerAccount
Write-Host "OK: TIGER_ACCOUNT=$TigerAccount"

if (-not [string]::IsNullOrWhiteSpace($TigerLicense)) {
    gh secret set TIGER_LICENSE -R $Repo --env $Environment --body $TigerLicense
    Write-Host "OK: TIGER_LICENSE"
}

Write-Host ""
Write-Host "Verify: https://github.com/$Repo/settings/environments"
Write-Host "Secret name must be one of: TIGER_PRIVATE_KEY | PRIVATE_KEY | KEY"
Write-Host "Then merge PR / re-run workflow CD - Lightsail Windows Paper Deploy"
