@echo off
rem Inicia o Discovery (porta 50052). Pode rodar com dois cliques.
rem Na primeira vez cria o ambiente virtual (.venv) e instala as dependencias.
title DISCOVERY :50052
cd /d "%~dp0"
if not exist .venv (
  echo Primeira execucao: criando o ambiente virtual e instalando dependencias...
  python -m venv .venv || goto erro
  .venv\Scripts\python.exe -m pip install -r requirements.txt || goto erro
)
rem O seed cria os 5 perfis de demonstracao; se ja existirem, so ignora.
.venv\Scripts\python.exe -m discovery.seed
.venv\Scripts\python.exe -m discovery.servidor
pause
exit /b

:erro
echo.
echo Falhou. Confira se o Python 3.12 ou superior esta instalado e no PATH.
pause
