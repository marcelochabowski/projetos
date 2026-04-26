@echo off
setlocal

rem Always run from this folder so relative OBJ paths resolve.
pushd "%~dp0"

set "CONVERTER_PATH=%~dp0.."
set "SAMPLE_DATA_PATH=%~dp0..\nya out"
set "OUT_FILE=%SAMPLE_DATA_PATH%\TESTE4.NYA"

echo Using converter: "%CONVERTER_PATH%\ModelConverter.exe"
echo Output file: "%OUT_FILE%"

"%CONVERTER_PATH%\ModelConverter.exe" -i "WEP_P001_entry05_DCM1A.obj" -o "%OUT_FILE%" -t smooth -s 1.5
if errorlevel 1 (
	echo.
	echo ERROR: ModelConverter failed.
	popd
	exit /b 1
)

if exist "%OUT_FILE%" (
	for %%A in ("%OUT_FILE%") do echo Generated size: %%~zA bytes
) else (
	echo ERROR: Output file was not created.
	popd
	exit /b 1
)

popd
endlocal