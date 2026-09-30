@echo off
REM Thin launcher for the GeopoliticsTrackerDailyAutorun scheduled task.
REM Deliberately the simplest possible interpreter (cmd.exe, not PowerShell
REM or Python) for this outermost layer - fewer moving parts than either,
REM so less surface for THIS file itself to fail on before even reaching
REM step 1 below. %~dp0 is this .bat file's own directory (trailing
REM backslash included), independent of Task Scheduler's working directory -
REM same reasoning as invoking daily_autorun.py by full path instead of
REM `-m` (see register_scheduled_task.ps1's "Working-directory note").
REM
REM Step 1 sends the "run started" email BEFORE step 2 is even attempted -
REM so if step 2 crashes immediately (exactly what happened 2026-09-30:
REM a ModuleNotFoundError from the old `-m` launch method), the started
REM email has already gone out. See scripts/scheduler_notify.py for why
REM that script has to stay independent of daily_autorun.py's own imports.

set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..
set PYTHON_EXE=%PROJECT_ROOT%\venv\Scripts\python.exe

"%PYTHON_EXE%" "%SCRIPT_DIR%scheduler_notify.py" started
"%PYTHON_EXE%" "%SCRIPT_DIR%daily_autorun.py"
