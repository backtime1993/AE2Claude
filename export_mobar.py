"""Export MoBar scriptlets into a new directory without changing the shipped library.

Run with --output to choose a new or empty directory. To integrate an export,
review its scripts and merge its registry with the existing library metadata.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re


SETTINGS = Path(os.path.expanduser(r"~\AppData\Roaming\MoBar\settings-v2.json"))
_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.IGNORECASE)


def _slug(name: str) -> str:
    # Windows filenames are case insensitive and forbid these characters even
    # when an export is prepared on another OS for use in After Effects.
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f ()（）≥]+', '-', name)
    value = re.sub(r'-+', '-', value).strip('-. ')[:120].rstrip('. ')
    value = value or 'unnamed'
    if _RESERVED.match(value):
        value = '_' + value
    return value


def prepare_scriptlets(settings: dict) -> list[tuple[dict, str]]:
    """Validate all entries and allocate unique names before writing any files."""
    if not isinstance(settings, dict) or not isinstance(settings.get('userPanels', []), list):
        raise ValueError('MoBar settings must contain a userPanels array')
    entries = []
    used = set()
    for panel in settings.get('userPanels', []):
        if not isinstance(panel, dict) or not isinstance(panel.get('items', []), list):
            raise ValueError('Each MoBar panel must contain an items array')
        for item in panel.get('items', []):
            if not isinstance(item, dict):
                raise ValueError('MoBar items must be objects')
            if item.get('type') != 'scriptlet':
                continue
            name, code = item.get('name', 'unnamed'), item.get('command', '')
            if not isinstance(name, str) or not isinstance(code, str):
                raise ValueError('Scriptlet name and command must be strings')
            if code.startswith('"'):
                try:
                    code = json.loads(code)
                except json.JSONDecodeError:
                    pass  # A normal JSX string literal need not be JSON encoded.
            if not isinstance(code, str):
                raise ValueError('Decoded scriptlet command must be a string')
            base = _slug(name)
            slug, suffix = base, 2
            while slug.casefold() in used:
                slug = f'{base}-{suffix}'
                suffix += 1
            used.add(slug.casefold())
            entries.append(({'slug': slug, 'name': name, 'file': slug + '.jsx'}, code))
    return entries


def export_scriptlets(settings_path: Path, output: Path) -> list[dict]:
    entries = prepare_scriptlets(json.loads(Path(settings_path).read_text(encoding='utf-8-sig')))
    output = Path(output)
    if output.is_symlink() or output.is_junction():
        raise ValueError('Export output must not be a link or junction')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FileExistsError('Export output must be a new or empty directory: ' + str(output))
    output.mkdir(parents=True, exist_ok=True)
    registry = [metadata for metadata, _ in entries]
    for metadata, code in entries:
        with (output / metadata['file']).open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(code)
    with (output / 'registry.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(registry, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    return registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path, default=SETTINGS)
    parser.add_argument('--output', type=Path,
                        help='New or empty output directory; never overwrite an existing script library')
    args = parser.parse_args(argv)
    output = args.output or Path.cwd() / ('mobar-export-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    try:
        registry = export_scriptlets(args.settings, output)
    except (OSError, ValueError) as error:
        parser.exit(1, f'error: {error}\n')
    print(json.dumps({'ok': True, 'count': len(registry), 'output': str(output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
