@echo off
rem Inicia o Gateway + Auth + site (porta 8000; Auth gRPC na 50051). Antes, confira os enderecos em config.py.
rem Na primeira vez cria o ambiente virtual (.venv) e instala as dependencias.
title GATEWAY + AUTH :8000
cd /d "%~dp0"
if not exist .venv (
  echo Primeira execucao: criando o ambiente virtual e instalando dependencias...
  python -m venv .venv || goto erro
  .venv\Scripts\python.exe -m pip install -r requirements.txt || goto erro
)
rem O seed cria as 5 contas de demonstracao (senha 123); se ja existirem, so ignora.
.venv\Scripts\python.exe -m auth_gateway.seed
echo.
echo Site: http://localhost:8000
.venv\Scripts\python.exe -m auth_gateway.gateway
pause
exit /b

:erro
echo.
echo Falhou. Confira se o Python 3.12 ou superior esta instalado e no PATH.
pause
