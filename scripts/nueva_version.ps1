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

# --- app/config.py ---
$cfg = Get-Content "app\config.py" -Raw
$cfg = $cfg -replace 'VERSION\s*=\s*"[^"]+"', "VERSION = `"$Version`""
Set-Content "app\config.py" $cfg -NoNewline -Encoding utf8

# --- version_info.txt ---
$vi = Get-Content "version_info.txt" -Raw
$vi = $vi -replace 'filevers=\([^)]+\)',   "filevers=($verTuple)"
$vi = $vi -replace 'prodvers=\([^)]+\)',   "prodvers=($verTuple)"
$vi = $vi -replace "'FileVersion',\s*'[^']+'",    "'FileVersion', '$verDots'"
$vi = $vi -replace "'ProductVersion',\s*'[^']+'", "'ProductVersion', '$verDots'"
Set-Content "version_info.txt" $vi -NoNewline -Encoding utf8

# --- installer.iss ---
$iss = Get-Content "installer.iss" -Raw
$iss = $iss -replace '#define AppVersion\s+"[^"]+"', "#define AppVersion   `"$Version`""
Set-Content "installer.iss" $iss -NoNewline -Encoding utf8

Write-Host "Version actualizada a $Version"

git add app\config.py version_info.txt installer.iss
git commit -m "chore: bump version to $Version"
git tag "v$Version"
git push
git push --tags

Write-Host ""
Write-Host "Tag v$Version publicado. GitHub Actions construira el EXE en ~5 minutos."
Write-Host "Progreso: https://github.com/juah3h32/FARMACIA/actions"
