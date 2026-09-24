#!/usr/bin/env python3
"""
farm-harvest — the self-improving Farm's harvester (MVP, ONE source: GitHub).

Searches GitHub for recently-active repos matching the stack's interest topics,
scores stack-fit cheaply, posts candidates to the brain (/farm/add, deduped by
url), and raises ONE digest notification so Shaan can review at the human gate.

This generalizes the existing ralph/scraper discovery loop into the brain. It
does NOT auto-integrate anything — proposal only. Execution-gate (sandboxed
integration) is a later step; nothing here runs harvested code.

Run:  farm-harvest.py            (scheduled weekly by a scheduled_trigger)
Env:  SISO_BRAIN_URL / SISO_BRAIN_TOKEN (write tier)
"""
import json, os, subprocess, sys, urllib.request, urllib.error, urllib.parse

HOME = os.path.expanduser("~")
SISO_BRAIN = os.environ.get("SISO_BRAIN_BIN", f"{HOME}/SISO_Workspace/SISO_Agents/siso-agent-brain/extensions/braind/siso-brain")

# what the JARVIS stack cares about — drives both the search and the fit score
QUERIES = [
    "agent orchestration cli",
    "durable execution agents",
    "terminal multiplexer ai agents",
    "agent memory persistent",
]
FIT_KEYWORDS = ["agent", "orchestrat", "cli", "terminal", "memory", "durable",
                "mcp", "skill", "workflow", "tmux", "claude", "codex", "fleet"]


def brain(*args):
    try:
        out = subprocess.run([sys.executable, SISO_BRAIN, *args], capture_output=True, text=True, timeout=20)
        return json.loads(out.stdout) if out.stdout.strip() else {}
    except Exception as e:
        return {"error": str(e)}


def gh_search(query, per_page=8):
    """GitHub repo search, sorted by recent activity. Public API, unauthenticated (low volume)."""
    q = urllib.parse.quote(f"{query} pushed:>2026-01-01")
    url = f"https://api.github.com/search/repositories?q={q}&sort=updated&order=desc&per_page={per_page}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "siso-farm-harvest"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode()).get("items", [])
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"gh search {query!r}: HTTP {e.code} (rate limit?)\n")
        return []
    except Exception as e:
        sys.stderr.write(f"gh search {query!r}: {e}\n")
        return []


def fit_score(repo):
    """Cheap stack-fit: keyword density in name+description + a stars nudge."""
    text = ((repo.get("name") or "") + " " + (repo.get("description") or "")).lower()
    hits = sum(1 for k in FIT_KEYWORDS if k in text)
    kw = min(hits / 5.0, 1.0)                      # up to 1.0 from keywords
    stars = repo.get("stargazers_count", 0)
    star_nudge = min(stars / 20000.0, 0.3)         # up to +0.3 for popularity
    return round(min(kw * 0.8 + star_nudge, 1.0), 2)


def main():
    harvested, new = 0, 0
    for query in QUERIES:
        for repo in gh_search(query):
            harvested += 1
            score = fit_score(repo)
            if score < 0.25:
                continue  # below the noise floor — skip
            resp = brain("farm-add",
                         "--source", "github-topics",
                         "--name", repo.get("full_name", repo.get("name", "?")),
                         "--url", repo.get("html_url", ""),
                         "--summary", (repo.get("description") or "")[:200],
                         "--signal", f"{repo.get('stargazers_count',0)}* · q={query}",
                         "--fit", str(score))
            if isinstance(resp, dict) and resp.get("new"):
                new += 1

    pending = brain("farm-candidates", "--verdict", "new")
    n_pending = pending.get("count", 0) if isinstance(pending, dict) else 0
    if new:
        brain("notify",
              "--summary", f"Farm: {new} new candidate(s) to review ({n_pending} pending total)",
              "--urgency", "normal", "--from-agent", "farm")
    print(json.dumps({"harvested": harvested, "new": new, "pending_total": n_pending}, indent=2))


if __name__ == "__main__":
    main()
