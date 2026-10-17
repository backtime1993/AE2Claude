"""AE-only modal capture, independent of the JSX bridge. No input or desktop capture."""
from __future__ import annotations
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import threading

# Local operator configuration only; never accepted as an MCP argument.
AE_EXE = os.environ.get("AE2CLAUDE_UI_EXE", str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Adobe" / "Adobe After Effects (Beta)" / "Support Files" / "AfterFX (Beta).exe"))
MAX_DIALOGS = 2
WORKER_TIMEOUT = 6
IS_WINDOWS = os.name == 'nt'
_CAPTURE_LOCK = threading.Lock()

def api():
    if not IS_WINDOWS:
        raise OSError('Windows required')
    u, g, k = C.WinDLL('user32', use_last_error=True), C.WinDLL('gdi32', use_last_error=True), C.WinDLL('kernel32', use_last_error=True)
    def sig(d, name, args, result):
        f = getattr(d, name); f.argtypes = args; f.restype = result
        return f
    ptr = C.c_void_p
    cb = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    sig(u, 'EnumWindows', [cb, W.LPARAM], W.BOOL)
    sig(u, 'EnumChildWindows', [W.HWND, cb, W.LPARAM], W.BOOL)
    for name in ('IsWindowVisible','IsWindowEnabled','IsIconic','IsHungAppWindow'):
        sig(u, name, [W.HWND], W.BOOL)
    sig(u,'GetWindowThreadProcessId',[W.HWND,C.POINTER(W.DWORD)],W.DWORD)
    sig(u,'GetWindowTextW',[W.HWND,W.LPWSTR,C.c_int],C.c_int)
    sig(u,'GetClassNameW',[W.HWND,W.LPWSTR,C.c_int],C.c_int)
    sig(u,'GetWindowRect',[W.HWND,C.POINTER(W.RECT)],W.BOOL)
    sig(u,'GetWindow',[W.HWND,W.UINT],W.HWND)
    sig(u,'GetForegroundWindow',[],W.HWND)
    sig(u,'OpenInputDesktop',[W.DWORD,W.BOOL,W.DWORD],W.HANDLE)
    sig(u,'CloseDesktop',[W.HANDLE],W.BOOL)
    sig(u,'GetUserObjectInformationW',[W.HANDLE,C.c_int,ptr,W.DWORD,C.POINTER(W.DWORD)],W.BOOL)
    sig(u,'SendMessageTimeoutW',[W.HWND,W.UINT,W.WPARAM,W.LPARAM,W.UINT,W.UINT,C.POINTER(C.c_size_t)],W.LPARAM)
    sig(k,'OpenProcess',[W.DWORD,W.BOOL,W.DWORD],W.HANDLE)
    sig(k,'QueryFullProcessImageNameW',[W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)],W.BOOL)
    sig(k,'CloseHandle',[W.HANDLE],W.BOOL)
    sig(u,'GetWindowDC',[W.HWND],W.HDC)
    sig(u,'ReleaseDC',[W.HWND,W.HDC],C.c_int)
    sig(u,'PrintWindow',[W.HWND,W.HDC,W.UINT],W.BOOL)
    sig(g,'CreateCompatibleDC',[W.HDC],W.HDC)
    sig(g,'CreateCompatibleBitmap',[W.HDC,C.c_int,C.c_int],ptr)
    sig(g,'SelectObject',[W.HDC,ptr],ptr)
    sig(g,'DeleteObject',[ptr],W.BOOL)
    sig(g,'DeleteDC',[W.HDC],W.BOOL)
    sig(g,'GetDIBits',[W.HDC,ptr,W.UINT,W.UINT,ptr,ptr,W.UINT],C.c_int)
    try:
        sig(u,'SetProcessDpiAwarenessContext',[ptr],W.BOOL)(ptr(-4))
    except AttributeError:
        pass
    return u,g,k,cb

def window_pid(u, hwnd):
    pid=W.DWORD(); u.GetWindowThreadProcessId(hwnd,C.byref(pid)); return pid.value

def process_path(k,pid):
    handle=k.OpenProcess(0x1000,False,pid)
    if not handle: return ''
    try:
        buf=C.create_unicode_buffer(32768); size=W.DWORD(len(buf))
        return buf.value if k.QueryFullProcessImageNameW(handle,0,buf,C.byref(size)) else ''
    finally: k.CloseHandle(handle)

def text(u,hwnd,child=False):
    buf=C.create_unicode_buffer(2048)
    if child:
        result=C.c_size_t()
        u.SendMessageTimeoutW(hwnd,0x000D,len(buf),C.addressof(buf),0x0002,80,C.byref(result))
    else: u.GetWindowTextW(hwnd,buf,len(buf))
    return buf.value

def select_dialogs(rows, owner_of):
    """Require a unique AE main and a same-process modal; do not guess an instance."""
    mains = [r for r in rows if r['class'].startswith('AE_CApplication')]
    if len(mains) != 1:
        return None, [], 'ae_not_found' if not mains else 'ambiguous_ae_instances'
    main = mains[0]
    if main['enabled'] or main['minimized']:
        return main, [], 'main_minimized' if main['minimized'] else 'not_blocked'
    dialogs = []
    for row in rows:
        if row['pid'] != main['pid'] or row['hwnd'] == main['hwnd'] or not row['enabled']:
            continue
        owner, chain = row['owner'], set()
        for _ in range(12):
            if not owner or owner in chain:
                break
            chain.add(owner)
            owner = owner_of(owner)
        if main['hwnd'] in chain or row['class'] == '#32770':
            dialogs.append(row)
    return main, dialogs, 'blocked' if dialogs else 'disabled_without_identifiable_dialog'


def enumerate_ui():
    u,g,k,CB=api(); rows=[]; paths={}
    desktop = u.OpenInputDesktop(0, False, 1)
    desktop_name, needed = C.create_unicode_buffer(256), W.DWORD()
    try:
        interactive = bool(desktop and u.GetUserObjectInformationW(
            desktop, 2, desktop_name, C.sizeof(desktop_name), C.byref(needed))
            and desktop_name.value.casefold() == 'default')
    finally:
        if desktop:
            u.CloseDesktop(desktop)
    if not interactive:
        return {'ok':False, 'blocked':None, 'state':'interactive_desktop_unavailable',
                'main':None, 'dialogs':[], 'windows':[]}
    @CB
    def visit(hwnd,param):
        if not u.IsWindowVisible(hwnd): return True
        pid=window_pid(u,hwnd)
        if pid not in paths: paths[pid]=process_path(k,pid)
        if paths[pid].casefold()!=AE_EXE.casefold(): return True
        rect=W.RECT(); cls=C.create_unicode_buffer(256)
        u.GetWindowRect(hwnd,C.byref(rect)); u.GetClassNameW(hwnd,cls,len(cls))
        if rect.right<=rect.left or rect.bottom<=rect.top: return True
        rows.append({'hwnd':int(hwnd),'pid':pid,'title':text(u,hwnd),'class':cls.value,
                     'owner':int(u.GetWindow(hwnd,4) or 0),'enabled':bool(u.IsWindowEnabled(hwnd)),
                     'minimized':bool(u.IsIconic(hwnd)), 'hung':bool(u.IsHungAppWindow(hwnd)),
                     'rect':[rect.left,rect.top,rect.right,rect.bottom]})
        return len(rows)<64
    u.EnumWindows(visit,0)
    main, popups, state = select_dialogs(rows, lambda hwnd: int(u.GetWindow(hwnd,4) or 0))
    deadline=time.monotonic()+2
    for row in popups[:MAX_DIALOGS]:
        children=[]
        @CB
        def child(hwnd,param):
            if time.monotonic()>deadline or len(children)>=48: return False
            if u.IsWindowVisible(hwnd):
                cls=C.create_unicode_buffer(256); u.GetClassNameW(hwnd,cls,len(cls))
                value=text(u,hwnd,True)
                if value: children.append({'hwnd':int(hwnd),'class':cls.value,'text':value,'enabled':bool(u.IsWindowEnabled(hwnd))})
            return True
        u.EnumChildWindows(row['hwnd'],child,0)
        row['controls']=children
    return {'ok':state != 'ambiguous_ae_instances','blocked':bool(popups),'state':state,'main':main,'dialogs':popups,'windows':rows,
            'captureGate':'AE main disabled and visible enabled same-process owned dialog',
            'classification':'unclassified; inspect screenshot/text, never auto-dismiss'}

class BitmapHeader(C.Structure):
    _fields_=[('size',W.DWORD),('width',W.LONG),('height',W.LONG),('planes',W.WORD),('bits',W.WORD),('compression',W.DWORD),('image_size',W.DWORD),('xppm',W.LONG),('yppm',W.LONG),('colors',W.DWORD),('important',W.DWORD)]

def print_window(expected,path):
    hwnd = expected["hwnd"]
    ui=enumerate_ui()
    eligible=ui['dialogs']
    row=next((r for r in eligible if r['hwnd']==hwnd),None)
    if not ui['blocked'] or not row or any(row[k] != expected[k] for k in ('hwnd','pid','owner','class')): return {'ok':False,'reason':'no_longer_blocked_or_window_changed'}
    if row['minimized'] or row['hung']: return {'ok':False,'reason':'window_minimized_or_unresponsive'}
    width=row['rect'][2]-row['rect'][0]; height=row['rect'][3]-row['rect'][1]
    if width*height>16_000_000: return {'ok':False,'reason':'window_exceeds_capture_budget'}
    u,g,k,CB=api(); dc=u.GetWindowDC(hwnd); mem=g.CreateCompatibleDC(dc); bmp=g.CreateCompatibleBitmap(dc,width,height)
    old=None
    try:
        if not dc or not mem or not bmp: raise OSError('GDI allocation failed')
        old=g.SelectObject(mem,bmp)
        success=u.PrintWindow(hwnd,mem,2)
        g.SelectObject(mem,old); old=None
        if not success: return {'ok':False,'reason':'PrintWindow_failed'}
        header=BitmapHeader(); header.size=C.sizeof(header); header.width=width; header.height=-height; header.planes=1; header.bits=32
        pixels=C.create_string_buffer(width*height*4)
        if g.GetDIBits(mem,bmp,0,height,pixels,C.byref(header),0)!=height: raise OSError('Incomplete bitmap')
        from PIL import Image,ImageStat
        image=Image.frombytes('RGB',(width,height),pixels.raw,'raw','BGRX')
        variance=sum(ImageStat.Stat(image.resize((64,64))).var)
        image.save(path)
        return {'ok':True,'path':str(path),'hwnd':hwnd,'pid':row['pid'],'title':row['title'],'width':width,'height':height,'method':'PrintWindow-full-window','suspectBlank':variance<1,'contentVerified':False}
    finally:
        if old: g.SelectObject(mem,old)
        if bmp: g.DeleteObject(bmp)
        if mem: g.DeleteDC(mem)
        if dc: u.ReleaseDC(hwnd,dc)

def worker(args,timeout):
    python=Path(sys.executable).with_name('python.exe')
    result=subprocess.run([str(python),str(Path(__file__).resolve()),*args],capture_output=True,text=True,encoding='utf-8',timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode: raise RuntimeError(result.stderr[-1500:])
    return json.loads(result.stdout)

def capture_blocked(output):
    """Only create images after a confirmed modal gate. At most 18s of workers."""
    if not IS_WINDOWS:
        return {'ok':False, 'state':'unsupported_platform', 'blocked':None, 'captures':[]}
    if not _CAPTURE_LOCK.acquire(blocking=False):
        return {'ok':False, 'state':'capture_busy', 'blocked':None, 'captures':[]}
    try:
        try:
            ui = worker(['enumerate'], WORKER_TIMEOUT)
        except (subprocess.TimeoutExpired, OSError, RuntimeError, ValueError) as exc:
            return {'ok':False, 'state':'inspection_failed', 'blocked':None,
                    'error':str(exc)[-1000:], 'captures':[]}
        ui['captures'] = []
        ui['dialogCount'] = len(ui['dialogs'])
        ui['truncated'] = len(ui['dialogs']) > MAX_DIALOGS
        ui['limitations'] = ('Only visible AE modal windows. Custom controls may have no readable text; '
                             'inspect images. Blank/partial GPU or locked-session captures are possible. '
                             'No automatic dismissal, desktop fallback, or project writes.')
        if not ui['blocked']:
            return ui
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        for row in ui['dialogs'][:MAX_DIALOGS]:
            path = output / ('ae-ui-' + uuid.uuid4().hex + '.png')
            identity = {k:row[k] for k in ('hwnd','pid','owner','class')}
            try:
                item = worker(['capture',json.dumps(identity),str(path)], WORKER_TIMEOUT)
                if item.get('suspectBlank'):
                    item.update(ok=False, reason='suspect_blank_capture')
            except (subprocess.TimeoutExpired, OSError, RuntimeError, ValueError) as exc:
                item = {'ok':False, 'reason':'capture_timeout' if isinstance(exc, subprocess.TimeoutExpired)
                        else 'capture_failed', 'error':str(exc)[-1000:]}
            item.setdefault('hwnd', row['hwnd'])
            item.setdefault('pid', row['pid'])
            if not item.get('ok'):
                path.unlink(missing_ok=True)
                item.pop('path', None)
            ui['captures'].append(item)
        ui['ok'] = all(c.get('ok') for c in ui['captures']) and not ui['truncated']
        ui['state'] = 'blocked' if ui['ok'] else 'blocked_capture_incomplete'
        return ui
    finally:
        _CAPTURE_LOCK.release()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    command = sys.argv[1]
    if command == 'enumerate':
        result = enumerate_ui()
    elif command == 'capture':
        result = print_window(json.loads(sys.argv[2]), Path(sys.argv[3]))
    else:
        raise ValueError('unknown worker mode')
    print(json.dumps(result, ensure_ascii=False))
