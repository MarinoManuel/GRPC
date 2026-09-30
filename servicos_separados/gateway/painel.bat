@echo off
rem Painel de saude: mostra ao vivo se cada servico esta no ar (rode depois do iniciar.bat).
title PAINEL DE SAUDE
cd /d "%~dp0"
if not exist .venv (
  echo Rode primeiro o iniciar.bat, que cria o ambiente virtual.
  pause
  exit /b
)
.venv\Scripts\python.exe -m painel.painel
pause
