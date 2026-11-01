@echo off
REM One-click start: MySQL (members) + web server + ngrok public URL.
REM Double-click this file. Three windows open - keep all three open.
REM First time only: ngrok config add-authtoken <your token>

cd /d "%~dp0"

netstat -ano | findstr ":3306 " | findstr LISTENING >nul
if errorlevel 1 (
  echo [1/3] Starting MySQL...
  start "MySQL - KEEP OPEN" /d C:\xampp\mysql C:\xampp\mysql\bin\mysqld.exe --defaults-file=C:\xampp\mysql\bin\my.ini --standalone --console
) else (
  echo [1/3] MySQL already running
)

netstat -ano | findstr ":8000 " | findstr LISTENING >nul
if errorlevel 1 (
  echo [2/3] Starting web server...
  start "Web uvicorn - KEEP OPEN" cmd /k "set PYTHONIOENCODING=utf-8&& venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000"
) else (
  echo [2/3] Web server already running
)

tasklist /FI "IMAGENAME eq ngrok.exe" | findstr /I ngrok.exe >nul
if errorlevel 1 (
  echo [3/3] Starting ngrok...
  start "ngrok - KEEP OPEN" ngrok http 127.0.0.1:8000
) else (
  echo [3/3] ngrok already running - see URL at http://127.0.0.1:4040
)

echo.
echo Done. Public URL: see the "Forwarding https://..." line in the ngrok window,
echo or open http://127.0.0.1:4040 in a browser.
echo First search takes 15-20 seconds (loading models).
pause
