@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在啟動 台股財報分析…
start "" http://localhost:8899
python server.py
pause
