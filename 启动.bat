@echo off
chcp 65001 >nul
cd /d "%~dp0"
title TickFlow 面板
echo 正在启动面板，日 K 若落后会自动补齐。关掉这个窗口即停止。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1"
if errorlevel 1 pause
