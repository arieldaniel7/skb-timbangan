@echo off
setlocal
cd /d "%~dp0"
echo [1/4] Memasang dependensi...
python -m pip install -r requirements.txt pyinstaller==5.13.2 || goto :err
echo [2/4] Menjalankan tes...
python -m unittest discover -s tests || goto :err
echo [3/4] Membangun Scaler.exe...
rmdir /s /q build dist 2>nul
python -m PyInstaller --noconfirm --clean --windowed --name Scaler --collect-all lupa --hidden-import serial.tools.list_ports_windows --add-data "lua;lua" main.py || goto :err
echo [4/4] Menyiapkan folder...
mkdir dist\Scaler\data 2>nul
mkdir dist\Scaler\backups 2>nul
echo.
echo Selesai: dist\Scaler\Scaler.exe
echo Skrip Lua bawaan ikut terbundel; saat pertama jalan disalin ke folder Lua (bisa dipisah, lihat README).
exit /b 0
:err
echo Build GAGAL.
exit /b 1
