@echo off
echo Starting CrossBoard Server...
start "CrossBoard Server" cmd /k "venv\Scripts\uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

timeout /t 3

echo Starting CrossClip Desktop App...
start "CrossBoard Desktop" cmd /c "venv\Scripts\python desktop_gui.py"

echo.
echo ==============================================
echo CrossBoard is running!
echo Generating Connection info...
venv\Scripts\python generate_qr.py
echo ==============================================

pause
