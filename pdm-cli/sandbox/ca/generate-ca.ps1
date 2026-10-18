# PowerShell equivalent of generate-ca.sh — runs openssl inside an Alpine container
# so no host-side openssl / WSL bash is required.
#
# Usage (from project root or anywhere):
#   pwsh tools/pdm-cli/sandbox/ca/generate-ca.ps1
# or:
#   .\tools\pdm-cli\sandbox\ca\generate-ca.ps1

$ErrorActionPreference = "Stop"

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$out = Join-Path $dir "out"
New-Item -ItemType Directory -Force -Path $out | Out-Null

if ((Test-Path (Join-Path $out "ca.crt")) -and (Test-Path (Join-Path $out "ca.key"))) {
    Write-Host "CA already exists in $out. Delete the directory to regenerate."
    exit 0
}

# Use alpine/openssl image (~5 MB, has openssl preinstalled). Mount out/ as /out.
$outPosix = $out -replace '\\', '/'

docker run --rm `
    -v "${outPosix}:/out" `
    -w /out `
    --entrypoint sh `
    alpine/openssl `
    -c "openssl genrsa -out ca.key 4096 && openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -subj '/CN=PDM Sandbox Root CA' -out ca.crt"

if ($LASTEXITCODE -ne 0) {
    Write-Error "openssl container failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Generated CA at ${out}:"
Get-ChildItem $out | Format-Table Name, Length, LastWriteTime
Write-Host ""
Write-Host "Next: docker compose -f docker-compose.full.yml -f tools/pdm-cli/sandbox/docker-compose.sandbox.yml up -d"
Write-Host "Then once: docker compose -f docker-compose.full.yml exec pdm-backend-sandbox update-ca-certificates"
