@echo off
rem ===========================================================================
rem  Rotina de Intimacoes - Kelly Silva Advocacia
rem  Teste de conectividade dos 26 tribunais.
rem
rem  Basta dar DOIS CLIQUES neste arquivo. Ele acha o Python, instala o que
rem  faltar e roda o teste. Nao precisa de certificado nem de senha.
rem ===========================================================================
setlocal
cd /d "%~dp0"

echo.
echo ===========================================================
echo   ROTINA DE INTIMACOES - Teste de conectividade
echo   Kelly Silva Advocacia
echo ===========================================================
echo.

rem --- 1. localiza o Python --------------------------------------------------
set "PY="
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto :achou_python
where python >nul 2>&1
if not errorlevel 1 set "PY=python"
:achou_python

if not defined PY (
  echo [ERRO] Python nao encontrado neste computador.
  echo.
  echo Baixe em: https://www.python.org/downloads/
  echo.
  echo IMPORTANTE: na PRIMEIRA tela do instalador, marque a caixinha
  echo "Add Python to PATH" antes de clicar em Install. Sem isso o
  echo Windows nao acha o Python e este arquivo vai falhar de novo.
  echo.
  pause
  exit /b 1
)

echo Python encontrado.
%PY% --version
echo.

rem --- 2. confere que esta na pasta certa ------------------------------------
if not exist "varredura_tribunais.py" (
  echo [ERRO] Este arquivo nao esta na pasta do projeto.
  echo.
  echo Ele precisa ficar na mesma pasta que o varredura_tribunais.py,
  echo dentro da pasta Rotina-de-intima-es que voce baixou do GitHub.
  echo.
  echo Pasta atual: %CD%
  echo.
  pause
  exit /b 1
)

rem --- 3. instala a unica dependencia necessaria -----------------------------
%PY% -c "import requests" >nul 2>&1
if errorlevel 1 (
  echo Instalando a biblioteca 'requests'. Pode levar um minuto...
  %PY% -m pip install --quiet --disable-pip-version-check requests
  if errorlevel 1 (
    echo.
    echo [ERRO] Nao foi possivel instalar a biblioteca 'requests'.
    echo Se o escritorio usa proxy ou antivirus corporativo, pode ser isso.
    echo.
    pause
    exit /b 1
  )
  echo Instalada.
  echo.
)

rem --- 4. roda o teste -------------------------------------------------------
echo Testando os 26 tribunais em 3 vias.
echo Leva de 1 a 3 minutos. Pode deixar rodando.
echo.

%PY% varredura_tribunais.py --testar-conectividade

echo.
echo ===========================================================
echo   Resultado tambem salvo em: dados\conectividade.json
echo   Mande esse arquivo, ou copie a tabela acima, para o Claude.
echo ===========================================================
echo.
pause
