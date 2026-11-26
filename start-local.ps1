. (Join-Path $PSScriptRoot 'runtime-paths.ps1')
$pythonExe=Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$node=Get-Command node.exe -ErrorAction SilentlyContinue
if (-not (Test-Path -LiteralPath $pythonExe) -or -not $node -or -not (Test-Path -LiteralPath 'UI/node_modules/vite/bin/vite.js')) { throw '먼저 설치.cmd를 실행해주세요.' }
& $pythonExe -B 'tools/configure-local.py'
if ($LASTEXITCODE -ne 0) { throw '설정 확인에 실패했습니다.' }
$services=@(
 @{Name='inference';Port=8001;Exe=$pythonExe;Args='-B -u AI/Multimodal/inference/multimodal_inference_server.py';Dir=$PSScriptRoot},
 @{Name='gateway';Port=8787;Exe=$pythonExe;Args='-B -u storage_gateway_server.py';Dir=(Join-Path $PSScriptRoot 'Admin/Backend')},
 @{Name='web';Port=5174;Exe=$node.Source;Args='node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5174 --strictPort';Dir=(Join-Path $PSScriptRoot 'UI')}
)
foreach ($service in $services) {
 if (Get-NetTCPConnection -LocalPort $service.Port -State Listen -ErrorAction SilentlyContinue) { Write-Output "$($service.Name): $($service.Port) 포트 사용 중. 중복 실행하지 않습니다.";continue }
 $p=Start-Process -FilePath $service.Exe -ArgumentList $service.Args -WorkingDirectory $service.Dir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $PSScriptRoot ".local/$($service.Name).log") -RedirectStandardError (Join-Path $PSScriptRoot ".local/$($service.Name).err.log")
 $p.Id | Set-Content -LiteralPath (Join-Path $PSScriptRoot ".local/$($service.Name).pid")
}
Start-Process 'http://127.0.0.1:5174'
Write-Output '서버 시작 요청 완료. 초기 로딩이 끝나면 웹에서 이용하세요. 종료는 종료.cmd를 실행하세요.'
