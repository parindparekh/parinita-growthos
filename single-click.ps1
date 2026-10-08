$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function New-Secret {
  $bytes = New-Object byte[] 24
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  return -join ($bytes | ForEach-Object { $_.ToString("x2") })
}

if (-not (Test-Path ".env")) {
  $out = foreach ($line in Get-Content ".env.example") {
    while ($line.Contains("__GENERATE__")) {
      $i = $line.IndexOf("__GENERATE__")
      $line = $line.Substring(0, $i) + (New-Secret) + $line.Substring($i + 12)
    }
    $line
  }
  [System.IO.File]::WriteAllLines((Join-Path $PSScriptRoot ".env"), $out)
  Write-Host "Created .env with generated secrets. Keys are in .env: API_KEY and API_KEYS."
}

if (Select-String -Path ".env" -Pattern "__GENERATE__|^API_KEY=(change-me-now)?$" -Quiet) {
  Write-Error "Refusing to start: .env still contains placeholder or default credentials."
}

docker compose up -d --build
for ($i = 0; $i -lt 60; $i++) {
  try {
    Invoke-WebRequest -UseBasicParsing "http://localhost:8080/health" | Out-Null
    Write-Host "Parinita GrowthOS is healthy at http://localhost:8080"
    exit 0
  } catch { Start-Sleep -Seconds 2 }
}
Write-Error "GrowthOS did not become healthy. Run: docker compose logs --tail=200"
