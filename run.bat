@echo off
echo.
echo  ============================================
echo    LeadPulse - Starting Development Server
echo  ============================================
echo.
uv run uvicorn app.main:app --reload --port 8000
pause
