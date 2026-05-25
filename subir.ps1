# Lee VERSION actual de app/config.py
$line    = Select-String -Path "app\config.py" -Pattern 'VERSION\s*=\s*"(\d+\.\d+\.\d+)"'
$current = $line.Matches[0].Groups[1].Value
$parts   = $current.Split('.')

# Incrementa patch automaticamente
$parts[2] = [int]$parts[2] + 1
$nueva = "$($parts[0]).$($parts[1]).$($parts[2])"

Write-Host "Version actual: $current  ->  Nueva: $nueva"
.\scripts\nueva_version.ps1 $nueva
