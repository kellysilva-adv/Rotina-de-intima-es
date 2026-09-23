@echo off
rem ===========================================================================
rem  Rotina de Intimacoes - Kelly Silva Advocacia
rem  VARREDURA DIARIA: le os processos, busca as movimentacoes novas,
rem  calcula os prazos e abre o relatorio no navegador.
rem
rem  Dois cliques neste arquivo. Nao precisa de certificado nem de senha.
rem ===========================================================================
setlocal
cd /d "%~dp0"

echo.
echo ===========================================================
echo   VARREDURA DE PRAZOS - Kelly Silva Advocacia
echo ===========================================================
echo.

rem --- 1. Python que realmente funciona (o atalho falso do Windows nao passa)
set "PY="
call :checar_cmd "py -3"
call :checar_cmd "python"
call :checar_cmd "python3"
for /f "delims=" %%D in ('dir /b /ad "%LOCALAPPDATA%\Programs\Python\Python3*" 2^>nul') do (
  call :checar_exe "%LOCALAPPDATA%\Programs\Python\%%D\python.exe"
)
for /f "delims=" %%D in ('dir /b /ad "%ProgramFiles%\Python3*" 2^>nul') do (
  call :checar_exe "%ProgramFiles%\%%D\python.exe"
)
if not defined PY goto :sem_python

rem --- 2. esta na pasta certa? ------------------------------------------------
if not exist "varredura_tribunais.py" (
  echo [ERRO] Este arquivo precisa ficar na mesma pasta do varredura_tribunais.py.
  echo Pasta atual: %CD%
  echo.
  pause
  exit /b 1
)

rem --- 3. os processos estao cadastrados? -------------------------------------
if not exist "relatorio_prazos.json" (
  echo [ERRO] Nao encontrei o cadastro de processos ^(relatorio_prazos.json^).
  echo.
  echo Se voce tem a planilha em CSV nesta pasta, gere o cadastro com:
  echo    %PY% varredura_tribunais.py --importar-processos planilha.csv
  echo.
  pause
  exit /b 1
)

rem --- 4. dependencia ---------------------------------------------------------
%PY% -c "import requests" >nul 2>&1
if errorlevel 1 (
  echo Instalando a biblioteca 'requests'...
  %PY% -m pip install --quiet --disable-pip-version-check requests
  if errorlevel 1 (
    echo [ERRO] Nao foi possivel instalar 'requests'.
    pause
    exit /b 1
  )
)

rem --- 5. varredura -----------------------------------------------------------
echo Buscando movimentacoes novas nos tribunais.
echo Sao centenas de processos - pode levar alguns minutos.
echo.

%PY% varredura_tribunais.py --fonte datajud
if errorlevel 1 goto :deu_erro

rem --- 6. abre o relatorio ----------------------------------------------------
echo.
if exist "prazos_urgentes_diarios.html" (
  echo Abrindo o relatorio no navegador...
  start "" "prazos_urgentes_diarios.html"
) else (
  echo [AVISO] O relatorio nao foi gerado. Veja as mensagens acima.
)

echo.
echo ===========================================================
echo   Pronto.
echo.
echo   prazos_urgentes_diarios.html  - abre no navegador
echo   prazos_urgentes_diarios.md    - mesma tabela, para o Claude
echo.
echo   Historico de cada dia em: dados\historico\
echo ===========================================================
echo.
pause
exit /b 0


rem ===========================================================================
:checar_cmd
if defined PY goto :eof
set "SAIDA="
for /f "tokens=*" %%V in ('%~1 -c "print(9731)" 2^>nul') do set "SAIDA=%%V"
if not "%SAIDA%"=="9731" goto :eof
set "PY=%~1"
goto :eof

:checar_exe
if defined PY goto :eof
if not exist "%~1" goto :eof
set "SAIDA="
for /f "tokens=*" %%V in ('""%~1" -c "print(9731)"" 2^>nul') do set "SAIDA=%%V"
if not "%SAIDA%"=="9731" goto :eof
set "PY="%~1""
goto :eof


:sem_python
echo [ERRO] Nao ha Python instalado neste computador.
echo.
echo Baixe em https://www.python.org/downloads/ e marque, na PRIMEIRA tela
echo do instalador, a caixinha "Add python.exe to PATH".
echo.
pause
exit /b 1

:deu_erro
echo.
echo ===========================================================
echo   A varredura NAO terminou.
echo.
echo   Copie a mensagem de erro acima e mande para o Claude.
echo ===========================================================
echo.
pause
exit /b 1
