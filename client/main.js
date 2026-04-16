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
    let focusAEWindow = null;
    let mouseLoadError = null;

    function initMouse() {
        if (sendInputClick || mouseLoadError) return;
        try {
            const extRoot = cs.getSystemPath(SystemPath.EXTENSION);
            const koffiPath = cep_node.require('path').join(extRoot, 'node_modules', 'koffi');
            const koffi = cep_node.require(koffiPath);
            const user32 = koffi.load('user32.dll');

            // INPUT union layout (Windows x64): size 40 bytes total.
            //   DWORD type             (4)
            //   <4 bytes pad>          (4)
            //   MOUSEINPUT mi          (32): LONG dx, LONG dy, DWORD mouseData, DWORD dwFlags,
            //                                DWORD time, ULONG_PTR dwExtraInfo
            const INPUT = koffi.struct('INPUT', {
                type:       'uint32',
                _pad:       'uint32',
                dx:         'int32',
                dy:         'int32',
                mouseData:  'uint32',
                dwFlags:    'uint32',
                time:       'uint32',
                dwExtraInfo:'uintptr_t',
                _tail:      'uint32'
            });
            const SendInput = user32.func('uint32 SendInput(uint32, _In_ INPUT*, int32)');
            const GetSystemMetrics = user32.func('int32 GetSystemMetrics(int32)');
            const SetCursorPos = user32.func('int32 SetCursorPos(int32, int32)');
            const FindWindowA = user32.func('void* FindWindowA(const char*, const char*)');
            const SetForegroundWindow = user32.func('int32 SetForegroundWindow(void*)');
            const ShowWindow = user32.func('int32 ShowWindow(void*, int32)');
            const BringWindowToTop = user32.func('int32 BringWindowToTop(void*)');
            const SW_RESTORE = 9;

            const SM_CXSCREEN = 0, SM_CYSCREEN = 1;
            const INPUT_MOUSE = 0;
            const MOUSEEVENTF_MOVE = 0x0001;
            const MOUSEEVENTF_LEFTDOWN = 0x0002;
            const MOUSEEVENTF_LEFTUP = 0x0004;
            const MOUSEEVENTF_ABSOLUTE = 0x8000;
            const MOUSEEVENTF_VIRTUALDESK = 0x4000;

            // --- AE window focus ---
            // AE classname "AE_CApplication_26.3" (varies by version). Find by class prefix.
            focusAEWindow = function () {
                const candidates = ['AE_CApplication_26.3', 'AE_CApplication_26.2', 'AE_CApplication_26.1', 'AE_CApplication_26.0', 'AE_CApplication_25.0', 'AE_CApplication_24.0'];
                for (let i = 0; i < candidates.length; i++) {
                    const hwnd = FindWindowA(candidates[i], null);
                    if (hwnd) {
                        ShowWindow(hwnd, SW_RESTORE);
                        BringWindowToTop(hwnd);
                        SetForegroundWindow(hwnd);
                        return { ok: true, class: candidates[i] };
                    }
                }
                return { ok: false, tried: candidates };
            };

            sendInputClick = function (screenX, screenY, opts) {
                opts = opts || {};
                const preMoveMs = opts.preMoveMs != null ? opts.preMoveMs : 30;
                const holdMs = opts.holdMs != null ? opts.holdMs : 40;

                // Cursor to approximate target first (helps multi-monitor absolute calc)
                SetCursorPos(screenX, screenY);

                // ABSOLUTE coords are 0..65535 over the primary screen (or virtual desktop).
                const sw = GetSystemMetrics(SM_CXSCREEN);
                const sh = GetSystemMetrics(SM_CYSCREEN);
                const ax = Math.round((screenX * 65535) / Math.max(1, sw - 1));
                const ay = Math.round((screenY * 65535) / Math.max(1, sh - 1));

                const mkInput = (flags) => ({
                    type: INPUT_MOUSE,
                    _pad: 0,
                    dx: ax,
                    dy: ay,
                    mouseData: 0,
                    dwFlags: flags | MOUSEEVENTF_ABSOLUTE,
                    time: 0,
                    dwExtraInfo: 0,
                    _tail: 0
                });

                function sendOne(flags) {
                    const buf = [mkInput(flags)];
                    const n = SendInput(1, buf, koffi.sizeof(INPUT));
                    if (n !== 1) throw new Error('SendInput returned ' + n);
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
        return {
            ok: true,
            port: PORT,
            ae: v,
            mouse_ready: !!sendInputClick,
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

    async function handleFocusAE() {
        initMouse();
        if (!focusAEWindow) throw new Error('focus_unavailable:' + mouseLoadError);
        return focusAEWindow();
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
            'var pins=mesh.property("ADBE FreePin3 PosPins");',
            'var flags=[];',
            'for(var p=1;p<=pins.numProperties;p++){',
            '  var pp=pins.property(p);',
            '  try{',
            '    var vtx=pp.property("ADBE FreePin3 PosPin Vtx Index"); var vtxV=vtx ? vtx.value : null;',
            '    flags.push({index:p,name:pp.name,vtx_index:vtxV});',
            '  }catch(_p){flags.push({index:p,name:pp.name,err:String(_p)});}',
            '}',
            'return {pin_count:pins.numProperties,has_effect:true,has_mesh:true,mesh_tri_count:(mesh.property("ADBE FreePin3 Mesh Tri Count")?mesh.property("ADBE FreePin3 Mesh Tri Count").value:null),pins:flags};'
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
            attempts.push({ attempt: attempt, screen: [sx, sy], after_count: afterCount, click: clickRes });
            if (afterCount > beforeCount) {
                const newPin = after && after.pins ? after.pins[after.pins.length - 1] : null;
                return {
                    placed: true,
                    attempts: attempts.length,
                    pin_index: afterCount,
                    before_count: beforeCount,
                    after_count: afterCount,
                    new_pin: newPin,
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

    const ROUTES = {
        'GET /health':        function () { return handleHealth(); },
        'GET /logs':          function (req) { return handleLogs(req); },
        'POST /eval':         function (req, body) { return handleEval(body); },
        'GET /viewer-state':  function () { return handleViewerState(); },
        'POST /click-screen': function (req, body) { return handleClickScreen(body); },
        'POST /focus-ae':     function () { return handleFocusAE(); },
        'POST /ensure-viewer':function (req, body) { return handleEnsureViewer(body); },
        'POST /place-pin':    function (req, body) { return handlePlacePin(body); },
        'POST /begin-session':function (req, body) { return handleBeginSession(body); },
        'POST /end-session':  function () { return handleEndSession(); }
    };

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
    function startServer() {
        const server = http.createServer(function (req, res) { dispatch(req, res); });
        server.on('error', function (err) {
            setStatus('listen_error', 'status-err');
            log('listen error: ' + err.message);
        });
        server.listen(PORT, '127.0.0.1', function () {
            const addr = server.address();
            endpointEl.textContent = '127.0.0.1:' + PORT;
            setStatus('listening', 'status-ok');
            log('HTTP listening on ' + JSON.stringify(addr));
            initMouse();
        });
        // Keep the Node event loop alive even if the panel is minimized/hidden.
        setInterval(function(){}, 60000);
    }

    startServer();
    log('panel booted');
})();
