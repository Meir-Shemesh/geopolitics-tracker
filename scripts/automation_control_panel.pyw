"""GUI control panel for the project's two unattended scheduled runs - a small
tkinter window so their Windows Task Scheduler tasks and state files never
need to be managed by hand-typed schtasks/PowerShell commands. tkinter is
Python's stdlib GUI toolkit - no new dependency.

Two tabs, two fully separate mechanisms - nothing on one tab reads or writes
anything the other tab's mechanism uses:
  - "ריצה יומית": scripts/daily_autorun.py (task GeopoliticsTrackerDailyAutorun,
    .pause_automation, automation_state/config.json + state.json +
    killswitch.flag).
  - "דוח מגמות דו-שבועי": scripts/biweekly_autorun.py (task
    GeopoliticsTrackerBiweeklyAutorun, automation_state/biweekly_state.json,
    biweekly_killswitch.flag, biweekly_pause_next.flag).

.pyw (not .py) so double-clicking it launches with pythonw.exe - no console
window. Every subprocess call to schtasks.exe explicitly passes
creationflags=subprocess.CREATE_NO_WINDOW for the same reason (schtasks.exe
is a console-subsystem program; spawning it from a windowed/no-console
parent would otherwise flash a new console window open for each call).

Reads/writes exactly the same files the two wrapper scripts themselves read/
write - this is a thin control surface over that state, not a second source
of truth for it.
"""
import json
import subprocess
import sys
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = PROJECT_ROOT / "automation_state"
LOG_DIR = STATE_DIR / "logs"
STATE_FILE = STATE_DIR / "state.json"
CONFIG_FILE = STATE_DIR / "config.json"
PAUSE_FLAG = PROJECT_ROOT / ".pause_automation"
KILLSWITCH_FLAG = STATE_DIR / "killswitch.flag"
SCHEDULED_TASK_NAME = "GeopoliticsTrackerDailyAutorun"
DAILY_FAILURE_LIMIT = 2  # daily_autorun.CONSECUTIVE_FAILURE_LIMIT

# Biweekly mechanism - same names scripts/biweekly_autorun.py defines.
BW_TASK_NAME = "GeopoliticsTrackerBiweeklyAutorun"
BW_STATE_FILE = STATE_DIR / "biweekly_state.json"
BW_KILLSWITCH_FLAG = STATE_DIR / "biweekly_killswitch.flag"
BW_PAUSE_NEXT_FLAG = STATE_DIR / "biweekly_pause_next.flag"
BW_FAILURE_LIMIT = 2          # biweekly_autorun.CONSECUTIVE_FAILURE_LIMIT
BW_EXPECTED_INTERVAL_DAYS = 7  # the task fires every Thursday, due period or not
BW_DEFAULT_STATE = {
    "consecutive_failures": 0, "last_run_at": None, "last_outcome": None,
    "last_detail": None, "last_period": None,
}

GREEN, RED, BLUE, AMBER = "#2a7", "#a33", "#246", "#a60"

TASKBAR_ALLOWANCE = 48  # logical px kept clear at the bottom of the screen for the taskbar

# The three results the biweekly tab must never blur together, plus the two
# "did not really run" ones. "skipped" is deliberately neither green nor
# "no data": it is the expected result most Thursdays, and it is not a report.
BW_OUTCOME_TEXT = {
    "published": ("רצה ופרסמה דוח חדש", GREEN),
    "skipped": ("רצה ודילגה כצפוי - אין תקופה חדשה שהגיע זמנה", BLUE),
    "failed": ("נכשלה - הייתה תקופה שהגיע זמנה ולא הופק דוח", RED),
    "paused": ("דולגה - השהיה ידנית לריצה אחת (תקופה הייתה מוכנה)", AMBER),
    "stopped": ("לא רצה - מפסק-החירום הדו-שבועי פעיל", RED),
}

NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def run_schtasks(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["schtasks", *args], capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW
    )


def _ps_literal(value: str) -> str:
    """Single-quoted PowerShell string literal, with embedded quotes doubled per
    PowerShell's own escaping rule - safe even though none of our real schtasks
    args need it today."""
    return "'" + value.replace("'", "''") + "'"


ELEVATION_CANCELLED = 1223  # ERROR_CANCELLED - what Start-Process -Verb RunAs raises
# when the user dismisses/denies the UAC prompt itself.


def run_schtasks_elevated(args: list[str]) -> tuple[int, str]:
    """Runs schtasks.exe elevated via a UAC prompt, for the specific actions confirmed
    by hand (2026-09-30) to need Administrator rights on this task even though its own
    Run-As-User is this same account: plain /Change /Enable or /Disable from a normal
    (non-elevated) session fails with 'Access is denied' - a Task-Scheduler ACL thing,
    not a Log-on-as-a-batch-job permission problem. Deliberately scoped to ONLY the one
    schtasks call that needs it (via PowerShell's Start-Process -Verb RunAs), so opening
    this app, checking status, pausing-today, saving the quota, or opening the log never
    trigger a UAC prompt - only clicking the Enable/Disable button does.
    Returns (exit_code, message) - exit_code 0 is success, ELEVATION_CANCELLED means the
    user dismissed the UAC prompt itself (not a real schtasks failure)."""
    arg_list_literal = ",".join(_ps_literal(a) for a in args)
    ps_command = (
        "try { "
        f"$p = Start-Process -FilePath schtasks -ArgumentList {arg_list_literal} "
        "-Verb RunAs -WindowStyle Hidden -Wait -PassThru -ErrorAction Stop; "
        "exit $p.ExitCode "
        "} catch { "
        "Write-Output $_.Exception.Message; "
        f"exit {ELEVATION_CANCELLED} "
        "}"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_command],
        capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW,
    )
    if result.returncode == 0:
        return 0, ""
    if result.returncode == ELEVATION_CANCELLED:
        return ELEVATION_CANCELLED, "בקשת ההרשאה (UAC) בוטלה - לא נעשה שינוי."
    return result.returncode, (result.stdout.strip() or result.stderr.strip() or f"קוד שגיאה {result.returncode}")


def query_task(task_name: str = SCHEDULED_TASK_NAME) -> dict:
    """Returns {'exists': bool, 'state': str|None, 'next_run': str|None, 'error': str|None}."""
    result = run_schtasks(["/Query", "/TN", task_name, "/V", "/FO", "LIST"])
    if result.returncode != 0:
        return {"exists": False, "state": None, "next_run": None, "error": result.stderr.strip() or result.stdout.strip()}
    info = {"exists": True, "state": None, "next_run": None, "error": None}
    for line in result.stdout.splitlines():
        if line.startswith("Scheduled Task State:"):
            info["state"] = line.split(":", 1)[1].strip()
        elif line.startswith("Next Run Time:"):
            info["next_run"] = line.split(":", 1)[1].strip()
    return info


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(default)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


class ControlPanel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("גאופוליטיקה - בקרת אוטומציה")

        self.hebrew_font = tkfont.Font(family="Segoe UI", size=10)
        self.bold_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.title_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")

        self._mapped = False
        self._build_widgets()
        self.refresh()

        # Explicit, measured sizing - not implicit auto-expand. Confirmed by hand
        # (2026-09-30) that BOTH of these are real, separate bugs:
        # (1) calling resizable(False, False) before all widgets exist can freeze the
        #     window at whatever size it had at that moment, clipping content packed in
        #     afterwards with no scrollbar and no error;
        # (2) even fixing (1) alone and just calling update_idletasks() once before
        #     resizable() was STILL not enough - a real screenshot after that fix still
        #     cut off the quota section/refresh/feedback, because winfo_reqheight() can
        #     undercount before the window has actually been mapped to the screen once.
        # The fix that was empirically verified to work: force a real map+draw cycle
        # first (update() does this; update_idletasks() alone does not), THEN read the
        # now-accurate winfo_reqwidth()/reqheight() and set geometry to EXACTLY that -
        # no guessing, no reliance on implicit auto-expand timing - and only lock
        # resizable() after this explicit size is set.
        self.update()
        self._fit_to_content()
        self.resizable(False, False)
        self._mapped = True

    def _fit_to_content(self):
        """Sizes the window to exactly what its content needs AND slides it up
        if that would push the bottom edge below the usable screen. A window
        locked with resizable(False, False) cannot be shrunk by the user, and
        the bottom row is the feedback line where every action reports back -
        measured 2026-10-13 on this machine (1920x1080 at 150% = 1280x720
        logical): the two-tab panel was 704 logical px tall and sat with its
        bottom ~55 px below the screen edge at Windows' default position."""
        self.update_idletasks()
        width, height = self.winfo_reqwidth(), self.winfo_reqheight()
        decoration = max(0, self.winfo_rooty() - self.winfo_y())   # title bar + top border
        lowest_top = self.winfo_screenheight() - TASKBAR_ALLOWANCE - (height + decoration)
        y = max(0, min(self.winfo_y(), lowest_top))
        self.geometry(f"{width}x{height}+{self.winfo_x()}+{y}")

    # ---------- widget construction ----------

    def _build_widgets(self):
        header = tk.Label(self, text="בקרת אוטומציה", font=self.title_font, anchor="e", justify="right")
        header.pack(fill="x", padx=12, pady=(8, 2))

        ttk.Style(self).configure("TNotebook.Tab", font=self.bold_font, padding=(14, 5))
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        daily_tab = tk.Frame(self.notebook)
        biweekly_tab = tk.Frame(self.notebook)
        self.notebook.add(daily_tab, text="ריצה יומית")
        self.notebook.add(biweekly_tab, text="דוח מגמות דו-שבועי")

        self._build_daily_tab(daily_tab)
        self._build_biweekly_tab(biweekly_tab)

        tk.Button(self, text="רענן", font=self.hebrew_font, command=self.refresh).pack(fill="x", padx=12, pady=(0, 2))

        self.feedback_label = tk.Label(
            self, text="", font=self.hebrew_font, anchor="e", justify="right", wraplength=430,
        )
        self.feedback_label.pack(fill="x", padx=12, pady=(2, 8))

    def _build_daily_tab(self, tab):
        status_frame = tk.LabelFrame(tab, text="מצב נוכחי", font=self.bold_font, labelanchor="ne")
        status_frame.pack(fill="x", padx=12, pady=3)
        self.status_labels: dict[str, tk.Label] = {}
        for key in ("task", "next_run", "last_run", "failures", "killswitch", "paused_today", "quota"):
            lbl = tk.Label(status_frame, text="", font=self.hebrew_font, anchor="e", justify="right")
            lbl.pack(fill="x", padx=10, pady=1)
            self.status_labels[key] = lbl

        actions_frame = tk.LabelFrame(tab, text="פעולות", font=self.bold_font, labelanchor="ne")
        actions_frame.pack(fill="x", padx=12, pady=3)

        self.btn_toggle_task = tk.Button(actions_frame, text="...", font=self.hebrew_font, command=self.on_toggle_task)
        self.btn_toggle_task.pack(fill="x", padx=10, pady=2)

        self.btn_toggle_pause = tk.Button(actions_frame, text="...", font=self.hebrew_font, command=self.on_toggle_pause_today)
        self.btn_toggle_pause.pack(fill="x", padx=10, pady=2)

        tk.Button(actions_frame, text="פתח לוג אחרון", font=self.hebrew_font, command=self.on_open_log).pack(
            fill="x", padx=10, pady=2
        )

        tk.Button(
            actions_frame, text="אפס מונה-כשלים ושחרר מפסק-חירום", font=self.hebrew_font, fg="#a33",
            command=self.on_reset_failures,
        ).pack(fill="x", padx=10, pady=2)

        quota_frame = tk.LabelFrame(tab, text="מכסת-ריצות מראש (ריק = ללא הגבלה)", font=self.bold_font, labelanchor="ne")
        quota_frame.pack(fill="x", padx=12, pady=3)

        row1 = tk.Frame(quota_frame)
        row1.pack(fill="x", padx=10, pady=(3, 1))
        tk.Label(row1, text="ריצות שנותרו:", font=self.hebrew_font, anchor="e", justify="right", width=24).pack(
            side="right"
        )
        self.entry_remaining_runs = tk.Entry(row1, font=self.hebrew_font, justify="right")
        self.entry_remaining_runs.pack(side="right", fill="x", expand=True, padx=(0, 6))

        row2 = tk.Frame(quota_frame)
        row2.pack(fill="x", padx=10, pady=1)
        tk.Label(row2, text="תאריך-סיום (YYYY-MM-DD):", font=self.hebrew_font, anchor="e", justify="right", width=24).pack(
            side="right"
        )
        self.entry_end_date = tk.Entry(row2, font=self.hebrew_font, justify="right")
        self.entry_end_date.pack(side="right", fill="x", expand=True, padx=(0, 6))

        tk.Button(quota_frame, text="שמור הגדרות-מכסה", font=self.hebrew_font, command=self.on_save_quota).pack(
            fill="x", padx=10, pady=(2, 4)
        )

    def _build_biweekly_tab(self, tab):
        status_frame = tk.LabelFrame(tab, text="מצב נוכחי", font=self.bold_font, labelanchor="ne")
        status_frame.pack(fill="x", padx=12, pady=3)
        self.bw_labels: dict[str, tk.Label] = {}
        self.bw_status_frame = status_frame
        for key in ("task", "next_run", "last_run", "last_period", "last_reason_caption", "last_reason",
                    "freshness", "failures", "killswitch", "pause_next"):
            # "last_reason" shows the wrapper's own English text verbatim, so it
            # is laid out left-to-right on a line of its own - mixed into a
            # Hebrew sentence, bidi reordering scrambles it.
            ltr = key == "last_reason"
            lbl = tk.Label(
                status_frame, text="", font=self.hebrew_font, wraplength=410,
                anchor="w" if ltr else "e", justify="left" if ltr else "right",
            )
            self.bw_labels[key] = lbl

        actions_frame = tk.LabelFrame(tab, text="פעולות", font=self.bold_font, labelanchor="ne")
        actions_frame.pack(fill="x", padx=12, pady=3)

        self.bw_btn_toggle_task = tk.Button(actions_frame, text="...", font=self.hebrew_font, command=self.on_bw_toggle_task)
        self.bw_btn_toggle_task.pack(fill="x", padx=10, pady=2)

        self.bw_btn_toggle_pause = tk.Button(actions_frame, text="...", font=self.hebrew_font, command=self.on_bw_toggle_pause_next)
        self.bw_btn_toggle_pause.pack(fill="x", padx=10, pady=2)

        tk.Button(actions_frame, text="פתח לוג דו-שבועי אחרון", font=self.hebrew_font, command=self.on_bw_open_log).pack(
            fill="x", padx=10, pady=2
        )

        tk.Button(
            actions_frame, text="אפס מונה-כשלים ושחרר מפסק-חירום", font=self.hebrew_font, fg=RED,
            command=self.on_bw_reset_failures,
        ).pack(fill="x", padx=10, pady=2)

        tk.Label(
            tab, font=self.hebrew_font, anchor="e", justify="right", wraplength=430, fg="#555",
            text="המשימה רצה כל יום חמישי ב-01:30 ומפיקה דוח רק בחמישי שאחרי סגירת תקופה (אחת לשבועיים). "
                 "בשאר השבועות \"דילגה כצפוי\" היא התוצאה התקינה.",
        ).pack(fill="x", padx=12, pady=(1, 4))

    # ---------- state reading + rendering ----------

    def refresh(self):
        self._refresh_daily()
        self._refresh_biweekly()
        # The biweekly tab's lines appear, disappear and wrap with its state
        # (a failure reason, the stale-run warning), so the height needed is
        # not fixed. Once the window has been mapped (see __init__ for why
        # only then), re-fit it on every refresh instead of clipping the
        # bottom rows at whatever size the first refresh happened to need.
        if self._mapped:
            self._fit_to_content()

    def _refresh_biweekly(self):
        task_info = query_task(BW_TASK_NAME)
        state = load_json(BW_STATE_FILE, BW_DEFAULT_STATE)
        L = self.bw_labels

        if not task_info["exists"]:
            L["task"].config(text="משימה מתוזמנת: לא נמצאה", fg=RED)
            self._bw_task_enabled = None
        else:
            enabled = task_info["state"] == "Enabled"
            self._bw_task_enabled = enabled
            L["task"].config(
                text=f"משימה מתוזמנת: {'פעילה (Enabled)' if enabled else 'מושהית (Disabled)'}",
                fg=GREEN if enabled else RED,
            )
        L["next_run"].config(text=f"ריצה הבאה: {task_info['next_run'] or '-'}")

        # Like the daily tab: this is the automated MECHANISM's last run (what
        # scripts/biweekly_autorun.py recorded), not "the latest published
        # period" - a period produced by hand does not show up here.
        outcome = state.get("last_outcome")
        last_run_at = state.get("last_run_at")
        when = (last_run_at or "").replace("T", " ")
        if outcome in BW_OUTCOME_TEXT:
            text, colour = BW_OUTCOME_TEXT[outcome]
            L["last_run"].config(text=f"ריצה אחרונה של המנגנון האוטומטי: {text} ({when})", fg=colour)
        elif outcome:
            L["last_run"].config(text=f"ריצה אחרונה של המנגנון האוטומטי: תוצאה לא מוכרת '{outcome}' ({when})", fg=RED)
        else:
            L["last_run"].config(text="ריצה אחרונה של המנגנון האוטומטי: אין נתונים עדיין (טרם רץ)", fg="black")

        period = state.get("last_period") or ""
        L["last_period"].config(text=f"תקופה: {period.replace('..', ' עד ')}" if period else "")
        show_reason = outcome == "failed" and bool(state.get("last_detail"))
        L["last_reason_caption"].config(text="סיבת הכשל, כפי שנרשמה" if show_reason else "", fg=RED)
        L["last_reason"].config(text=state["last_detail"] if show_reason else "", fg=RED)

        # A run that never happened (machine off at 01:30) records nothing, so
        # the last outcome alone would keep showing an old, reassuring result.
        freshness_text, freshness_colour = "", "black"
        if last_run_at and self._bw_task_enabled:
            try:
                age = datetime.now() - datetime.fromisoformat(last_run_at)
                if age > timedelta(days=BW_EXPECTED_INTERVAL_DAYS, hours=12):
                    freshness_text = (f"שימו לב: לא נרשמה ריצה כבר {age.days} ימים, אף שהמשימה אמורה לרוץ כל שבוע - "
                                      f"ייתכן שהמחשב היה כבוי ב-01:30")
                    freshness_colour = RED
            except ValueError:
                pass
        L["freshness"].config(text=freshness_text, fg=freshness_colour)

        failures = state.get("consecutive_failures", 0)
        if failures >= BW_FAILURE_LIMIT:
            failures_note = " (הגיע לסף מפסק-החירום)"
        elif failures >= BW_FAILURE_LIMIT - 1 and failures > 0:
            failures_note = " (כשל נוסף יפעיל את מפסק-החירום!)"
        else:
            failures_note = ""
        L["failures"].config(
            text=f"כשלים רצופים: {failures} מתוך {BW_FAILURE_LIMIT}{failures_note}", fg=RED if failures >= 1 else "black",
        )

        self._bw_killswitch = BW_KILLSWITCH_FLAG.exists()
        L["killswitch"].config(
            text="מפסק-חירום דו-שבועי: פעיל - שום ריצה לא תתבצע עד לשחרור" if self._bw_killswitch
            else "מפסק-חירום דו-שבועי: לא פעיל",
            fg=RED if self._bw_killswitch else "black",
        )

        self._bw_pause_next = BW_PAUSE_NEXT_FLAG.exists()
        L["pause_next"].config(
            text="מושהה לריצה הבאה: כן - הדוח הבא שיגיע זמנו ידולג פעם אחת" if self._bw_pause_next
            else "מושהה לריצה הבאה: לא",
            fg=AMBER if self._bw_pause_next else "black",
        )

        # Lines with nothing to say are removed rather than left as blank rows;
        # re-packing all of them keeps the order fixed.
        for lbl in L.values():
            lbl.pack_forget()
        for lbl in L.values():
            if lbl.cget("text"):
                lbl.pack(fill="x", padx=10, pady=1)

        if self._bw_task_enabled is None:
            self.bw_btn_toggle_task.config(text="(משימה לא נמצאה - הריצו את register_biweekly_task.ps1)", state="disabled")
        else:
            self.bw_btn_toggle_task.config(
                text="השהה את הדוח הדו-שבועי לגמרי" if self._bw_task_enabled else "הפעל את הדוח הדו-שבועי",
                state="normal",
            )
        self.bw_btn_toggle_pause.config(
            text="בטל השהיית הריצה הבאה" if self._bw_pause_next else "השהה רק את הריצה הבאה"
        )

    def _refresh_daily(self):
        task_info = query_task()
        state = load_json(STATE_FILE, {"consecutive_failures": 0, "last_run_date": None, "last_run_status": None})
        config = load_json(CONFIG_FILE, {"remaining_runs": None, "end_date": None})
        paused_today = PAUSE_FLAG.exists()

        if not task_info["exists"]:
            self.status_labels["task"].config(text="משימה מתוזמנת: לא נמצאה", fg="#a33")
            self._task_enabled = None
        else:
            enabled = task_info["state"] == "Enabled"
            self._task_enabled = enabled
            self.status_labels["task"].config(
                text=f"משימה מתוזמנת: {'פעילה (Enabled)' if enabled else 'מושהית (Disabled)'}",
                fg="#2a7" if enabled else "#a33",
            )
        self.status_labels["next_run"].config(text=f"ריצה הבאה: {task_info['next_run'] or '-'}")

        # Label says "the automated MECHANISM's last run", not "the last published report" -
        # deliberately explicit (2026-09-30 finding): this reads automation_state/state.json,
        # which is written ONLY by scripts/daily_autorun.py's own main() - it does NOT update
        # when a report gets produced by some other means (e.g. a manual step-by-step run of
        # fetch/analyze/synthesize/render/publish). The two can genuinely show different dates
        # without that being a bug - confirmed by hand: state.json said 2026-09-28 (the one real
        # daily_autorun.py run so far, its Part-6 dry run) while reports/ already had 2026-09-29
        # from a manual run. The old wording ("ריצה אחרונה") looked like it meant the latter.
        if state.get("last_run_date"):
            status_txt = "הצליחה" if state.get("last_run_status") == "success" else "נכשלה"
            self.status_labels["last_run"].config(
                text=f"ריצה אחרונה של המנגנון האוטומטי: {status_txt} ({state['last_run_date']})",
                fg="#2a7" if state.get("last_run_status") == "success" else "#a33",
            )
        else:
            self.status_labels["last_run"].config(
                text="ריצה אחרונה של המנגנון האוטומטי: אין נתונים עדיין (טרם רץ)", fg="black"
            )

        failures = state.get("consecutive_failures", 0)
        if failures >= DAILY_FAILURE_LIMIT:
            failures_note = " (הגיע לסף מפסק-החירום)"
        elif failures >= DAILY_FAILURE_LIMIT - 1 and failures > 0:
            failures_note = " (כשל נוסף יפעיל את מפסק-החירום!)"
        else:
            failures_note = ""
        self.status_labels["failures"].config(
            text=f"כשלים רצופים: {failures} מתוך {DAILY_FAILURE_LIMIT}{failures_note}",
            fg=RED if failures >= 1 else "black",
        )

        # The flag file - not the counter - is what actually stops
        # daily_autorun.py (it checks the file first and exits). The counter can
        # read 0 while the flag is still on disk, so this has to be shown on its
        # own line, not inferred from the number above.
        self._killswitch = KILLSWITCH_FLAG.exists()
        self.status_labels["killswitch"].config(
            text="מפסק-חירום יומי: פעיל - שום ריצה לא תתבצע עד לשחרור" if self._killswitch
            else "מפסק-חירום יומי: לא פעיל",
            fg=RED if self._killswitch else "black",
        )

        self._paused_today = paused_today
        self.status_labels["paused_today"].config(
            text=f"מושהה להיום: {'כן' if paused_today else 'לא'}", fg="#a33" if paused_today else "black"
        )

        remaining = config.get("remaining_runs")
        end_date = config.get("end_date")
        if remaining is None and end_date is None:
            quota_txt = "ללא הגבלה"
        else:
            parts = []
            if remaining is not None:
                parts.append(f"{remaining} ריצות נותרו")
            if end_date is not None:
                parts.append(f"עד {end_date}")
            quota_txt = " / ".join(parts)
        self.status_labels["quota"].config(text=f"מכסת-ריצות: {quota_txt}")

        self.entry_remaining_runs.delete(0, tk.END)
        if remaining is not None:
            self.entry_remaining_runs.insert(0, str(remaining))
        self.entry_end_date.delete(0, tk.END)
        if end_date is not None:
            self.entry_end_date.insert(0, str(end_date))

        if self._task_enabled is None:
            self.btn_toggle_task.config(text="(משימה לא נמצאה - הריצו את register_scheduled_task.ps1)", state="disabled")
        else:
            self.btn_toggle_task.config(
                text="השהה אוטומציה לגמרי" if self._task_enabled else "הפעל אוטומציה", state="normal"
            )
        self.btn_toggle_pause.config(text="בטל השהיית-היום" if paused_today else "השהה רק להיום")

    def _set_feedback(self, message: str, ok: bool = True):
        self.feedback_label.config(text=message, fg="#2a7" if ok else "#a33")

    # ---------- actions ----------

    def on_toggle_task(self):
        if self._task_enabled is None:
            return
        action = "/Disable" if self._task_enabled else "/Enable"
        # Enable/Disable needs Administrator rights on this task (confirmed by hand,
        # 2026-09-30 - see run_schtasks_elevated's docstring) - a UAC prompt appears now,
        # scoped to only this one call.
        self._set_feedback("מבקש הרשאת-מנהל (UAC) לביצוע הפעולה...", ok=True)
        self.update_idletasks()
        exit_code, message = run_schtasks_elevated(["/Change", "/TN", SCHEDULED_TASK_NAME, action])
        if exit_code == 0:
            self._set_feedback(f"המשימה {'הושהתה' if action == '/Disable' else 'הופעלה'} בהצלחה.", ok=True)
        elif exit_code == ELEVATION_CANCELLED:
            self._set_feedback(message, ok=False)
        else:
            self._set_feedback(f"הפעולה נכשלה: {message}", ok=False)
        self.refresh()

    def on_toggle_pause_today(self):
        try:
            if PAUSE_FLAG.exists():
                PAUSE_FLAG.unlink()
                self._set_feedback("השהיית-היום בוטלה.", ok=True)
            else:
                PAUSE_FLAG.write_text(
                    f"נוצר ידנית דרך לוח-הבקרה ב-{datetime.now().isoformat(timespec='seconds')}\n", encoding="utf-8"
                )
                self._set_feedback("היום הושהה - הריצה המתוזמנת של היום תדולג (לא תיספר ככישלון).", ok=True)
        except OSError as e:
            self._set_feedback(f"הפעולה נכשלה: {e}", ok=False)
        self.refresh()

    def on_open_log(self):
        if not LOG_DIR.exists():
            self._set_feedback("תיקיית הלוגים עדיין לא קיימת - עוד לא הייתה ריצה.", ok=False)
            return
        # Daily logs are named {date}.log; "biweekly_*.log" in the same folder
        # belongs to the other tab and would sort after every one of them.
        logs = sorted(LOG_DIR.glob("[0-9]*.log"))
        if not logs:
            self._set_feedback("לא נמצאו קובצי-לוג.", ok=False)
            return
        latest = logs[-1]
        try:
            subprocess.Popen(["notepad.exe", str(latest)])
            self._set_feedback(f"נפתח: {latest.name}", ok=True)
        except OSError as e:
            self._set_feedback(f"פתיחת הלוג נכשלה: {e}", ok=False)

    def on_reset_failures(self):
        state = load_json(STATE_FILE, {"consecutive_failures": 0, "last_run_date": None, "last_run_status": None})
        current = state.get("consecutive_failures", 0)
        flag = KILLSWITCH_FLAG.exists()
        # "counter is 0" alone must not end this early: a flag left on disk with a
        # counter already at 0 is exactly the state that keeps the run blocked.
        if current == 0 and not flag:
            self._set_feedback("מונה-הכשלים היומי על 0 ומפסק-החירום לא פעיל - אין מה לאפס.", ok=True)
            return
        if not messagebox.askyesno(
            "אישור איפוס - ריצה יומית",
            f"כשלים רצופים: {current}. מפסק-חירום: {'פעיל' if flag else 'לא פעיל'}.\n"
            f"לאפס את המונה ל-0 ולשחרר את המפסק? (מומלץ רק אחרי שבדקתם ותיקנתם את הסיבה לכשלים)\n\n"
            f"הפעולה נוגעת רק לריצה היומית - מונה-הכשלים של הדוח הדו-שבועי לא משתנה.",
        ):
            return
        try:
            state["consecutive_failures"] = 0
            save_json(STATE_FILE, state)
            if flag:
                KILLSWITCH_FLAG.unlink()
        except OSError as e:
            self._set_feedback(f"האיפוס נכשל: {e}", ok=False)
            self.refresh()
            return
        self.refresh()
        # When the breaker trips, daily_autorun.py also disables the Windows task;
        # releasing the flag does not re-enable it.
        if flag and self._task_enabled is False:
            self._set_feedback("אופס ושוחרר. המשימה המתוזמנת עדיין מושהית - לחצו \"הפעל אוטומציה\".", ok=False)
        else:
            self._set_feedback("מונה-הכשלים היומי אופס ומפסק-החירום שוחרר.", ok=True)

    def on_bw_toggle_task(self):
        if self._bw_task_enabled is None:
            return
        action = "/Disable" if self._bw_task_enabled else "/Enable"
        self._set_feedback("מבקש הרשאת-מנהל (UAC) לביצוע הפעולה...", ok=True)
        self.update_idletasks()
        exit_code, message = run_schtasks_elevated(["/Change", "/TN", BW_TASK_NAME, action])
        if exit_code == 0:
            self._set_feedback(
                f"המשימה הדו-שבועית {'הושהתה' if action == '/Disable' else 'הופעלה'} בהצלחה. הריצה היומית לא הושפעה.", ok=True
            )
        elif exit_code == ELEVATION_CANCELLED:
            self._set_feedback(message, ok=False)
        else:
            self._set_feedback(f"הפעולה נכשלה: {message}", ok=False)
        self.refresh()

    def on_bw_toggle_pause_next(self):
        try:
            if BW_PAUSE_NEXT_FLAG.exists():
                BW_PAUSE_NEXT_FLAG.unlink()
                self._set_feedback("השהיית הריצה הדו-שבועית הבאה בוטלה.", ok=True)
            else:
                BW_PAUSE_NEXT_FLAG.parent.mkdir(parents=True, exist_ok=True)
                BW_PAUSE_NEXT_FLAG.write_text(
                    f"נוצר ידנית דרך לוח-הבקרה ב-{datetime.now().isoformat(timespec='seconds')}\n", encoding="utf-8"
                )
                self._set_feedback(
                    "הדוח הדו-שבועי הבא שיגיע זמנו ידולג פעם אחת (לא ייספר ככישלון), וההשהיה תוסר מעצמה. "
                    "שבוע שבו אין תקופה מוכנה לא מנצל את ההשהיה. הריצה היומית לא הושפעה.", ok=True
                )
        except OSError as e:
            self._set_feedback(f"הפעולה נכשלה: {e}", ok=False)
        self.refresh()

    def on_bw_open_log(self):
        logs = sorted(LOG_DIR.glob("biweekly_*.log")) if LOG_DIR.exists() else []
        if not logs:
            self._set_feedback("לא נמצאו קובצי-לוג דו-שבועיים - עוד לא הייתה ריצה.", ok=False)
            return
        latest = logs[-1]
        try:
            subprocess.Popen(["notepad.exe", str(latest)])
            self._set_feedback(f"נפתח: {latest.name}", ok=True)
        except OSError as e:
            self._set_feedback(f"פתיחת הלוג נכשלה: {e}", ok=False)

    def on_bw_reset_failures(self):
        state = load_json(BW_STATE_FILE, BW_DEFAULT_STATE)
        current = state.get("consecutive_failures", 0)
        flag = BW_KILLSWITCH_FLAG.exists()
        if current == 0 and not flag:
            self._set_feedback("מונה-הכשלים הדו-שבועי על 0 ומפסק-החירום לא פעיל - אין מה לאפס.", ok=True)
            return
        if not messagebox.askyesno(
            "אישור איפוס - דוח דו-שבועי",
            f"כשלים רצופים: {current}. מפסק-חירום: {'פעיל' if flag else 'לא פעיל'}.\n"
            f"לאפס את המונה ל-0 ולשחרר את המפסק? (מומלץ רק אחרי שבדקתם ותיקנתם את הסיבה לכשלים)\n\n"
            f"הפעולה נוגעת רק לדוח הדו-שבועי - מונה-הכשלים של הריצה היומית לא משתנה.",
        ):
            return
        try:
            state["consecutive_failures"] = 0
            save_json(BW_STATE_FILE, state)
            if flag:
                BW_KILLSWITCH_FLAG.unlink()
        except OSError as e:
            self._set_feedback(f"האיפוס נכשל: {e}", ok=False)
            self.refresh()
            return
        self.refresh()
        if flag and self._bw_task_enabled is False:
            self._set_feedback("אופס ושוחרר. המשימה המתוזמנת עדיין מושהית - לחצו \"הפעל את הדוח הדו-שבועי\".", ok=False)
        else:
            self._set_feedback("מונה-הכשלים הדו-שבועי אופס ומפסק-החירום שוחרר.", ok=True)

    def on_save_quota(self):
        remaining_text = self.entry_remaining_runs.get().strip()
        end_date_text = self.entry_end_date.get().strip()

        remaining_value = None
        if remaining_text:
            try:
                remaining_value = int(remaining_text)
                if remaining_value < 0:
                    raise ValueError
            except ValueError:
                self._set_feedback("'ריצות שנותרו' חייב להיות מספר שלם לא-שלילי, או ריק.", ok=False)
                return

        end_date_value = None
        if end_date_text:
            try:
                datetime.strptime(end_date_text, "%Y-%m-%d")
                end_date_value = end_date_text
            except ValueError:
                self._set_feedback("'תאריך-סיום' חייב להיות בפורמט YYYY-MM-DD, או ריק.", ok=False)
                return

        config = load_json(CONFIG_FILE, {"remaining_runs": None, "end_date": None})
        config["remaining_runs"] = remaining_value
        config["end_date"] = end_date_value
        save_json(CONFIG_FILE, config)
        self._set_feedback("הגדרות-המכסה נשמרו.", ok=True)
        self.refresh()


if __name__ == "__main__":
    app = ControlPanel()
    app.mainloop()
