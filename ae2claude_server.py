"""PyShiftAE bridge server for embedded AE Python."""

import io
import json
import sys
import threading
import traceback
from multiprocessing.connection import Listener
from http.server import HTTPServer, BaseHTTPRequestHandler

_AE_PORT = 8089
_AE_PIPE = r"\\.\pipe\PyShiftAEBridge"

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


def _health_payload():
    return {
        "status": "ok",
        "engine": "PyShiftAE",
        "module": "PyShiftCore" if psc is not None else None,
        "module_available": psc is not None,
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
        result = app.executeScript(script)
        # Check for in-band error from C++ layer
        if isinstance(result, str) and result.startswith('{"__jsx_error__":'):
            import json as _j
            err_obj = _j.loads(result)
            return {"ok": False, "error": err_obj.get("__jsx_error__", result)}
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


try:
    _srv = HTTPServer(("127.0.0.1", _AE_PORT), _AEHandler)
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
