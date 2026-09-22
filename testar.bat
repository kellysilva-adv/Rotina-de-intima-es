@echo off
rem ===========================================================================
rem  Rotina de Intimacoes - Kelly Silva Advocacia
rem  Teste de conectividade dos 26 tribunais.
rem
rem  Dois cliques neste arquivo. Nao precisa de certificado nem de senha.
rem ===========================================================================
setlocal
cd /d "%~dp0"

echo.
echo ===========================================================
echo   ROTINA DE INTIMACOES - Teste de conectividade
echo   Kelly Silva Advocacia
echo ===========================================================
echo.

rem --- 1. procura um Python QUE REALMENTE FUNCIONE ---------------------------
rem  Nao basta perguntar ao Windows se o comando existe: ele mantem um
rem  'python.exe' falso em WindowsApps que so serve para abrir a Microsoft
rem  Store. Ele aparece como existente e falha ao ser executado. Por isso
rem  cada candidato aqui e testado RODANDO de verdade.
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
for /f "delims=" %%D in ('dir /b /ad "C:\Python3*" 2^>nul') do (
  call :checar_exe "C:\%%D\python.exe"
)

if not defined PY goto :sem_python

echo Python funcionando:
%PY% --version
echo.

rem --- 2. confere que esta na pasta do projeto -------------------------------
if not exist "varredura_tribunais.py" (
  echo [ERRO] Este arquivo nao esta na pasta do projeto.
  echo.
  echo Ele precisa ficar junto do varredura_tribunais.py, dentro da pasta
  echo que voce extraiu do ZIP.
  echo.
  echo Pasta atual: %CD%
  echo.
  pause
  exit /b 1
)

rem --- 3. instala a unica dependencia ----------------------------------------
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
echo   Resultado salvo em: dados\conectividade.json
echo   Mande esse arquivo, ou copie a tabela acima, para o Claude.
echo ===========================================================
echo.
pause
exit /b 0


rem ===========================================================================
rem  Sub-rotinas
rem ===========================================================================

rem  Como o candidato e validado: nao por codigo de saida, e sim exigindo que
rem  ele DEVOLVA a conta certa. O atalho falso do Windows escreve o recado da
rem  Microsoft Store e nunca responde 9731 - entao nunca passa por aqui.

rem Testa um comando do PATH (ex.: "py -3", "python").
:checar_cmd
if defined PY goto :eof
set "SAIDA="
for /f "tokens=*" %%V in ('%~1 -c "print(9731)" 2^>nul') do set "SAIDA=%%V"
if not "%SAIDA%"=="9731" goto :eof
set "PY=%~1"
goto :eof

rem Testa um python.exe em caminho completo (pode ter espaco no nome).
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
echo Se voce viu a mensagem "Python nao foi encontrado; executar sem
echo argumentos para instalar do Microsoft Store", ela veio de um ATALHO
echo FALSO do Windows - nao de um Python de verdade.
echo.
echo COMO RESOLVER (5 minutos):
echo.
echo   1. Abra: https://www.python.org/downloads/
echo   2. Clique no botao amarelo "Download Python"
echo   3. Execute o arquivo baixado
echo   4. NA PRIMEIRA TELA, marque a caixinha embaixo:
echo.
echo          [X] Add python.exe to PATH
echo.
echo      Esse e o passo que todo mundo pula. Sem ele o Windows
echo      continua achando o atalho falso e nada funciona.
echo   5. Clique em "Install Now" e espere terminar
echo   6. FECHE esta janela e de dois cliques no testar.bat de novo
echo.
echo Se mesmo assim nao funcionar, desligue os atalhos falsos:
echo   Configuracoes ^> Aplicativos ^> Configuracoes avancadas do
echo   aplicativo ^> Aliases de execucao do aplicativo
echo   e DESLIGUE as chaves "python.exe" e "python3.exe".
echo.
pause
exit /b 1
