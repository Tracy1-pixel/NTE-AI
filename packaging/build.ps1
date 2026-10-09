param([string]$Version = "1.5.0")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
python -m PyInstaller --noconfirm --clean --windowed --onedir --name NTE-AI --add-data "assets;assets" --collect-all rapidocr_onnxruntime --collect-all onnxruntime --collect-all pyautogui --collect-all pynput app.py 2>&1 | Tee-Object -FilePath pyinstaller-build.log
if ($LASTEXITCODE -ne 0) {
    $detail = (Get-Content pyinstaller-build.log -Tail 12) -join " | "
    Write-Output "::error::PyInstaller failed: $detail"
    throw "PyInstaller failed"
}
$process = Start-Process -FilePath ".\dist\NTE-AI\NTE-AI.exe" -ArgumentList @("--self-test", "bundled-test.json") -Wait -PassThru
if ($process.ExitCode -ne 0) {
    if (Test-Path bundled-test.json) { Write-Output "::error::Bundled smoke test: $(Get-Content bundled-test.json -Raw)" }
    else { Write-Output "::error::Bundled process exited $($process.ExitCode) without a self-test report" }
    throw "Bundled application smoke test failed"
}
$report = Get-Content bundled-test.json -Raw | ConvertFrom-Json
if ($report.status -ne "passed" -or !$report.frozen) { throw "Bundled OCR test did not pass" }
$compiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (!(Test-Path $compiler)) { $compiler = (Get-Command ISCC.exe -ErrorAction Stop).Source }
& $compiler "/DAppVersion=$Version" packaging\installer.iss 2>&1 | Tee-Object -FilePath inno-build.log
if ($LASTEXITCODE -ne 0) {
    $detail = (Get-Content inno-build.log -Tail 8) -join " | "
    Write-Output "::error::Inno Setup failed: $detail"
    throw "Installer build failed"
}
$installDir = Join-Path $env:TEMP "NTE-AI-installer-smoke"
$installer = Join-Path (Get-Location) "dist\installer\NTE-AI-Setup-$Version.exe"
$process = Start-Process -FilePath $installer -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=`"$installDir`"" -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Installer smoke test failed" }
$shortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "异环助手.lnk"
if (!(Test-Path $shortcut)) { throw "Desktop shortcut was not created" }
$process = Start-Process -FilePath (Join-Path $installDir "NTE-AI.exe") -ArgumentList @("--self-test", "installed-test.json") -Wait -PassThru
if ($process.ExitCode -ne 0) {
    if (Test-Path installed-test.json) { Write-Output "::error::Installed smoke test: $(Get-Content installed-test.json -Raw)" }
    throw "Installed application smoke test failed"
}
$report = Get-Content installed-test.json -Raw | ConvertFrom-Json
if ($report.status -ne "passed" -or $report.gui -ne "passed" -or $report.overlay -ne "passed" -or $report.stop_button -ne "passed" -or $report.cursor_capture -ne "passed" -or $report.star_anchors -ne "passed") { throw "Installed GUI/OCR/anchor/cursor/overlay test failed" }
