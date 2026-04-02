@echo off
title ZenonFinder Bot
cd /d "C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly"
echo ============================================
echo  ZenonFinder Bot - Iniciando...
echo  %date% %time%
echo ============================================

:restart
echo [%time%] Iniciando bot...
"C:\Users\Dell\Documents\CLAUDE DESKTOP\Claude Leads Instantly\venv\Scripts\python.exe" -X utf8 start_monitor.py
echo [%time%] Bot detenido (exit code: %errorlevel%). Reiniciando en 10 segundos...
timeout /t 10 /nobreak
goto restart
