"""PyShiftAE bridge server for embedded AE Python."""

import io
import hashlib
import json
import sys
import threading
import time
from functools import wraps
from socketserver import ThreadingMixIn
import traceback
from multiprocessing.connection import Listener
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

_AE_PORT = 8089
_AE_PIPE = r"\\.\pipe\PyShiftAEBridge"
BRIDGE_VERSION = "4.3.1"
_JSX_ERROR_KEY = "__ae2claude_error__"
_EXECUTION_LOCK = threading.Lock()
_EXECUTION_STATE = {"startedAt": None, "completed": 0, "busyRejected": 0}
_MAX_REQUEST_BYTES = 2 * 1024 * 1024


def _serialized(operation):
    @wraps(operation)
    def guarded(*args, **kwargs):
        if not _EXECUTION_LOCK.acquire(blocking=False):
            _EXECUTION_STATE["busyRejected"] += 1
            return {"ok": False, "kind": "busy", "error": "AE bridge is executing another operation",
                    "outcome": "not_started", "retrySafe": True}
        _EXECUTION_STATE["startedAt"] = time.monotonic()
        try:
            return operation(*args, **kwargs)
        finally:
            _EXECUTION_STATE["completed"] += 1
            _EXECUTION_STATE["startedAt"] = None
            _EXECUTION_LOCK.release()
    return guarded


def _wrap_jsx_for_structured_errors(code: str) -> str:
    """Catch parse/runtime errors without relying on ExtendScript's optional JSON."""
    source = json.dumps(str(code), ensure_ascii=True)
    # ES3 only. Keep helpers local and restore dialog handling on every exit.
    prefix = r'''(function(){
function __ae2q(v){
 if(v===null || typeof v==="undefined")return "null";
 var s=String(v),r='"',i,c,n;
 for(i=0;i<s.length;i++){
  c=s.charAt(i);n=s.charCodeAt(i);
  if(c==='"'||c==='\\')r+='\\'+c;
  else if(n<32||n===8232||n===8233)r+='\\u'+('0000'+n.toString(16)).slice(-4);
  else r+=c;
 }
 return r+'"';
}
function __ae2field(e,k){try{return e && e[k]!=null?String(e[k]):null;}catch(_){return null;}}
function __ae2line(e){var n=Number(__ae2field(e,"line"));return n>0 && isFinite(n)?String(n):"null";}
var __ae2quiet=false;
try{
 if(typeof app!=="undefined" && app.beginSuppressDialogs){app.beginSuppressDialogs();__ae2quiet=true;}
'''
    suffix = r'''
}catch(__ae2e){
 var message;try{message=String(__ae2e);}catch(_){message="Unprintable ExtendScript error";}
 return '{"__ae2claude_error__":'+__ae2q(message)+
 ',"name":'+__ae2q(__ae2field(__ae2e,"name"))+
 ',"line":'+__ae2line(__ae2e)+
 ',"fileName":'+__ae2q(__ae2field(__ae2e,"fileName"))+
 ',"stack":'+__ae2q(__ae2field(__ae2e,"stack"))+'}';
}finally{if(__ae2quiet)app.endSuppressDialogs(false);}
})();'''
    return prefix + 'return eval(' + source + ');' + suffix


try:
    import PyShiftCore as psc
except Exception:
    psc = None

app = getattr(psc, "app", None)
_BASE_GLOBALS = {}
if psc is not None:
    _BASE_GLOBALS["psc"] = psc
if app is not None:
    _BASE_GLOBALS["app"] = app

_TRANSPORT_STATE = {
    "http": False,
    "pipe": False,
}
_TRANSPORT_ERRORS = {}


def _plugin_artifact_payload():
    path = Path(__file__).resolve().with_name("AE2Claude.aex")
    payload = {"path": str(path), "present": path.is_file()}
    if not path.is_file():
        return payload
    try:
        payload.update(
            {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
                "modified_ns": path.stat().st_mtime_ns,
            }
        )
    except OSError as exc:
        payload["error"] = str(exc)
    return payload


_PLUGIN_ARTIFACT = _plugin_artifact_payload()


def _health_payload():
    native = psc.bridgeDiagnostics() if psc is not None and hasattr(psc, "bridgeDiagnostics") else None
    started = _EXECUTION_STATE["startedAt"]
    return {
        "status": "ok",
        "bridge_version": BRIDGE_VERSION,
        "engine": "PyShiftAE",
        "module": "PyShiftCore" if psc is not None else None,
        "module_available": psc is not None,
        "python_version": sys.version.split()[0],
        "plugin_artifact": dict(_PLUGIN_ARTIFACT),
        "port": _AE_PORT,
        "pipe": _AE_PIPE,
        "transports": {
            "http": _TRANSPORT_STATE["http"],
            "pipe": _TRANSPORT_STATE["pipe"],
        },
        "transport_errors": dict(_TRANSPORT_ERRORS),
        "native": native,
        "execution": {"busy": _EXECUTION_LOCK.locked(), "elapsedMs": round((time.monotonic() - started) * 1000) if started else 0,
                      "completed": _EXECUTION_STATE["completed"], "busyRejected": _EXECUTION_STATE["busyRejected"]},
        "features": {"wrapsJsxErrors": True, "nativeDeadline": native is not None,
                     "healthWhileBusy": True, "maxRequestBytes": _MAX_REQUEST_BYTES,
                     "nativeAutomation": getattr(psc, "native_snapshot", None) is not None},
    }


@_serialized
def _execute_native(request):
    """Allowlisted JSON requests share the same busy gate as Python and JSX."""
    from ae_native_protocol import OPERATIONS, normalize_request
    try:
        if not isinstance(request, dict) or set(request) != {"operation", "arguments"}:
            raise ValueError("native request requires operation and arguments")
        operation = request["operation"]
        arguments = normalize_request(operation, request["arguments"])
        function = getattr(psc, OPERATIONS[operation], None)
        if function is None:
            return {"ok": False, "kind": "native_unavailable", "error": "Install and load native-automation-20260912 or newer",
                    "outcome": "not_started", "retrySafe": True}
    except (ValueError, TypeError, OverflowError) as exc:
        return {"ok": False, "kind": "native_validation", "error": str(exc),
                "outcome": "not_started", "retrySafe": True}
    try:
        return {"ok": True, "result": function(**arguments)}
    except Exception as exc:
        # A timeout or commit failure is not proof that a write did not happen.
        not_started = "outcome=not_started" in str(exc)
        return {"ok": False, "kind": "native", "error": str(exc),
                "outcome": "not_started" if not_started else "unknown", "retrySafe": not_started}


@_serialized
def _execute_code(source, prefer_exec=False):
    old_stdout = sys.stdout
    capture = io.StringIO()
    sys.stdout = capture
    result = error = None
    try:
        exec_globals = dict(globals())
        exec_globals.update(_BASE_GLOBALS)
        if prefer_exec:
            exec_locals = dict(exec_globals)
            exec_locals["_result"] = None
            compiled = compile(source, "<ae>", "exec")
            exec(compiled, exec_locals, exec_locals)
            result = exec_locals.get("_result")
        else:
            try:
                result = eval(source, exec_globals, exec_globals)
            except SyntaxError:
                exec_locals = dict(exec_globals)
                exec_locals["_result"] = None
                compiled = compile(source, "<ae>", "exec")
                exec(compiled, exec_locals, exec_locals)
                result = exec_locals.get("_result")
    except Exception:
        error = traceback.format_exc()
    finally:
        output = capture.getvalue()
        sys.stdout = old_stdout

    response = {"ok": error is None}
    if result is not None:
        response["result"] = repr(result)
    if output:
        response["output"] = output
    if error:
        response["error"] = error
    return response


def _handle_request(payload):
    if isinstance(payload, str):
        return _execute_code(payload)

    if not isinstance(payload, dict):
        return {
            "ok": False,
            "error": f"Unsupported payload type: {type(payload).__name__}",
        }

    action = payload.get("action", "eval")
    if action == "health":
        return _health_payload()

    code = payload.get("code", "")
    if not code:
        return {"ok": False, "error": "Missing 'code' in request"}

    return _execute_code(code, prefer_exec=(action == "exec"))


def _serve_pipe(listener):
    while True:
        conn = listener.accept()
        try:
            payload = conn.recv()
            conn.send(_handle_request(payload))
        except EOFError:
            pass
        except Exception:
            try:
                conn.send({"ok": False, "error": traceback.format_exc()})
            except Exception:
                pass
        finally:
            conn.close()


@_serialized
def _execute_jsx(script, timeout_ms=120000):
    """Execute ExtendScript via AEGP_ExecuteScript and return result."""
    try:
        if not app or not hasattr(app, "executeScript"):
            return {"ok": False, "error": "executeScript not available"}
        if not 1 <= timeout_ms <= 600000:
            return {"ok": False, "kind": "validation", "error": "timeout_ms must be 1-600000", "outcome": "not_started", "retrySafe": True}
        if psc is not None and hasattr(psc, "bridgeDiagnostics"):
            result = app.executeScript(_wrap_jsx_for_structured_errors(script), timeout_ms)
        else:
            result = app.executeScript(_wrap_jsx_for_structured_errors(script))
        if isinstance(result, str) and result.startswith("{"):
            try:
                err_obj = json.loads(result)
            except json.JSONDecodeError:
                err_obj = None
            if isinstance(err_obj, dict) and _JSX_ERROR_KEY in err_obj:
                response = {
                    "ok": False,
                    "kind": "jsx",
                    "error": err_obj.get(_JSX_ERROR_KEY, "Unknown JSX error"),
                }
                for key in ("name", "line", "fileName", "stack"):
                    if err_obj.get(key) is not None:
                        response[key] = err_obj[key]
                return response
            if isinstance(err_obj, dict) and "__jsx_error__" in err_obj:
                return {
                    "ok": False,
                    "kind": "jsx-native",
                    "error": err_obj.get("__jsx_error__", result),
                }
        return {"ok": True, "result": result}
    except Exception as exc:
        not_started = str(exc).startswith(("AE task deadline expired before execution;", "AE task cancelled before execution;", "AE task queue overloaded;", "AE dispatcher is shutting down;"))
        return {"ok": False, "error": str(exc), "kind": "native",
                "outcome": "not_started" if not_started else "unknown", "retrySafe": not_started}


class _AEHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def _respond(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionError, OSError):
            pass  # Client deadline does not cancel or replay the AE operation.

    def do_POST(self):
        path = self.path.rstrip("/")
        if path not in {"", "/exec", "/jsx", "/native"}:
            self._respond({"ok": False, "error": "unknown_endpoint", "outcome": "not_started"}, 404)
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 < n <= _MAX_REQUEST_BYTES:
                self._respond({"ok": False, "error": "invalid_body_size", "outcome": "not_started"}, 413)
                return
            raw = self.rfile.read(n)
            if len(raw) != n:
                raise ValueError("incomplete_body")
            body = raw.decode("utf-8")
            timeout_ms = int(self.headers.get("X-AE-Timeout-Ms", "120000"))
            if path == "/native":
                response = _execute_native(json.loads(body))
            else:
                response = _execute_jsx(body, timeout_ms) if path == "/jsx" else _execute_code(body)
            self._respond(response)
        except (ValueError, UnicodeError, OSError) as exc:
            self._respond({"ok": False, "error": str(exc), "outcome": "not_started"}, 400)

    def do_GET(self):
        if self.path.rstrip("/") not in {"", "/health"}:
            self._respond({"ok": False, "error": "unknown_endpoint"}, 404)
            return
        self._respond(_health_payload())

    def log_message(self, *args):
        pass


class _AEHTTPServer(ThreadingMixIn, HTTPServer):
    """Bounded transport concurrency; AE/Python execution is still serialized."""
    allow_reuse_address = True
    request_queue_size = 64
    daemon_threads = True
    block_on_close = False

    def __init__(self, *args, **kwargs):
        self._slots = threading.BoundedSemaphore(16)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


# Importing this module in tests/CLI must never occupy the live AE ports.
if psc is not None:
    try:
        _srv = _AEHTTPServer(("127.0.0.1", _AE_PORT), _AEHandler)
    except Exception:
        _TRANSPORT_ERRORS["http"] = traceback.format_exc()
    else:
        _TRANSPORT_STATE["http"] = True
        threading.Thread(target=_srv.serve_forever, daemon=True).start()

    try:
        _pipe_listener = Listener(_AE_PIPE, family="AF_PIPE")
    except Exception:
        _TRANSPORT_ERRORS["pipe"] = traceback.format_exc()
    else:
        _TRANSPORT_STATE["pipe"] = True
        threading.Thread(target=_serve_pipe, args=(_pipe_listener,), daemon=True).start()
