/* AE2Claude PinClicker — CEP extension main
 * Exposes HTTP on 127.0.0.1:8891:
 *   GET  /health                       -> {ok, port, ae_version}
 *   POST /eval        {code}           -> {result}
 *   GET  /viewer-state                 -> {comp_name, zoom, panel_rect, view_center_screen, comp_to_screen}
 *   POST /click-screen {x, y, [delay_ms]} -> {ok}
 *   POST /place-pin   {layer_index, comp_x, comp_y, retry, inset_px, comp_name}
 *                                      -> {placed, pin_index, attempts, actual_comp}
 *   POST /begin-session {layer_index}  -> snapshot of active comp / layer / time / tool
 *   POST /end-session                  -> restore snapshot
 *
 * All JSX work goes through CSInterface.evalScript. Click uses koffi + user32 SendInput.
 */

(function () {
    'use strict';

    const PORT = 8891;

    const cs = new CSInterface();
    const logEl = document.getElementById('log');
    const statusEl = document.getElementById('status');
    const endpointEl = document.getElementById('endpoint');
    const reqCountEl = document.getElementById('reqcount');
    const errCountEl = document.getElementById('errcount');

    let reqCount = 0;
    let errCount = 0;

    // Log ring-buffer kept in memory so /logs can expose it regardless of panel visibility.
    const logBuffer = [];
    const LOG_BUFFER_MAX = 400;
    let logFilePath = null;

    function log(msg) {
        const line = new Date().toISOString().substr(11, 12) + ' ' + msg;
        logBuffer.push(line);
        if (logBuffer.length > LOG_BUFFER_MAX) logBuffer.shift();
        if (logEl) {
            logEl.textContent = line + '\n' + logEl.textContent;
            if (logEl.textContent.length > 20000) {
                logEl.textContent = logEl.textContent.substring(0, 15000);
            }
        }
        try { console.log(line); } catch (_) {}
        if (logFilePath && fs) {
            try { fs.appendFile(logFilePath, line + '\n', function(){}); } catch (_) {}
        }
    }

    function setStatus(text, cls) {
        if (!statusEl) return;
        statusEl.textContent = text;
        statusEl.className = cls || '';
    }

    function bumpReq() { reqCount += 1; if (reqCountEl) reqCountEl.textContent = reqCount; }
    function bumpErr() { errCount += 1; if (errCountEl) errCountEl.textContent = errCount; }

    // --- Node.js loading -----------------------------------------------------
    let http, url, path, fs;
    let extensionVersion = 'unknown';
    try {
        http = cep_node.require('http');
        url = cep_node.require('url');
        path = cep_node.require('path');
        fs = cep_node.require('fs');
    } catch (err) {
        setStatus('cep_node missing', 'status-err');
        log('FATAL: cep_node.require failed: ' + err.message);
        return;
    }

    try {
        const packagePath = path.join(cs.getSystemPath(SystemPath.EXTENSION), 'package.json');
        extensionVersion = JSON.parse(fs.readFileSync(packagePath, 'utf8')).version || 'unknown';
    } catch (err) {
        log('package version read failed: ' + err.message);
    }

    try {
        const extRoot = cs.getSystemPath(SystemPath.EXTENSION);
        const logDir = path.join(extRoot, 'logs');
        try { fs.mkdirSync(logDir, { recursive: true }); } catch (_) {}
        logFilePath = path.join(logDir, 'cep.log');
        fs.appendFileSync(logFilePath, '\n=== boot ' + new Date().toISOString() + ' pid=' + (process && process.pid) + ' ===\n');
    } catch (err) {
        try { console.warn('log file init failed: ' + err.message); } catch (_) {}
    }

    // --- Mouse click via koffi + SendInput -----------------------------------
    // Loaded lazily so HTTP can still answer /health even if koffi fails.
    let sendInputClick = null;
    let sendInputDrag = null;
    let sendKeySequence = null;
    let focusAEWindow = null;
    let enumerateAEWindows = null;
    let getAEWindowRect = null;
    let mouseLoadError = null;

    function initMouse() {
        if (sendInputClick || mouseLoadError) return;
        try {
            const extRoot = cs.getSystemPath(SystemPath.EXTENSION);
            const koffiPath = cep_node.require('path').join(extRoot, 'node_modules', 'koffi');
            const koffi = cep_node.require(koffiPath);
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
            log('mouse: koffi SendInput loaded');
        } catch (err) {
            mouseLoadError = err.message || String(err);
            log('mouse: koffi load FAILED: ' + mouseLoadError);
        }
    }

    // --- JSX helpers ---------------------------------------------------------
    function evalJSX(code) {
        return new Promise(function (resolve) {
            cs.evalScript(code, function (result) { resolve(result); });
        });
    }

    async function evalJSXJson(code) {
        const wrapped = '(function(){try{var __r=(function(){' + code + '\n})();return typeof __r==="string"?__r:JSON.stringify(__r);}catch(e){return JSON.stringify({__jsx_error:String(e)});}})();';
        const raw = await evalJSX(wrapped);
        if (raw == null || raw === 'undefined') return null;
        try { return JSON.parse(raw); } catch (_) { return raw; }
    }

    async function aeVersion() {
        try {
            const r = await evalJSXJson('return { version: app.version, build: app.buildName };');
            return r || { version: 'unknown' };
        } catch (_) { return { version: 'unknown' }; }
    }

    // --- HTTP routing --------------------------------------------------------
    function readBody(req) {
        return new Promise(function (resolve, reject) {
            const chunks = [];
            req.on('data', function (c) { chunks.push(c); });
            req.on('end', function () {
                try {
                    const raw = Buffer.concat(chunks).toString('utf8');
                    resolve(raw.length ? JSON.parse(raw) : {});
                } catch (e) { reject(e); }
            });
            req.on('error', reject);
        });
    }

    function sendJson(res, status, body) {
        res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
        res.end(JSON.stringify(body));
    }

    // Session snapshot state
    let session = null;

    async function handleHealth() {
        const v = await aeVersion();
        const windowInfo = getAEWindowRect ? getAEWindowRect() : { error: 'window_runtime_unavailable' };
        return {
            ok: true,
            port: PORT,
            extension_version: extensionVersion,
            ae: v,
            window: windowInfo,
            mouse_ready: !!sendInputClick,
            keyboard_ready: !!sendKeySequence,
            focus_ready: !!focusAEWindow,
            mouse_error: mouseLoadError,
            session_active: !!session
        };
    }

    async function handleEval(body) {
        const code = body && body.code;
        if (typeof code !== 'string' || !code.length) throw new Error('missing code');
        const r = await evalJSXJson(code);
        return { result: r };
    }

    async function handleViewerState() {
        // Read AE viewer rect + zoom directly via ExtendScript.
        // activeViewer.views[0].options exposes zoom (float).
        const code = [
            'var v=app.activeViewer;',
            'if(!v) return {error:"no_active_viewer"};',
            'var ai=app.project ? app.project.activeItem : null;',
            'var comp_info=null;',
            'if(ai && (ai instanceof CompItem)){',
            '  comp_info={name:ai.name,id:ai.id,width:ai.width,height:ai.height,time:ai.time};',
            '}',
            'var view=null;',
            'try{',
            '  var view0=v.views && v.views.length ? v.views[0] : null;',
            '  if(view0){',
            '    var opts=view0.options;',
            '    view={zoom:opts ? Number(opts.zoom) : null,',
            '          channels:opts ? String(opts.channels) : null,',
            '          resolution:opts ? String(opts.fastPreview) : null};',
            '  }',
            '}catch(eView){view={error:String(eView)};}',
            'return {comp:comp_info,view:view,viewer_type:String(v.type)};'
        ].join('');
        return await evalJSXJson(code);
    }

    async function handleClickScreen(body) {
        initMouse();
        if (!sendInputClick) throw new Error('mouse_unavailable:' + mouseLoadError);
        const x = body && Number(body.x);
        const y = body && Number(body.y);
        if (!Number.isFinite(x) || !Number.isFinite(y)) throw new Error('bad_xy');
        const opts = {};
        if (body && body.pre_move_ms != null) opts.preMoveMs = Number(body.pre_move_ms);
        if (body && body.hold_ms != null) opts.holdMs = Number(body.hold_ms);
        const r = await sendInputClick(x, y, opts);
        return r;
    }

    // Windows Virtual Key subset we need.
    const VK = {
        CTRL: 0x11, SHIFT: 0x10, ALT: 0x12,
        A:0x41,B:0x42,C:0x43,D:0x44,E:0x45,F:0x46,G:0x47,H:0x48,I:0x49,J:0x4A,K:0x4B,L:0x4C,
        M:0x4D,N:0x4E,O:0x4F,P:0x50,Q:0x51,R:0x52,S:0x53,T:0x54,U:0x55,V:0x56,W:0x57,X:0x58,
        Y:0x59,Z:0x5A,
        ESC:0x1B, ENTER:0x0D, SPACE:0x20, TAB:0x09,
        // OEM symbol keys on a US layout
        SLASH: 0xBF,    // / and ?
        PERIOD: 0xBE,   // . and >
        COMMA: 0xBC,    // , and <
        SEMICOLON: 0xBA,// ; and :
        QUOTE: 0xDE,    // ' and "
        LBRACKET: 0xDB, // [ and {
        RBRACKET: 0xDD, // ] and }
        MINUS: 0xBD,    // - and _
        EQUALS: 0xBB,   // = and +
        BACKSLASH: 0xDC,// \ and |
        BACKTICK: 0xC0, // ` and ~
        F1: 0x70, F2: 0x71, F3: 0x72, F4: 0x73, F5: 0x74, F6: 0x75,
        F7: 0x76, F8: 0x77, F9: 0x78, F10: 0x79, F11: 0x7A, F12: 0x7B
    };

    function parseCombo(text) {
        // "Ctrl+P" -> [{vk:CTRL},{vk:P},{vk:P,up},{vk:CTRL,up}]
        const parts = String(text).split('+').map(s => s.trim().toUpperCase());
        const vks = parts.map(p => {
            const v = VK[p];
            if (v == null) throw new Error('unknown_key:' + p);
            return v;
        });
        const downs = vks.map(v => ({ vk: v }));
        const ups = vks.slice().reverse().map(v => ({ vk: v, up: true }));
        return downs.concat(ups);
    }

    async function handleSetTool(body) {
        initMouse();
        if (!sendKeySequence) throw new Error('keyboard_unavailable:' + mouseLoadError);
        if (!focusAEWindow) throw new Error('focus_unavailable');

        const combo = body && body.hotkey ? String(body.hotkey) : 'Ctrl+P';
        const expect = body && body.expect_tool ? String(body.expect_tool) : null;
        const preFocus = body && body.pre_focus !== false;

        if (preFocus) focusAEWindow();
        await new Promise(r => setTimeout(r, 80));
        // If viewer is not active, ExtendScript ensures it.
        await evalJSXJson('try{app.activeViewer.setActive();}catch(_){} return {tool_before:app.toolName};');
        await new Promise(r => setTimeout(r, 30));

        let seq;
        try { seq = parseCombo(combo); }
        catch (e) { throw new Error('bad_hotkey:' + e.message); }
        await sendKeySequence(seq, { betweenMs: 20 });

        // Wait a beat for AE to actually commit the tool switch.
        await new Promise(r => setTimeout(r, 120));
        const after = await evalJSXJson('return { tool: app.toolName };');
        const ok = expect ? (after && after.tool === expect) : true;
        return { ok: ok, tool: after && after.tool, expected: expect, combo: combo };
    }

    async function handlePressKey(body) {
        initMouse();
        if (!sendKeySequence) throw new Error('keyboard_unavailable:' + mouseLoadError);
        if (!body || !body.hotkey) throw new Error('missing_hotkey');
        const preFocus = body.pre_focus !== false;
        if (preFocus && focusAEWindow) { focusAEWindow(); await new Promise(r => setTimeout(r, 60)); }
        const seq = parseCombo(String(body.hotkey));
        await sendKeySequence(seq, { betweenMs: body.between_ms != null ? Number(body.between_ms) : 20 });
        return { ok: true, sent: body.hotkey };
    }

    async function handleDrag(body) {
        initMouse();
        if (!sendInputDrag) throw new Error('drag_unavailable:' + mouseLoadError);
        if (!body || body.from_x == null || body.from_y == null || body.to_x == null || body.to_y == null) {
            throw new Error('missing from_x/from_y/to_x/to_y');
        }
        return await sendInputDrag(
            Number(body.from_x), Number(body.from_y),
            Number(body.to_x), Number(body.to_y),
            {
                preHoldMs: body.pre_hold_ms != null ? Number(body.pre_hold_ms) : undefined,
                segMs: body.seg_ms != null ? Number(body.seg_ms) : undefined,
                segments: body.segments != null ? Number(body.segments) : undefined,
                postMs: body.post_ms != null ? Number(body.post_ms) : undefined,
            }
        );
    }

    // Middle-button drag pan. AE always treats middle-drag as Pan regardless
    // of the active tool, so the user's Puppet sub-tool stays on 位置控点.
    async function handleViewerPanMiddle(body) {
        initMouse();
        if (!sendInputDrag || !focusAEWindow)
            throw new Error('pan_middle_unavailable:' + mouseLoadError);
        const dx = Number(body && body.dx);
        const dy = Number(body && body.dy);
        if (!Number.isFinite(dx) || !Number.isFinite(dy)) throw new Error('bad_dx_dy');
        const ae = getAEWindowRect();
        const fromX = body.from_x != null ? Number(body.from_x) : ae.center_x;
        const fromY = body.from_y != null ? Number(body.from_y) : ae.center_y;
        focusAEWindow();
        await new Promise(r => setTimeout(r, 80));
        const r = await sendInputDrag(fromX, fromY, fromX + dx, fromY + dy, {
            button: 'middle', preHoldMs: 60, segMs: 10, segments: 18, postMs: 60,
        });
        return { ok: true, mode: 'middle-drag', drag: r };
    }

    // SPACE-held pan. AE's Space-hold = temporary Hand Tool — release Space
    // and AE reverts to whatever tool was active before. This lets us pan
    // the Composition viewer without switching the Puppet sub-tool away from
    // 位置控点.
    async function handleViewerPanSpace(body) {
        initMouse();
        if (!sendInputDrag || !sendKeySequence || !focusAEWindow)
            throw new Error('pan_space_unavailable:' + mouseLoadError);
        const dx = Number(body && body.dx);
        const dy = Number(body && body.dy);
        if (!Number.isFinite(dx) || !Number.isFinite(dy)) throw new Error('bad_dx_dy');

        const ae = getAEWindowRect();
        const fromX = body.from_x != null ? Number(body.from_x) : ae.center_x;
        const fromY = body.from_y != null ? Number(body.from_y) : ae.center_y;
        const toX = fromX + dx;
        const toY = fromY + dy;

        focusAEWindow();
        await new Promise(r => setTimeout(r, 80));
        // Warm-up click so the viewer has keyboard focus; Space has to reach AE.
        await sendInputClick(fromX, fromY, { preMoveMs: 20, holdMs: 20 });
        await new Promise(r => setTimeout(r, 150));

        // SPACE DOWN (VK_SPACE = 0x20)
        await sendKeySequence([{ vk: 0x20 }], { betweenMs: 0 });
        await new Promise(r => setTimeout(r, 120));

        let dragRes;
        try {
            dragRes = await sendInputDrag(fromX, fromY, toX, toY, {
                preHoldMs: 80, segMs: 10, segments: 20, postMs: 80,
            });
        } finally {
            // SPACE UP — always, so we never leave AE stuck in pan mode.
            await sendKeySequence([{ vk: 0x20, up: true }], { betweenMs: 0 });
            await new Promise(r => setTimeout(r, 60));
        }

        return { ok: true, mode: 'space+drag', drag: dragRes, from: [fromX, fromY], to: [toX, toY] };
    }

    // High-level: switch to Hand Tool, drag viewer by (dx, dy) screen pixels,
    // then (optionally) switch back. Panning in AE = Hand Tool drag.
    async function handleViewerPan(body) {
        initMouse();
        if (!sendInputDrag || !sendKeySequence || !focusAEWindow)
            throw new Error('pan_unavailable:' + mouseLoadError);
        const dx = Number(body && body.dx);
        const dy = Number(body && body.dy);
        if (!Number.isFinite(dx) || !Number.isFinite(dy)) throw new Error('bad_dx_dy');

        // Need a (from_x, from_y) inside the Composition viewer panel so that
        // the drag is interpreted by the viewer, not some other panel.
        const ae = getAEWindowRect();
        const fromX = body.from_x != null ? Number(body.from_x) : ae.center_x;
        const fromY = body.from_y != null ? Number(body.from_y) : ae.center_y;
        const toX = fromX + dx;
        const toY = fromY + dy;

        focusAEWindow();
        await new Promise(r => setTimeout(r, 80));
        // Click the viewer first to give it keyboard focus before hotkeys.
        // Tiny move-only click pattern, no LEFTDOWN/UP.
        await sendInputClick(fromX, fromY, { preMoveMs: 20, holdMs: 20 });
        await new Promise(r => setTimeout(r, 120));

        // Press H (Hand Tool)
        await sendKeySequence([{ vk: 0x48 }, { vk: 0x48, up: true }], { betweenMs: 20 });
        await new Promise(r => setTimeout(r, 180));

        const dragRes = await sendInputDrag(fromX, fromY, toX, toY, {
            preHoldMs: 80, segMs: 10, segments: 20, postMs: 80,
        });

        return { ok: true, drag: dragRes, from: [fromX, fromY], to: [toX, toY] };
    }

    async function handleFocusAE() {
        initMouse();
        if (!focusAEWindow) throw new Error('focus_unavailable:' + mouseLoadError);
        return focusAEWindow();
    }

    async function handleEnumAE() {
        initMouse();
        if (!enumerateAEWindows) throw new Error('enum_unavailable:' + mouseLoadError);
        return enumerateAEWindows();
    }

    async function handleAERect() {
        initMouse();
        if (!getAEWindowRect) throw new Error('ae_rect_unavailable:' + mouseLoadError);
        const r = getAEWindowRect();
        if (r && !r.error) {
            r.virtual_desktop = {
                x: 0,
                y: 0  // placeholder; actual virtual origin is added by /viewer-state if needed
            };
        }
        return r;
    }

    async function handleEnsureViewer(body) {
        const compName = body && typeof body.comp_name === 'string' ? body.comp_name.replace(/\"/g, '\\"') : null;
        const compId = body && body.comp_id != null ? Number(body.comp_id) : null;
        const layerIndex = body && body.layer_index != null ? Number(body.layer_index) : null;

        const code = [
            'var target_comp=null;',
            'if(' + (compId != null ? 1 : 0) + '){',
            '  for(var i=1;i<=app.project.numItems;i++){var it=app.project.item(i); if(it.id==' + (compId || 0) + '){target_comp=it;break;}}',
            '}',
            'if(!target_comp && ' + (compName ? 1 : 0) + '){',
            '  for(var i2=1;i2<=app.project.numItems;i2++){var it2=app.project.item(i2); if(it2 instanceof CompItem && it2.name=="' + (compName || '') + '"){target_comp=it2;break;}}',
            '}',
            'if(target_comp){target_comp.openInViewer();}',
            'var ai=app.project.activeItem;',
            'if(!ai || !(ai instanceof CompItem)) return {error:"no_active_comp",active:(ai?ai.name:null)};',
            'try{app.activeViewer.setActive();}catch(_a){}',
            'var layer=null;',
            'if(' + (layerIndex != null ? 1 : 0) + '){',
            '  if(' + (layerIndex || 0) + '>=1 && ' + (layerIndex || 0) + '<=ai.numLayers){layer=ai.layer(' + (layerIndex || 0) + ');}',
            '}',
            'var sel_info=null;',
            'if(layer){',
            '  for(var k=1;k<=ai.numLayers;k++){ai.layer(k).selected=(ai.layer(k)==layer);}',
            '  sel_info={index:layer.index,name:layer.name,enabled:layer.enabled,solo:layer.solo};',
            '}',
            'return {ok:true,comp:{id:ai.id,name:ai.name,width:ai.width,height:ai.height,time:ai.time},layer:sel_info,tool:app.toolName};'
        ].join('');
        return await evalJSXJson(code);
    }

    // --- Puppet pin count reader -----------------------------------------
    // Reads PosPins + HghtPins + StarchPins and returns per-group + total
    // counts. pin_count is the sum so that /place-pin can detect a landing
    // regardless of which Puppet sub-tool (Position/Starch/Bend/Advanced/
    // Overlap) Ctrl+P happened to be cycled into.
    async function readPuppetPinCount(compId, layerIndex) {
        const code = [
            'var target=null;',
            'for(var i=1;i<=app.project.numItems;i++){var it=app.project.item(i); if(it.id==' + compId + '){target=it;break;}}',
            'if(!target) return {error:"comp_not_found"};',
            'if(' + layerIndex + '<1 || ' + layerIndex + '>target.numLayers) return {error:"layer_index_out_of_range"};',
            'var layer=target.layer(' + layerIndex + ');',
            'var effects=null;',
            'try{effects=layer.property("ADBE Effect Parade");}catch(_1){}',
            'if(!effects) return {pin_count:0,has_effect:false,has_mesh:false};',
            'var fx=null;',
            'try{fx=effects.property("ADBE FreePin3");}catch(_2){}',
            'if(!fx) return {pin_count:0,has_effect:false,has_mesh:false};',
            'var arap=fx.property("ADBE FreePin3 ARAP Group");',
            'if(!arap) return {pin_count:0,has_effect:true,has_mesh:false};',
            'var mg=arap.property("ADBE FreePin3 Mesh Group");',
            'if(!mg || mg.numProperties<1) return {pin_count:0,has_effect:true,has_mesh:false};',
            'var mesh=mg.property(1);',
            'var posPins=mesh.property("ADBE FreePin3 PosPins");',
            'var hghtPins=null; try{hghtPins=mesh.property("ADBE FreePin3 HghtPins");}catch(_h){}',
            'var starchPins=null; try{starchPins=mesh.property("ADBE FreePin3 StarchPins");}catch(_s){}',
            'var nPos=posPins?posPins.numProperties:0;',
            'var nHght=hghtPins?hghtPins.numProperties:0;',
            'var nStarch=starchPins?starchPins.numProperties:0;',
            'var flags=[];',
            'for(var p=1;p<=nPos;p++){',
            '  var pp=posPins.property(p);',
            '  try{',
            '    var vtx=pp.property("ADBE FreePin3 PosPin Vtx Index"); var vtxV=vtx ? vtx.value : null;',
            '    var typ=pp.property("ADBE FreePin3 PosPin Type"); var typV=typ ? typ.value : null;',
            '    flags.push({index:p,name:pp.name,vtx_index:vtxV,type:typV,group:"PosPins"});',
            '  }catch(_p){flags.push({index:p,name:pp.name,err:String(_p),group:"PosPins"});}',
            '}',
            'return {',
            '  pin_count:nPos+nHght+nStarch,',
            '  pos_count:nPos,',
            '  hght_count:nHght,',
            '  starch_count:nStarch,',
            '  has_effect:true,has_mesh:true,',
            '  mesh_tri_count:(mesh.property("ADBE FreePin3 Mesh Tri Count")?mesh.property("ADBE FreePin3 Mesh Tri Count").value:null),',
            '  pins:flags',
            '};'
        ].join('');
        return await evalJSXJson(code);
    }

    // --- /place-pin atomic -----------------------------------------------
    // { comp_id, layer_index, screen_x, screen_y, retries=3, inset_px=3,
    //   inset_dir=[dx,dy], poll_ms=150, poll_timeout_ms=2500,
    //   pre_focus=true, pre_click_ms=40, hold_ms=40 }
    async function handlePlacePin(body) {
        if (!body) throw new Error('missing_body');
        initMouse();
        if (!sendInputClick) throw new Error('mouse_unavailable:' + mouseLoadError);

        const compId = Number(body.comp_id);
        const layerIndex = Number(body.layer_index);
        if (!compId || !layerIndex) throw new Error('missing_comp_id_or_layer_index');
        const sx0 = Number(body.screen_x), sy0 = Number(body.screen_y);
        if (!Number.isFinite(sx0) || !Number.isFinite(sy0)) throw new Error('bad_screen_xy');

        const retries = body.retries != null ? Math.max(0, Number(body.retries)) : 3;
        const insetPx = body.inset_px != null ? Math.max(0, Number(body.inset_px)) : 3;
        const insetDir = Array.isArray(body.inset_dir) && body.inset_dir.length === 2
            ? [Number(body.inset_dir[0]), Number(body.inset_dir[1])]
            : [0, 0];
        const dirLen = Math.hypot(insetDir[0], insetDir[1]) || 1;
        const stepX = (insetDir[0] / dirLen) * insetPx;
        const stepY = (insetDir[1] / dirLen) * insetPx;

        const pollMs = body.poll_ms != null ? Math.max(50, Number(body.poll_ms)) : 150;
        const pollTimeoutMs = body.poll_timeout_ms != null ? Math.max(500, Number(body.poll_timeout_ms)) : 2500;
        const preClickMs = body.pre_click_ms != null ? Number(body.pre_click_ms) : 40;
        const holdMs = body.hold_ms != null ? Number(body.hold_ms) : 40;
        const preFocus = body.pre_focus !== false;

        const before = await readPuppetPinCount(compId, layerIndex);
        if (before && before.error) return { placed: false, reason: before.error };
        const beforeCount = Number(before.pin_count || 0);

        if (preFocus && focusAEWindow) focusAEWindow();
        // Short delay so the AE main window has foreground before we inject the click.
        await new Promise(r => setTimeout(r, 80));

        const attempts = [];
        for (let attempt = 0; attempt <= retries; attempt++) {
            const sx = Math.round(sx0 + stepX * attempt);
            const sy = Math.round(sy0 + stepY * attempt);
            const clickRes = await sendInputClick(sx, sy, { preMoveMs: preClickMs, holdMs: holdMs });
            const deadline = Date.now() + pollTimeoutMs;
            let after = null;
            while (Date.now() < deadline) {
                await new Promise(r => setTimeout(r, pollMs));
                after = await readPuppetPinCount(compId, layerIndex);
                if (after && Number(after.pin_count || 0) > beforeCount) break;
            }
            const afterCount = after ? Number(after.pin_count || 0) : beforeCount;
            const posDelta = (after ? Number(after.pos_count || 0) : 0) - (before ? Number(before.pos_count || 0) : 0);
            const hghtDelta = (after ? Number(after.hght_count || 0) : 0) - (before ? Number(before.hght_count || 0) : 0);
            const starchDelta = (after ? Number(after.starch_count || 0) : 0) - (before ? Number(before.starch_count || 0) : 0);
            attempts.push({ attempt: attempt, screen: [sx, sy], after_count: afterCount, pos_delta: posDelta, hght_delta: hghtDelta, starch_delta: starchDelta, click: clickRes });
            if (afterCount > beforeCount) {
                const newPin = after && after.pins ? after.pins[after.pins.length - 1] : null;
                const pinGroup = posDelta > 0 ? 'PosPins' : (hghtDelta > 0 ? 'HghtPins' : (starchDelta > 0 ? 'StarchPins' : 'unknown'));
                // Force PosPin Type = 1 only when the new pin actually lives in
                // PosPins. Hght/Starch pins are separate property groups; caller
                // must retry after Ctrl+P rotation to land in PosPins.
                const forceType = body.force_type === false ? false : (body.force_type != null ? Number(body.force_type) : 1);
                let typeResult = null;
                if (forceType && pinGroup === 'PosPins') {
                    const coerceCode = (
                        'var t=null;for(var i=1;i<=app.project.numItems;i++){var it=app.project.item(i); if(it.id==' + compId + '){t=it;break;}}'
                        + 'if(!t) return {err:"no_comp"};'
                        + 'var layer=t.layer(' + layerIndex + ');'
                        + 'var pins=layer.property("ADBE Effect Parade").property("ADBE FreePin3").property("ADBE FreePin3 ARAP Group").property("ADBE FreePin3 Mesh Group").property(1).property("ADBE FreePin3 PosPins");'
                        + 'var pp=pins.property(1);'
                        + 'var tp=pp.property("ADBE FreePin3 PosPin Type");'
                        + 'var before=tp.value; var err=null; try{tp.setValue(' + forceType + ');}catch(e){err=String(e);}'
                        + 'return {before:before,after:tp.value,error:err};'
                    );
                    try { typeResult = await evalJSXJson(coerceCode); } catch (e) { typeResult = { error: String(e) }; }
                }
                return {
                    placed: true,
                    attempts: attempts.length,
                    pin_index: afterCount,
                    before_count: beforeCount,
                    after_count: afterCount,
                    new_pin: newPin,
                    pin_group: pinGroup,
                    pos_delta: posDelta,
                    hght_delta: hghtDelta,
                    starch_delta: starchDelta,
                    type_coerce: typeResult,
                    tries: attempts
                };
            }
        }
        return { placed: false, attempts: attempts.length, before_count: beforeCount, tries: attempts };
    }

    async function handleBeginSession(body) {
        const code = [
            'var snap={};',
            'snap.ts=new Date().getTime();',
            'snap.active_item_id=app.project && app.project.activeItem ? app.project.activeItem.id : null;',
            'snap.tool=app.toolName || null;',
            'try{',
            '  var ai=app.project ? app.project.activeItem : null;',
            '  if(ai && ai instanceof CompItem){',
            '    snap.comp_time=ai.time;',
            '    var sel=[];',
            '    for(var i=0;i<ai.selectedLayers.length;i++){sel.push(ai.selectedLayers[i].index);}',
            '    snap.selected_layer_indexes=sel;',
            '    var solo=[];',
            '    for(var k=1;k<=ai.numLayers;k++){solo.push({index:k,solo:ai.layer(k).solo,enabled:ai.layer(k).enabled});}',
            '    snap.layers=solo;',
            '  }',
            '}catch(eS){snap.snapshot_error=String(eS);}',
            'return snap;'
        ].join('');
        const snap = await evalJSXJson(code);
        session = { snapshot: snap, ts: Date.now() };
        return { ok: true, snapshot: snap };
    }

    async function handleEndSession() {
        if (!session) return { ok: true, restored: false, reason: 'no_session' };
        const snap = session.snapshot || {};
        const snapJson = JSON.stringify(snap);
        const code = [
            'var snap=' + snapJson + ';',
            'try{',
            '  if(snap.tool){app.executeCommand(app.findMenuCommandId && app.findMenuCommandId(snap.tool) || 0);}',
            '}catch(_t){}',
            'try{',
            '  if(snap.active_item_id){',
            '    for(var i=1;i<=app.project.numItems;i++){var it=app.project.item(i); if(it.id===snap.active_item_id){it.openInViewer();break;}}',
            '  }',
            '  var ai=app.project.activeItem;',
            '  if(ai && (ai instanceof CompItem)){',
            '    if(snap.comp_time!=null) ai.time=snap.comp_time;',
            '    if(snap.layers){',
            '      for(var j=0;j<snap.layers.length;j++){',
            '        var meta=snap.layers[j]; if(meta.index<=ai.numLayers){ai.layer(meta.index).solo=!!meta.solo; ai.layer(meta.index).enabled=!!meta.enabled;}',
            '      }',
            '    }',
            '    if(snap.selected_layer_indexes){',
            '      for(var k=1;k<=ai.numLayers;k++){ai.layer(k).selected=false;}',
            '      for(var m=0;m<snap.selected_layer_indexes.length;m++){',
            '        var idx=snap.selected_layer_indexes[m]; if(idx<=ai.numLayers) ai.layer(idx).selected=true;',
            '      }',
            '    }',
            '  }',
            '}catch(eR){return {restore_error:String(eR)};}',
            'return {ok:true};'
        ].join('');
        const r = await evalJSXJson(code);
        session = null;
        return { ok: true, restored: true, detail: r };
    }

    async function handleLogs(req) {
        const parsed = url.parse(req.url, true);
        const tail = parsed.query && parsed.query.tail ? Math.max(1, Math.min(LOG_BUFFER_MAX, parseInt(parsed.query.tail, 10) || 100)) : 100;
        const slice = logBuffer.slice(-tail);
        return { lines: slice, log_file: logFilePath, buffer_size: logBuffer.length };
    }

    // --- Ensure Puppet Position Pin tool ---------------------------------
    // Probe-click at the given screen point. If it lands in PosPins: done.
    // If in another puppet group: remove probe + Ctrl+P rotate + retry.
    // If NO pin appears: Ctrl+P (activates Puppet from non-puppet tool) + retry.
    // Always cleans up probe pins it created.
    async function handleEnsurePuppetPositionTool(body) {
        if (!body) throw new Error('missing_body');
        const compId = Number(body.comp_id);
        const layerIndex = Number(body.layer_index);
        if (!compId || !layerIndex) throw new Error('missing_comp_id_or_layer_index');
        const maxRot = body.max_rotations != null ? Math.max(1, Number(body.max_rotations)) : 6;
        let probeX = body.probe_x != null ? Number(body.probe_x) : null;
        let probeY = body.probe_y != null ? Number(body.probe_y) : null;
        if (probeX == null || probeY == null) {
            const ae = getAEWindowRect && getAEWindowRect();
            if (!ae || ae.error) throw new Error('need_probe_point_or_ae_rect');
            probeX = ae.center_x; probeY = ae.center_y;
        }

        initMouse();
        if (!sendInputClick || !focusAEWindow || !sendKeySequence)
            throw new Error('runtime_unavailable:' + mouseLoadError);

        // One-time focus + move cursor into viewer so Ctrl+P reaches AE.
        focusAEWindow();
        await new Promise(r => setTimeout(r, 80));

        async function probeOnce() {
            const before = await readPuppetPinCount(compId, layerIndex);
            if (before && before.error) return { error: before.error };
            const b = { pos: Number(before.pos_count||0), hght: Number(before.hght_count||0), starch: Number(before.starch_count||0) };
            await sendInputClick(probeX, probeY, { preMoveMs: 30, holdMs: 40 });
            const deadline = Date.now() + 1500;
            let after = before;
            while (Date.now() < deadline) {
                await new Promise(r => setTimeout(r, 100));
                after = await readPuppetPinCount(compId, layerIndex);
                if (after && (Number(after.pos_count||0) > b.pos
                    || Number(after.hght_count||0) > b.hght
                    || Number(after.starch_count||0) > b.starch)) break;
            }
            const a = { pos: Number(after.pos_count||0), hght: Number(after.hght_count||0), starch: Number(after.starch_count||0) };
            const group = (a.pos > b.pos) ? 'PosPins'
                : (a.hght > b.hght) ? 'HghtPins'
                : (a.starch > b.starch) ? 'StarchPins' : null;
            return { before: b, after: a, group };
        }

        async function removeLast(group) {
            // group ∈ PosPins / HghtPins / StarchPins
            const mn = group === 'PosPins' ? 'ADBE FreePin3 PosPins'
                : group === 'HghtPins' ? 'ADBE FreePin3 HghtPins'
                : 'ADBE FreePin3 StarchPins';
            const code = [
                'var t=null;for(var i=1;i<=app.project.numItems;i++){var it=app.project.item(i); if(it.id==' + compId + '){t=it;break;}}',
                'if(!t) return {err:"no_comp"};',
                'var L=t.layer(' + layerIndex + ');',
                'var fx=L.property("ADBE Effect Parade").property("ADBE FreePin3");',
                'var g=fx.property("ADBE FreePin3 ARAP Group").property("ADBE FreePin3 Mesh Group").property(1).property("' + mn + '");',
                'if(g && g.numProperties>=1){g.property(g.numProperties).remove(); return {removed:true};}',
                'return {removed:false};'
            ].join('');
            try { return await evalJSXJson(code); } catch (e) { return { error: String(e) }; }
        }

        const trail = [];
        // Pass 0: try without Ctrl+P first — maybe user is already on PosPin.
        for (let cycle = 0; cycle <= maxRot; cycle++) {
            const r = await probeOnce();
            trail.push({ cycle, probe: r });
            if (r.error) return { ok: false, error: r.error, trail };
            if (r.group === 'PosPins') {
                // Clean up probe pin
                await removeLast('PosPins');
                return { ok: true, tool: 'position_pin', cycles: cycle, trail };
            }
            if (r.group) {
                // Wrong puppet sub-tool — clean up + rotate
                await removeLast(r.group);
            }
            if (cycle === maxRot) break;
            // Rotate Ctrl+P (activates puppet from non-puppet; cycles within puppet)
            await sendKeySequence(parseCombo('Ctrl+P'), { betweenMs: 20 });
            await new Promise(r => setTimeout(r, 180));
        }
        return { ok: false, reason: 'max_rotations', trail };
    }

    const ROUTES = {
        'GET /health':        function () { return handleHealth(); },
        'GET /logs':          function (req) { return handleLogs(req); },
        'POST /eval':         function (req, body) { return handleEval(body); },
        'GET /viewer-state':  function () { return handleViewerState(); },
        'POST /click-screen': function (req, body) { return handleClickScreen(body); },
        'POST /drag':         function (req, body) { return handleDrag(body); },
        'POST /viewer-pan':   function (req, body) { return handleViewerPan(body); },
        'POST /viewer-pan-space': function (req, body) { return handleViewerPanSpace(body); },
        'POST /viewer-pan-middle': function (req, body) { return handleViewerPanMiddle(body); },
        'POST /set-tool':     function (req, body) { return handleSetTool(body); },
        'POST /press-key':    function (req, body) { return handlePressKey(body); },
        'POST /focus-ae':     function () { return handleFocusAE(); },
        'GET /ae-rect':       function () { return handleAERect(); },
        'GET /enum-ae-windows': function () { return handleEnumAE(); },
        'POST /ensure-viewer':function (req, body) { return handleEnsureViewer(body); },
        'POST /ensure-puppet-position-tool': function (req, body) { return handleEnsurePuppetPositionTool(body); },
        'POST /place-pin':    function (req, body) { return handlePlacePin(body); },
        'POST /begin-session':function (req, body) { return handleBeginSession(body); },
        'POST /end-session':  function () { return handleEndSession(); },
        'GET /diag':          function () { return handleDiag(); },
        'POST /reload-self':  function () { return handleReloadSelf(); }
    };

    async function handleDiag() {
        let sizes = null;
        if (sendInputClick) {
            try {
                const extRoot = cs.getSystemPath(SystemPath.EXTENSION);
                const koffiPath = cep_node.require('path').join(extRoot, 'node_modules', 'koffi');
                const koffi = cep_node.require(koffiPath);
                sizes = {};
                try { sizes.INPUT = koffi.sizeof(koffi.struct('__probe_INPUT__', {type:'uint32',_pad:'uint32',dx:'int32',dy:'int32',mouseData:'uint32',dwFlags:'uint32',time:'uint32',dwExtraInfo:'uintptr_t',_tail:'uint32'})); }
                catch (e) { sizes.INPUT_err = String(e); }
            } catch (e) { sizes = { load_err: String(e) }; }
        }
        return {
            pid: process.pid,
            arch: process.arch,
            node: process.version,
            mouse_ready: !!sendInputClick,
            keyboard_ready: !!sendKeySequence,
            koffi_sizes: sizes,
            log_buffer_size: logBuffer.length
        };
    }

    async function handleReloadSelf() {
        log('reload-self requested; closing server then reloading');
        try {
            if (httpServer && httpServer.closeAllConnections) httpServer.closeAllConnections();
            if (httpServer) httpServer.close();
        } catch (e) { log('reload close error: ' + e.message); }
        setTimeout(function () { try { window.location.reload(); } catch (_) {} }, 400);
        return { ok: true, reloading_in_ms: 400 };
    }

    async function dispatch(req, res) {
        const parsed = url.parse(req.url, true);
        const key = req.method + ' ' + parsed.pathname;
        const handler = ROUTES[key];
        bumpReq();
        if (!handler) {
            sendJson(res, 404, { error: 'no_route', key: key, known: Object.keys(ROUTES) });
            return;
        }
        let body = {};
        if (req.method === 'POST' || req.method === 'PUT') {
            try { body = await readBody(req); }
            catch (e) { bumpErr(); sendJson(res, 400, { error: 'bad_json', detail: e.message }); return; }
        }
        try {
            const result = await handler(req, body);
            sendJson(res, 200, result == null ? { ok: true } : result);
        } catch (err) {
            bumpErr();
            log('ERR ' + key + ': ' + (err && err.message ? err.message : String(err)));
            sendJson(res, 500, { error: err && err.message ? err.message : String(err), route: key });
        }
    }

    // --- boot ----------------------------------------------------------------
    let httpServer = null;

    function startServer() {
        httpServer = http.createServer(function (req, res) { dispatch(req, res); });
        httpServer.on('error', function (err) {
            setStatus('listen_error', 'status-err');
            log('listen error: ' + err.message);
        });
        httpServer.listen(PORT, '127.0.0.1', function () {
            const addr = httpServer.address();
            endpointEl.textContent = '127.0.0.1:' + PORT;
            setStatus('listening', 'status-ok');
            log('HTTP listening on ' + JSON.stringify(addr));
            initMouse();
        });
        // Keep the Node event loop alive even if the panel is minimized/hidden.
        setInterval(function(){}, 60000);
    }

    // Expose a shutdown hook on the window so subsequent reloads can close
    // the previous server before re-listening. Not stored on the JS heap
    // (which is reset on reload) — on `window` which CEF keeps alive.
    if (window.__ae2claude_prior_server) {
        try {
            log('detected prior httpServer from reload; closing before bind');
            const prior = window.__ae2claude_prior_server;
            try { if (prior.closeAllConnections) prior.closeAllConnections(); } catch (_) {}
            prior.close();
        } catch (e) { log('prior close error: ' + e.message); }
        window.__ae2claude_prior_server = null;
    }

    startServer();
    window.__ae2claude_prior_server = httpServer;
    log('panel booted');
})();
