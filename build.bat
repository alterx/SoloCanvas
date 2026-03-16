@echo off
setlocal

echo ============================================================
echo  SoloCanvas - Build Script
echo ============================================================
echo.

:: Project root = directory containing this batch file
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

:: Use the project's Python installation (Python 3.14 with all dependencies)
set PYTHON=C:\Users\popes\AppData\Local\Python\bin\python.exe
set PIP=C:\Users\popes\AppData\Local\Python\bin\pip.exe

:: Ensure PyInstaller is installed in the correct Python environment
%PIP% install --quiet pyinstaller

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

%PYTHON% -m PyInstaller ^
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

:: Create the Decks folder next to the exe (users populate this with their own decks)
if not exist "dist\SoloCanvas\Decks" (
    mkdir "dist\SoloCanvas\Decks"
    echo Created dist\SoloCanvas\Decks\
)

:: Create the Images folder next to the exe (user image library)
if not exist "dist\SoloCanvas\Images" (
    mkdir "dist\SoloCanvas\Images"
    echo Created dist\SoloCanvas\Images\
)

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
