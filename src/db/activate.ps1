# Dot-source after activating the project virtualenv. Reads simple KEY=VALUE .env.
$dbProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$dbEnvPath = Join-Path $dbProjectRoot '.env'
if (-not (Test-Path -LiteralPath $dbEnvPath)) { throw 'Copy .env.example to .env and set POSTGRES_PASSWORD first.' }
foreach ($dbLine in Get-Content -LiteralPath $dbEnvPath) {
    $dbLine = $dbLine.Trim()
    if (-not $dbLine -or $dbLine.StartsWith('#')) { continue }
    $dbParts = $dbLine.Split('=', 2)
    if ($dbParts.Count -ne 2) { throw 'Expected KEY=VALUE in .env' }
    $dbKey = $dbParts[0].Trim()
    if ($dbKey -notin @('POSTGRES_USER', 'POSTGRES_DB', 'POSTGRES_PASSWORD', 'POSTGRES_PORT')) { continue }
    $dbValue = $dbParts[1].Trim()
    if ($dbValue.Length -ge 2 -and (($dbValue.StartsWith('"') -and $dbValue.EndsWith('"')) -or ($dbValue.StartsWith("'") -and $dbValue.EndsWith("'")))) {
        $dbValue = $dbValue.Substring(1, $dbValue.Length - 2)
    }
    [Environment]::SetEnvironmentVariable($dbKey, $dbValue, 'Process')
}
if (-not $env:POSTGRES_PASSWORD) { throw 'POSTGRES_PASSWORD is required.' }
$env:ALEMBIC_CONFIG = Join-Path $PSScriptRoot 'alembic.ini'
$dbHostUrl = & python -c "import os; from sqlalchemy.engine import URL; print(URL.create('postgresql+psycopg', username=os.getenv('POSTGRES_USER', 'datt'), password=os.environ['POSTGRES_PASSWORD'], host='127.0.0.1', port=int(os.getenv('POSTGRES_PORT', '5432')), database=os.getenv('POSTGRES_DB', 'datt')).render_as_string(hide_password=False))"
if ($LASTEXITCODE -ne 0) { throw 'Could not construct PostgreSQL URL; activate the virtualenv and install DB dependencies.' }
$env:DATT_DATABASE_URL = $dbHostUrl
Remove-Variable dbHostUrl, dbValue -ErrorAction SilentlyContinue
