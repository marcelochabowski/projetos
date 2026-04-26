@echo off
REM Run Ymir with the project's CUE image (edit YMIR_PATH to point to your ymir.exe)

REM Set full path to your Ymir executable here:
SET "YMIR_PATH=C:\Path\To\ymir.exe"

REM Cue file relative to this script (Tools\scripts -> repo root)
SET "CUE_PATH=%~dp0..\..\Projects\teste\BuildDrop\teste.cue"

IF NOT EXIST "%YMIR_PATH%" (
    echo YMIR not found at "%YMIR_PATH%". Please edit this file and set the correct path to ymir.exe
    pause
    exit /b 1
)

IF NOT EXIST "%CUE_PATH%" (
    echo CUE file not found: "%CUE_PATH%". Build the project first (see Projects\teste\compile.bat)
    pause
    exit /b 1
)

echo Starting Ymir with %CUE_PATH%
start "" "%YMIR_PATH%" "%CUE_PATH%"
