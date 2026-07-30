#!/usr/bin/env python3
"""Import proven durable task state from legacy SISO SQLite layouts.

The Brain service must be stopped while applying an import. Dry-run is the
default. Only explicit, reviewed fields are copied; unknown tables and columns
are reported by capability policy rather than guessed into the target schema.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
from typing import Any


TASK_COLUMNS = (
    "id", "parent_task_id", "blocked_by_task_id", "assigned_agent_id", "created_by_agent_id",
    "title", "description", "status", "workspace_path", "executive_summary", "tokens_burned",
    "started_at", "completed_at", "created_at", "updated_at", "project_id", "priority",
    "due_date", "time_spent", "notes", "urgency_score", "tags", "archived_at",
    "estimated_minutes", "source_tool",
)
ALLOWED_EVENTS = {"BOOT", "THOUGHT", "ACTION", "TOOL_CALL", "ERROR", "HANDOFF", "COMPLETED", "USER_PROMPT"}
ALLOWED_TASK_STATUSES = {"pending", "in_progress", "blocked", "completed", "cancelled", "archived", "failed"}
ALLOWED_STEP_STATUSES = {"pending", "in_progress", "retry", "done", "error", "cancelled"}
TASK_STATUS_MAP = {"done": "completed", "paused": "blocked", "error": "failed"}
STEP_STATUS_MAP = {"completed": "done", "failed": "error", "blocked": "retry"}


def open_source(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def open_target(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def tables(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def detect_profile(connection: sqlite3.Connection) -> str:
    available = tables(connection)
    task_columns = columns(connection, "tasks") if "tasks" in available else set()
    if "task_steps" in available and "pipeline_type" in task_columns:
        return "task-manager"
    if "assigned_agent_id" in task_columns and ("timeline_events" in available or "artifacts" in available):
        return "os-database"
    raise ValueError("source does not match a reviewed os-database or task-manager layout")


def value(row: sqlite3.Row, name: str, default: Any = None) -> Any:
    return row[name] if name in row.keys() and row[name] is not None else default


def normalize_task(row: sqlite3.Row, profile: str) -> dict[str, Any] | None:
    task_id = value(row, "id")
    if not task_id:
        return None
    if profile == "task-manager":
        priority = value(row, "priority", 1)
        try:
            urgency = max(0, min(100, int(priority) * 10))
        except (TypeError, ValueError):
            urgency = 0
        metadata = value(row, "metadata", "")
        pipeline = value(row, "pipeline_type", "unknown")
        status = TASK_STATUS_MAP.get(str(value(row, "status", "pending")), value(row, "status", "pending"))
        if status not in ALLOWED_TASK_STATUSES:
            status = "pending"
        return {
            "id": task_id,
            "parent_task_id": None,
            "blocked_by_task_id": None,
            "assigned_agent_id": value(row, "assigned_to"),
            "created_by_agent_id": value(row, "created_by"),
            "title": value(row, "title"),
            "description": value(row, "description", value(row, "title", "Imported legacy task")),
            "status": status,
            "workspace_path": None,
            "executive_summary": None,
            "tokens_burned": 0,
            "started_at": None,
            "completed_at": None,
            "created_at": value(row, "created_at"),
            "updated_at": value(row, "updated_at"),
            "project_id": value(row, "project_id"),
            "priority": str(priority),
            "due_date": None,
            "time_spent": 0,
            "notes": metadata,
            "urgency_score": urgency,
            "tags": value(row, "category", ""),
            "archived_at": None,
            "estimated_minutes": 0,
            "source_tool": f"legacy-task-manager:{pipeline}",
        }
    result = {name: value(row, name) for name in TASK_COLUMNS}
    result["description"] = result["description"] or result["title"] or "Imported legacy task"
    result["status"] = TASK_STATUS_MAP.get(str(result["status"] or "pending"), result["status"] or "pending")
    if result["status"] not in ALLOWED_TASK_STATUSES:
        result["status"] = "pending"
    result["priority"] = str(result["priority"] or "medium")
    result["tokens_burned"] = result["tokens_burned"] or 0
    result["time_spent"] = result["time_spent"] or 0
    result["urgency_score"] = result["urgency_score"] or 0
    result["estimated_minutes"] = result["estimated_minutes"] or 0
    result["source_tool"] = "legacy-os-database"
    return result


def insert_row(connection: sqlite3.Connection, table: str, item: dict[str, Any], ordered: tuple[str, ...]) -> bool:
    placeholders = ",".join("?" for _ in ordered)
    names = ",".join(ordered)
    cursor = connection.execute(
        f"INSERT OR IGNORE INTO {table}({names}) VALUES({placeholders})",
        [item.get(name) for name in ordered],
    )
    return cursor.rowcount == 1


def counter() -> dict[str, int]:
    return {"seen": 0, "accepted": 0, "written_or_planned": 0, "existing": 0, "invalid": 0}


def import_legacy(source_path: Path, target_path: Path, profile: str | None, apply: bool,
                  include_memory: bool, include_timeline: bool) -> dict[str, Any]:
    if source_path.resolve() == target_path.resolve():
        raise ValueError("source and target must be different databases")
    source = open_source(source_path)
    target = open_target(target_path)
    selected = profile or detect_profile(source)
    source_tables = tables(source)
    target_tables = tables(target)
    required = {"tasks", "task_steps", "task_artifacts", "memories", "timeline_events"}
    missing = sorted(required - target_tables)
    if missing:
        source.close(); target.close()
        raise ValueError(f"target is not migrated; missing tables: {', '.join(missing)}")

    stats = {name: counter() for name in ("tasks", "task_steps", "task_artifacts", "memories", "timeline_events")}
    exclusions = [
        {"capability": "sessions", "reason": "session execution belongs to Agent Runtime"},
        {"capability": "tools_and_permissions", "reason": "tool discovery and execution authority have separate owners"},
        {"capability": "project_hierarchy", "reason": "projects, missions, and goals belong to Project OS"},
        {"capability": "automations_and_templates", "reason": "composed procedures and scheduling do not belong in shared storage"},
        {"capability": "custom_fields_and_generic_relationships", "reason": "consumer value remains unverified"},
        {"capability": "raw_sql_and_runtime_state", "reason": "never imported or exposed"},
    ]
    if selected == "os-database" and "artifacts" in source_tables:
        exclusions.append({"capability": "file_path_artifacts", "reason": "private machine paths are not copied; publish a reviewed locator separately"})
    if "memories" in source_tables and not include_memory:
        exclusions.append({"capability": "memory_content", "reason": "privacy-sensitive memory requires explicit --include-memory"})
    if "timeline_events" in source_tables and not include_timeline:
        exclusions.append({"capability": "timeline_content", "reason": "activity content requires explicit --include-timeline"})

    try:
        target.execute("BEGIN IMMEDIATE")
        for row in source.execute("SELECT * FROM tasks"):
            bucket = stats["tasks"]; bucket["seen"] += 1
            item = normalize_task(row, selected)
            if not item:
                bucket["invalid"] += 1; continue
            bucket["accepted"] += 1
            if insert_row(target, "tasks", item, TASK_COLUMNS): bucket["written_or_planned"] += 1
            else: bucket["existing"] += 1

        task_ids = {row[0] for row in target.execute("SELECT id FROM tasks")}
        step_ids: set[str] = set()
        if selected == "task-manager" and "task_steps" in source_tables:
            ordered = ("id", "task_id", "step_name", "status", "assigned_role", "step_order", "input_payload", "output_payload", "error_log")
            for row in source.execute("SELECT * FROM task_steps"):
                bucket = stats["task_steps"]; bucket["seen"] += 1
                if not value(row, "id") or value(row, "task_id") not in task_ids or not value(row, "step_name"):
                    bucket["invalid"] += 1; continue
                item = {
                    "id": value(row, "id"), "task_id": value(row, "task_id"), "step_name": value(row, "step_name"),
                    "status": STEP_STATUS_MAP.get(str(value(row, "status", "pending")), value(row, "status", "pending")),
                    "assigned_role": value(row, "assigned_agent_role"), "step_order": value(row, "step_order", 0),
                    "input_payload": value(row, "input_payload"), "output_payload": value(row, "output_payload"),
                    "error_log": value(row, "error_log"),
                }
                if item["status"] not in ALLOWED_STEP_STATUSES:
                    bucket["invalid"] += 1; continue
                bucket["accepted"] += 1
                if insert_row(target, "task_steps", item, ordered): bucket["written_or_planned"] += 1
                else: bucket["existing"] += 1
                step_ids.add(item["id"])

        if selected == "task-manager" and "artifacts" in source_tables:
            ordered = ("id", "task_id", "step_id", "artifact_type", "content", "version", "created_at")
            for row in source.execute("SELECT * FROM artifacts"):
                bucket = stats["task_artifacts"]; bucket["seen"] += 1
                if not value(row, "id") or value(row, "task_id") not in task_ids or value(row, "content") is None:
                    bucket["invalid"] += 1; continue
                source_step = value(row, "created_by_step_id")
                item = {
                    "id": value(row, "id"), "task_id": value(row, "task_id"),
                    "step_id": source_step if source_step in step_ids else None,
                    "artifact_type": value(row, "artifact_type", "legacy"), "content": value(row, "content"),
                    "version": value(row, "version", 1), "created_at": value(row, "created_at"),
                }
                bucket["accepted"] += 1
                if insert_row(target, "task_artifacts", item, ordered): bucket["written_or_planned"] += 1
                else: bucket["existing"] += 1

        if include_memory and "memories" in source_tables:
            ordered = ("id", "task_id", "agent_id", "type", "content", "created_at")
            for row in source.execute("SELECT * FROM memories"):
                bucket = stats["memories"]; bucket["seen"] += 1
                if not value(row, "id") or not value(row, "type") or value(row, "content") is None:
                    bucket["invalid"] += 1; continue
                item = {name: value(row, name) for name in ordered}
                bucket["accepted"] += 1
                if insert_row(target, "memories", item, ordered): bucket["written_or_planned"] += 1
                else: bucket["existing"] += 1

        if include_timeline and selected == "os-database" and "timeline_events" in source_tables:
            ordered = ("id", "task_id", "agent_id", "event_type", "message", "metadata", "timestamp")
            for row in source.execute("SELECT * FROM timeline_events"):
                bucket = stats["timeline_events"]; bucket["seen"] += 1
                kind = str(value(row, "event_type", "")).upper()
                if not value(row, "id") or not value(row, "agent_id") or kind not in ALLOWED_EVENTS:
                    bucket["invalid"] += 1; continue
                item = {name: value(row, name) for name in ordered}; item["event_type"] = kind
                bucket["accepted"] += 1
                if insert_row(target, "timeline_events", item, ordered): bucket["written_or_planned"] += 1
                else: bucket["existing"] += 1

        if apply: target.commit()
        else: target.rollback()
    except Exception:
        target.rollback()
        raise
    finally:
        source.close(); target.close()

    return {
        "ok": True,
        "mode": "apply" if apply else "dry-run",
        "profile": selected,
        "privacy_options": {"include_memory": include_memory, "include_timeline": include_timeline},
        "capabilities": stats,
        "excluded": exclusions,
        "note": "written_or_planned means inserted in apply mode and would insert in dry-run mode",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Dry-run-first legacy task-state importer; stop Agent Brain before --apply")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--profile", choices=("os-database", "task-manager"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--include-memory", action="store_true", help="explicitly include privacy-sensitive memory content")
    parser.add_argument("--include-timeline", action="store_true", help="explicitly include activity/timeline content")
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error("source database does not exist")
    if not args.target.is_file():
        parser.error("target database does not exist; apply Brain migrations first")
    try:
        report = import_legacy(args.source, args.target, args.profile, args.apply, args.include_memory, args.include_timeline)
    except (sqlite3.Error, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
