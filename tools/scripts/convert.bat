@echo off
set CONVERTER_PATH=E:\download\360\SaturnRingLib-main\tools\ModelConverter
set SAMPLE_DATA_PATH=E:\download\360\SaturnRingLib-main\tools\ModelConverter\nya out
%CONVERTER_PATH%\ModelConverter.exe -i "soco0001.obj" "soco0002.obj" "soco0003.obj" "soco0004.obj" "bud_04.obj" "bud_05.obj" "bud_06.obj" "bud_07.obj" "bud_08.obj" "bud_09.obj" "bud_10.obj" "bud_11.obj" -o "%SAMPLE_DATA_PATH%\BUD.NYA" -t smooth
pause