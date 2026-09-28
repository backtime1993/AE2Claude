"""Opt-in AE startup preferences: skip Home and continue after prior-session crashes.

Run with AE closed. Only existing keys are changed, with backups and rollback.
Project auto-save/recovery, plugins, workspaces and crash reporting are untouched.
The debug key is version dependent; fail closed when it is absent or ambiguous.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from datetime import datetime


HOME = re.compile(rb'(?m)^([ \t]*"Show Welcome Screen"[ \t]*=[ \t]*)(00|01)([ \t]*\r*)$')
CRASH = re.compile(rb'(?m)^(AE\.DebugShowPreviousCrashWarning\t)(true|false)(\t(?:true|false)[ \t]*\r*)$')


def plan(directory: Path, home: bool | None, crash: bool | None, debug_file: Path | None = None) -> list[dict]:
    directory = directory.resolve(strict=True)
    homes = []
    for path in directory.glob('*.txt'):
        data = path.read_bytes()
        if HOME.search(data):
            homes.append((path, data))
    if len(homes) != 1:
        raise ValueError('Expected exactly one existing Home Screen preference')
    debug = (directory / 'Debug Database.txt') if debug_file is None else debug_file.resolve(strict=True)
    specs = [(homes[0][0], homes[0][1], HOME, home, b'01', b'00', 'homeScreen'),
             (debug, debug.read_bytes(), CRASH, crash, b'true', b'false', 'crashRepairPrompt')]
    rows = []
    for path, data, pattern, wanted, yes, no, key in specs:
        matches = list(pattern.finditer(data))
        if len(matches) != 1:
            raise ValueError('Unsupported or ambiguous preference: ' + key)
        match = matches[0]
        if key == 'homeScreen':
            headers = re.findall(rb'(?m)^\["([^"\r\n]+)"\]', data[:match.start()])
            if not headers or headers[-1] != b'General Section':
                raise ValueError('Home Screen preference is in an unexpected section')
        current = match.group(2) == yes
        value = current if wanted is None else wanted
        replacement = match.group(1) + (yes if value else no) + match.group(3)
        after = data[:match.start()] + replacement + data[match.end():]
        rows.append({'path': path, 'before': data, 'after': after,
                     'key': key, 'current': current, 'desired': value})
    return rows


def atomic_write(path: Path, data: bytes) -> None:
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name+'.ae2claude-', delete=False) as stream:
            tmp = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None and tmp.exists():
            tmp.unlink()


def apply(rows: list[dict], backup_root: Path) -> dict:
    changes = [row for row in rows if row['before'] != row['after']]
    result = {'changed': len(changes), 'backup': None}
    if not changes:
        return result
    # Check both inputs before writing either; never race an app preference save.
    for row in rows:
        if row['path'].read_bytes() != row['before']:
            raise RuntimeError('Preferences changed while preparing; close AE and retry')
    backup = backup_root / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup.mkdir(parents=True, exist_ok=False)
    record = []
    for row in rows:
        (backup / row['path'].name).write_bytes(row['before'])
        record.append({'path': str(row['path']), 'key': row['key'], 'before': row['current'],
                       'after': row['desired'], 'sha256Before': hashlib.sha256(row['before']).hexdigest()})
    (backup/'manifest.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    written = []
    try:
        for row in changes:
            atomic_write(row['path'], row['after'])
            written.append(row)
            if row['path'].read_bytes() != row['after']:
                raise RuntimeError('Preference verification failed')
    except Exception:
        for row in reversed(written):
            atomic_write(row['path'], row['before'])
        raise
    result['backup'] = str(backup)
    return result


def require_ae_closed() -> None:
    if os.name != 'nt':
        raise RuntimeError('This configuration tool currently supports Windows only')
    check = subprocess.run(['powershell.exe','-NoProfile','-Command',
                            "@(Get-Process -Name 'AfterFX*' -ErrorAction SilentlyContinue).Count"],
                           capture_output=True, text=True, timeout=10, check=True)
    if int(check.stdout.strip()) != 0:
        raise RuntimeError('Close After Effects before changing startup preferences')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefs-dir', type=Path, required=True)
    parser.add_argument('--debug-db', type=Path, help='Existing Debug Database.txt when AE stores it in a separate major-version directory')
    parser.add_argument('--home-screen', choices=['show','skip'])
    parser.add_argument('--crash-repair', choices=['show','continue'])
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-dir', type=Path)
    args = parser.parse_args()
    if args.apply:
        if args.backup_dir is None:
            parser.error('--apply requires --backup-dir')
        require_ae_closed()
    home = None if args.home_screen is None else args.home_screen == 'show'
    crash = None if args.crash_repair is None else args.crash_repair == 'show'
    rows = plan(args.prefs_dir, home, crash, args.debug_db)
    result = {'ok': True, 'applied': args.apply,
              'preferences': {r['key']: {'current': r['current'], 'desired': r['desired']} for r in rows}}
    if args.apply:
        result.update(apply(rows, args.backup_dir))
        verified = plan(args.prefs_dir, None, None, args.debug_db)
        result['verified'] = {r['key']:r['current'] for r in verified}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
