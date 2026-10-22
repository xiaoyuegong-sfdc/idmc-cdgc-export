"""Per-execution log files for the IDMC scripts.

Each run writes <logFolder>/<log_name>.log (default <script>_<timestamp>.log) with the tasks performed,
their results, status and duration, plus the overall status and execution time.
logFolder comes from the config file (default: ./logs).

While a long export job runs, progress() keeps <log_name>_in_progress.log up to date
(rewritten at most every 2 minutes with the job status and timestamp); it is deleted
once the final log is written.

    with RunLog("export_business_assets", config_file, "Export_Business_Assets_1792505693") as log:
        with log.task("Authenticate") as t:
            ...
            t["result"] = "logged in"
"""
import os
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import datetime

DEFAULT_LOG_FOLDER = "logs"  # relative to the current folder
PROGRESS_INTERVAL = 120  # seconds between intermediate log updates


def _log_folder(config_file):
    """logFolder from the .properties config, read leniently so logging works even if the config is broken."""
    try:
        for line in open(config_file, encoding="utf-8"):
            key, sep, value = line.strip().partition("=")
            if sep and key.strip() == "logFolder" and value.strip():
                return value.strip()
    except OSError:
        pass
    return DEFAULT_LOG_FOLDER


def _error_text(exc):
    if isinstance(exc, SystemExit):
        return str(exc.code).removeprefix("ERROR: ") if exc.code not in (None, 0) else ""
    if isinstance(exc, KeyboardInterrupt):
        return "interrupted by user"
    return f"{type(exc).__name__}: {exc}"


class RunLog:
    def __init__(self, script, config_file, log_name=None):
        self.script = script
        self.folder = _log_folder(config_file)
        self.started = datetime.now()
        self.log_name = log_name or f"{script}_{self.started:%Y%m%d_%H%M%S}"
        self.tasks = []
        self.progress_path = os.path.join(self.folder, f"{self.log_name}_in_progress.log")
        self.updates = []  # (timestamp, note) written to the intermediate log
        self.summary = []  # free-form lines added by the script, written as a "Summary" section
        self._last_progress = None

    def progress(self, note, elapsed=None):
        """Record a job status update; rewrites the intermediate log on the first call, then every 2 minutes."""
        now = time.time()
        if self._last_progress is not None and now - self._last_progress < PROGRESS_INTERVAL:
            return
        self._last_progress = now
        suffix = f" (waited {elapsed:.0f} s)" if elapsed is not None else ""
        self.updates.append(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {note}{suffix}")
        try:
            self._write("RUNNING", "", "", path=self.progress_path,
                        extra=["", "Job status updates (every 2 minutes)"] + [f"  {u}" for u in self.updates])
        except OSError as e:
            print(f"WARNING: could not write intermediate log: {e}", file=sys.stderr)

    @contextmanager
    def task(self, name):
        entry = {"name": name, "status": "RUNNING", "result": "", "error": ""}
        self.tasks.append(entry)
        start = time.time()
        try:
            yield entry
            entry["status"] = "SUCCESS"
        except BaseException as e:
            failed = not (isinstance(e, SystemExit) and e.code in (None, 0))
            entry["status"] = "FAILED" if failed else "SUCCESS"
            entry["error"] = _error_text(e)
            raise
        finally:
            entry["duration"] = time.time() - start

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        failed = exc is not None and not (isinstance(exc, SystemExit) and exc.code in (None, 0))
        error = _error_text(exc) if failed else ""
        detail = "".join(traceback.format_exception(exc_type, exc, tb)) \
            if failed and not isinstance(exc, (SystemExit, KeyboardInterrupt)) else ""
        try:
            extra = ["", "Summary"] + [f"  {line}" for line in self.summary] if self.summary else ()
            path = self._write("FAILED" if failed else "SUCCESS", error, detail, extra=extra)
            print(f"Log written to {os.path.abspath(path)}")
        except OSError as e:
            print(f"WARNING: could not write log file: {e}", file=sys.stderr)
        else:
            if os.path.exists(self.progress_path):
                os.remove(self.progress_path)
        return False  # never swallow the exception

    def _write(self, status, error, detail, path=None, extra=()):
        finished = datetime.now()
        os.makedirs(self.folder, exist_ok=True)
        path = path or os.path.join(self.folder, f"{self.log_name}.log")
        running = status == "RUNNING"
        width = max([len(t["name"]) for t in self.tasks] + [4])
        lines = [
            f"Script     : {self.script}.py",
            f"Arguments  : {' '.join(sys.argv[1:]) or '(none)'}",
            f"Started    : {self.started:%Y-%m-%d %H:%M:%S}",
            f"Updated    : {finished:%Y-%m-%d %H:%M:%S}" if running else f"Finished   : {finished:%Y-%m-%d %H:%M:%S}",
            f"Duration   : {(finished - self.started).total_seconds():.1f} s",
            f"Status     : {status}",
            "",
            "Tasks",
        ]
        for i, t in enumerate(self.tasks, 1):
            lines.append(f"  {i}. {t['name']:<{width}}  {t['status']:<7}  {t.get('duration', 0):7.1f} s")
            if t["result"]:
                lines.append(f"     result: {t['result']}")
            if t["error"]:
                lines.append(f"     error : {t['error']}")
        if not self.tasks:
            lines.append("  (none)")
        lines += extra
        if error:
            lines += ["", f"Error      : {error}"]
        if detail:
            lines += ["", detail.rstrip()]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return path
