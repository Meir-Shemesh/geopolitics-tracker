@echo off
REM Thin launcher for the GeopoliticsTrackerBiweeklyAutorun scheduled task
REM (Thursdays 01:30 local). Same shape and reasoning as
REM run_daily_autorun_launcher.bat: cmd.exe as the outermost layer, and the
REM entry point invoked by its own full path via %~dp0 - never `-m` - because
REM Task Scheduler does not start in the project folder (see
REM register_scheduled_task.ps1's "Working-directory note").
REM
REM No "started" email here, on purpose: this fires every Thursday but only
REM does real work one week in two, so a weekly "started" mail would be noise.
REM A night that never ran is caught instead by daily_autorun.py's own
REM "closed biweekly period missing" warning in the next daily summary email.

set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..
set PYTHON_EXE=%PROJECT_ROOT%\venv\Scripts\python.exe

"%PYTHON_EXE%" "%SCRIPT_DIR%biweekly_autorun.py"
