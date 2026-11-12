@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python tidak ditemukan. Instal Python 3.10+ dan aktifkan Add Python to PATH.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Membuat virtual environment...
  python -m venv .venv
  if errorlevel 1 goto failed
)
call ".venv\Scripts\activate.bat"
echo Memasang dependensi Flask...
python -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo.
echo Menjalankan SiTanggap K3 pada http://127.0.0.1:5000
python app.py
goto end
:failed
echo.
echo Terjadi kesalahan. Periksa instalasi Python dan koneksi internet.
pause
:end
endlocal
