@echo off
cd /d "%~dp0"
python bot.py %*
if errorlevel 1 pause
