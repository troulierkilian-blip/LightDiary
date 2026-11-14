param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$iconFile = Join-Path $PSScriptRoot 'assets\app.ico'
$versionFile = Join-Path $PSScriptRoot 'version_info.txt'
$checkData = (Join-Path $PSScriptRoot 'assets\check.svg') + ';assets'
$noticeData = (Join-Path $PSScriptRoot 'THIRD_PARTY_NOTICES.txt') + ';.'
$licenseData = (Join-Path $PSScriptRoot 'licenses') + ';licenses'
$foodData = (Join-Path $PSScriptRoot 'lightdiary\data\catalog.json') + ';lightdiary\data'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '无法建立 Python 开发环境。' }
}
& $pythonPath -m pip install --disable-pip-version-check --index-url https://pypi.org/simple -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败。' }
$previousPlatform = $env:QT_QPA_PLATFORM
$previousPath = $env:PATH
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
try {
    # Keep unrelated tools' ICU DLLs out of dependency resolution. Qt uses Windows ICU.
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $env:QT_QPA_PLATFORM = 'offscreen'
    New-Item -ItemType Directory -Force '.qa\tmp' | Out-Null
    $env:TEMP = (Resolve-Path '.qa\tmp').Path
    $env:TMP = $env:TEMP
    if (-not $SkipTests) {
        & $pythonPath -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) { throw '测试未通过，停止打包。' }
    }
    & $pythonPath main.py --generate-icon assets\app.ico
    if ($LASTEXITCODE -ne 0) { throw '图标生成失败。' }
    & $pythonPath -m PyInstaller --noconfirm --clean --onedir --windowed --name '轻盈日记' --icon $iconFile --version-file $versionFile --add-data $checkData --add-data $noticeData --add-data $licenseData --add-data $foodData --distpath build\folder --workpath build\folder-work --specpath build main.py
    if ($LASTEXITCODE -ne 0) { throw '目录版打包失败。' }
    $folderExe = Join-Path $PSScriptRoot 'build\folder\轻盈日记\轻盈日记.exe'
    $folderProcess = Start-Process -FilePath $folderExe -ArgumentList '--smoke-test .qa\folder' -WindowStyle Hidden -Wait -PassThru
    if ($folderProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath '.qa\folder\report.json')) { throw '目录版运行验证失败。' }
    & $pythonPath -m PyInstaller --noconfirm --clean --onefile --windowed --name '轻盈日记' --icon $iconFile --version-file $versionFile --add-data $checkData --add-data $noticeData --add-data $licenseData --add-data $foodData --distpath dist --workpath build\single-work --specpath build main.py
    if ($LASTEXITCODE -ne 0) { throw '单文件 EXE 打包失败。' }
    $singleExe = Join-Path $PSScriptRoot 'dist\轻盈日记.exe'
    $singleProcess = Start-Process -FilePath $singleExe -ArgumentList '--smoke-test .qa\single' -WindowStyle Hidden -Wait -PassThru
    if ($singleProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath '.qa\single\report.json')) { throw '单文件 EXE 运行验证失败。' }
    Copy-Item -LiteralPath '使用说明.md','THIRD_PARTY_NOTICES.txt' -Destination dist
    & $pythonPath tests\release_qa.py
    if ($LASTEXITCODE -ne 0) { throw '原生 EXE 发布验证失败。' }
    $exeFile = Get-Item -LiteralPath '.\dist\轻盈日记.exe'
    Get-FileHash -LiteralPath $exeFile.FullName -Algorithm SHA256 | Format-List
    Write-Output ('完成：' + $exeFile.FullName)
} finally {
    $env:QT_QPA_PLATFORM = $previousPlatform
    $env:PATH = $previousPath
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
}
