'use strict';
module.exports = function createNativeRuntime(koffi) {
    let sendInputClick, sendInputDrag, sendKeySequence, focusAEWindow, enumerateAEWindows, enumerateAETopWindows, dismissAEScriptDialogs, getAEWindowRect;
    const user32 = koffi.load('user32.dll');
    const kernel32 = koffi.load('kernel32.dll');
    const GetLastError = kernel32.func('uint32 GetLastError()');

    // INPUT union layout (Windows x64): size 40 bytes total.
    //   DWORD type             (4)
    //   <4 bytes pad>          (4)
    //   MOUSEINPUT mi          (32): LONG dx, LONG dy, DWORD mouseData, DWORD dwFlags,
    //                                DWORD time, ULONG_PTR dwExtraInfo
    // Skip koffi structs — Windows INPUT layout needs explicit padding that
    // koffi struct declarations are awkward about. Use raw 40-byte Buffers.
    const INPUT_SIZE = 40;
    const SendInput = user32.func('uint32 SendInput(uint32, _In_ void*, int32)');
    const GetSystemMetrics = user32.func('int32 GetSystemMetrics(int32)');
    const SetCursorPos = user32.func('int32 SetCursorPos(int32, int32)');
    const SetForegroundWindow = user32.func('int32 SetForegroundWindow(void*)');
    const ShowWindow = user32.func('int32 ShowWindow(void*, int32)');
    const BringWindowToTop = user32.func('int32 BringWindowToTop(void*)');
    const IsIconic = user32.func('int32 IsIconic(void*)');
    const GetClassNameA = user32.func('int32 GetClassNameA(void*, _Out_ char*, int32)');
    const GetWindowTextA = user32.func('int32 GetWindowTextA(void*, _Out_ char*, int32)');
    const GetWindowTextW = user32.func('int32 GetWindowTextW(void*, _Out_ uint16_t*, int32)');
    const GetWindowThreadProcessId = user32.func('uint32 GetWindowThreadProcessId(void*, _Out_ uint32*)');
    const PostMessageW = user32.func('int32 PostMessageW(void*, uint32, uint64, int64)');
    const RECT = koffi.struct('RECT', { left: 'int32', top: 'int32', right: 'int32', bottom: 'int32' });
    const GetWindowRect = user32.func('int32 GetWindowRect(void*, _Out_ RECT*)');
    const IsWindowVisible = user32.func('int32 IsWindowVisible(void*)');
    const EnumWindowsProc = koffi.proto('int32 EnumWindowsProc(void*, int64)');
    const EnumWindows = user32.func('int32 EnumWindows(EnumWindowsProc*, int64)');
    const EnumChildWindowsProc = koffi.proto('int32 EnumChildWindowsProc(void*, int64)');
    const EnumChildWindows = user32.func('int32 EnumChildWindows(void*, EnumChildWindowsProc*, int64)');
    const SW_RESTORE = 9;

    // Discover the AE main window by class prefix instead of maintaining
    // a version whitelist. This covers AE 27.0 and future AE releases.
    function findAEHwnd() {
        const matches = [];
        const cb = koffi.register(function (hwnd, lparam) {
            const classBuf = Buffer.alloc(256);
            const textBuf = Buffer.alloc(512);
            let cls = '';
            let text = '';
            try {
                const n = GetClassNameA(hwnd, classBuf, 255);
                cls = classBuf.toString('utf8', 0, Math.max(0, n));
            } catch (_) {}
            if (cls.indexOf('AE_CApplication') !== 0) return 1;
            try {
                const n = GetWindowTextA(hwnd, textBuf, 511);
                text = textBuf.toString('utf8', 0, Math.max(0, n));
            } catch (_) {}
            const rect = { left: 0, top: 0, right: 0, bottom: 0 };
            let area = 0;
            try {
                if (GetWindowRect(hwnd, rect)) {
                    area = Math.max(0, rect.right - rect.left) * Math.max(0, rect.bottom - rect.top);
                }
            } catch (_) {}
            matches.push({
                hwnd: hwnd,
                cls: cls,
                text: text,
                visible: IsWindowVisible(hwnd) !== 0,
                area: area
            });
            return 1;
        }, koffi.pointer(EnumWindowsProc));
        try {
            EnumWindows(cb, 0);
        } finally {
            koffi.unregister(cb);
        }
        matches.sort(function (a, b) {
            if (a.visible !== b.visible) return a.visible ? -1 : 1;
            return b.area - a.area;
        });
        return matches.length ? matches[0] : null;
    }

    function hwndString(hwnd) {
        try { return '0x' + koffi.address(hwnd).toString(16); }
        catch (_) { return '?'; }
    }

    function windowPid(hwnd) {
        const pidBuf = Buffer.alloc(4);
        GetWindowThreadProcessId(hwnd, pidBuf);
        return pidBuf.readUInt32LE(0);
    }

    function windowTextW(hwnd) {
        const textBuf = Buffer.alloc(4096);
        const n = GetWindowTextW(hwnd, textBuf, 2047);
        return n > 0 ? textBuf.toString('utf16le', 0, n * 2) : '';
    }

    enumerateAETopWindows = function () {
        const aeWindow = findAEHwnd();
        if (!aeWindow) return { error: 'AE window not found', discovery: 'EnumWindows:AE_CApplication*' };
        const aePid = windowPid(aeWindow.hwnd);
        const aeHwnd = hwndString(aeWindow.hwnd);
        const rows = [];
        const cb = koffi.register(function (hwnd, lparam) {
            if (windowPid(hwnd) !== aePid) return 1;
            const classBuf = Buffer.alloc(256);
            let cls = '';
            try {
                const n = GetClassNameA(hwnd, classBuf, 255);
                cls = classBuf.toString('utf8', 0, Math.max(0, n));
            } catch (_) {}
            const rect = { left: 0, top: 0, right: 0, bottom: 0 };
            try { GetWindowRect(hwnd, rect); } catch (_) {}
            rows.push({
                hwnd: hwndString(hwnd),
                cls: cls,
                text: windowTextW(hwnd),
                visible: IsWindowVisible(hwnd) !== 0,
                is_main: hwndString(hwnd) === aeHwnd,
                rect: {
                    left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom,
                    w: rect.right - rect.left, h: rect.bottom - rect.top
                }
            });
            return 1;
        }, koffi.pointer(EnumWindowsProc));
        try { EnumWindows(cb, 0); }
        finally { koffi.unregister(cb); }
        return { ae_pid: aePid, ae_hwnd: aeHwnd, count: rows.length, rows: rows };
    };

    dismissAEScriptDialogs = function (baselineHandles) {
        const aeWindow = findAEHwnd();
        if (!aeWindow) return { ok: false, error: 'AE window not found', found: 0, dismissed: 0, dialogs: [] };
        const aePid = windowPid(aeWindow.hwnd);
        const baseline = baselineHandles || {};
        const dialogs = [];
        const cb = koffi.register(function (hwnd, lparam) {
            if (windowPid(hwnd) !== aePid || IsWindowVisible(hwnd) === 0) return 1;
            const handle = hwndString(hwnd);
            if (baseline[handle]) return 1;
            const classBuf = Buffer.alloc(256);
            let cls = '';
            try {
                const n = GetClassNameA(hwnd, classBuf, 255);
                cls = classBuf.toString('utf8', 0, Math.max(0, n));
            } catch (_) {}
            if (cls !== '#32770') return 1;
            const rect = { left: 0, top: 0, right: 0, bottom: 0 };
            try { GetWindowRect(hwnd, rect); } catch (_) {}
            dialogs.push({
                hwnd: handle,
                cls: cls,
                text: windowTextW(hwnd),
                rect: {
                    left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom,
                    w: rect.right - rect.left, h: rect.bottom - rect.top
                },
                _hwnd: hwnd
            });
            return 1;
        }, koffi.pointer(EnumWindowsProc));
        try { EnumWindows(cb, 0); }
        finally { koffi.unregister(cb); }

        const WM_COMMAND = 0x0111, WM_KEYDOWN = 0x0100, WM_KEYUP = 0x0101;
        const IDOK = 1, VK_RETURN = 0x0D;
        let dismissed = 0;
        dialogs.forEach(function (row) {
            try {
                PostMessageW(row._hwnd, WM_COMMAND, IDOK, 0);
                PostMessageW(row._hwnd, WM_KEYDOWN, VK_RETURN, 0);
                PostMessageW(row._hwnd, WM_KEYUP, VK_RETURN, 0);
                dismissed += 1;
            } catch (err) { row.dismiss_error = String(err); }
            delete row._hwnd;
        });
        return { ok: true, found: dialogs.length, dismissed: dismissed, dialogs: dialogs };
    };

    // --- Enumerate every descendant HWND of AE main window with class/text/rect/visibility.
    enumerateAEWindows = function () {
        const aeWindow = findAEHwnd();
        if (!aeWindow) return { error: 'AE window not found', discovery: 'EnumWindows:AE_CApplication*' };
        const aeHwnd = aeWindow.hwnd;

        const rows = [];
        const classBuf = Buffer.alloc(256);
        const textBuf = Buffer.alloc(512);

        const cb = koffi.register(function (hwnd, lparam) {
            let row = { hwnd: '?' };
            try {
                row.hwnd = '0x' + koffi.address(hwnd).toString(16);
            } catch (_) {}
            try {
                classBuf.fill(0);
                const n = GetClassNameA(hwnd, classBuf, 255);
                row.cls = classBuf.toString('utf8', 0, Math.max(0, n));
            } catch (_) { row.cls = ''; }
            try {
                textBuf.fill(0);
                const n = GetWindowTextA(hwnd, textBuf, 511);
                row.text = textBuf.toString('utf8', 0, Math.max(0, n));
            } catch (_) { row.text = ''; }
            try { row.visible = IsWindowVisible(hwnd) !== 0; } catch (_) { row.visible = false; }
            try {
                const rectObj = { left: 0, top: 0, right: 0, bottom: 0 };
                if (GetWindowRect(hwnd, rectObj)) {
                    row.rect = { left: rectObj.left, top: rectObj.top, right: rectObj.right, bottom: rectObj.bottom, w: rectObj.right - rectObj.left, h: rectObj.bottom - rectObj.top };
                }
            } catch (_) {}
            rows.push(row);
            return 1;
        }, koffi.pointer(EnumChildWindowsProc));

        try {
            EnumChildWindows(aeHwnd, cb, 0);
        } finally {
            koffi.unregister(cb);
        }
        let aeHwndStr = '?';
        try { aeHwndStr = '0x' + koffi.address(aeHwnd).toString(16); } catch (_) {}
        return { ae_hwnd: aeHwndStr, ae_class: aeWindow.cls, count: rows.length, rows: rows };
    };

    const SM_CXSCREEN = 0, SM_CYSCREEN = 1;
    const SM_XVIRTUALSCREEN = 76, SM_YVIRTUALSCREEN = 77;
    const SM_CXVIRTUALSCREEN = 78, SM_CYVIRTUALSCREEN = 79;
    const INPUT_MOUSE = 0;
    const MOUSEEVENTF_MOVE = 0x0001;
    const MOUSEEVENTF_LEFTDOWN = 0x0002;
    const MOUSEEVENTF_LEFTUP = 0x0004;
    const MOUSEEVENTF_ABSOLUTE = 0x8000;
    const MOUSEEVENTF_VIRTUALDESK = 0x4000;

    // --- Keyboard SendInput (VK codes) ---
    const INPUT_KEYBOARD = 1;
    const KEYEVENTF_KEYUP = 0x0002;

    sendKeySequence = function (keys, opts) {
        // keys: array of { vk, up?:false }
        opts = opts || {};
        const betweenMs = opts.betweenMs != null ? opts.betweenMs : 15;

        function buildKey(vk, up) {
            const b = Buffer.alloc(INPUT_SIZE);
            b.writeUInt32LE(INPUT_KEYBOARD, 0);  // type
            // 4..7 pad
            b.writeUInt16LE(vk, 8);              // wVk
            b.writeUInt16LE(0, 10);              // wScan
            b.writeUInt32LE(up ? KEYEVENTF_KEYUP : 0, 12);  // dwFlags
            b.writeUInt32LE(0, 16);              // time
            // 20..27: dwExtraInfo (8 bytes) — leave 0
            // 28..39: trailing union padding
            return b;
        }

        function sendOne(vk, up) {
            const buf = buildKey(vk, up);
            const n = SendInput(1, buf, INPUT_SIZE);
            if (n !== 1) throw new Error('SendInput KEYBD returned ' + n + ' lastErr=' + GetLastError());
        }

        return new Promise(function (resolve, reject) {
            let i = 0;
            function step() {
                if (i >= keys.length) return resolve({ ok: true, keys: keys.length });
                try {
                    const k = keys[i++];
                    sendOne(k.vk, !!k.up);
                    setTimeout(step, betweenMs);
                } catch (e) { reject(e); }
            }
            step();
        });
    };

    // --- AE window focus ---
    focusAEWindow = function () {
        const r = findAEHwnd();
        if (!r) return { ok: false, error: 'ae_window_not_found', discovery: 'EnumWindows:AE_CApplication*' };
        const wasMin = IsIconic(r.hwnd) ? true : false;
        if (wasMin) ShowWindow(r.hwnd, SW_RESTORE);
        BringWindowToTop(r.hwnd);
        SetForegroundWindow(r.hwnd);
        return { ok: true, class: r.cls, was_minimized: wasMin };
    };
    getAEWindowRect = function () {
        const r = findAEHwnd();
        if (!r) return { error: 'ae_window_not_found', discovery: 'EnumWindows:AE_CApplication*' };
        const rc = { left: 0, top: 0, right: 0, bottom: 0 };
        const got = GetWindowRect(r.hwnd, rc);
        if (!got) return { error: 'GetWindowRect failed' };
        return {
            class: r.cls,
            left: rc.left, top: rc.top, right: rc.right, bottom: rc.bottom,
            width: rc.right - rc.left, height: rc.bottom - rc.top,
            center_x: Math.round((rc.left + rc.right) / 2),
            center_y: Math.round((rc.top + rc.bottom) / 2)
        };
    };

    const MOUSEEVENTF_MIDDLEDOWN = 0x0020;
    const MOUSEEVENTF_MIDDLEUP = 0x0040;

    // --- SendInput drag (multi-segment LEFTDOWN...MOVE...LEFTUP) ---
    sendInputDrag = function (fromX, fromY, toX, toY, opts) {
        opts = opts || {};
        const preHoldMs = opts.preHoldMs != null ? opts.preHoldMs : 60;
        const segMs = opts.segMs != null ? opts.segMs : 12;
        const segments = opts.segments != null ? Math.max(4, opts.segments) : 16;
        const postMs = opts.postMs != null ? opts.postMs : 60;
        const button = (opts.button === 'middle') ? 'middle' : 'left';
        const downFlag = button === 'middle' ? MOUSEEVENTF_MIDDLEDOWN : MOUSEEVENTF_LEFTDOWN;
        const upFlag = button === 'middle' ? MOUSEEVENTF_MIDDLEUP : MOUSEEVENTF_LEFTUP;

        function toAbs(px, py) {
            const vx = GetSystemMetrics(SM_XVIRTUALSCREEN);
            const vy = GetSystemMetrics(SM_YVIRTUALSCREEN);
            const vw = GetSystemMetrics(SM_CXVIRTUALSCREEN);
            const vh = GetSystemMetrics(SM_CYVIRTUALSCREEN);
            return [
                Math.round(((px - vx) * 65535) / Math.max(1, vw - 1)),
                Math.round(((py - vy) * 65535) / Math.max(1, vh - 1))
            ];
        }

        function buildMouseAt(ax, ay, flags) {
            const b = Buffer.alloc(INPUT_SIZE);
            b.writeUInt32LE(INPUT_MOUSE, 0);
            b.writeInt32LE(ax, 8);
            b.writeInt32LE(ay, 12);
            b.writeUInt32LE(0, 16);
            b.writeUInt32LE(flags | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 20);
            return b;
        }

        function fire(ax, ay, flags) {
            const buf = buildMouseAt(ax, ay, flags);
            const n = SendInput(1, buf, INPUT_SIZE);
            if (n !== 1) throw new Error('SendInput DRAG ' + flags.toString(16) + ' returned ' + n + ' lastErr=' + GetLastError());
        }

        return new Promise(function (resolve, reject) {
            try {
                SetCursorPos(fromX, fromY);
                const [ax0, ay0] = toAbs(fromX, fromY);
                fire(ax0, ay0, MOUSEEVENTF_MOVE);
                fire(ax0, ay0, downFlag);

                let step = 0;
                function stepFn() {
                    step += 1;
                    const t = step / segments;
                    const x = Math.round(fromX + (toX - fromX) * t);
                    const y = Math.round(fromY + (toY - fromY) * t);
                    const [ax, ay] = toAbs(x, y);
                    try {
                        fire(ax, ay, MOUSEEVENTF_MOVE);
                    } catch (e) { reject(e); return; }
                    if (step < segments) {
                        setTimeout(stepFn, segMs);
                    } else {
                        setTimeout(function () {
                            try {
                                fire(ax, ay, upFlag);
                                setTimeout(function () {
                                    resolve({ ok: true, from: [fromX, fromY], to: [toX, toY], segments: segments });
                                }, postMs);
                            } catch (e) { reject(e); }
                        }, segMs);
                    }
                }
                setTimeout(stepFn, preHoldMs);
            } catch (e) { reject(e); }
        });
    };

    sendInputClick = function (screenX, screenY, opts) {
        opts = opts || {};
        const preMoveMs = opts.preMoveMs != null ? opts.preMoveMs : 30;
        const holdMs = opts.holdMs != null ? opts.holdMs : 40;

        // Cursor to approximate target first (helps multi-monitor absolute calc)
        SetCursorPos(screenX, screenY);

        // ABSOLUTE+VIRTUALDESK: coords 0..65535 over the entire virtual desktop
        // (all monitors combined). Single-monitor SM_CXSCREEN would mis-map
        // clicks to the primary screen when AE is on a secondary monitor.
        const vx = GetSystemMetrics(SM_XVIRTUALSCREEN);
        const vy = GetSystemMetrics(SM_YVIRTUALSCREEN);
        const vw = GetSystemMetrics(SM_CXVIRTUALSCREEN);
        const vh = GetSystemMetrics(SM_CYVIRTUALSCREEN);
        const ax = Math.round(((screenX - vx) * 65535) / Math.max(1, vw - 1));
        const ay = Math.round(((screenY - vy) * 65535) / Math.max(1, vh - 1));

        function buildMouse(flags) {
            const b = Buffer.alloc(INPUT_SIZE);
            b.writeUInt32LE(INPUT_MOUSE, 0);  // type
            // 4..7 pad
            b.writeInt32LE(ax, 8);            // dx
            b.writeInt32LE(ay, 12);           // dy
            b.writeUInt32LE(0, 16);           // mouseData
            b.writeUInt32LE(flags | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 20);  // dwFlags
            b.writeUInt32LE(0, 24);           // time
            // 28..31 pad, 32..39 dwExtraInfo (leave 0)
            return b;
        }

        function sendOne(flags) {
            const buf = buildMouse(flags);
            const n = SendInput(1, buf, INPUT_SIZE);
            if (n !== 1) throw new Error('SendInput MOUSE returned ' + n + ' lastErr=' + GetLastError());
        }

        return new Promise(function (resolve, reject) {
            try {
                sendOne(MOUSEEVENTF_MOVE);
                setTimeout(function () {
                    try {
                        sendOne(MOUSEEVENTF_LEFTDOWN);
                        setTimeout(function () {
                            try {
                                sendOne(MOUSEEVENTF_LEFTUP);
                                resolve({ ok: true, screen: [screenX, screenY], abs: [ax, ay] });
                            } catch (e) { reject(e); }
                        }, holdMs);
                    } catch (e) { reject(e); }
                }, preMoveMs);
            } catch (e) { reject(e); }
        });
    };

    return { sendInputClick, sendInputDrag, sendKeySequence, focusAEWindow, enumerateAEWindows, enumerateAETopWindows, dismissAEScriptDialogs, getAEWindowRect };
};
