@echo off

if not exist ./BuildDrop/*.cue (
    echo "CUE/ISO missing, please build first."
    GOTO end
)

rem Emulator selection, empty is mednafen
IF "%1" == "" GOTO mednafen
IF "%1" == "mednafen" GOTO mednafen
IF "%1" == "kronos" GOTO kronos
IF "%1" == "yabause" GOTO yabause

rem We do not know what emulator user wants
echo "%1" is not supported
GOTO end

:kronos
rem Run Kronos
where /q kronos.exe

IF ERRORLEVEL 1 (
    echo Using project Kronos installation!
    SET KRONOS=../../emulators/kronos/kronos.exe
) else (
    echo Using system's Kronos installation!
    SET KRONOS=kronos.exe
)

FOR %%F IN (./BuildDrop/*.cue) DO (
    start "" "%KRONOS%" -a -i "%%~fF"
    exit /b
)

GOTO end
rem Kronos block end

:yabause
rem Run yabause
where /q yabause.exe

IF ERRORLEVEL 1 (
    echo Using project yabause installation!
    SET YABAUSE=../../emulators/yabause/yabause.exe
) else (
    echo Using system's yabause installation!
    SET YABAUSE=yabause.exe
)

SET "YABAUSE_BIOS="
IF EXIST "../../emulators/yabause/mpr-17933.bin" SET "YABAUSE_BIOS=../../emulators/yabause/mpr-17933.bin"
IF EXIST "../../emulators/mednafen/mpr-17933.bin" SET "YABAUSE_BIOS=../../emulators/mednafen/mpr-17933.bin"
IF EXIST "../../emulators/mednafen/firmware/mpr-17933.bin" SET "YABAUSE_BIOS=../../emulators/mednafen/firmware/mpr-17933.bin"
IF EXIST "../../emulators/ymir/Saturn BIOS/mpr-17933.bin" SET "YABAUSE_BIOS=../../emulators/ymir/Saturn BIOS/mpr-17933.bin"

FOR %%F IN (./BuildDrop/*.cue) DO (
    IF DEFINED YABAUSE_BIOS (
        echo Using Yabause BIOS at "%YABAUSE_BIOS%"
        start "" "%YABAUSE%" -a -b "%YABAUSE_BIOS%" -i "%%~fF"
    ) else (
        echo Yabause BIOS not found, trying emulated BIOS.
        start "" "%YABAUSE%" -a -nb -i "%%~fF"
    )
    exit /b
)

GOTO end
rem yabause block end

:mednafen
rem Run mednafen
where /q mednafen.exe

IF ERRORLEVEL 1 (
    echo Using project mednafen installation!
    SET MEDNAFEN=../../emulators/mednafen/mednafen.exe
) else (
    echo Using system's mednafen installation!
    SET MEDNAFEN=mednafen.exe
)

FOR %%F IN (./BuildDrop/*.cue) DO (
    start "" "%MEDNAFEN%" "%%~fF"
    exit /b
)

GOTO end
rem mednafen block end

:end
