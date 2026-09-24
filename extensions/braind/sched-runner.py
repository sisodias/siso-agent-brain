#!/usr/bin/env python3
"""
sched-runner — fires due scheduled_triggers from the brain DB.

Runs on the Mini (the brain host) every few minutes via launchd. For each
enabled trigger, decides if it's due (interval since last_run, or weekly/daily/
hourly cadence), runs its command, and records last_run. This is the piece that
makes scheduled_triggers actually fire (farm weekly, future digests, etc).

Respects the global kill-switch: if control_flags has global paused=1, it runs
nothing. Reads/writes the DB directly (runs ON the Mini = the single writer host).

Run:  sched-runner.py            (idempotent; safe to run every N minutes)
Env:  SISO_DB (default ~/SISO_Workspace/.SystemDB/sisosystem.db)
"""
import os, sqlite3, subprocess, sys, time

HOME = os.path.expanduser("~")
DB = os.environ.get("SISO_DB", f"{HOME}/SISO_Workspace/.SystemDB/sisosystem.db")

# cadence -> minimum seconds between runs
CADENCE = {"hourly": 3600, "daily": 86400, "weekly": 604800}


def due(schedule, last_run_epoch, now):
    s = (schedule or "").strip().lower()
    if s in CADENCE:
        return (now - last_run_epoch) >= CADENCE[s]
    if s.startswith("every"):  # "every 300s" / "every 30m" / "every 2h"
        try:
            num = "".join(ch for ch in s if ch.isdigit())
            unit = s.rstrip()[-1]
            secs = int(num) * {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(unit, 60)
            return (now - last_run_epoch) >= secs
        except Exception:
            return False
    # unknown schedule: run at most daily as a safe default
    return (now - last_run_epoch) >= 86400


def main():
    now = time.time()
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row

    paused = c.execute("SELECT 1 FROM control_flags WHERE scope='global' AND paused=1").fetchone()
    if paused:
        print("global halt active — sched-runner running nothing")
        return

    rows = c.execute("SELECT * FROM scheduled_triggers WHERE enabled=1").fetchall()
    fired = []
    for r in rows:
        lr = r["last_run"]
        # parse last_run to epoch; treat missing as long ago (always due)
        last_epoch = 0
        if lr:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    last_epoch = time.mktime(time.strptime(lr[:19], fmt)); break
                except Exception:
                    pass
        if not due(r["schedule"], last_epoch, now):
            continue
        cmd = r["command"]
        try:
            subprocess.Popen(["/bin/zsh", "-lc", cmd],
                             stdout=open(f"/tmp/sched-{r['id']}.log", "a"),
                             stderr=subprocess.STDOUT)
            c.execute("UPDATE scheduled_triggers SET last_run=? WHERE id=?",
                      (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)), r["id"]))
            c.commit()
            fired.append(r["name"])
        except Exception as e:
            sys.stderr.write(f"trigger {r['id']} failed: {e}\n")
    c.close()
    print(f"sched-runner: fired {len(fired)} -> {fired}" if fired else "sched-runner: nothing due")


if __name__ == "__main__":
    main()
