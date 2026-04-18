@echo off
setlocal

echo ============================================================
echo  SoloCanvas - Build Script
echo ============================================================
echo.

:: Project root = directory containing this batch file
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

:: Prefer the project's .venv (where all dependencies including pymupdf are
:: installed).  Fall back to the first Python 3 found on PATH.
set PYTHON=
if exist "%ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
    echo Using project virtual environment: %ROOT%\.venv
) else (
    for %%C in (python3.exe python.exe) do (
        if not defined PYTHON (
            for /f "delims=" %%P in ('where %%C 2^>nul') do (
                if not defined PYTHON (
                    echo %%P | findstr /i "WindowsApps" >nul 2>&1
                    if errorlevel 1 (
                        for /f "tokens=2 delims= " %%V in ('"%%P" --version 2^>^&1') do (
                            for /f "tokens=1 delims=." %%M in ("%%V") do (
                                if "%%M"=="3" set PYTHON=%%P
                            )
                        )
                    )
                )
            )
        )
    )
)

if not defined PYTHON (
    echo [ERROR] Python 3 not found on PATH and no .venv found.
    echo.
    echo Run launch.bat first to create the virtual environment, then retry.
    pause
    exit /b 1
)

for /f "tokens=2 delims= " %%V in ('"%PYTHON%" --version 2^>^&1') do set PYVER=%%V
echo Found Python %PYVER%  (%PYTHON%)
echo.

:: Ensure PyInstaller is installed in the correct Python environment
echo Installing/verifying PyInstaller...
"%PYTHON%" -m pip install pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller.
    pause
    exit /b 1
)

:: Clean previous build artefacts
if exist "dist\SoloCanvas" (
    echo Removing previous dist...
    rmdir /s /q "dist\SoloCanvas"
)
if exist "build\SoloCanvas" (
    rmdir /s /q "build\SoloCanvas"
)

echo Building SoloCanvas...
echo.

"%PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --windowed ^
    --onedir ^
    --name SoloCanvas ^
    --distpath dist ^
    --workpath build ^
    --specpath build ^
    --icon "%ROOT%\resources\images\scrollcanvas.io.ico" ^
    --hidden-import "PyQt6.QtSvg" ^
    --hidden-import "PyQt6.QtSvgWidgets" ^
    --hidden-import "PyQt6.QtPdf" ^
    --hidden-import "PyQt6.QtPdfWidgets" ^
    --collect-all qtawesome ^
    --collect-all markdown ^
    --collect-all markdownify ^
    --collect-all pymupdf ^
    --hidden-import "fitz" ^
    --hidden-import "pymupdf" ^
    --hidden-import "bs4" ^
    main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. See output above.
    pause
    exit /b 1
)

:: Copy Dice and resources folders next to the exe
echo Copying Dice assets...
xcopy /e /i /y "%ROOT%\Dice" "dist\SoloCanvas\Dice" >nul

echo Copying resources...
xcopy /e /i /y "%ROOT%\resources" "dist\SoloCanvas\resources" >nul

:: Copy Decks and Images folders next to the exe
echo Copying Decks...
xcopy /e /i /y "%ROOT%\Decks" "dist\SoloCanvas\Decks" >nul

echo Copying Images...
xcopy /e /i /y "%ROOT%\Images" "dist\SoloCanvas\Images" >nul

:: Create the Notes folder next to the exe (global Markdown notepad storage)
if not exist "dist\SoloCanvas\Notes" (
    mkdir "dist\SoloCanvas\Notes"
    mkdir "dist\SoloCanvas\Notes\Images"
    echo Created dist\SoloCanvas\Notes\
)

echo.
echo ============================================================
echo  Build complete!
echo  Executable:  dist\SoloCanvas\SoloCanvas.exe
echo  Dice assets: dist\SoloCanvas\Dice\      (copied next to exe)
echo  Resources:   dist\SoloCanvas\resources\ (copied next to exe)
echo  Deck folder: dist\SoloCanvas\Decks\     (add your card decks here)
echo  Img folder:  dist\SoloCanvas\Images\    (add your images here)
echo ============================================================
echo.

endlocal
pause
