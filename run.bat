@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

rem ==============================================================================
rem fut-bin - Melhores Momentos (Pelada) para Windows
rem Cria/ativa o ambiente virtual (.venv) e roda os scripts do pipeline.
rem ==============================================================================

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "VENV_DIR=%SCRIPT_DIR%.venv"

rem 1. Localizar o Python
set "PYTHON_EXE="
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_EXE=python"
) else (
    py -3 --version >nul 2>&1
    if %errorlevel% equ 0 (
        set "PYTHON_EXE=py -3"
    )
)

if not defined PYTHON_EXE (
    echo [ERRO] Python não foi encontrado no PATH.
    echo Instale o Python em https://www.python.org/downloads/ e marque a opção "Add python.exe to PATH".
    echo Ou instale pelo terminal: winget install Python.Python.3.12
    echo.
    pause
    exit /b 1
)

rem 2. Criar ou validar o ambiente virtual (.venv)
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo 🔧 Criando ambiente virtual em .venv ...
    %PYTHON_EXE% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERRO] Falha ao criar ambiente virtual em %VENV_DIR%.
        pause
        exit /b 1
    )
    echo 📦 Instalando dependências de requirements.txt ...
    "%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip -q
    "%VENV_DIR%\Scripts\pip.exe" install -r "%SCRIPT_DIR%requirements.txt" -q
)

call "%VENV_DIR%\Scripts\activate.bat"

rem 3. Avisar se ffmpeg não estiver no PATH
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo ⚠ ffmpeg não encontrado no PATH.
    echo   Instale-o antes de continuar (ex.: winget install Gyan.FFmpeg ou baixe em https://ffmpeg.org)
    echo.
)

rem 4. Processar o comando
set "CMD=%~1"
set "ARGS="

if "%CMD%"=="" (
    echo ==============================================================================
    echo fut-bin - Melhores Momentos (Pelada)
    echo ==============================================================================
    echo.
    echo Escolha um comando:
    echo   [1] site          - Assistente no navegador (recomendado)
    echo   [2] marcador      - Abrir marcador.html no navegador
    echo   [3] shell         - Abrir terminal com ambiente virtual ativado
    echo   [4] folha_placar  - Corte manual (folhas de contato)
    echo   [5] detectar_gols - Detecção de gols / corte
    echo   [6] montar_video  - Montagem do vídeo final
    echo   [7] diagnosticar  - Diagnóstico da região do placar
    echo   [8] ajuda         - Exibir instruções de uso
    echo.
    set "ESCOLHA="
    set /p "ESCOLHA=Opção [1]: "
    if "!ESCOLHA!"=="" set "CMD=site"
    if "!ESCOLHA!"=="1" set "CMD=site"
    if "!ESCOLHA!"=="2" set "CMD=marcador"
    if "!ESCOLHA!"=="3" set "CMD=shell"
    if "!ESCOLHA!"=="4" set "CMD=folha_placar"
    if "!ESCOLHA!"=="5" set "CMD=detectar_gols"
    if "!ESCOLHA!"=="6" set "CMD=montar_video"
    if "!ESCOLHA!"=="7" set "CMD=diagnosticar"
    if "!ESCOLHA!"=="8" set "CMD=help"
    if not defined CMD set "CMD=!ESCOLHA!"
) else (
    call :pegar_args %*
)

if /i "%CMD%"=="site" goto :cmd_site
if /i "%CMD%"=="folha_placar" goto :cmd_folha_placar
if /i "%CMD%"=="detectar_gols" goto :cmd_detectar_gols
if /i "%CMD%"=="montar_video" goto :cmd_montar_video
if /i "%CMD%"=="diagnosticar" goto :cmd_diagnosticar
if /i "%CMD%"=="marcador" goto :cmd_marcador
if /i "%CMD%"=="shell" goto :cmd_shell
if /i "%CMD%"=="help" goto :cmd_help
if /i "%CMD%"=="-h" goto :cmd_help
if /i "%CMD%"=="--help" goto :cmd_help
if /i "%CMD%"=="/?" goto :cmd_help

echo ❌ Comando desconhecido: %CMD%
echo.
goto :cmd_help

:cmd_site
start "" /B "%VENV_DIR%\Scripts\python.exe" -c "import time, sys, webbrowser; time.sleep(1.5); host='127.0.0.1'; port='8000'; args=sys.argv[1:]; host=args[args.index('--host')+1] if '--host' in args else host; port=args[args.index('--port')+1] if '--port' in args else port; webbrowser.open(f'http://{host}:{port}')" !ARGS!
python "%SCRIPT_DIR%assistente_web.py" !ARGS!
goto :cmd_end

:cmd_folha_placar
python "%SCRIPT_DIR%folha_placar.py" !ARGS!
goto :cmd_end

:cmd_detectar_gols
python "%SCRIPT_DIR%detectar_gols.py" !ARGS!
goto :cmd_end

:cmd_montar_video
python "%SCRIPT_DIR%montar_video.py" !ARGS!
goto :cmd_end

:cmd_diagnosticar
python "%SCRIPT_DIR%diagnosticar_placar.py" !ARGS!
goto :cmd_end

:cmd_marcador
start "" "%SCRIPT_DIR%marcador.html"
goto :cmd_end

:cmd_shell
echo Ambiente virtual ativado (.venv).
echo Digite 'exit' para sair do shell.
cmd /k
goto :cmd_end

:cmd_help
echo Uso: run.bat ^<comando^> [opções do script]
echo.
echo Comandos (ver README.md para o fluxo completo):
echo   site               Assistente completo no navegador (passo a passo, sem rodar nada na mão)
echo   folha_placar       Corte manual - folhas de contato do placar / conversão de horários -^> gols.json
echo   detectar_gols      Corte manual - corta os clipes de gol (ou detecção automática do placar)
echo   montar_video       Corte manual - monta o vídeo final a partir de partida.json
echo   diagnosticar       Conferência da região/estabilidade do placar
echo   marcador           Abre o marcador.html isolado (sem servidor) no navegador padrão
echo   shell              Só ativa o ambiente virtual num terminal (sem rodar nada)
echo.
echo Exemplos:
echo   run.bat site
echo   run.bat site --port 8000
echo   run.bat folha_placar --source_video_path pelada.mp4 --fim 58:23 --intervalo 10
echo   run.bat detectar_gols --source_video_path pelada.mp4 --cortar --output_dir gols
echo   run.bat montar_video --partida partida.json --clipes gols/clipes
echo   run.bat marcador
goto :cmd_end

:pegar_args
shift
:loop_args
if "%~1"=="" goto :eof
set "ARGS=!ARGS! %1"
shift
goto :loop_args

:cmd_end
if errorlevel 1 (
    echo.
    echo O comando terminou com erro (código %errorlevel%).
)
exit /b %errorlevel%
