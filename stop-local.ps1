$ErrorActionPreference='Stop'
$all=@(Get-CimInstance Win32_Process)
foreach($name in @('web','gateway','inference')) {
 $pidPath=Join-Path $PSScriptRoot ".local/$name.pid"
 if (-not (Test-Path -LiteralPath $pidPath)) { continue }
 $recorded=[int](Get-Content -LiteralPath $pidPath)
 $p=$all | Where-Object ProcessId -eq $recorded
 $expected=if($name -eq 'web'){'node_modules/vite/bin/vite.js'}elseif($name -eq 'inference'){'multimodal_inference_server.py'}else{'storage_gateway_server.py'}
 if ($p -and $p.CommandLine -and $p.CommandLine.Contains($expected)) {
  $owned=[System.Collections.Generic.HashSet[int]]::new();[void]$owned.Add([int]$p.ProcessId)
  do {$added=$false;foreach($child in $all){if($owned.Contains([int]$child.ParentProcessId)-and -not $owned.Contains([int]$child.ProcessId)){[void]$owned.Add([int]$child.ProcessId);$added=$true}}}while($added)
  foreach($processIdToStop in $owned){Stop-Process -Id $processIdToStop -Force -ErrorAction SilentlyContinue}
 }
}
Write-Output '이 공유본으로 실행한 서버를 종료했습니다.'
