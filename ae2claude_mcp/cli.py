"""Structured AE2Claude CLI generated from the Agent capability model."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .agent_runtime import execute_batch
from .capabilities import capabilities
from .runtime import authorize, bridge, call_bridge_method, require_enabled


def _json_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid JSON: {exc.msg}") from exc


def _layer_ref(value: str) -> Any:
    if value.startswith("id:"):
        return {"id": int(value[3:])}
    if value.startswith("index:"):
        return {"index": int(value[6:])}
    if value.startswith("name:"):
        return {"name": value[5:]}
    try:
        return int(value)
    except ValueError:
        return value


def _read_json_document(path: str) -> Any:
    text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
    return json.loads(text)


def _emit(value: Any, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    elif output_format == "ndjson":
        items = value if isinstance(value, list) else [value]
        for item in items:
            print(json.dumps(item, ensure_ascii=False, default=str))
    elif isinstance(value, str):
        print(value)
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ae2claude",
        description="Structured Agent CLI for the running After Effects instance.",
    )
    parser.add_argument("--version", action="version", version=f"ae2claude {__version__}")
    parser.add_argument("--format", choices=("json", "text", "ndjson"), default="json")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=None, help="bridge timeout in seconds")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="live bridge, project, and comp status")

    cap = sub.add_parser("capabilities", aliases=["methods"], help="search operation schemas")
    cap.add_argument("query", nargs="?", default="")
    cap.add_argument("--category", default="")

    inspect_parser = sub.add_parser("inspect", help="inspect a layer property graph")
    inspect_parser.add_argument("--layer", required=True, type=_layer_ref)
    inspect_parser.add_argument("--path", type=_json_value, default=[])
    inspect_parser.add_argument("--depth", type=int, default=3)
    inspect_parser.add_argument("--max-nodes", type=int, default=512)
    inspect_parser.add_argument("--backend", choices=("auto", "native", "jsx"), default="auto")

    get_parser = sub.add_parser("get", help="read one property by matchName path")
    get_parser.add_argument("--layer", required=True, type=_layer_ref)
    get_parser.add_argument("--path", required=True, type=_json_value)
    get_parser.add_argument("--time", type=float, default=None)
    get_parser.add_argument("--pre-expression", action="store_true")
    get_parser.add_argument("--backend", choices=("auto", "native", "jsx"), default="auto")

    set_parser = sub.add_parser("set", help="set one property or keyframe")
    set_parser.add_argument("--layer", required=True, type=_layer_ref)
    set_parser.add_argument("--path", required=True, type=_json_value)
    set_parser.add_argument("--value", required=True, type=_json_value)
    set_parser.add_argument("--time", type=float, default=None)
    set_parser.add_argument("--undo-name", default="AE2Claude CLI Set Property")
    set_parser.add_argument("--backend", choices=("auto", "native", "jsx"), default="auto")
    set_parser.add_argument("--confirm", action="store_true")

    prop_batch = sub.add_parser("property-batch", help="one-dispatch property plan from JSON")
    prop_batch.add_argument("file", help="JSON operations file, or - for stdin")
    prop_batch.add_argument("--layer", required=True, type=_layer_ref)
    prop_batch.add_argument("--dry-run", action="store_true")
    prop_batch.add_argument("--undo-name", default="AE2Claude CLI Property Batch")
    prop_batch.add_argument("--keep-going", action="store_true")
    prop_batch.add_argument("--backend", choices=("auto", "native", "jsx"), default="auto")
    prop_batch.add_argument("--confirm", action="store_true")

    batch = sub.add_parser("batch", help="method-call plan with $0.field references")
    batch.add_argument("file", help="JSON operations file, or - for stdin")
    batch.add_argument("--dry-run", action="store_true")
    batch.add_argument("--keep-going", action="store_true")
    batch.add_argument("--confirm", action="store_true")
    batch.add_argument("--request-id", default=None)

    call = sub.add_parser("call", help="invoke one self-described bridge method")
    call.add_argument("method")
    call.add_argument("--args", type=_json_value, default=[])
    call.add_argument("--kwargs", type=_json_value, default={})
    call.add_argument("--confirm", action="store_true")

    jsx = sub.add_parser("jsx", help="execute raw ExtendScript from text or stdin")
    jsx.add_argument("code", nargs="?", default=None)
    jsx.add_argument("--confirm", action="store_true")

    return parser


def dispatch(args: argparse.Namespace) -> Any:
    if args.port is not None:
        os.environ["AE2CLAUDE_PORT"] = str(args.port)
    if args.timeout is not None:
        os.environ["AE2CLAUDE_TIMEOUT"] = str(args.timeout)

    if args.command in {"capabilities", "methods"}:
        return capabilities(query=args.query, category=args.category)
    if args.command == "batch":
        return execute_batch(
            _read_json_document(args.file),
            dry_run=args.dry_run,
            fail_fast=not args.keep_going,
            confirm=args.confirm,
            request_id=args.request_id,
        )
    if args.command == "call":
        result = call_bridge_method(
            args.method, args.args, args.kwargs, confirm=args.confirm
        )
        return {"ok": True, "method": args.method, "result": result}

    require_enabled()
    with bridge() as ae:
        if args.command == "status":
            return {
                "ok": True,
                "version": __version__,
                "health": ae.health,
                "project": ae.project_info(),
                "comp": ae.comp_info() or None,
            }
        if args.command == "inspect":
            return ae.inspect_properties(
                args.layer, args.path or None, args.depth, args.max_nodes, args.backend
            )
        if args.command == "get":
            value = ae.get_property(
                args.layer, args.path, args.time, args.pre_expression, args.backend
            )
            return {"ok": True, "value": value}
        if args.command == "set":
            authorize("write", confirm=args.confirm)
            return ae.set_property(
                args.layer, args.path, args.value, args.time, args.undo_name, args.backend
            )
        if args.command == "property-batch":
            operations = _read_json_document(args.file)
            if any(str(item.get("action", "")).lower() == "set" for item in operations):
                authorize("write", confirm=args.confirm)
            return ae.property_batch(
                args.layer,
                operations,
                args.dry_run,
                args.undo_name,
                not args.keep_going,
                args.backend,
            )
        if args.command == "jsx":
            authorize("destructive", confirm=args.confirm)
            code = args.code if args.code is not None else sys.stdin.read()
            return {"ok": True, "result": ae.run_jsx(code)}
    raise RuntimeError(f"unsupported command: {args.command}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = dispatch(args)
        _emit(result, args.format)
        if isinstance(result, dict) and result.get("ok") is False:
            raise SystemExit(4)
    except (ConnectionError, TimeoutError) as exc:
        _emit({"ok": False, "error": str(exc), "kind": "connection"}, args.format)
        raise SystemExit(3) from exc
    except Exception as exc:
        _emit({"ok": False, "error": str(exc), "kind": "operation"}, args.format)
        raise SystemExit(4) from exc


if __name__ == "__main__":
    main()
