"""GUI control panel for scripts/daily_autorun.py's unattended scheduled task -
a small tkinter window so the Windows Task Scheduler task, .pause_automation
flag, automation_state/config.json quota, and automation_state/state.json
failure counter never need to be managed by hand-typed schtasks/PowerShell
commands. tkinter is Python's stdlib GUI toolkit - no new dependency.

.pyw (not .py) so double-clicking it launches with pythonw.exe - no console
window. Every subprocess call to schtasks.exe explicitly passes
creationflags=subprocess.CREATE_NO_WINDOW for the same reason (schtasks.exe
is a console-subsystem program; spawning it from a windowed/no-console
parent would otherwise flash a new console window open for each call).

Reads/writes exactly the same files scripts/daily_autorun.py itself reads/
writes (automation_state/state.json, automation_state/config.json,
.pause_automation) - this is a thin control surface over that state, not a
second source of truth for it.
"""
import json
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = PROJECT_ROOT / "automation_state"
LOG_DIR = STATE_DIR / "logs"
STATE_FILE = STATE_DIR / "state.json"
CONFIG_FILE = STATE_DIR / "config.json"
PAUSE_FLAG = PROJECT_ROOT / ".pause_automation"
SCHEDULED_TASK_NAME = "GeopoliticsTrackerDailyAutorun"

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


def query_task() -> dict:
    """Returns {'exists': bool, 'state': str|None, 'next_run': str|None, 'error': str|None}."""
    result = run_schtasks(["/Query", "/TN", SCHEDULED_TASK_NAME, "/V", "/FO", "LIST"])
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
        self.title("גאופוליטיקה יומי - בקרת אוטומציה")

        self.hebrew_font = tkfont.Font(family="Segoe UI", size=10)
        self.bold_font = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.title_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")

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
        self.geometry(f"{self.winfo_reqwidth()}x{self.winfo_reqheight()}")
        self.resizable(False, False)

    # ---------- widget construction ----------

    def _build_widgets(self):
        header = tk.Label(self, text="בקרת אוטומציה - הרצה יומית", font=self.title_font, anchor="e", justify="right")
        header.pack(fill="x", padx=12, pady=(12, 6))

        status_frame = tk.LabelFrame(self, text="מצב נוכחי", font=self.bold_font, labelanchor="ne")
        status_frame.pack(fill="x", padx=12, pady=6)
        self.status_labels: dict[str, tk.Label] = {}
        for key in ("task", "next_run", "last_run", "failures", "paused_today", "quota"):
            lbl = tk.Label(status_frame, text="", font=self.hebrew_font, anchor="e", justify="right")
            lbl.pack(fill="x", padx=10, pady=2)
            self.status_labels[key] = lbl

        actions_frame = tk.LabelFrame(self, text="פעולות", font=self.bold_font, labelanchor="ne")
        actions_frame.pack(fill="x", padx=12, pady=6)

        self.btn_toggle_task = tk.Button(actions_frame, text="...", font=self.hebrew_font, command=self.on_toggle_task)
        self.btn_toggle_task.pack(fill="x", padx=10, pady=4)

        self.btn_toggle_pause = tk.Button(actions_frame, text="...", font=self.hebrew_font, command=self.on_toggle_pause_today)
        self.btn_toggle_pause.pack(fill="x", padx=10, pady=4)

        tk.Button(actions_frame, text="פתח לוג אחרון", font=self.hebrew_font, command=self.on_open_log).pack(
            fill="x", padx=10, pady=4
        )

        tk.Button(
            actions_frame, text="אפס מונה-כשלים", font=self.hebrew_font, fg="#a33",
            command=self.on_reset_failures,
        ).pack(fill="x", padx=10, pady=4)

        quota_frame = tk.LabelFrame(self, text="מכסת-ריצות מראש (ריק = ללא הגבלה)", font=self.bold_font, labelanchor="ne")
        quota_frame.pack(fill="x", padx=12, pady=6)

        row1 = tk.Frame(quota_frame)
        row1.pack(fill="x", padx=10, pady=(6, 2))
        tk.Label(row1, text="ריצות שנותרו:", font=self.hebrew_font, anchor="e", justify="right", width=24).pack(
            side="right"
        )
        self.entry_remaining_runs = tk.Entry(row1, font=self.hebrew_font, justify="right")
        self.entry_remaining_runs.pack(side="right", fill="x", expand=True, padx=(0, 6))

        row2 = tk.Frame(quota_frame)
        row2.pack(fill="x", padx=10, pady=2)
        tk.Label(row2, text="תאריך-סיום (YYYY-MM-DD):", font=self.hebrew_font, anchor="e", justify="right", width=24).pack(
            side="right"
        )
        self.entry_end_date = tk.Entry(row2, font=self.hebrew_font, justify="right")
        self.entry_end_date.pack(side="right", fill="x", expand=True, padx=(0, 6))

        tk.Button(quota_frame, text="שמור הגדרות-מכסה", font=self.hebrew_font, command=self.on_save_quota).pack(
            fill="x", padx=10, pady=(4, 8)
        )

        tk.Button(self, text="רענן", font=self.hebrew_font, command=self.refresh).pack(fill="x", padx=12, pady=(0, 4))

        self.feedback_label = tk.Label(
            self, text="", font=self.hebrew_font, anchor="e", justify="right", wraplength=430,
        )
        self.feedback_label.pack(fill="x", padx=12, pady=(4, 12))

    # ---------- state reading + rendering ----------

    def refresh(self):
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
        self.status_labels["failures"].config(
            text=f"כשלים רצופים: {failures}" + (" (מפסק-חירום עלול להתפעל!)" if failures >= 1 else ""),
            fg="#a33" if failures >= 1 else "black",
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
        logs = sorted(LOG_DIR.glob("*.log"))
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
        if current == 0:
            self._set_feedback("מונה-הכשלים כבר על 0 - אין מה לאפס.", ok=True)
            return
        if not messagebox.askyesno(
            "אישור איפוס",
            f"מונה-הכשלים הרצופים כרגע עומד על {current}.\n"
            f"לאפס אותו ל-0? (מומלץ רק אחרי שבדקתם ותיקנתם את הסיבה לכשלים)",
        ):
            return
        state["consecutive_failures"] = 0
        save_json(STATE_FILE, state)
        self._set_feedback("מונה-הכשלים אופס ל-0.", ok=True)
        self.refresh()

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
