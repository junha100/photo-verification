$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
foreach ($entry in @{TEMP='.local/tmp';TMP='.local/tmp';TMPDIR='.local/tmp';XDG_CACHE_HOME='.local/cache';HF_HOME='.local/cache/huggingface';HF_HUB_CACHE='.local/cache/huggingface/hub';HUGGINGFACE_HUB_CACHE='.local/cache/huggingface/hub';TRANSFORMERS_CACHE='.local/cache/huggingface/transformers';TORCH_HOME='.local/cache/torch';PIP_CACHE_DIR='.local/cache/pip';npm_config_cache='.local/cache/npm';PYTHONPYCACHEPREFIX='.local/cache/python'}.GetEnumerator()) {
 $path=Join-Path $PSScriptRoot $entry.Value
 New-Item -ItemType Directory -Path $path -Force | Out-Null
 [Environment]::SetEnvironmentVariable($entry.Key,$path,'Process')
}
