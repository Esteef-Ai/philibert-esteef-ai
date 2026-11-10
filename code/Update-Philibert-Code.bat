@echo off
rem Update Philibert Code by Esteef.Ai from Philibert's repository - see code\update.py
title Updating Philibert Code
set PYTHONNOUSERSITE=1
set PYTHONPATH=
"%~dp0..\runtime\win-x64\python\python.exe" "%~dp0update.py"
