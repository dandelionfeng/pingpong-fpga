# 启动 BNDSTT 纯人工标注工具（一个命令）
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File vision\bndstt_mvp\start_manual_annotation.ps1
#
# 它会用项目自带的 CUDA venv 启动本地标注服务器，并打印浏览器地址。

$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
$python = Join-Path $repo '.venv\c-detector\Scripts\python.exe'
$server = Join-Path $repo 'vision\bndstt_mvp\manual_annotation_server.py'

if (-not (Test-Path $python)) {
    Write-Host "找不到 Python：$python" -ForegroundColor Red
    Write-Host "请确认 .venv\\c-detector 存在。" -ForegroundColor Red
    exit 1
}

Write-Host "使用解释器：$python" -ForegroundColor Cyan
Write-Host "启动标注服务器（Ctrl+C 停止）..." -ForegroundColor Cyan

& $python $server --host 127.0.0.1 --port 8765 --find-port
