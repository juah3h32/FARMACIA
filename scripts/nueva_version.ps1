param(
    [Parameter(Mandatory=$true)]
    [string]$Version
)

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    Write-Error "Formato invalido. Usa: .\scripts\nueva_version.ps1 1.2.0"
    exit 1
}

$parts = $Version.Split('.')
$verTuple = "$($parts[0]),$($parts[1]),$($parts[2]),0"
$verDots  = "$Version.0"

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

# --- app/config.py ---
$cfg = [System.IO.File]::ReadAllText((Resolve-Path "app\config.py"), $utf8NoBom)
$cfg = $cfg -replace 'VERSION\s*=\s*"[^"]+"', "VERSION = `"$Version`""
[System.IO.File]::WriteAllText((Resolve-Path "app\config.py"), $cfg, $utf8NoBom)

# --- version_info.txt ---
$vi = [System.IO.File]::ReadAllText((Resolve-Path "version_info.txt"), $utf8NoBom)
$vi = $vi -replace 'filevers=\([^)]+\)',   "filevers=($verTuple)"
$vi = $vi -replace 'prodvers=\([^)]+\)',   "prodvers=($verTuple)"
$vi = $vi -replace "'FileVersion',\s*'[^']+'",    "'FileVersion', '$verDots'"
$vi = $vi -replace "'ProductVersion',\s*'[^']+'", "'ProductVersion', '$verDots'"
[System.IO.File]::WriteAllText((Resolve-Path "version_info.txt"), $vi, $utf8NoBom)

# --- installer.iss ---
$iss = [System.IO.File]::ReadAllText((Resolve-Path "installer.iss"), $utf8NoBom)
$iss = $iss -replace '#define AppVersion\s+"[^"]+"', "#define AppVersion   `"$Version`""
[System.IO.File]::WriteAllText((Resolve-Path "installer.iss"), $iss, $utf8NoBom)

Write-Host "Version actualizada a $Version"

git add app\config.py version_info.txt installer.iss
git commit -m "chore: bump version to $Version"
git tag "v$Version"
git push
git push --tags

Write-Host ""
Write-Host "Tag v$Version publicado. GitHub Actions construira el EXE en ~5 minutos."
Write-Host "Progreso: https://github.com/juah3h32/FARMACIA/actions"
