#!/usr/bin/env python3
"""
siso-doctor — verify the JARVIS base is healthy + register project divisions.

Run from any machine. Checks the full stack end-to-end and prints a PASS/FAIL
report (the "cohesion proof"): brain reachable, auth tiers, schema version,
Face serving, fleet live, divisions registered. With --register, it (re)registers
the known SISO project divisions in the brain (in-place — repos are not moved).

Usage:  siso-doctor.py [--register]
Env:    SISO_BRAIN_URL / SISO_BRAIN_TOKEN
"""
import argparse, json, os, subprocess, sys, urllib.request, ssl

HOME = os.path.expanduser("~")
SISO_BRAIN = os.environ.get("SISO_BRAIN_BIN", f"{HOME}/SISO_Workspace/SISO_Agents/siso-agent-brain/extensions/braind/siso-brain")
WS = f"{HOME}/SISO_Workspace"

# Known SISO project divisions (registered in-place; repo_path is where each lives).
DIVISIONS = [
    ("oracle-streaming", "Oracle Streaming", f"{WS}/SISO_Agency/apps/oracle-streaming"),
    ("isso-dashboard", "ISSO Dashboard", f"{WS}/SISO_Agency/apps/isso-dashboard"),
    ("agent-base", "SISO Agent Base", f"{WS}/SISO_Agents/siso-agent-base"),
    ("internal-lab", "SISO Internal Lab / LifeLock", f"{WS}/SISO_Internal_Lab"),
    ("agency", "SISO Agency", f"{WS}/SISO_Agency"),
    ("team-entrepreneurship", "Team Entrepreneurship", f"{WS}/personal/team-entrepreneurship"),
    ("library", "SISO Library", f"{WS}/SISO_Knowledge"),
]


def brain(*args):
    try:
        out = subprocess.run([sys.executable, SISO_BRAIN, *args], capture_output=True, text=True, timeout=20)
        return json.loads(out.stdout) if out.stdout.strip() else {}
    except Exception as e:
        return {"error": str(e)}


def face_ok(url):
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(url, context=ctx, timeout=8) as r:
            return r.status == 200 and b"SISO Base" in r.read()[:4000]
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", action="store_true")
    a = ap.parse_args()

    checks = []
    def chk(name, ok, detail=""):
        checks.append((name, ok, detail))

    h = brain("health")
    online = isinstance(h, dict) and h.get("ok")
    chk("brain reachable", online, h.get("db", "") if online else h.get("error", "unreachable"))
    if online:
        chk("schema tiers loaded", set(h.get("tiers_loaded", [])) >= {"read", "write", "spawn"}, str(h.get("tiers_loaded")))
        chk("timeline non-empty", h.get("timeline_events", 0) > 0, f"{h.get('timeline_events')} events")

    fleet = brain("fleet")
    running = sum(1 for f in fleet.get("fleet", []) if f.get("status") == "running") if isinstance(fleet, dict) else 0
    chk("fleet live", running > 0, f"{running} running")

    halt = brain("halt-status")
    chk("not globally paused", isinstance(halt, dict) and not halt.get("global_paused"), "paused!" if (isinstance(halt, dict) and halt.get("global_paused")) else "ok")

    url = os.environ.get("SISO_FACE_URL", "https://shaans-mac-mini.tail100d11.ts.net:8831/")
    chk("Face serving", face_ok(url), url)

    if a.register:
        n = 0
        for did, name, path in DIVISIONS:
            exists = os.path.isdir(path)
            resp = brain("division-register", "--id", did, "--name", name,
                         "--repo", path, "--status", "active" if exists else "archived")
            if isinstance(resp, dict) and resp.get("ok"):
                n += 1
        chk(f"divisions registered ({n})", n == len(DIVISIONS), f"{n}/{len(DIVISIONS)}")

    divs = brain("divisions")
    chk("divisions present", isinstance(divs, dict) and divs.get("count", 0) > 0, f"{divs.get('count', 0)} divisions")

    # report
    allok = all(ok for _, ok, _ in checks)
    print("=== SISO DOCTOR ===")
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:28} {detail}")
    print(f"\n{'ALL SYSTEMS GO' if allok else 'DEGRADED — see FAILs above'}")
    sys.exit(0 if allok else 1)


if __name__ == "__main__":
    main()
