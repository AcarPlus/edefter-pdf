# e-Defter PDF exe derlemesi: .\build.ps1  →  build\dist\eDefterPDF\ ve build\eDefterPDF-windows.zip
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path .venv)) {
    python -m venv .venv
    .venv\Scripts\python -m pip install -r requirements.txt
}
$xslt = Join-Path $PSScriptRoot 'xslt'
.venv\Scripts\pyinstaller --noconfirm --clean --windowed --name eDefterPDF `
    --add-data "$xslt;xslt" --collect-all saxonche `
    --distpath build\dist --workpath build\work --specpath build main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller başarısız" }
$zip = 'build\eDefterPDF-windows.zip'
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path build\dist\eDefterPDF -DestinationPath $zip
Write-Host "Hazır: $zip"
