"""Filesystem-backed After Effects project checkpoints.

Creating a checkpoint saves the current project and copies the resulting AEP.
Reverting first creates a recovery checkpoint, then atomically restores the
selected AEP over the original project path and reopens it in After Effects.
"""
from __future__ import annotations

import hashlib
import json
import ntpath
import os
import secrets
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ae_bridge import AEBridge


def _canonical_path(source_path: str) -> str:
    drive, _ = ntpath.splitdrive(source_path)
    if drive:
        return ntpath.normcase(ntpath.normpath(source_path))
    return os.path.normcase(os.path.abspath(os.path.normpath(source_path)))


def project_key(source_path: str) -> str:
    drive, _ = ntpath.splitdrive(source_path)
    stem = (
        ntpath.splitext(ntpath.basename(source_path))[0]
        if drive
        else Path(source_path).stem
    )
    safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in stem)
    digest = hashlib.sha256(_canonical_path(source_path).encode("utf-8")).hexdigest()
    return f"{(safe.strip() or 'project')[:48]}_{digest[:12]}"


class CheckpointStore:
    def __init__(self, root: Path | None = None, keep: int | None = None) -> None:
        configured = os.environ.get("AE2CLAUDE_CHECKPOINT_DIR")
        self.root = Path(root or configured or (Path(tempfile.gettempdir()) / "ae2claude_checkpoints"))
        self.root.mkdir(parents=True, exist_ok=True)
        configured_keep = os.environ.get("AE2CLAUDE_CHECKPOINT_KEEP")
        self.keep = max(1, keep or int(configured_keep or "30"))

    def make_id(self) -> str:
        return f"{int(time.time() * 1000)}_{secrets.token_hex(4)}"

    def project_dir(self, source_path: str) -> Path:
        path = self.root / project_key(source_path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def aep_path(self, source_path: str, checkpoint_id: str) -> Path:
        return self.project_dir(source_path) / f"{checkpoint_id}.aep"

    def meta_path(self, source_path: str, checkpoint_id: str) -> Path:
        return self.project_dir(source_path) / f"{checkpoint_id}.json"

    def write_meta(self, source_path: str, checkpoint_id: str, data: dict[str, Any]) -> dict[str, Any]:
        meta = {
            "id": checkpoint_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sourceProjectPath": source_path,
            **data,
        }
        target = self.meta_path(source_path, checkpoint_id)
        staged = target.with_suffix(".json.tmp")
        staged.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(staged, target)
        return meta

    def list(self, source_path: str, limit: int = 20) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for meta_path in self.project_dir(source_path).glob("*.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            aep = self.aep_path(source_path, str(meta.get("id", "")))
            if aep.exists() and _canonical_path(meta.get("sourceProjectPath", source_path)) == _canonical_path(source_path):
                entries.append(meta)
        entries.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
        return entries[: max(1, min(limit, 200))]

    def lookup(self, source_path: str, checkpoint_id: str) -> Path:
        if not checkpoint_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in checkpoint_id):
            raise ValueError("Invalid checkpoint id")
        path = self.aep_path(source_path, checkpoint_id)
        if not path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_id}")
        return path

    def prune(self, source_path: str) -> list[str]:
        entries = self.list(source_path, limit=10_000)
        removed: list[str] = []
        for meta in entries[self.keep :]:
            checkpoint_id = str(meta["id"])
            self.aep_path(source_path, checkpoint_id).unlink(missing_ok=True)
            self.meta_path(source_path, checkpoint_id).unlink(missing_ok=True)
            removed.append(checkpoint_id)
        return removed


def _saved_project_path(ae: AEBridge) -> str | None:
    value = ae.project_info().get("file")
    if not value or value == "unsaved":
        return None
    return str(value)


def create_checkpoint(
    ae: AEBridge,
    label: str = "MCP checkpoint",
    *,
    store: CheckpointStore | None = None,
) -> dict[str, Any]:
    store = store or CheckpointStore()
    source_path = _saved_project_path(ae)
    if source_path is None:
        return {"ok": True, "skipped": True, "reason": "unsaved_project"}

    checkpoint_id = store.make_id()
    destination = store.aep_path(source_path, checkpoint_id)
    destination_json = json.dumps(str(destination), ensure_ascii=False)
    code = f"""
(function () {{
    if (app.project.file === null) {{
        return JSON.stringify({{ok:true,skipped:true,reason:"unsaved_project"}});
    }}
    try {{ app.project.save(); }}
    catch (err) {{ return JSON.stringify({{ok:false,error:"save_failed: " + String(err)}}); }}
    var source = app.project.file;
    var destination = new File({destination_json});
    if (!source.copy(destination.fsName)) {{
        return JSON.stringify({{ok:false,error:"checkpoint_copy_failed"}});
    }}
    var comp = app.project.activeItem;
    return JSON.stringify({{
        ok:true,sourceProjectPath:source.fsName,savedTo:destination.fsName,
        sizeBytes:destination.length,
        activeCompId:(comp && comp instanceof CompItem) ? String(comp.id) : null,
        currentTime:(comp && comp instanceof CompItem) ? comp.time : 0
    }});
}})();
"""
    raw = ae.run_jsx(code, timeout=120_000)
    result = json.loads(raw)
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "checkpoint_failed"))
    if result.get("skipped"):
        return result
    if not destination.exists() or destination.stat().st_size == 0:
        raise RuntimeError("AE reported success but checkpoint file is missing")
    meta = store.write_meta(
        source_path,
        checkpoint_id,
        {
            "label": label[:200],
            "activeCompId": result.get("activeCompId"),
            "currentTime": result.get("currentTime", 0),
            "sizeBytes": destination.stat().st_size,
        },
    )
    meta["path"] = str(destination)
    meta["pruned"] = store.prune(source_path)
    return {"ok": True, **meta}


def list_checkpoints(
    ae: AEBridge,
    *,
    limit: int = 20,
    store: CheckpointStore | None = None,
) -> dict[str, Any]:
    source_path = _saved_project_path(ae)
    if source_path is None:
        return {"ok": True, "project": None, "checkpoints": []}
    store = store or CheckpointStore()
    return {
        "ok": True,
        "project": source_path,
        "checkpoints": store.list(source_path, limit=limit),
    }


def revert_checkpoint(
    ae: AEBridge,
    checkpoint_id: str,
    *,
    store: CheckpointStore | None = None,
) -> dict[str, Any]:
    store = store or CheckpointStore()
    source_path = _saved_project_path(ae)
    if source_path is None:
        raise RuntimeError("Cannot revert an unsaved project")
    checkpoint = store.lookup(source_path, checkpoint_id)

    recovery = create_checkpoint(ae, f"Before revert to {checkpoint_id}", store=store)
    source = Path(source_path)
    staged = source.parent / f".{source.name}.ae2claude-{checkpoint_id}.tmp"
    close_result = json.loads(
        ae.run_jsx(
            '(function(){try{app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);'
            'return JSON.stringify({ok:true});}catch(e){return JSON.stringify({ok:false,error:String(e)});}})();',
            timeout=60_000,
        )
    )
    if not close_result.get("ok"):
        raise RuntimeError(close_result.get("error", "project_close_failed"))

    try:
        shutil.copy2(checkpoint, staged)
        os.replace(staged, source)
    except Exception:
        staged.unlink(missing_ok=True)
        ae.run_jsx(f'app.open(new File({json.dumps(str(source), ensure_ascii=False)}));', timeout=120_000)
        raise

    open_code = f"""
(function () {{
    try {{
        app.open(new File({json.dumps(str(source), ensure_ascii=False)}));
        return JSON.stringify({{ok:true,path:app.project.file.fsName}});
    }} catch (err) {{
        return JSON.stringify({{ok:false,error:String(err)}});
    }}
}})();
"""
    opened = json.loads(ae.run_jsx(open_code, timeout=120_000))
    if not opened.get("ok"):
        raise RuntimeError(opened.get("error", "project_reopen_failed"))
    return {
        "ok": True,
        "restoredCheckpoint": checkpoint_id,
        "project": source_path,
        "recoveryCheckpoint": recovery.get("id"),
    }
