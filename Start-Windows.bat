@echo off
rem Philibert by Esteef.Ai. The setup / start window is the only window you see.
start "" powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0setup\windows.ps1"
