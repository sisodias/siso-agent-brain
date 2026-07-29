#!/usr/bin/env python3
"""Publication, schema, live API, outbox, merge, and install receipts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sqlite3
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = [
    "README.md", "LICENSE", "AGENTS.md", "PROVENANCE.md", "MIGRATION-MAP.json",
    "src/server.py", "bin/siso-brain", "bin/siso-brain-server",
    "migrations/001_core.sql", "migrations/002_coordination.sql",
    "scripts/migrate.py", "tools/spine_merge.py", "docs/ARCHITECTURE.html",
    "install.sh", "uninstall.sh",
]
TEXT_SUFFIXES = {".md", ".html", ".json", ".jsonl", ".py", ".sh", ".sql", ""}
FORBIDDEN = [
    "/" + "Users/", "shaans-" + "mac-mini", "tail100" + "d11",
    "dangerously-" + "skip-permissions", "sk-" + "or-v1-",
    "gh" + "p_", "github" + "_pat_",
]


def run(command: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=True)


def check_publication() -> None:
    for relative in REQUIRED:
        assert (ROOT / relative).is_file(), f"missing required file: {relative}"
    for path in ROOT.rglob("*"):
        if ".git" in path.parts:
            continue
        assert not path.is_symlink(), f"symlink is not publishable: {path.relative_to(ROOT)}"
        if path.is_file() and path.suffix in TEXT_SUFFIXES:
            source = path.read_text(encoding="utf-8", errors="ignore")
            for marker in FORBIDDEN:
                assert marker not in source, f"forbidden publication marker in {path.relative_to(ROOT)}"


def check_syntax() -> None:
    for path in ROOT.rglob("*.py"):
        if ".git" not in path.parts:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
    for path in ("bin/siso-brain-server", "install.sh", "uninstall.sh"):
        run(["zsh", "-n", path])
    json.loads((ROOT / "MIGRATION-MAP.json").read_text(encoding="utf-8"))


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def server_env(folder: Path, port: int) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "SISO_DB": str(folder / "brain.db"),
        "SISO_BRAIN_BIND": "127.0.0.1",
        "SISO_BRAIN_PORT": str(port),
        "SISO_BRAIN_URL": f"http://127.0.0.1:{port}",
        "SISO_BRAIN_TOKENS_DIR": str(folder / "tokens"),
        "SISO_BRAIN_TOKEN": "test-write-token",
        "SISO_BRAIN_OUTBOX": str(folder / "outbox.ndjson"),
        "SISO_BRAIN_TIMEOUT_SECONDS": "0.3",
    })
    return env


def create_tokens(folder: Path) -> None:
    token_dir = folder / "tokens"
    token_dir.mkdir(parents=True)
    for tier in ("read", "write", "spawn"):
        (token_dir / f"{tier}.token").write_text(f"test-{tier}-token\n", encoding="utf-8")


def start_server(env: dict[str, str]) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [str(ROOT / "bin/siso-brain-server")], cwd=ROOT, env=env,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    health = env["SISO_BRAIN_URL"] + "/health"
    for _ in range(80):
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(f"server exited early\n{stdout}\n{stderr}")
        try:
            with urllib.request.urlopen(health, timeout=0.2) as response:
                if json.loads(response.read())["ok"]:
                    return process
        except Exception:
            time.sleep(0.05)
    process.terminate()
    raise AssertionError("server did not become healthy")


def stop_server(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=3)


def client(env: dict[str, str], *arguments: str) -> object:
    completed = run(["bin/siso-brain", *arguments], env=env)
    return json.loads(completed.stdout)


def check_live_contract(folder: Path) -> None:
    create_tokens(folder)
    port = free_port()
    env = server_env(folder, port)
    first = run(["scripts/migrate.py"], env=env).stdout
    second = run(["scripts/migrate.py"], env=env).stdout
    assert "applied=2" in first and "applied=0" in second

    process = start_server(env)
    try:
        health = client(env, "health")
        assert health["ok"] is True and "db" not in health
        try:
            urllib.request.urlopen(env["SISO_BRAIN_URL"] + "/face", timeout=1)
            raise AssertionError("private face unexpectedly enabled")
        except urllib.error.HTTPError as error:
            assert error.code == 404

        assert client(env, "heartbeat", "--id", "worker-1", "--machine", "test")["ok"]
        assert client(env, "fleet")["count"] == 1
        assert client(env, "memory-write", "--content", "repository boundaries follow outcomes", "--agent", "worker-1")["ok"]
        assert client(env, "memory-recall", "--q", "boundaries")["count"] == 1
        assert client(env, "timeline", "--agent", "worker-1", "--type", "ACTION", "--message", "verified")["ok"]
        assert client(env, "cost", "--agent", "worker-1", "--usd", "0.01")["ok"]

        question = client(env, "question-ask", "--question", "Proceed?", "--from-agent", "worker-1")
        assert question["ok"] and client(env, "questions")["count"] == 1
        assert client(env, "answer", "--id", question["id"], "--answer", "yes")["updated"] == 1

        assert client(env, "division-register", "--id", "library", "--name", "Great Library")["ok"]
        delegated = client(env, "delegate", "--division", "library", "--intent", "Publish evidence")
        assert delegated["ok"] and client(env, "inbox", "--division", "library")["count"] == 1
        assert client(env, "inbox-reply", "--division", "library", "--body", "Published", "--ack-intent", delegated["id"])["ok"]
        assert client(env, "roundup")["count"] == 1

        assert client(env, "unit-register", "--id", "skills/example", "--kind", "skill", "--tier", "capability")["ok"]
        assert client(env, "gate", "--unit", "skills/example")["decision"] == "allow"
        assert client(env, "unit-record-outcome", "--id", "skills/example", "--verdict", "worked")["tier"] == "capability"
        assert client(env, "challenge", "--target", "skills/example", "--argument", "A simpler contract may win")["ok"]

        assert client(env, "halt", "--reason", "test")["paused"] is True
        assert client(env, "gate", "--unit", "skills/example")["decision"] == "deny"
        assert client(env, "halt", "--resume")["paused"] is False
    finally:
        stop_server(process)

    unreachable = env.copy()
    unreachable["SISO_BRAIN_URL"] = f"http://127.0.0.1:{free_port()}"
    queued = client(unreachable, "memory-write", "--content", "queued while offline")
    assert queued["queued"] is True and (folder / "outbox.ndjson").is_file()

    second_port = free_port()
    replay = server_env(folder, second_port)
    process = start_server(replay)
    try:
        assert client(replay, "drain")["drained"] == 1
        assert client(replay, "memory-recall", "--q", "queued while offline")["count"] == 1
    finally:
        stop_server(process)


def check_merge(folder: Path) -> None:
    source = folder / "source.db"
    target = folder / "target.db"
    run(["scripts/migrate.py", "--database", str(source)])
    run(["scripts/migrate.py", "--database", str(target)])
    with sqlite3.connect(source) as connection:
        connection.execute("INSERT INTO memories(id,type,content) VALUES('merge-memory','semantic_fact','merge me')")
        connection.commit()
    run(["tools/spine_merge.py", "--source", str(source), "--target", str(target), "--quiet"])
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT count(*) FROM memories").fetchone()[0] == 0
    run(["tools/spine_merge.py", "--source", str(source), "--target", str(target), "--apply", "--quiet"])
    again = run(["tools/spine_merge.py", "--source", str(source), "--target", str(target), "--apply", "--quiet"]).stdout
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT count(*) FROM memories").fetchone()[0] == 1
    assert "inserted=0" in again


def check_install(folder: Path) -> None:
    install_root = folder / "application"
    bin_root = folder / "bin"
    data_root = folder / "persistent-state"
    data_root.mkdir(parents=True)
    marker = data_root / "must-survive"
    marker.write_text("state", encoding="utf-8")
    env = os.environ.copy()
    env.update({"SISO_AGENT_BRAIN_HOME": str(install_root), "SISO_BIN_DIR": str(bin_root), "SISO_DB": str(data_root / "brain.db")})
    run(["zsh", "install.sh"], env=env)
    assert (bin_root / "siso-brain").is_symlink() and (bin_root / "siso-brain-server").is_symlink()
    run([str(bin_root / "siso-brain"), "--help"], env=env)
    run(["zsh", "uninstall.sh"], env=env)
    assert not install_root.exists() and not (bin_root / "siso-brain").exists()
    assert marker.read_text(encoding="utf-8") == "state"


def main() -> None:
    check_publication()
    check_syntax()
    with tempfile.TemporaryDirectory(prefix="siso-agent-brain-check-") as value:
        folder = Path(value)
        check_live_contract(folder / "live")
        check_merge(folder / "merge")
        check_install(folder / "install")
    print("AGENT_BRAIN_CHECK_OK (publication, schema, live API, auth, outbox, merge, install, state-preserving uninstall)")


if __name__ == "__main__":
    main()
