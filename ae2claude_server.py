"""PyShiftAE bridge server for embedded AE Python."""

import io
import hashlib
import json
import sys
import threading
import traceback
from multiprocessing.connection import Listener
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

_AE_PORT = 8089
_AE_PIPE = r"\\.\pipe\PyShiftAEBridge"
BRIDGE_VERSION = "4.3.1"
_JSX_ERROR_KEY = "__ae2claude_error__"


def _wrap_jsx_for_structured_errors(code):
    source = json.dumps(str(code), ensure_ascii=True)
    return (
        '(function(){try{return eval(' + source + ');}'
        'catch(__ae2e){return JSON.stringify({'
        '__ae2claude_error__:String(__ae2e),'
        'name:(__ae2e&&__ae2e.name)?String(__ae2e.name):null,'
        'line:(__ae2e&&__ae2e.line)?Number(__ae2e.line):null,'
        'fileName:(__ae2e&&__ae2e.fileName)?String(__ae2e.fileName):null,'
        'stack:(__ae2e&&__ae2e.stack)?String(__ae2e.stack):null'
        '});}})();'
    )

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
    }


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


def _execute_jsx(script):
    """Execute ExtendScript via AEGP_ExecuteScript and return result."""
    try:
        if not app or not hasattr(app, "executeScript"):
            return {"ok": False, "error": "executeScript not available"}
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
    except Exception:
        return {"ok": False, "error": traceback.format_exc()}


class _AEHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n).decode("utf-8")

            path = self.path.rstrip("/")
            if path == "/jsx":
                resp = _execute_jsx(body)
            else:
                resp = _execute_code(body)

            b = json.dumps(resp, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        except Exception as e:
            err_b = str(e).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Length", str(len(err_b)))
            self.end_headers()
            self.wfile.write(err_b)

    def do_GET(self):
        b = json.dumps(_health_payload()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


class _AEHTTPServer(HTTPServer):
    """Serialize AE calls while allowing a bounded concurrent connection burst."""

    allow_reuse_address = True
    request_queue_size = 64


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
