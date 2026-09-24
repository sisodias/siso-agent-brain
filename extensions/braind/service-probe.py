#!/usr/bin/env python3
"""
service-probe — the hub-and-spoke health pulse for the Mac Mini.

Reads every registered service in mini_services, probes whether it's actually
alive (port listening, launchagent loaded, or process present), and writes
status + health + last_seen back into the brain. This is what makes the brain
SEE the whole Mini: agents can ask "what's running / what's down" and act.

Runs ON the Mini (single-writer host), via launchd every few minutes. Reads/
writes the spine DB directly like sched-runner. No LLM, deterministic, cheap.

Run:  service-probe.py
Env:  SISO_DB (default ~/SISO_Workspace/.SystemDB/sisosystem.db)
"""
import os, sqlite3, subprocess, time

HOME = os.path.expanduser("~")
DB = os.environ.get("SISO_DB", f"{HOME}/SISO_Workspace/.SystemDB/sisosystem.db")


def port_up(port):
    try:
        r = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                           capture_output=True, text=True, timeout=8)
        return "LISTEN" in r.stdout
    except Exception:
        return False


def agent_loaded(label):
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=8)
        return label in r.stdout
    except Exception:
        return False


def proc_present(needle):
    try:
        r = subprocess.run(["pgrep", "-f", needle], capture_output=True, text=True, timeout=8)
        return bool(r.stdout.strip())
    except Exception:
        return False


def http_health(port):
    """Best-effort HTTP probe; returns a short status string or None."""
    try:
        r = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "5",
             f"http://localhost:{port}/"], capture_output=True, text=True, timeout=8)
        code = r.stdout.strip()
        return f"http {code}" if code and code != "000" else None
    except Exception:
        return None


def main():
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT * FROM mini_services").fetchall()
    for s in rows:
        alive, health = False, None
        if s["port"]:
            alive = port_up(s["port"])
            if alive:
                health = http_health(s["port"])
        if not alive and s["launch_agent"]:
            alive = agent_loaded(s["launch_agent"])
            health = health or ("launchd-loaded" if alive else None)
        if not alive and s["command"]:
            # last resort: is a process matching the command running?
            needle = (s["command"].split()[0] if s["command"] else "")
            if needle:
                alive = proc_present(needle)
                health = health or ("proc-present" if alive else None)
        status = "running" if alive else "stopped"
        c.execute(
            "UPDATE mini_services SET status=?, health=?, last_seen=? WHERE id=?",
            (status, health or status, now, s["id"]))
    c.commit()
    up = c.execute("SELECT count(*) FROM mini_services WHERE status='running'").fetchone()[0]
    total = len(rows)
    print(f"service-probe: {up}/{total} running @ {now}")
    c.close()


if __name__ == "__main__":
    main()
