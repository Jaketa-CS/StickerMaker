@echo off
cd /d "%~dp0"
python_embed\python.exe sticker_maker.py %1
pause
