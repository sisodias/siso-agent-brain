#!/usr/bin/env python3
"""
braind — the JARVIS brain-API daemon.

One authoritative spine DB lives on the Mac Mini (the brain host). Every agent on
every machine (MacBook, VPS) reads/writes that ONE database THROUGH this API —
never by touching the file. This is what makes the consolidation hold.

Design (locked decisions, see docs/jarvis/):
  - stdlib only (http.server + sqlite3). No external deps.
  - The Mini is the single writer of the DB file. Clients call the API.
  - Auth = split tokens: READ < WRITE < SPAWN. A leaked read token cannot write/spawn.
  - Transport: TCP on 127.0.0.1:8830, exposed to the tailnet via `tailscale serve`
    (same recipe as Bifrost). Tailnet-only — never public.
  - Reuses the existing spine DB schema (tasks/memories/timeline_events/cli_instances).

Run:  python3 braind.py            # binds 127.0.0.1:8830
Env:  SISO_DB    (default ~/SISO_Workspace/.SystemDB/sisosystem.db)
      SISO_BRAIN_PORT (default 8830)
      SISO_BRAIN_TOKENS_DIR (default ~/.siso/brain-tokens)
"""
import json, os, sqlite3, sys, subprocess, time, uuid, hmac, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = os.path.expanduser("~")
DB_PATH = os.environ.get("SISO_DB", f"{HOME}/SISO_Workspace/.SystemDB/sisosystem.db")
PORT = int(os.environ.get("SISO_BRAIN_PORT", "8830"))
TOKENS_DIR = os.environ.get("SISO_BRAIN_TOKENS_DIR", f"{HOME}/.siso/brain-tokens")

# token tiers, ordered: a tier grants its own scope + all lower scopes
TIERS = ["read", "write", "spawn"]
UNIT_TIERS = ["disposable", "capability", "core", "contract"]
UNIT_AUTO_PROMOTE_STREAK = 3


def _load_tokens():
    """Read the three token files. Each maps a secret -> the max tier it grants."""
    tok = {}
    for tier in TIERS:
        p = os.path.join(TOKENS_DIR, f"{tier}.token")
        try:
            with open(p) as f:
                secret = f.read().strip()
            if secret:
                tok[secret] = tier
        except FileNotFoundError:
            pass
    return tok


TOKENS = _load_tokens()


def _tier_ok(have, need):
    """Does tier `have` satisfy required tier `need`? (spawn>=write>=read)"""
    return TIERS.index(have) >= TIERS.index(need)


def _db():
    # one connection per request thread; WAL allows concurrent readers + 1 writer.
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=5000")
    return c


def _ensure_units_table(c):
    """Create `units` lazily if missing. Guarded with PRAGMA for idempotence."""
    if c.execute("PRAGMA table_info(units)").fetchall():
        return
    c.execute("""CREATE TABLE IF NOT EXISTS units(
        id TEXT PRIMARY KEY,
        kind TEXT,
        tier TEXT,
        provenance TEXT,
        rating REAL,
        clean_streak INTEGER DEFAULT 0,
        regressions INTEGER DEFAULT 0,
        circuit_open INTEGER DEFAULT 0,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_units_tier ON units(tier)")
    c.commit()


def _unit_tier_index(tier):
    if tier not in UNIT_TIERS:
        return UNIT_TIERS.index("capability")
    return UNIT_TIERS.index(tier)


def _unit_record_outcome(c, unit_id, verdict):
    verdict = (verdict or "").strip().lower()
    if verdict not in ("worked", "no-effect", "regressed"):
        raise ValueError(f"invalid verdict: {verdict}")

    _ensure_units_table(c)
    row = c.execute("SELECT tier, clean_streak, regressions, circuit_open FROM units WHERE id=?", (unit_id,)).fetchone()
    if not row:
        c.execute("INSERT INTO units(id, kind, tier, provenance, rating, clean_streak, regressions, circuit_open) "
                  "VALUES(?,?,?,?,?,?,?,0)",
                  (unit_id, "unit", "capability", None, None, 0, 0))
        row = c.execute("SELECT tier, clean_streak, regressions, circuit_open FROM units WHERE id=?", (unit_id,)).fetchone()

    tier = row["tier"] or "capability"
    idx = _unit_tier_index(tier)
    clean_streak = row["clean_streak"] or 0
    regressions = row["regressions"] or 0
    circuit_open = row["circuit_open"] or 0
    changed = False

    if verdict == "worked":
        clean_streak += 1
        if clean_streak >= UNIT_AUTO_PROMOTE_STREAK:
            clean_streak = 0
            if idx < len(UNIT_TIERS) - 2:
                idx += 1
                tier = UNIT_TIERS[idx]
                changed = True

    elif verdict == "regressed":
        regressions += 1
        clean_streak = 0
        if idx > 0:
            idx -= 1
            tier = UNIT_TIERS[idx]
            changed = True
        if regressions >= 2:
            circuit_open = 1

    if not changed and (verdict == "no-effect" or row["tier"] == tier):
        tier = row["tier"] or "capability"

    c.execute("UPDATE units SET tier=?, clean_streak=?, regressions=?, circuit_open=?, updated_at=CURRENT_TIMESTAMP "
              "WHERE id=?", (tier, clean_streak, regressions, circuit_open, unit_id))
    c.commit()
    return {
        "unit_id": unit_id,
        "verdict": verdict,
        "tier": tier,
        "clean_streak": clean_streak,
        "regressions": regressions,
        "circuit_open": circuit_open
    }


def _rows(cur):
    return [dict(r) for r in cur.fetchall()]


def _esc(s):
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def home_domain(cwd):
    repo_root = None
    try:
        resolved = subprocess.run(
            ["git", "-C", cwd or os.getcwd(), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if resolved.returncode == 0 and resolved.stdout.strip():
            repo_root = resolved.stdout.strip()
    except Exception:
        repo_root = None
    return os.path.basename((repo_root or (cwd or "")).rstrip("/")) or "unknown"


def _render_face(fleet, tasks, mems, events, nev):
    """The Face — a self-contained dashboard of the live brain. Auto-refreshes."""
    running = sum(1 for f in fleet if f.get("status") == "running")
    def fleet_rows():
        out = []
        for f in fleet:
            dot = "#5ad19a" if f.get("status") == "running" else "#6b7685"
            out.append(f"<tr><td><span style='color:{dot}'>●</span> {_esc(f.get('name') or f.get('id'))}</td>"
                       f"<td>{_esc(f.get('machine') or '?')}</td><td class=mut>{_esc((f.get('cwd') or '')[:48])}</td></tr>")
        return "".join(out) or "<tr><td colspan=3 class=mut>no agents</td></tr>"
    def task_rows():
        out = []
        for t in tasks:
            out.append(f"<tr><td>{_esc(t.get('status'))}</td><td>{_esc(t.get('title') or (t.get('description') or '')[:70])}</td></tr>")
        return "".join(out) or "<tr><td colspan=2 class=mut>no active tasks</td></tr>"
    def mem_rows():
        return "".join(f"<li><span class=mut>({_esc(m.get('tier'))} {_esc(m.get('confidence'))})</span> {_esc((m.get('content') or '')[:120])}</li>" for m in mems) or "<li class=mut>memory empty</li>"
    def evt_rows():
        return "".join(f"<li><span class=mut>{_esc((e.get('timestamp') or '')[:19])}</span> <b>{_esc(e.get('event_type'))}</b> {_esc(e.get('agent_id'))}: {_esc((e.get('message') or '')[:80])}</li>" for e in events) or "<li class=mut>no events</li>"
    return f"""<!DOCTYPE html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<meta http-equiv=refresh content=15>
<title>SISO Base</title>
<style>
body{{background:#0b0e14;color:#e6edf3;font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;padding:1.2em}}
h1{{font-size:1.3em;margin:0 0 .1em}} h2{{font-size:.95em;color:#6fb3ff;margin:1.4em 0 .4em;text-transform:uppercase;letter-spacing:.05em}}
.mut{{color:#8b98a9}} .grid{{display:grid;grid-template-columns:1fr 1fr;gap:1.4em}}
table{{border-collapse:collapse;width:100%;font-size:.86em}} td{{border-bottom:1px solid #1f2733;padding:.3em .5em}}
ul{{list-style:none;padding:0;margin:0;font-size:.84em}} li{{padding:.25em 0;border-bottom:1px solid #161d28}}
.bar{{color:#5ad19a;font-weight:700}} .head{{display:flex;justify-content:space-between;align-items:baseline}}
a{{color:#6fb3ff}}
</style></head><body>
<div class=head><h1>🧠 SISO Base <span class=mut style='font-size:.6em'>agent-zero · the brain</span></h1>
<div class=mut>{running} running / {len(fleet)} agents · {nev} events · auto-refresh 15s</div></div>
<div class=grid>
<div><h2>Fleet</h2><table>{fleet_rows()}</table></div>
<div><h2>Active Tasks ({len(tasks)})</h2><table>{task_rows()}</table></div>
</div>
<div class=grid style='margin-top:.5em'>
<div><h2>Memory</h2><ul>{mem_rows()}</ul></div>
<div><h2>Recent Timeline</h2><ul>{evt_rows()}</ul></div>
</div>
<p class=mut style='margin-top:2em;font-size:.8em'>Served by braind on the Mac Mini · talk to agent-zero in a terminal: <code>agent-zero</code></p>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ---- helpers -----------------------------------------------------------
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth(self, need):
        """Return True if the request bearer token satisfies `need` tier, else send 401/403."""
        hdr = self.headers.get("Authorization", "")
        secret = hdr[7:].strip() if hdr.startswith("Bearer ") else ""
        # constant-time-ish lookup
        have = None
        for known, tier in TOKENS.items():
            if hmac.compare_digest(known, secret):
                have = tier
                break
        if have is None:
            self._send(401, {"error": "unauthorized", "hint": "Bearer <token>"})
            return False
        if not _tier_ok(have, need):
            self._send(403, {"error": "forbidden", "have": have, "need": need})
            return False
        return True

    def _body(self):
        n = int(self.headers.get("Content-Length", "0") or "0")
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode())
        except Exception:
            return {}

    # ---- routing -----------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?")[0]
        q = {}
        if "?" in self.path:
            q = {k: v[0] for k, v in urllib.parse.parse_qs(self.path.split("?", 1)[1]).items()}

        if path == "/" or path == "/face":
            # The Face: a self-contained dashboard rendering the live brain.
            # No auth on the shell (tailnet-only); it fetches data via /face/data
            # using a token the page is given at serve time is overkill for v1 —
            # instead it renders a server-side snapshot so it works with zero JS auth.
            try:
                c = _db()
                fleet = _rows(c.execute("SELECT id,name,machine,cwd,status,last_heartbeat FROM cli_instances ORDER BY last_heartbeat DESC LIMIT 30"))
                tasks = _rows(c.execute("SELECT title,description,status,priority FROM tasks WHERE status NOT IN ('completed','cancelled','archived','done') ORDER BY urgency_score DESC, created_at ASC LIMIT 25"))
                mems = _rows(c.execute("SELECT content,tier,confidence FROM memories ORDER BY confidence DESC, created_at DESC LIMIT 15"))
                events = _rows(c.execute("SELECT agent_id,event_type,message,timestamp FROM timeline_events ORDER BY timestamp DESC LIMIT 20"))
                nev = c.execute("SELECT count(*) FROM timeline_events").fetchone()[0]
                c.close()
            except Exception as e:
                return self._send(500, {"error": str(e)})
            html = _render_face(fleet, tasks, mems, events, nev).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        if path == "/health":
            # no auth — liveness only, exposes no data
            try:
                c = _db()
                n = c.execute("SELECT count(*) FROM timeline_events").fetchone()[0]
                c.close()
                return self._send(200, {"ok": True, "db": DB_PATH, "timeline_events": n,
                                        "tiers_loaded": sorted(set(TOKENS.values())), "ts": int(time.time())})
            except Exception as e:
                return self._send(500, {"ok": False, "error": str(e)})

        if path == "/tasks":
            if not self._auth("read"):
                return
            c = _db()
            agent = q.get("agent")
            # 'active' = not in a terminal state (exclude completed/cancelled/archived noise)
            ACTIVE = "status NOT IN ('completed','cancelled','archived','done')"
            if agent:
                cur = c.execute(f"SELECT * FROM tasks WHERE assigned_agent_id=? AND {ACTIVE} "
                                "ORDER BY urgency_score DESC, created_at ASC", (agent,))
            else:
                cur = c.execute(f"SELECT * FROM tasks WHERE {ACTIVE} "
                                "ORDER BY urgency_score DESC, created_at ASC LIMIT 200")
            out = _rows(cur)
            c.close()
            return self._send(200, {"tasks": out, "count": len(out)})

        if path == "/memory/recall":
            if not self._auth("read"):
                return
            c = _db()
            term = q.get("q", "")
            tier = q.get("tier")
            agent = q.get("agent")
            sql = "SELECT * FROM memories WHERE 1=1"
            args = []
            if term:
                sql += " AND content LIKE ?"
                args.append(f"%{term}%")
            if tier:
                sql += " AND tier=?"
                args.append(tier)
            if agent:
                sql += " AND agent_id=?"
                args.append(agent)
            # decided relevance ordering: confidence then recency
            sql += " ORDER BY confidence DESC, created_at DESC LIMIT 50"
            out = _rows(c.execute(sql, args))
            c.close()
            return self._send(200, {"memories": out, "count": len(out)})

        if path == "/brain/ask":
            if not self._auth("read"):
                return
            query = (q.get("q") or "").strip()
            if not query:
                return self._send(400, {"error": "q required"})
            try:
                k = int(q.get("k", "8"))
            except ValueError:
                return self._send(400, {"error": "k must be integer"})
            if k < 1:
                return self._send(400, {"error": "k must be >= 1"})
            dim = (q.get("dim") or "").strip()
            terms = [t for t in query.split() if t]
            if not terms:
                return self._send(400, {"error": "empty q"})

            hit_expr = []
            score_terms = []
            args = []
            for term in terms:
                p = f"%{term}%"
                for col in ("title", "body", "evidence_quote"):
                    hit_expr.append(f"{col} LIKE ?")
                    score_terms.append(f"CASE WHEN {col} LIKE ? THEN 1 ELSE 0 END")
                    args.append(p)
                    args.append(p)

            sql = "SELECT dim,title,body,domain,recurrence,importance,evidence_quote,session_id FROM session_extract WHERE (" + " OR ".join(hit_expr) + ")"
            if dim:
                # explicit dim filter stays a hard filter (caller asked for it)
                sql += " AND dim=?"
                args.append(dim)
                routed = []
            else:
                # #3 intent routing: BOOST the dims that answer this query type rather than
                # hard-filtering — a hard filter over-narrows and returns nothing when the
                # literal terms live in a dim the router excluded (verified failure mode).
                try:
                    import brain_intent
                    routed = brain_intent.classify(query)
                except Exception:
                    routed = []

            # score = term-hit count (OR matching, already in WHERE) + importance
            #         + home-domain boost + intent-dim boost. All soft.
            boost_parts = list(score_terms)
            boost_parts.append("COALESCE(importance,0)")
            if q.get("cwd"):
                boost_parts.append("CASE WHEN domain=? THEN 1 ELSE 0 END")
                args.append(home_domain(q.get("cwd")))
            if not dim and routed:
                boost_parts.append("CASE WHEN dim IN (%s) THEN 1 ELSE 0 END" % ",".join("?" * len(routed)))
                args.extend(routed)
            score = "(" + " + ".join(boost_parts) + ")"
            sql += f" ORDER BY {score} DESC, recurrence DESC LIMIT {k}"
            c = _db()
            out = _rows(c.execute(sql, args))
            c.close()
            return self._send(200, out)

        if path == "/fleet":
            if not self._auth("read"):
                return
            c = _db()
            out = _rows(c.execute("SELECT id,name,machine,cwd,status,last_heartbeat,last_session_id "
                                  "FROM cli_instances ORDER BY last_heartbeat DESC"))
            c.close()
            return self._send(200, {"fleet": out, "count": len(out)})

        if path == "/notifications":
            if not self._auth("read"):
                return
            c = _db()
            only_unseen = q.get("unseen") == "1"
            sql = "SELECT * FROM notifications" + (" WHERE seen=0" if only_unseen else "") + " ORDER BY created_at DESC LIMIT 50"
            out = _rows(c.execute(sql))
            c.close()
            return self._send(200, {"notifications": out, "count": len(out)})

        if path == "/questions":
            if not self._auth("read"):
                return
            c = _db()
            out = _rows(c.execute("SELECT * FROM pending_questions WHERE status='awaiting' ORDER BY created_at ASC"))
            c.close()
            return self._send(200, {"questions": out, "count": len(out)})

        if path == "/halt/status":
            if not self._auth("read"):
                return
            c = _db()
            out = _rows(c.execute("SELECT scope,paused,reason,updated_at FROM control_flags WHERE paused=1"))
            c.close()
            return self._send(200, {"paused": out, "global_paused": any(r["scope"] == "global" for r in out)})

        if path == "/divisions":
            if not self._auth("read"):
                return
            c = _db()
            out = _rows(c.execute("SELECT * FROM divisions ORDER BY status, name"))
            c.close()
            return self._send(200, {"divisions": out, "count": len(out)})

        if path == "/roundup":
            # agent-zero's cross-division status view: each division + its latest up-status.
            if not self._auth("read"):
                return
            c = _db()
            divs = _rows(c.execute("SELECT id,name,status,zero_agent,zero_status,last_intent_at FROM divisions WHERE status!='archived' ORDER BY name"))
            for d in divs:
                latest = c.execute("SELECT body,created_at FROM division_inbox WHERE division=? AND direction='up' ORDER BY created_at DESC LIMIT 1", (d["id"],)).fetchone()
                d["latest_status"] = latest[0] if latest else None
                d["status_at"] = latest[1] if latest else None
                d["open_intents"] = c.execute("SELECT count(*) FROM division_inbox WHERE division=? AND direction='down' AND status='open'", (d["id"],)).fetchone()[0]
            c.close()
            return self._send(200, {"divisions": divs, "count": len(divs)})

        if path == "/inbox":
            # a division-zero reads its open down-intents
            if not self._auth("read"):
                return
            div = q.get("division")
            if not div:
                return self._send(400, {"error": "division required"})
            c = _db()
            out = _rows(c.execute("SELECT * FROM division_inbox WHERE division=? AND direction='down' AND status='open' ORDER BY created_at ASC", (div,)))
            c.close()
            return self._send(200, {"inbox": out, "count": len(out)})

        if path == "/gate":
            # Autonomy enforcement, LOCK-THE-LOOP model: a mutation's risk = the UNIT's declared tier,
            # cross-checked against the loop allowlist. The LOOP is contract; the layout is capability.
            #   unit tier -> autonomy tier: contract->T3 (always human-gated) | core->T2 (approve) |
            #   capability->T1 (farm freely; auto-promote after N clean uses) | disposable->T0 (auto-vault)
            if not self._auth("read"):
                return
            unit = q.get("unit")            # the unit being mutated (preferred)
            tier = (q.get("tier") or "").upper()  # legacy direct-tier still works
            division = q.get("division")
            c = _db()
            _ensure_units_table(c)
            gp = c.execute("SELECT 1 FROM control_flags WHERE scope='global' AND paused=1").fetchone()
            dp = c.execute("SELECT 1 FROM control_flags WHERE scope=? AND paused=1", (division,)).fetchone() if division else None
            unit_tier = None
            circuit_open = 0
            if unit:
                row = c.execute("SELECT tier FROM units WHERE id=?", (unit,)).fetchone()
                if row:
                    row2 = c.execute("SELECT tier, circuit_open FROM units WHERE id=?", (unit,)).fetchone()
                    unit_tier = row2["tier"] if row2 else "capability"
                    circuit_open = int(row2["circuit_open"] or 0) if row2 else 0
            c.close()
            if gp or dp:
                return self._send(200, {"decision": "deny", "reason": "halt active"})
            if unit and circuit_open == 1:
                return self._send(200, {"decision": "deny", "reason": "circuit-open", "unit": unit, "unit_tier": unit_tier})
            UNIT2AUTO = {"contract": "T3", "core": "T2", "capability": "T1", "disposable": "T0"}
            if unit_tier:
                tier = UNIT2AUTO.get(unit_tier, "T2")
            tier = tier or "T1"
            decision = {"T0": "allow", "T1": "allow", "T2": "needs-approval", "T3": "needs-approval"}.get(tier, "needs-approval")
            return self._send(200, {"decision": decision, "tier": tier, "unit": unit, "unit_tier": unit_tier,
                                    "note": "contract=the LOOP (always gated); capability incl. the layout (farm freely)"})

        if path == "/digest":
            # "what happened while I was away" — rollup since a timestamp (default last 24h)
            if not self._auth("read"):
                return
            since = q.get("since", "")  # ISO-ish; if empty, use last 24h
            c = _db()
            where = "WHERE timestamp >= ?" if since else "WHERE timestamp >= datetime('now','-1 day')"
            args = (since,) if since else ()
            events = _rows(c.execute(f"SELECT event_type, count(*) n FROM timeline_events {where} GROUP BY event_type ORDER BY n DESC", args))
            recent = _rows(c.execute(f"SELECT agent_id,event_type,message,timestamp FROM timeline_events {where} ORDER BY timestamp DESC LIMIT 15", args))
            unseen = c.execute("SELECT count(*) FROM notifications WHERE seen=0").fetchone()[0]
            asking = c.execute("SELECT count(*) FROM pending_questions WHERE status='awaiting'").fetchone()[0]
            try:
                cost = c.execute("SELECT COALESCE(ROUND(SUM(est_usd),2),0), COALESCE(SUM(tokens_in+tokens_out),0) FROM cost_events").fetchone()
            except Exception:
                cost = (0, 0)
            c.close()
            return self._send(200, {"since": since or "last 24h", "event_counts": events,
                                    "recent": recent, "unseen_notifications": unseen,
                                    "awaiting_questions": asking, "total_cost_usd": cost[0], "total_tokens": cost[1]})

        if path == "/farm/candidates":
            if not self._auth("read"):
                return
            c = _db()
            v = q.get("verdict")
            sql = "SELECT * FROM farm_candidates" + (" WHERE verdict=?" if v else "") + " ORDER BY fit_score DESC, harvested_at DESC LIMIT 50"
            out = _rows(c.execute(sql, (v,) if v else ()))
            c.close()
            return self._send(200, {"candidates": out, "count": len(out)})

        return self._send(404, {"error": "not found", "path": path})

    def do_POST(self):
        path = self.path.split("?")[0]
        b = self._body()

        if path == "/memory/write":
            if not self._auth("write"):
                return
            content = b.get("content")
            if not content:
                return self._send(400, {"error": "content required"})
            mid = b.get("id") or f"mem_{uuid.uuid4().hex[:12]}"
            c = _db()
            c.execute("INSERT INTO memories(id,task_id,agent_id,type,content,tier,confidence) "
                      "VALUES(?,?,?,?,?,?,?)",
                      (mid, b.get("task_id"), b.get("agent_id"), b.get("type", "semantic_fact"),
                       content, b.get("tier", "episodic"), float(b.get("confidence", 0.6))))
            c.commit()
            c.close()
            return self._send(200, {"ok": True, "id": mid})

        if path == "/timeline/append":
            if not self._auth("write"):
                return
            agent = b.get("agent_id")
            etype = b.get("event_type")
            if not agent or not etype:
                return self._send(400, {"error": "agent_id and event_type required"})
            eid = b.get("id") or f"evt_{uuid.uuid4().hex[:12]}"
            c = _db()
            try:
                c.execute("INSERT INTO timeline_events(id,task_id,agent_id,event_type,message,metadata,root_task_id) "
                          "VALUES(?,?,?,?,?,?,?)",
                          (eid, b.get("task_id"), agent, etype, b.get("message"),
                           json.dumps(b.get("metadata")) if b.get("metadata") else None,
                           b.get("root_task_id")))
                c.commit()
            except sqlite3.IntegrityError as e:
                c.close()
                return self._send(400, {"error": f"event_type must be one of BOOT/THOUGHT/ACTION/TOOL_CALL/ERROR/HANDOFF/COMPLETED/USER_PROMPT: {e}"})
            c.close()
            return self._send(200, {"ok": True, "id": eid})

        if path == "/voice/utterance":
            # The SISO Voice mirror: one dictation transcript (TEXT ONLY, never audio).
            # Idempotent on client_id (the freeflow UUID) so re-POSTing a queued
            # outbox line is safe. Near-copy of /timeline/append.
            if not self._auth("write"):
                return
            client_id = b.get("client_id")
            raw = b.get("raw_transcript")
            if not client_id or not raw:
                return self._send(400, {"error": "client_id and raw_transcript required"})
            vid = b.get("id") or f"vu_{uuid.uuid4().hex}"
            wc = b.get("word_count")
            if wc is None:
                wc = len(raw.split())
            c = _db()
            c.execute(
                "INSERT INTO voice_utterances(id,client_id,captured_at,raw_transcript,cleaned_transcript,"
                "intent,app_name,bundle_id,window_title,model,word_count,machine,agent_id,task_id,"
                "session_id,embedding_model,metadata) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(client_id) DO UPDATE SET "
                "raw_transcript=excluded.raw_transcript, cleaned_transcript=excluded.cleaned_transcript, "
                "model=excluded.model, word_count=excluded.word_count, received_at=CURRENT_TIMESTAMP",
                (vid, client_id, b.get("captured_at"), raw, b.get("cleaned_transcript"),
                 b.get("intent", "dictation"), b.get("app_name"), b.get("bundle_id"),
                 b.get("window_title"), b.get("model"), int(wc), b.get("machine"),
                 b.get("agent_id"), b.get("task_id"), b.get("session_id"),
                 b.get("embedding_model"),
                 json.dumps(b.get("metadata")) if b.get("metadata") else None))
            c.commit()
            c.close()
            return self._send(200, {"ok": True, "id": vid})

        if path == "/cost/add":
            if not self._auth("write"):
                return
            c = _db()
            cid = f"cost_{uuid.uuid4().hex[:12]}"
            c.execute("INSERT INTO cost_events(id,agent_id,run_id,cli,model,tokens_in,tokens_out,est_usd) "
                      "VALUES(?,?,?,?,?,?,?,?)",
                      (cid, b.get("agent_id"), b.get("run_id"), b.get("cli"), b.get("model"),
                       int(b.get("tokens_in", 0)), int(b.get("tokens_out", 0)), float(b.get("est_usd", 0.0))))
            c.commit()
            c.close()
            return self._send(200, {"ok": True, "id": cid})

        if path == "/notify":
            if not self._auth("write"):
                return
            if not b.get("summary"):
                return self._send(400, {"error": "summary required"})
            nid = f"ntf_{uuid.uuid4().hex[:12]}"
            c = _db()
            c.execute("INSERT INTO notifications(id,urgency,summary,body,from_agent,needs_answer) VALUES(?,?,?,?,?,?)",
                      (nid, b.get("urgency", "normal"), b["summary"], b.get("body"),
                       b.get("from_agent"), 1 if b.get("needs_answer") else 0))
            c.commit(); c.close()
            return self._send(200, {"ok": True, "id": nid})

        if path == "/notifications/seen":
            if not self._auth("write"):
                return
            c = _db()
            if b.get("id"):
                c.execute("UPDATE notifications SET seen=1 WHERE id=?", (b["id"],))
            else:
                c.execute("UPDATE notifications SET seen=1 WHERE seen=0")
            c.commit(); c.close()
            return self._send(200, {"ok": True})

        if path == "/ask":
            if not self._auth("write"):
                return
            if not b.get("question"):
                return self._send(400, {"error": "question required"})
            qid = f"q_{uuid.uuid4().hex[:12]}"
            c = _db()
            c.execute("INSERT INTO pending_questions(id,from_agent,question,options,blocking_task_id) VALUES(?,?,?,?,?)",
                      (qid, b.get("from_agent"), b["question"],
                       json.dumps(b.get("options")) if b.get("options") else None, b.get("blocking_task_id")))
            # asking also raises a notification (so Shaan sees it)
            c.execute("INSERT INTO notifications(id,urgency,summary,from_agent,needs_answer) VALUES(?,?,?,?,1)",
                      (f"ntf_{uuid.uuid4().hex[:12]}", "high", "Agent needs your answer: " + b["question"][:80], b.get("from_agent")))
            c.commit(); c.close()
            return self._send(200, {"ok": True, "id": qid})

        if path == "/answer":
            if not self._auth("write"):
                return
            if not b.get("id") or b.get("answer") is None:
                return self._send(400, {"error": "id and answer required"})
            c = _db()
            cur = c.execute("UPDATE pending_questions SET status='answered', answer=?, answered_at=CURRENT_TIMESTAMP "
                            "WHERE id=? AND status='awaiting'", (b["answer"], b["id"]))
            c.commit()
            n = cur.rowcount
            c.close()
            return self._send(200, {"ok": n > 0, "updated": n})

        if path == "/challenge":
            # the self-gaslight ledger: file a rated challenge against a reigning unit (incl. the layout).
            if not self._auth("write"):
                return
            target = b.get("target"); arg = b.get("argument")
            if not target or not arg:
                return self._send(400, {"error": "target and argument required"})
            cid = f"chl_{uuid.uuid4().hex[:12]}"
            c = _db()
            c.execute("INSERT INTO challenges(id,target,challenger,argument,rating) VALUES(?,?,?,?,?)",
                      (cid, target, b.get("challenger", "adversary-sweep"), arg, b.get("rating")))
            c.commit(); c.close()
            return self._send(200, {"ok": True, "id": cid, "target": target})

        if path == "/unit/register":
            # register/update a governed unit's tier + provenance + challenge_hook (required to promote).
            if not self._auth("write"):
                return
            uid = b.get("id")
            if not uid:
                return self._send(400, {"error": "id required"})
            c = _db()
            _ensure_units_table(c)
            c.execute("""INSERT INTO units(id,kind,tier,provenance,rating,updated_at)
                         VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)
                         ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, tier=excluded.tier,
                           provenance=excluded.provenance, rating=COALESCE(excluded.rating, units.rating),
                           updated_at=CURRENT_TIMESTAMP""",
                      (uid, b.get("kind"), b.get("tier", "capability"), b.get("provenance"), b.get("rating")))
            c.commit(); c.close()
            return self._send(200, {"ok": True, "id": uid})

        if path == "/unit/record-outcome":
            # record remediation outcome against a unit and adjust auto-autonomy state.
            if not self._auth("write"):
                return
            unit_id = b.get("unit_id")
            verdict = b.get("verdict")
            if not unit_id or not verdict:
                return self._send(400, {"error": "unit_id and verdict required"})
            try:
                c = _db()
                out = _unit_record_outcome(c, unit_id, verdict)
                c.close()
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            return self._send(200, out)

        if path == "/delegate":
            # agent-zero delegates an intent DOWN to a division-zero.
            if not self._auth("write"):
                return
            div = b.get("division"); intent = b.get("intent")
            if not div or not intent:
                return self._send(400, {"error": "division and intent required"})
            did = f"del_{uuid.uuid4().hex[:12]}"
            c = _db()
            # the division must exist
            if not c.execute("SELECT 1 FROM divisions WHERE id=?", (div,)).fetchone():
                c.close()
                return self._send(404, {"error": f"no such division: {div}"})
            c.execute("INSERT INTO division_inbox(id,division,direction,kind,body,from_agent) "
                      "VALUES(?,?,?,?,?,?)", (did, div, "down", "intent", intent, b.get("from_agent", "agent-zero")))
            c.execute("UPDATE divisions SET zero_status='waking', last_intent_at=CURRENT_TIMESTAMP WHERE id=?", (div,))
            # raise a timeline event for visibility
            c.execute("INSERT INTO timeline_events(id,agent_id,event_type,message) VALUES(?,?,?,?)",
                      (f"evt_{uuid.uuid4().hex[:12]}", "agent-zero", "HANDOFF", f"delegate→{div}: {intent[:80]}"))
            c.commit(); c.close()
            return self._send(200, {"ok": True, "id": did, "division": div})

        if path == "/inbox/reply":
            # a division-zero reports status/result UP, and acks the intent it was working.
            if not self._auth("write"):
                return
            div = b.get("division"); body = b.get("body")
            if not div or not body:
                return self._send(400, {"error": "division and body required"})
            rid = f"up_{uuid.uuid4().hex[:12]}"
            c = _db()
            c.execute("INSERT INTO division_inbox(id,division,direction,kind,body,from_agent,status) "
                      "VALUES(?,?,?,?,?,?,?)",
                      (rid, div, "up", b.get("kind", "status"), body, b.get("from_agent", f"{div}-zero"), "done"))
            if b.get("ack_intent"):
                c.execute("UPDATE division_inbox SET status='done', updated_at=CURRENT_TIMESTAMP WHERE id=?", (b["ack_intent"],))
            c.execute("UPDATE divisions SET zero_status=? WHERE id=?", (b.get("zero_status", "active"), div))
            c.commit(); c.close()
            return self._send(200, {"ok": True, "id": rid})

        if path == "/divisions/register":
            if not self._auth("write"):
                return
            if not b.get("id") or not b.get("name"):
                return self._send(400, {"error": "id and name required"})
            c = _db()
            c.execute("""INSERT INTO divisions(id,name,repo_path,orchestrator,status,notes)
                         VALUES(?,?,?,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET name=excluded.name, repo_path=excluded.repo_path,
                           orchestrator=excluded.orchestrator, status=excluded.status, notes=excluded.notes""",
                      (b["id"], b["name"], b.get("repo_path"), b.get("orchestrator"),
                       b.get("status", "active"), b.get("notes")))
            c.commit(); c.close()
            return self._send(200, {"ok": True, "id": b["id"]})

        if path == "/farm/add":
            if not self._auth("write"):
                return
            if not b.get("name") or not b.get("source"):
                return self._send(400, {"error": "name and source required"})
            fid = b.get("id") or f"farm_{uuid.uuid4().hex[:12]}"
            c = _db()
            try:
                c.execute("INSERT INTO farm_candidates(id,source,name,url,summary,signal,fit_score,verdict) "
                          "VALUES(?,?,?,?,?,?,?,?)",
                          (fid, b["source"], b["name"], b.get("url"), b.get("summary"),
                           b.get("signal"), float(b.get("fit_score", 0.0)), b.get("verdict", "new")))
                c.commit()
                new = True
            except sqlite3.IntegrityError:
                new = False  # dup url — already harvested
            c.close()
            return self._send(200, {"ok": True, "id": fid, "new": new})

        if path == "/farm/decide":
            if not self._auth("write"):
                return
            if not b.get("id") or not b.get("verdict"):
                return self._send(400, {"error": "id and verdict required"})
            c = _db()
            cur = c.execute("UPDATE farm_candidates SET verdict=?, decided_by=?, decided_at=CURRENT_TIMESTAMP WHERE id=?",
                            (b["verdict"], b.get("decided_by", "shaan"), b["id"]))
            c.commit(); n = cur.rowcount; c.close()
            return self._send(200, {"ok": n > 0, "updated": n})

        if path == "/halt":
            if not self._auth("write"):
                return
            scope = b.get("scope", "global")
            paused = 0 if b.get("resume") else 1
            c = _db()
            c.execute("""INSERT INTO control_flags(scope,paused,reason,updated_at)
                         VALUES(?,?,?,CURRENT_TIMESTAMP)
                         ON CONFLICT(scope) DO UPDATE SET paused=excluded.paused,
                           reason=excluded.reason, updated_at=CURRENT_TIMESTAMP""",
                      (scope, paused, b.get("reason")))
            c.commit(); c.close()
            return self._send(200, {"ok": True, "scope": scope, "paused": bool(paused)})

        if path == "/fleet/heartbeat":
            if not self._auth("write"):
                return
            iid = b.get("id")
            if not iid:
                return self._send(400, {"error": "id required"})
            c = _db()
            # ISO-8601 UTC with Z to match existing rows' format (so ORDER BY sorts correctly)
            now = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
            c.execute("""INSERT INTO cli_instances(id,name,machine,cwd,status,last_heartbeat)
                         VALUES(?,?,?,?,?,?)
                         ON CONFLICT(id) DO UPDATE SET
                           status=excluded.status, machine=excluded.machine,
                           cwd=excluded.cwd, last_heartbeat=excluded.last_heartbeat""",
                      (iid, b.get("name", iid), b.get("machine"), b.get("cwd", ""), b.get("status", "running"), now))
            c.commit()
            c.close()
            return self._send(200, {"ok": True, "id": iid})

        return self._send(404, {"error": "not found", "path": path})

    def log_message(self, fmt, *a):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % a))


def main():
    if not TOKENS:
        sys.stderr.write(f"WARNING: no tokens loaded from {TOKENS_DIR} — all authed routes will 401.\n")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    sys.stderr.write(f"braind listening on 127.0.0.1:{PORT} | db={DB_PATH} | tiers={sorted(set(TOKENS.values()))}\n")
    srv.serve_forever()


if __name__ == "__main__":
    main()
