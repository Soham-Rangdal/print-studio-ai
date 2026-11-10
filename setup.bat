@echo off
rem Print Studio setup: double-click to install everything (see installer\install.ps1 for options).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1" %*
