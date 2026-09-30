@echo off
rem Inicia o Messaging (porta 50053). Pode rodar com dois cliques.
rem Na primeira vez cria o ambiente virtual (.venv) e instala as dependencias.
title MESSAGING :50053
cd /d "%~dp0"
if not exist .venv (
  echo Primeira execucao: criando o ambiente virtual e instalando dependencias...
  python -m venv .venv || goto erro
  .venv\Scripts\python.exe -m pip install -r requirements.txt || goto erro
)
.venv\Scripts\python.exe -m messaging.servidor
pause
exit /b

:erro
echo.
echo Falhou. Confira se o Python 3.12 ou superior esta instalado e no PATH.
pause
