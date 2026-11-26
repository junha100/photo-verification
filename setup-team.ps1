﻿. (Join-Path $PSScriptRoot 'runtime-paths.ps1')
$node = Get-Command node.exe -ErrorAction SilentlyContinue
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $node -or -not $npm) { throw 'Node.js 22.12 이상(LTS)을 먼저 설치한 뒤 다시 실행해주세요.' }
& $node.Source -e "const [a,b]=process.versions.node.split('.').map(Number);if(a<22||(a===22&&b<12))process.exit(1)"
if ($LASTEXITCODE -ne 0) { throw 'Node.js 22.12 이상이 필요합니다.' }
$pythonExe=Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
 $py=Get-Command py.exe -ErrorAction SilentlyContinue
 if ($py) { & $py.Source -3.12 -m venv '.venv' }
 else {
  $python=Get-Command python.exe -ErrorAction SilentlyContinue
  if (-not $python) { throw 'Python 3.12(64비트)을 먼저 설치해주세요.' }
  & $python.Source -c "import sys;assert sys.version_info[:2]==(3,12),'Python 3.12 required'"
  if ($LASTEXITCODE -ne 0) { throw 'Python 3.12가 필요합니다. 3.13 이상은 지원하지 않습니다.' }
  & $python.Source -m venv '.venv'
 }
 if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 실행 환경 생성에 실패했습니다.' }
}
& $pythonExe -B 'tools/download-models.py'
if ($LASTEXITCODE -ne 0) { throw 'GitHub 모델 다운로드에 실패했습니다.' }
& $pythonExe -B 'tools/verify-models.py'
if ($LASTEXITCODE -ne 0) { throw '모델 파일을 확인해주세요. 전체 공유본이 필요합니다.' }
& $pythonExe -m pip install 'torch==2.15.0' 'torchvision==0.29.2' --index-url 'https://download.pytorch.org/whl/cpu'
if ($LASTEXITCODE -ne 0) { throw 'PyTorch 설치에 실패했습니다.' }
& $pythonExe -m pip install -r 'requirements-local.lock.txt'
if ($LASTEXITCODE -ne 0) { throw 'Python 패키지 설치에 실패했습니다.' }
& $pythonExe -B 'tools/configure-local.py'
if ($LASTEXITCODE -ne 0) { throw '설정 파일 준비에 실패했습니다.' }
Push-Location (Join-Path $PSScriptRoot 'UI')
try {
 & $npm.Source ci --no-audit --no-fund
 if ($LASTEXITCODE -ne 0) { throw '웹 패키지 설치에 실패했습니다.' }
 & $npm.Source run build
 if ($LASTEXITCODE -ne 0) { throw '웹 화면 빌드에 실패했습니다.' }
} finally { Pop-Location }
Write-Output '설치 완료. 실행.cmd를 열면 됩니다. API 키는 루트 .env에서 변경할 수 있습니다.'
