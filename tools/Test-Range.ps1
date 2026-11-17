# Prova del download con ripresa (Range) sul sito vero: legge da solo l'indirizzo e un file dal catalogo.
# Non stampa l'indirizzo (contiene la parola segreta).
$root = Split-Path -Parent $PSScriptRoot
$cs = Get-Content (Join-Path $root 'app\Simpler\ContentStore.cs') -Raw
$base = ([regex]::Match($cs, 'DefaultBase\s*=\s*"([^"]+)"').Groups[1].Value).TrimEnd('/') + '/'
$cat = @('M:\3D\simpler-content\catalog.json', "$env:LOCALAPPDATA\Simpler\content\catalog.json") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $cat) { Write-Host 'NON TROVO catalog.json (ne in M:\3D\simpler-content ne in LOCALAPPDATA\Simpler\content)'; exit 1 }
$j = Get-Content $cat -Raw | ConvertFrom-Json
$m = $j.models | Sort-Object { [long]$_.size } -Descending | Select-Object -First 1
$url = $base + 'models/' + $m.file
Write-Host ("File provato: models/{0}  ({1:N1} MB nel catalogo)" -f $m.file, ($m.size / 1MB))
function Probe($range) {
  $h = & curl.exe -s -D - -o NUL -H "Range: bytes=$range" $url
  $status = ($h | Select-Object -First 1).Trim()
  $cr = ($h | Where-Object { $_ -match '^(?i)content-range' } | Select-Object -First 1)
  Write-Host ("  bytes=$range -> {0} | {1}" -f $status, $(if ($cr) { $cr.Trim() } else { 'nessun Content-Range' }))
  return @{ ok = ($status -match ' 206'); cr = $cr }
}
$a = Probe '0-99'
$b = Probe '100-199'
$total = if ($a.cr -match '/(\d+)') { [long]$Matches[1] } else { 0 }
Write-Host ''
if ($a.ok -and $b.ok -and $total -eq [long]$m.size) { Write-Host 'OK: il sito supporta la ripresa del download (206) e la dimensione coincide col catalogo.' }
elseif ($a.ok -and $b.ok) { Write-Host "ATTENZIONE: la ripresa funziona (206) ma la dimensione ($total) non coincide col catalogo ($($m.size))." }
else { Write-Host 'PROBLEMA: il sito non risponde 206: la ripresa non funziona, scrivimi questo testo.' }
