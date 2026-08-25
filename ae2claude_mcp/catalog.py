"""Searchable, path-confined catalog for bundled AE scripts."""
from __future__ import annotations

import json
import os
import re
import sysconfig
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


REPO_SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "scripts"
INSTALLED_SCRIPT_ROOT = (
    Path(sysconfig.get_path("data")) / "share" / "ae2claude" / "scripts"
)
SCRIPT_ROOT = Path(
    os.environ.get(
        "AE2CLAUDE_SCRIPT_ROOT",
        REPO_SCRIPT_ROOT if REPO_SCRIPT_ROOT.is_dir() else INSTALLED_SCRIPT_ROOT,
    )
)
VALID_RISKS = {"read", "write", "destructive"}
DEFAULT_MODES = ("default", "ctrl", "alt")
MODE_PATTERN = re.compile(r"^[a-z0-9_-]{1,32}$")


def load_script_registry(script_root: Path = SCRIPT_ROOT) -> list[dict[str, Any]]:
    """Load normalized registry entries; unknown scripts default to destructive."""
    path = script_root / "registry.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("scripts/registry.json must contain a list")

    entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug", "")).strip()
        name = str(item.get("name", "")).strip()
        filename = str(item.get("file", "")).strip()
        if not slug or not name or not filename:
            continue
        risk = str(item.get("risk", "destructive")).strip().lower()
        if risk not in VALID_RISKS:
            risk = "destructive"
        tags = item.get("tags", [])
        if not isinstance(tags, list):
            tags = [str(tags)]
        modes = item.get("modes", DEFAULT_MODES)
        if not isinstance(modes, list):
            modes = [str(modes)]
        normalized_modes = [str(mode).strip().lower() for mode in modes]
        entries.append(
            {
                "slug": slug,
                "name": name,
                "file": filename,
                "description": str(item.get("description", "")),
                "note": str(item.get("note", "")),
                "tags": [str(tag) for tag in tags],
                "modes": [
                    mode for mode in normalized_modes if MODE_PATTERN.fullmatch(mode)
                ],
                "risk": risk,
            }
        )
    return entries


def _search_text(entry: dict[str, Any]) -> str:
    return " ".join(
        [
            entry["slug"],
            entry["name"],
            entry["description"],
            entry["note"],
            *entry["tags"],
        ]
    ).casefold()


def _score(entry: dict[str, Any], query: str) -> float:
    key = query.casefold()
    slug = entry["slug"].casefold()
    name = entry["name"].casefold()
    haystack = _search_text(entry)
    if key == slug or key == name:
        return 1.0
    if key in slug or key in name:
        return 0.9
    if key in haystack:
        return 0.75
    return max(
        SequenceMatcher(None, key, slug).ratio(),
        SequenceMatcher(None, key, name).ratio(),
    )


def search_scripts(
    query: str = "",
    *,
    offset: int = 0,
    limit: int = 100,
    script_root: Path = SCRIPT_ROOT,
) -> dict[str, Any]:
    """Fuzzy-search the bundled registry with explicit pagination."""
    entries = load_script_registry(script_root)
    query = query.strip()
    if query:
        ranked = [(_score(entry, query), entry) for entry in entries]
        ranked = [pair for pair in ranked if pair[0] >= 0.25]
        ranked.sort(key=lambda pair: (-pair[0], pair[1]["name"].casefold()))
        matches = [{**entry, "score": round(score, 3)} for score, entry in ranked]
    else:
        matches = sorted(entries, key=lambda item: item["name"].casefold())

    offset = max(0, int(offset))
    limit = max(1, min(int(limit), 500))
    return {
        "query": query,
        "offset": offset,
        "limit": limit,
        "total": len(matches),
        "scripts": matches[offset:offset + limit],
    }


def resolve_script(query: str, script_root: Path = SCRIPT_ROOT) -> dict[str, Any]:
    """Resolve one registry entry while rejecting ambiguous fuzzy matches."""
    query = query.strip()
    if not query:
        raise ValueError("script must not be empty")
    entries = load_script_registry(script_root)
    key = query.casefold()

    exact = [
        entry
        for entry in entries
        if key in {entry["slug"].casefold(), entry["name"].casefold()}
    ]
    if len(exact) == 1:
        return exact[0]

    contains = [
        entry
        for entry in entries
        if key in entry["slug"].casefold() or key in entry["name"].casefold()
    ]
    if len(contains) == 1:
        return contains[0]
    if len(contains) > 1:
        choices = ", ".join(entry["slug"] for entry in contains[:10])
        raise ValueError(f"Ambiguous script '{query}': {choices}")

    ranked = sorted(
        ((_score(entry, query), entry) for entry in entries),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] < 0.55:
        raise ValueError(f"Unknown script: {query}")
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.05:
        raise ValueError(
            f"Ambiguous script '{query}': "
            f"{ranked[0][1]['slug']}, {ranked[1][1]['slug']}"
        )
    return ranked[0][1]


def script_path(entry: dict[str, Any], script_root: Path = SCRIPT_ROOT) -> Path:
    """Resolve a registry path and guarantee it stays inside scripts/."""
    root = script_root.resolve()
    path = (root / entry["file"]).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Registered script escapes scripts directory")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def read_script(entry: dict[str, Any], script_root: Path = SCRIPT_ROOT) -> str:
    path = script_path(entry, script_root)
    for encoding in ("utf-8-sig", "gb18030", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"Unable to decode script: {path}")


def prepare_script(
    entry: dict[str, Any], mode: str = "default", script_root: Path = SCRIPT_ROOT
) -> str:
    mode = mode.strip().lower()
    if not MODE_PATTERN.fullmatch(mode):
        raise ValueError(f"Unsupported mode: {mode}")
    if mode not in entry["modes"]:
        raise ValueError(f"Script '{entry['slug']}' does not support mode '{mode}'")
    code = read_script(entry, script_root)
    if mode != "default":
        code = f'var __mode__ = {json.dumps(mode)};\n' + code
    return code
