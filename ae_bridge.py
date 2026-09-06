"""
AE Bridge - Universal After Effects Automation via PyShiftAE
============================================================
通过 PyShiftAE 插件内嵌的 HTTP 服务器 (默认 8089) 与 After Effects 通信。

核心设计原则:
1. 所有 effect 属性使用 matchName (兼容中文/日文/英文 AE)
2. 每次调用执行最小操作单元 (避免 AE 对象引用失效)
3. 通过 AEGP_ExecuteScript 原生执行 ExtendScript
4. 内置 Dialog Dismisser 后台线程

使用:
    from ae_bridge import AEBridge

    with AEBridge() as ae:
        print(ae.comp_info())
        ae.add_text_layer("Hello", start=1.0, end=5.0)
        ae.add_effect("LayerName", "gaussian_blur", {"blurriness": 50})

依赖: 无外部依赖 (仅 Python 标准库)
"""
import json
import sys
import time
import threading
import subprocess
import urllib.request
import urllib.error
from typing import Optional, List, Dict, Any, Tuple, Union

__version__ = "4.3.1"

_JSX_ERROR_KEY = "__ae2claude_error__"


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


class JSXExecutionError(RuntimeError):
    """Machine-readable ExtendScript failure returned by the AE bridge."""

    def __init__(self, payload: Dict[str, Any]):
        self.payload = payload
        super().__init__(json.dumps(payload, ensure_ascii=False, default=str))

# ╔══════════════════════════════════════════════════════════╗
# ║              EFFECT MATCHNAME REGISTRY                  ║
# ╠══════════════════════════════════════════════════════════╣
# ║ AE Beta 26.1 中文 locale 下 display name 是中文,       ║
# ║ 用 matchName 才能保证跨语言兼容。                       ║
# ╚══════════════════════════════════════════════════════════╝

EFFECTS = {
    # --- Gaussian Blur ---
    "gaussian_blur": {
        "matchName": "ADBE Gaussian Blur 2",
        "props": {
            "blurriness":         "ADBE Gaussian Blur 2-0001",  # 模糊度
            "blur_direction":     "ADBE Gaussian Blur 2-0002",  # 模糊方向
            "repeat_edge_pixels": "ADBE Gaussian Blur 2-0003",  # 重复边缘像素 (bool: 0/1)
        }
    },
    # --- Drop Shadow ---
    "drop_shadow": {
        "matchName": "ADBE Drop Shadow",
        "props": {
            "shadow_color": "ADBE Drop Shadow-0001",  # 阴影颜色
            "opacity":      "ADBE Drop Shadow-0002",  # 不透明度
            "direction":    "ADBE Drop Shadow-0003",  # 方向
            "distance":     "ADBE Drop Shadow-0004",  # 距离
            "softness":     "ADBE Drop Shadow-0005",  # 柔和度
        }
    },
    # --- Fill ---
    "fill": {
        "matchName": "ADBE Fill",
        "props": {
            "fill_mask":  "ADBE Fill-0001",
            "all_masks":  "ADBE Fill-0002",
            "color":      "ADBE Fill-0003",
            "invert":     "ADBE Fill-0004",
            "h_feather":  "ADBE Fill-0005",
            "v_feather":  "ADBE Fill-0006",
            "opacity":    "ADBE Fill-0007",
        }
    },
    # --- Glow ---
    "glow": {
        "matchName": "ADBE Glo2",
        "props": {
            "glow_threshold":  "ADBE Glo2-0001",
            "glow_radius":     "ADBE Glo2-0002",
            "glow_intensity":  "ADBE Glo2-0003",
        }
    },
    # --- Levels ---
    "levels": {
        "matchName": "ADBE Easy Levels2",
        "props": {
            "channel":       "ADBE Easy Levels2-0001",
            "input_black":   "ADBE Easy Levels2-0003",
            "input_white":   "ADBE Easy Levels2-0004",
            "gamma":         "ADBE Easy Levels2-0005",
            "output_black":  "ADBE Easy Levels2-0006",
            "output_white":  "ADBE Easy Levels2-0007",
        }
    },
    # --- Hue/Saturation ---
    "hue_saturation": {
        "matchName": "ADBE HUE SATURATION",
        "props": {
            "channel_control": "ADBE HUE SATURATION-0002",
            "master_hue":      "ADBE HUE SATURATION-0004",
            "master_saturation": "ADBE HUE SATURATION-0005",
            "master_lightness": "ADBE HUE SATURATION-0006",
            "colorize":        "ADBE HUE SATURATION-0007",
        }
    },
    # --- Brightness & Contrast ---
    "brightness_contrast": {
        "matchName": "ADBE Brightness & Contrast 2",
        "props": {
            "brightness": "ADBE Brightness & Contrast 2-0001",
            "contrast":   "ADBE Brightness & Contrast 2-0002",
        }
    },
    # --- Tint ---
    "tint": {
        "matchName": "ADBE Tint",
        "props": {
            "map_black_to": "ADBE Tint-0001",
            "map_white_to": "ADBE Tint-0002",
            "tint_amount":  "ADBE Tint-0003",
        }
    },
    # --- Tritone ---
    "tritone": {
        "matchName": "ADBE Tritone",
        "props": {
            "highlights": "ADBE Tritone-0001",
            "midtones":   "ADBE Tritone-0002",
            "shadows":    "ADBE Tritone-0003",
            "blend":      "ADBE Tritone-0004",
        }
    },
    # --- CC Toner ---
    "cc_toner": {
        "matchName": "CC Toner",
        "props": {
            "tones":      "CC Toner-0005",
            "highlights": "CC Toner-0001",
            "brights":    "CC Toner-0006",
            "midtones":   "CC Toner-0002",
            "darktones":  "CC Toner-0007",
            "shadows":    "CC Toner-0003",
            "blend":      "CC Toner-0004",
        }
    },
    # --- Invert ---
    "invert": {
        "matchName": "ADBE Invert",
        "props": {
            "channel": "ADBE Invert-0001",
            "blend":   "ADBE Invert-0002",
        }
    },
    # --- Ramp/Gradient ---
    "gradient_ramp": {
        "matchName": "ADBE Ramp",
        "props": {
            "start_point": "ADBE Ramp-0001",
            "start_color": "ADBE Ramp-0002",
            "end_point":   "ADBE Ramp-0003",
            "end_color":   "ADBE Ramp-0004",
            "ramp_shape":  "ADBE Ramp-0005",
            "ramp_scatter": "ADBE Ramp-0006",
            "blend":       "ADBE Ramp-0007",
        }
    },
    # --- Turbulent Displace ---
    "turbulent_displace": {
        "matchName": "ADBE Turbulent Displace",
        "props": {
            "displacement":  "ADBE Turbulent Displace-0001",
            "amount":        "ADBE Turbulent Displace-0002",
            "size":          "ADBE Turbulent Displace-0003",
            "offset":        "ADBE Turbulent Displace-0004",
            "complexity":    "ADBE Turbulent Displace-0005",
            "evolution":     "ADBE Turbulent Displace-0006",
            "random_seed":   "ADBE Turbulent Displace-0010",
        }
    },
    # --- Fractal Noise ---
    "fractal_noise": {
        "matchName": "ADBE Fractal Noise",
        "props": {
            "fractal_type": "ADBE Fractal Noise-0001",
            "noise_type":   "ADBE Fractal Noise-0002",
            "invert":       "ADBE Fractal Noise-0003",
            "contrast":     "ADBE Fractal Noise-0004",
            "brightness":   "ADBE Fractal Noise-0005",
            "overflow":     "ADBE Fractal Noise-0006",
            "rotation":     "ADBE Fractal Noise-0008",
            "scale":        "ADBE Fractal Noise-0010",
            "offset":       "ADBE Fractal Noise-0013",
            "complexity":   "ADBE Fractal Noise-0015",
            "evolution":    "ADBE Fractal Noise-0023",
            "random_seed":  "ADBE Fractal Noise-0027",
            "opacity":      "ADBE Fractal Noise-0029",
            "blending_mode": "ADBE Fractal Noise-0030",
        }
    },
    # --- Radial Blur ---
    "radial_blur": {
        "matchName": "ADBE Radial Blur",
        "props": {
            "amount": "ADBE Radial Blur-0001",
            "center": "ADBE Radial Blur-0002",
            "type":   "ADBE Radial Blur-0003",
        }
    },
    # --- Camera Lens Blur ---
    "camera_lens_blur": {
        "matchName": "ADBE Camera Lens Blur",
        "props": {
            "blur_radius": "ADBE Camera Lens Blur-0001",
            "iris_shape":  "ADBE Camera Lens Blur-0003",
            "roundness":   "ADBE Camera Lens Blur-0004",
            "rotation":    "ADBE Camera Lens Blur-0006",
            "diffraction":  "ADBE Camera Lens Blur-0007",
            "highlight_gain": "ADBE Camera Lens Blur-0017",
            "highlight_threshold": "ADBE Camera Lens Blur-0018",
        }
    },
    # --- Mosaic ---
    "mosaic": {
        "matchName": "ADBE Mosaic",
        "props": {
            "horizontal_blocks": "ADBE Mosaic-0001",
            "vertical_blocks":   "ADBE Mosaic-0002",
        }
    },
    # --- Motion Tile ---
    "motion_tile": {
        "matchName": "ADBE Tile",
        "props": {
            "tile_center":  "ADBE Tile-0001",
            "tile_width":   "ADBE Tile-0002",
            "tile_height":  "ADBE Tile-0003",
            "output_width": "ADBE Tile-0004",
            "output_height": "ADBE Tile-0005",
            "mirror_edges": "ADBE Tile-0006",
            "phase":        "ADBE Tile-0007",
        }
    },
    # --- Posterize ---
    "posterize": {
        "matchName": "ADBE Posterize",
        "props": {
            "level": "ADBE Posterize-0001",
        }
    },
}

# ╔══════════════════════════════════════════════════════════╗
# ║              TRANSFORM PROPERTY REGISTRY                ║
# ╠══════════════════════════════════════════════════════════╣
# ║ Transform 属性 matchName + 缓动维度参考                 ║
# ╚══════════════════════════════════════════════════════════╝

TRANSFORM_PROPS = {
    "anchor_point": {
        "matchName": "ADBE Anchor Point",
        "path": 'property("Transform").property("Anchor Point")',
        "ease_dims": 2,   # 2D spatial (unless 3D layer)
        "spatial": True,
    },
    "position": {
        "matchName": "ADBE Position",
        "path": 'property("Transform").property("Position")',
        "ease_dims": 1,   # Spatial -> 1 KeyframeEase element
        "spatial": True,
    },
    "scale": {
        "matchName": "ADBE Scale",
        "path": 'property("Transform").property("Scale")',
        "ease_dims": 3,   # 3D, non-spatial -> 3 elements
        "spatial": False,
    },
    "rotation": {
        "matchName": "ADBE Rotate Z",
        "path": 'property("Transform").property("Rotation")',
        "ease_dims": 1,
        "spatial": False,
    },
    "opacity": {
        "matchName": "ADBE Opacity",
        "path": 'property("Transform").property("Opacity")',
        "ease_dims": 1,
        "spatial": False,
    },
}

# ╔══════════════════════════════════════════════════════════╗
# ║              SEMANTIC PROPERTY MAP                      ║
# ╠══════════════════════════════════════════════════════════╣
# ║ Agent-facing semantic names → AE property paths.        ║
# ║ Unknown names raise ValueError — no transparent         ║
# ║ passthrough of raw AE paths.                            ║
# ╚══════════════════════════════════════════════════════════╝

PROP_MAP = {
    "anchor_point": 'property("Transform").property("Anchor Point")',
    "position":     'property("Transform").property("Position")',
    "scale":        'property("Transform").property("Scale")',
    "rotation":     'property("Transform").property("Rotation")',
    "opacity":      'property("Transform").property("Opacity")',
}


def _resolve_prop(prop: str) -> str:
    """Resolve semantic property name to AE path. Raises ValueError if unknown."""
    path = PROP_MAP.get(prop)
    if path is None:
        raise ValueError(
            f"Unknown property '{prop}'. "
            f"Available: {list(PROP_MAP.keys())}. "
            f"Use run_jsx() for raw AE property access."
        )
    return path


# ╔══════════════════════════════════════════════════════════╗
# ║               BLEND MODE REGISTRY                       ║
# ╠══════════════════════════════════════════════════════════╣
# ║ 图层混合模式 BlendingMode 枚举映射                       ║
# ╚══════════════════════════════════════════════════════════╝

BLEND_MODES = {
    "normal": "BlendingMode.NORMAL",
    "dissolve": "BlendingMode.DISSOLVE",
    "darken": "BlendingMode.DARKEN",
    "multiply": "BlendingMode.MULTIPLY",
    "color_burn": "BlendingMode.COLOR_BURN",
    "linear_burn": "BlendingMode.LINEAR_BURN",
    "darker_color": "BlendingMode.DARKER_COLOR",
    "lighten": "BlendingMode.LIGHTEN",
    "screen": "BlendingMode.SCREEN",
    "color_dodge": "BlendingMode.COLOR_DODGE",
    "linear_dodge": "BlendingMode.LINEAR_DODGE",
    "lighter_color": "BlendingMode.LIGHTER_COLOR",
    "overlay": "BlendingMode.OVERLAY",
    "soft_light": "BlendingMode.SOFT_LIGHT",
    "hard_light": "BlendingMode.HARD_LIGHT",
    "vivid_light": "BlendingMode.VIVID_LIGHT",
    "linear_light": "BlendingMode.LINEAR_LIGHT",
    "pin_light": "BlendingMode.PIN_LIGHT",
    "hard_mix": "BlendingMode.HARD_MIX",
    "difference": "BlendingMode.DIFFERENCE",
    "exclusion": "BlendingMode.EXCLUSION",
    "hue": "BlendingMode.HUE",
    "saturation": "BlendingMode.SATURATION",
    "color": "BlendingMode.COLOR",
    "luminosity": "BlendingMode.LUMINOSITY",
    "add": "BlendingMode.ADD",
    "stencil_alpha": "BlendingMode.STENCIL_ALPHA",
    "silhouette_alpha": "BlendingMode.SILHOUETTE_ALPHA",
}

TRACK_MATTE_TYPES = {
    "alpha": "TrackMatteType.ALPHA",
    "alpha_inverted": "TrackMatteType.ALPHA_INVERTED",
    "luma": "TrackMatteType.LUMA",
    "luma_inverted": "TrackMatteType.LUMA_INVERTED",
    "none": "TrackMatteType.NO_TRACK_MATTE",
}

# ╔══════════════════════════════════════════════════════════╗
# ║                  AE BRIDGE CLASS                    ║
# ╚══════════════════════════════════════════════════════════╝

class AEBridge:
    """
    AE2Claude Bridge v4.3.1 - Agent-native API for After Effects.

    Design principles:
    - One method = one AE logical action (no fat methods)
    - Agent orchestrates: loops, filtering, multi-step workflows are caller's job
    - Semantic property names: "position", "opacity" etc. (no raw AE paths)

    Connection: PyShiftAE AEGP plugin HTTP server (default port 8089).

    Example:
        with AEBridge() as ae:
            ae.begin_undo("My Script")
            ae.add_text_layer("Hello")
            ae.set_text_style("Hello", font_size=56, fill_color=[1,1,1])
            ae.set_keyframes("Hello", "opacity", [(0, 0), (1, 100)])
            ae.apply_transform_easing("Hello", "opacity")
            ae.end_undo()
    """

    def __init__(self, port: int = 8089, timeout: int = 30,
                 auto_dismiss: bool = False, **_ignored):
        """
        Args:
            port: PyShiftAE HTTP 服务器端口 (默认 8089)
            timeout: HTTP 请求超时秒数
            auto_dismiss: 是否启动 Dialog Dismisser 后台线程
        """
        self.port = port
        self.timeout = timeout
        self._base_url = f"http://127.0.0.1:{port}"
        self.health = {}
        self._dismiss_thread = None
        self._dismiss_running = False
        self.last_jsx_error = None

        # 验证连接
        self._check_connection()

        # 可选: Dialog Dismisser
        if auto_dismiss:
            self.start_dismiss()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ── Connection ──────────────────────────────────────────

    def _check_connection(self):
        """验证 PyShiftAE HTTP 服务器可达"""
        try:
            req = urllib.request.Request(f'{self._base_url}/health')
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                if data.get('status') != 'ok':
                    raise ConnectionError("PyShiftAE health check failed")
                self.health = data
                server_version = str(data.get('bridge_version') or '')
                if server_version and server_version.split('.', 1)[0] != __version__.split('.', 1)[0]:
                    raise ConnectionError(
                        f"AE2Claude major version mismatch: client={__version__}, "
                        f"server={server_version}"
                    )
        except (urllib.error.URLError, OSError) as e:
            raise ConnectionError(
                f"Cannot connect to PyShiftAE on port {self.port}. "
                f"Make sure AE is running with PyShiftAE plugin loaded. "
                f"Error: {e}"
            )

    def close(self):
        """停止后台线程"""
        self._dismiss_running = False

    def reconnect(self):
        """重新验证连接 (AE 重启后调用)"""
        self._check_connection()

    # ── Core JSX Executor ──────────────────────────────────

    @staticmethod
    def _pin_request(path: str, payload: dict = None, timeout: float = 0.5) -> dict:
        data = None
        headers = {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(
            f'http://127.0.0.1:8891{path}', data=data, headers=headers
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    def _arm_script_dialog_watchdog(self, timeout_ms: int) -> Optional[str]:
        request_id = f'{threading.get_ident()}-{time.time_ns()}'
        try:
            self._pin_request(
                '/arm-script-dialog-watchdog',
                {
                    'request_id': request_id,
                    'timeout_ms': max(1000, min(120000, int(timeout_ms))),
                },
            )
            return request_id
        except Exception:
            return None

    def _script_dialog_watchdog_status(self, request_id: Optional[str]) -> Optional[dict]:
        if not request_id:
            return None
        try:
            status = self._pin_request('/script-dialog-watchdog-status')
        except Exception:
            return None
        return status if status.get('request_id') == request_id else None

    @staticmethod
    def dismiss_blocking_script_dialog(confirm: bool = False) -> dict:
        """Close only an AE #32770 script dialog through the independent CEP helper."""
        if not confirm:
            raise PermissionError('confirm=true required')
        return AEBridge._pin_request(
            '/dismiss-script-dialog', {'confirm': True}, timeout=3.0
        )

    def run_jsx(self, code: str, timeout: int = 60000) -> str:
        """
        通过 PyShiftAE AEGP_ExecuteScript 执行 ExtendScript 代码。

        Args:
            code: ExtendScript 代码字符串
            timeout: 超时毫秒数 (转换为秒用于 HTTP)

        Returns:
            ExtendScript 返回的字符串结果

        Raises:
            RuntimeError: 脚本执行出错
            ConnectionError: PyShiftAE 服务器不可达
        """
        request_id = self._arm_script_dialog_watchdog(timeout)
        data = _wrap_jsx_for_structured_errors(code).encode('utf-8')
        req = urllib.request.Request(
            f'{self._base_url}/jsx',
            data=data,
            headers={'Content-Type': 'text/plain; charset=utf-8'}
        )
        try:
            with urllib.request.urlopen(req, timeout=max(timeout / 1000, 5)) as resp:
                r = json.loads(resp.read())
        except (urllib.error.URLError, OSError) as e:
            recovery = self._script_dialog_watchdog_status(request_id)
            payload = {
                'ok': False,
                'kind': 'connection',
                'error': f'PyShiftAE request failed: {e}',
            }
            if recovery and recovery.get('dismissed'):
                payload['modal_recovery'] = recovery
            self.last_jsx_error = payload
            raise JSXExecutionError(payload) from e

        if r.get('ok'):
            result = r.get('result', '')
            try:
                guarded = json.loads(result) if isinstance(result, str) else None
            except (ValueError, TypeError):
                guarded = None
            if isinstance(guarded, dict) and _JSX_ERROR_KEY in guarded:
                r = dict(guarded, ok=False, kind='jsx', error=guarded[_JSX_ERROR_KEY])
            else:
                self.last_jsx_error = None
                return result
        payload = {
            'ok': False,
            'kind': r.get('kind', 'jsx'),
            'error': r.get('error', 'Unknown JSX error'),
        }
        for key in ('name', 'line', 'fileName', 'stack'):
            if r.get(key) is not None:
                payload[key] = r[key]
        recovery = self._script_dialog_watchdog_status(request_id)
        if recovery and recovery.get('dismissed'):
            payload['modal_recovery'] = recovery
        self.last_jsx_error = payload
        raise JSXExecutionError(payload)

    def run_jsx_checked(self, code: str, timeout: int = 60000,
                         expect: str = None) -> str:
        """
        执行 JSX 并检查结果。如果 expect 不为 None，结果不匹配时抛出异常。

        Args:
            code: ExtendScript 代码
            timeout: 超时毫秒数
            expect: 期望的返回值 (精确匹配)

        Returns:
            ExtendScript 结果字符串

        Raises:
            RuntimeError: 结果不匹配期望值
        """
        result = self.run_jsx(code, timeout)
        if expect is not None and result != expect:
            raise RuntimeError(
                f"JSX check failed: expected '{expect}', got '{result}'"
            )
        return result

    # ── Dialog Dismisser ───────────────────────────────────

    def start_dismiss(self):
        """启动 Dialog Dismisser 后台线程"""
        if self._dismiss_thread and self._dismiss_thread.is_alive():
            return
        self._dismiss_running = True
        self._dismiss_thread = threading.Thread(
            target=self._dialog_dismisser_loop, daemon=True
        )
        self._dismiss_thread.start()

    def stop_dismiss(self):
        """停止 Dialog Dismisser"""
        self._dismiss_running = False

    def _dialog_dismisser_loop(self):
        """后台循环: 自动关闭 AE 模态对话框"""
        if sys.platform != 'win32':
            return

        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32
        EnumWindows = user32.EnumWindows
        IsWindowVisible = user32.IsWindowVisible
        GetClassName = user32.GetClassNameW
        GetWindowThreadProcessId = user32.GetWindowThreadProcessId
        SetForegroundWindow = user32.SetForegroundWindow
        PostMessage = user32.PostMessageW
        WM_KEYDOWN, WM_KEYUP, VK_RETURN = 0x0100, 0x0101, 0x0D

        # 获取 AE PID
        ae_pid = self._find_ae_pid()

        WINFUNCTYPE = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
        )

        while self._dismiss_running:
            try:
                dialogs = []

                @WINFUNCTYPE
                def enum_cb(hwnd, lparam):
                    if not IsWindowVisible(hwnd):
                        return True
                    pid = ctypes.wintypes.DWORD()
                    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if ae_pid and pid.value != ae_pid:
                        return True
                    cls = ctypes.create_unicode_buffer(256)
                    GetClassName(hwnd, cls, 256)
                    if cls.value == '#32770':
                        dialogs.append(hwnd)
                    return True

                EnumWindows(enum_cb, 0)

                for hwnd in dialogs:
                    SetForegroundWindow(hwnd)
                    time.sleep(0.2)
                    PostMessage(hwnd, WM_KEYDOWN, VK_RETURN, 0)
                    PostMessage(hwnd, WM_KEYUP, VK_RETURN, 0)
                    time.sleep(0.5)
            except Exception:
                pass
            time.sleep(0.8)

    @staticmethod
    def _find_ae_pid() -> int:
        """查找 After Effects 进程 PID"""
        try:
            r = subprocess.run(
                ['powershell', '-c',
                 '(Get-Process | Where-Object '
                 '{$_.MainWindowTitle -like "*After Effects*"}).Id'],
                capture_output=True, text=True, timeout=5
            )
            if r.stdout.strip():
                return int(r.stdout.strip().split()[0])
        except Exception:
            pass
        return 0

    # ╔══════════════════════════════════════════════════════╗
    # ║              HIGH-LEVEL AE OPERATIONS               ║
    # ╚══════════════════════════════════════════════════════╝

    # ── Comp Info ──────────────────────────────────────────

    def comp_info(self) -> dict:
        """获取当前活动合成信息"""
        r = self.run_jsx(
            'var c=app.project.activeItem;'
            'c ? JSON.stringify({id:c.id,name:c.name,width:c.width,height:c.height,'
            'fps:1/c.frameDuration,duration:c.duration,numLayers:c.numLayers})'
            ': "null"'
        )
        if r == "null" or r == "undefined":
            return {}
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return {"raw": r}

    def project_info(self) -> dict:
        """获取项目信息"""
        r = self.run_jsx(
            'JSON.stringify({numItems:app.project.numItems,'
            'file:app.project.file?app.project.file.fsName:"unsaved"})'
        )
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return {"raw": r}

    # ── Undo Group ─────────────────────────────────────────

    def begin_undo(self, name: str = "Script"):
        """开始 undo 组"""
        self.run_jsx(f"app.beginUndoGroup({json.dumps(str(name), ensure_ascii=False)});")

    def end_undo(self):
        """结束 undo 组"""
        self.run_jsx('app.endUndoGroup();')

    # ── Layer Queries ──────────────────────────────────────

    def list_layers(self) -> List[dict]:
        """列出当前合成所有图层"""
        r = self.run_jsx(
            '(function(){var c=app.project.activeItem;'
            'if(!c || !(c instanceof CompItem))return "[]";var out=[];'
            'for(var i=1;i<=c.numLayers;i++){'
            'var l=c.layer(i);out.push({id:l.id,index:i,name:l.name,'
            'startTime:l.startTime,outPoint:l.outPoint,label:l.label});}'
            'return JSON.stringify(out);})()'
        )
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return []

    def get_layer_info(self, name: str) -> dict:
        """获取指定图层详细信息"""
        r = self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'JSON.stringify({{id:tl.id,name:tl.name,index:tl.index,'
            f'startTime:tl.startTime,outPoint:tl.outPoint,'
            f'inPoint:tl.inPoint,label:tl.label,'
            f'numEffects:tl.property("Effects").numProperties}});'
        )
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return {"raw": r}

    # ── Layer Management ───────────────────────────────────

    def remove_layer(self, name: str) -> str:
        """删除指定图层"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'try{{c.layer("{_esc(name)}").remove();"removed"}}'
            f'catch(e){{"ERR:"+e.toString()}}'
        )

    def rename_layer(self, old_name: str, new_name: str) -> str:
        """重命名图层"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(old_name)}").name="{_esc(new_name)}";'
            f'"renamed"'
        )

    def set_layer_label(self, name: str, label: int) -> str:
        """设置图层标签颜色 (0-16)"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(name)}").label={label};"ok"'
        )

    def set_layer_timing(self, name: str, start: float = None,
                          end: float = None) -> str:
        """设置图层的起止时间"""
        parts = ['var c=app.project.activeItem;',
                  f'var tl=c.layer("{_esc(name)}");']
        if start is not None:
            parts.append(f'tl.startTime={start};')
        if end is not None:
            parts.append(f'tl.outPoint={end};')
        parts.append('"ok"')
        return self.run_jsx(''.join(parts))

    # ── Text Layers ────────────────────────────────────────

    def add_text_layer(self, text: str, name: str = None) -> str:
        """
        Create a text layer. Returns the layer name.

        Use set_text_style() to configure font/color/size after creation.
        Use set_layer_timing() to set in/out points.
        Use set_layer_label() to set label color.

        Args:
            text: Text content
            name: Layer name (defaults to first 20 chars of text)
        """
        safe_txt = _esc(text)
        layer_name = _esc(name or text[:20])
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layers.addText("{safe_txt}");'
            f'tl.name="{layer_name}";'
            f'tl.name;'
        )
        return self.run_jsx(jsx)

    def add_solid(self, name: str, color: List[float],
                  width: int = None, height: int = None) -> str:
        """
        Create a solid layer. Returns the layer name.

        Args:
            name: Layer name
            color: [r, g, b] in 0-1 range
            width: Solid width (defaults to comp width)
            height: Solid height (defaults to comp height)
        """
        safe_name = _esc(name)
        jsx = (
            f'var c=app.project.activeItem;'
            f'var w={width if width else "c.width"};'
            f'var h={height if height else "c.height"};'
            f'var sl=c.layers.addSolid([{color[0]},{color[1]},{color[2]}],'
            f'"{safe_name}",w,h,c.pixelAspect,c.duration);'
            f'sl.name;'
        )
        return self.run_jsx(jsx)

    def center_anchor(self, name: str, at_time: float = 0) -> str:
        """将图层锚点居中 (基于 sourceRectAtTime)"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var rect=tl.sourceRectAtTime({at_time},false);'
            f'var ax=rect.left+rect.width/2;var ay=rect.top+rect.height/2;'
            f'tl.property("Transform").property("Anchor Point").setValue([ax,ay]);'
            f'"centered"'
        )

    # ── Keyframes ──────────────────────────────────────────

    def set_keyframes(self, name: str, prop: str,
                      keyframes: List[Tuple[float, Any]]) -> str:
        """
        Set keyframes on a transform property.

        Args:
            name: Layer name
            prop: Semantic property name ("position", "opacity", "scale",
                  "rotation", "anchor_point")
            keyframes: [(time_sec, value), ...]
                       position: [x, y] or [x, y, z]
                       scale: [sx, sy, sz] (sz defaults to 100 if 2D given)
                       opacity/rotation: single number
        """
        path = _resolve_prop(prop)
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var p=tl.{path};'
        )
        for t, val in keyframes:
            if prop == "scale" and isinstance(val, (list, tuple)) and len(val) == 2:
                val = list(val) + [100]
            if isinstance(val, (list, tuple)):
                jsx += f'p.setValueAtTime({t},{json.dumps(val)});'
            else:
                jsx += f'p.setValueAtTime({t},{val});'
        jsx += '"ok"'
        return self.run_jsx(jsx)

    def set_value(self, name: str, prop: str, value: Any,
                  at_time: float = None) -> str:
        """
        Set a transform property value (static or at specific time).

        Args:
            name: Layer name
            prop: Semantic property name
            value: The value to set
            at_time: If provided, sets value at this time (creates keyframe).
                     If None, sets static value.
        """
        path = _resolve_prop(prop)
        if prop == "scale" and isinstance(value, (list, tuple)) and len(value) == 2:
            value = list(value) + [100]
        val_str = json.dumps(value) if isinstance(value, (list, tuple)) else str(value)
        if at_time is not None:
            jsx = (
                f'var c=app.project.activeItem;'
                f'var tl=c.layer("{_esc(name)}");'
                f'tl.{path}.setValueAtTime({at_time},{val_str});'
                f'"ok"'
            )
        else:
            jsx = (
                f'var c=app.project.activeItem;'
                f'var tl=c.layer("{_esc(name)}");'
                f'tl.{path}.setValue({val_str});'
                f'"ok"'
            )
        return self.run_jsx(jsx)

    # ── Easing ─────────────────────────────────────────────

    def apply_transform_easing(self, name: str, prop: str,
                                speed: float = 0, influence: float = 80) -> str:
        """
        Apply easing to all keyframes of a single transform property.

        Args:
            name: Layer name
            prop: Semantic property name ("opacity", "position", "scale", "rotation", "anchor_point")
            speed: KeyframeEase speed (usually 0 for ease in/out)
            influence: KeyframeEase influence (33-100, default 80)
        """
        info = TRANSFORM_PROPS.get(prop)
        if not info:
            raise ValueError(
                f"Unknown transform property '{prop}'. "
                f"Available: {list(TRANSFORM_PROPS.keys())}"
            )
        dims = info["ease_dims"]
        ease_in = ",".join([f"new KeyframeEase({speed},{influence})"] * dims)
        ease_out = ",".join([f"new KeyframeEase({speed},{influence})"] * dims)
        path = info["path"]

        jsx = (
            f'try{{'
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var _p=tl.{path};'
            f'for(var k=1;k<=_p.numKeys;k++)'
            f'_p.setTemporalEaseAtKey(k,[{ease_in}],[{ease_out}]);'
            f'"ease_ok";'
            f'}}catch(e){{"EASE_ERR:"+e.toString()+" L:"+e.line;}}'
        )
        return self.run_jsx(jsx)

    def apply_effect_easing(self, name: str, effect_index: int,
                             prop_key: str, speed: float = 0,
                             influence: float = 80) -> str:
        """
        Apply easing to all keyframes of an effect property.

        Args:
            name: Layer name
            effect_index: 1-based effect index
            prop_key: Property key from EFFECTS registry
            speed: KeyframeEase speed
            influence: KeyframeEase influence
        """
        mn = self._resolve_effect_prop(prop_key)
        if mn is None:
            raise ValueError(f"Unknown effect prop_key '{prop_key}'")

        return self.run_jsx(
            f'try{{'
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var ef=tl.property("Effects").property({effect_index});'
            f'if(!ef){{"ERR:effect_not_found"}}else{{'
            f'var eI=new KeyframeEase({speed},{influence});'
            f'var eO=new KeyframeEase({speed},{influence});'
            f'var p=ef.property("{mn}");'
            f'for(var k=1;k<=p.numKeys;k++)'
            f'p.setTemporalEaseAtKey(k,[eI],[eO]);'
            f'"fx_ease_ok";}}'
            f'}}catch(e){{"FX_EASE_ERR:"+e.toString()+" L:"+e.line;}}'
        )

    # ── Effects ────────────────────────────────────────────

    def add_effect(self, name: str, effect_type: str) -> int:
        """
        Add an effect to a layer. Returns the effect's 1-based index.

        Args:
            name: Layer name
            effect_type: Effect type key from EFFECTS registry (e.g. "gaussian_blur")
        Returns:
            effect_index (int) — use this for all subsequent effect operations
        """
        fx = EFFECTS.get(effect_type)
        if not fx:
            raise ValueError(f"Unknown effect '{effect_type}'. Available: {list(EFFECTS.keys())}")
        result = self.add_effect_by_match_name(name, fx["matchName"])
        return int(result["index"])

    def add_effect_by_match_name(self, name: str, match_name: str) -> dict:
        """Add any installed effect by its locale-independent matchName.

        This is the generic counterpart to :meth:`add_effect`, whose semantic
        aliases intentionally cover only a small curated set. The effect group
        is checked with ``canAddProperty`` first and the returned index is the
        stable handle callers should retain after adding more effects.
        """
        if not match_name.strip():
            raise ValueError("match_name must not be empty")
        layer_json = json.dumps(name, ensure_ascii=False)
        match_json = json.dumps(match_name, ensure_ascii=False)
        jsx = (
            '(function(){'
            'var undoOpen=false;'
            'try{'
            'var c=app.project.activeItem;'
            'if(!c||!(c instanceof CompItem))return JSON.stringify({error:"no_active_comp"});'
            f'var tl=c.layer({layer_json});'
            'if(!tl)return JSON.stringify({error:"layer_not_found"});'
            'var group=tl.property("ADBE Effect Parade");'
            f'var mn={match_json};'
            'if(!group.canAddProperty(mn))return JSON.stringify({error:"effect_not_available",matchName:mn});'
            'app.beginUndoGroup("AE2Claude Add Effect");undoOpen=true;'
            'var effect=group.addProperty(mn);'
            'var result={index:effect.propertyIndex,name:effect.name,matchName:effect.matchName};'
            'app.endUndoGroup();undoOpen=false;'
            'return JSON.stringify(result);'
            '}catch(e){'
            'if(undoOpen){try{app.endUndoGroup();}catch(x){}}'
            'return JSON.stringify({error:e.toString(),line:e.line||null});'
            '}'
            '})()'
        )
        r = self.run_jsx(jsx)
        try:
            result = json.loads(r)
        except json.JSONDecodeError as exc:
            raise RuntimeError(r) from exc
        if not isinstance(result, dict) or result.get("error"):
            raise RuntimeError(str(result))
        return result

    def set_effect_property(self, name: str, effect_index: int,
                            property_match_name: str, value: Any,
                            at_time: float = None) -> dict:
        """Set an effect property by matchName, including nested properties."""
        if not property_match_name.strip():
            raise ValueError("property_match_name must not be empty")
        layer_json = json.dumps(name, ensure_ascii=False)
        prop_json = json.dumps(property_match_name, ensure_ascii=False)
        value_json = json.dumps(value, ensure_ascii=False)
        set_call = (
            f'p.setValueAtTime({float(at_time)},{value_json});'
            if at_time is not None
            else f'p.setValue({value_json});'
        )
        jsx = (
            '(function(){'
            'function find(group,mn){'
            'for(var i=1;i<=group.numProperties;i++){'
            'var child=group.property(i);'
            'if(child.matchName==mn)return child;'
            'if(child.numProperties>0){var nested=find(child,mn);if(nested)return nested;}'
            '}return null;}'
            'var undoOpen=false;'
            'try{'
            'var c=app.project.activeItem;'
            'if(!c||!(c instanceof CompItem))return JSON.stringify({error:"no_active_comp"});'
            f'var layer=c.layer({layer_json});'
            'if(!layer)return JSON.stringify({error:"layer_not_found"});'
            f'var effect=layer.property("ADBE Effect Parade").property({int(effect_index)});'
            'if(!effect)return JSON.stringify({error:"effect_not_found"});'
            f'var p=find(effect,{prop_json});'
            'if(!p)return JSON.stringify({error:"property_not_found"});'
            'app.beginUndoGroup("AE2Claude Set Effect Property");undoOpen=true;'
            + set_call +
            'app.endUndoGroup();undoOpen=false;'
            'var current;try{current=p.value;}catch(x){current=null;}'
            'return JSON.stringify({ok:true,effectIndex:effect.propertyIndex,'
            'propertyName:p.name,propertyMatchName:p.matchName,value:current});'
            '}catch(e){'
            'if(undoOpen){try{app.endUndoGroup();}catch(x){}}'
            'return JSON.stringify({error:e.toString(),line:e.line||null});'
            '}'
            '})()'
        )
        r = self.run_jsx(jsx)
        try:
            result = json.loads(r)
        except json.JSONDecodeError as exc:
            raise RuntimeError(r) from exc
        if not isinstance(result, dict) or result.get("error"):
            raise RuntimeError(str(result))
        return result

    def get_effect_property(self, name: str, effect_index: int,
                            property_match_name: str,
                            at_time: float = None) -> dict:
        """Read an effect property by matchName, including nested properties."""
        if not property_match_name.strip():
            raise ValueError("property_match_name must not be empty")
        layer_json = json.dumps(name, ensure_ascii=False)
        prop_json = json.dumps(property_match_name, ensure_ascii=False)
        read_expr = (
            f'p.valueAtTime({float(at_time)},false)'
            if at_time is not None
            else 'p.value'
        )
        jsx = (
            '(function(){'
            'function find(group,mn){'
            'for(var i=1;i<=group.numProperties;i++){'
            'var child=group.property(i);'
            'if(child.matchName==mn)return child;'
            'if(child.numProperties>0){var nested=find(child,mn);if(nested)return nested;}'
            '}return null;}'
            'try{'
            'var c=app.project.activeItem;'
            'if(!c||!(c instanceof CompItem))return JSON.stringify({error:"no_active_comp"});'
            f'var layer=c.layer({layer_json});'
            'if(!layer)return JSON.stringify({error:"layer_not_found"});'
            f'var effect=layer.property("ADBE Effect Parade").property({int(effect_index)});'
            'if(!effect)return JSON.stringify({error:"effect_not_found"});'
            f'var p=find(effect,{prop_json});'
            'if(!p)return JSON.stringify({error:"property_not_found"});'
            f'var value={read_expr};'
            'return JSON.stringify({effectIndex:effect.propertyIndex,'
            'propertyName:p.name,propertyMatchName:p.matchName,value:value});'
            '}catch(e){return JSON.stringify({error:e.toString(),line:e.line||null});}'
            '})()'
        )
        r = self.run_jsx(jsx)
        try:
            result = json.loads(r)
        except json.JSONDecodeError as exc:
            raise RuntimeError(r) from exc
        if not isinstance(result, dict) or result.get("error"):
            raise RuntimeError(str(result))
        return result

    def set_effect_props(self, name: str, effect_index: int,
                         props: Dict[str, Any]) -> str:
        """
        Set static property values on an effect.

        Args:
            name: Layer name
            effect_index: 1-based effect index (from add_effect or enumerate_effects)
            props: {prop_key: value} — prop_key from EFFECTS registry
        """
        jsx = (
            f'try{{'
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var ef=tl.property("Effects").property({effect_index});'
            f'if(!ef){{"ERR:effect_not_found"}}else{{'
        )
        for key, val in props.items():
            mn = self._resolve_effect_prop(key)
            if mn is None:
                continue
            if isinstance(val, (list, tuple)):
                jsx += f'ef.property("{mn}").setValue({json.dumps(val)});'
            else:
                jsx += f'ef.property("{mn}").setValue({val});'
        jsx += '"ok";}'
        jsx += '}catch(e){"FX_ERR:"+e.toString()}'
        return self.run_jsx(jsx)

    def set_effect_keyframes(self, name: str, effect_index: int,
                              keyframes: Dict[str, List[Tuple[float, Any]]]) -> str:
        """
        Set keyframes on effect properties.

        Args:
            name: Layer name
            effect_index: 1-based effect index
            keyframes: {prop_key: [(time, value), ...]}
        """
        jsx = (
            f'try{{'
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var ef=tl.property("Effects").property({effect_index});'
            f'if(!ef){{"ERR:effect_not_found"}}else{{'
        )
        for key, kfs in keyframes.items():
            mn = self._resolve_effect_prop(key)
            if mn is None:
                continue
            for t, val in kfs:
                if isinstance(val, (list, tuple)):
                    jsx += f'ef.property("{mn}").setValueAtTime({t},{json.dumps(val)});'
                else:
                    jsx += f'ef.property("{mn}").setValueAtTime({t},{val});'
        jsx += '"ok";}'
        jsx += '}catch(e){"FX_ERR:"+e.toString()}'
        return self.run_jsx(jsx)

    def enumerate_effects(self, name: str) -> List[dict]:
        """列出图层上的所有效果"""
        r = self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var fx=tl.property("Effects");var out=[];'
            f'for(var i=1;i<=fx.numProperties;i++){{'
            f'var e=fx.property(i);out.push({{index:i,name:e.name,matchName:e.matchName}});}}'
            f'JSON.stringify(out);'
        )
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return []

    # ── Expressions ────────────────────────────────────────

    def set_expression(self, name: str, prop_path: str, expr: str) -> str:
        """设置属性表达式"""
        safe_expr = _esc(expr)
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'tl.{prop_path}.expression="{safe_expr}";'
            f'"expr_ok"'
        )

    def clear_expression(self, name: str, prop_path: str) -> str:
        """清除属性表达式"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'tl.{prop_path}.expression="";'
            f'"cleared"'
        )

    # ── Import ─────────────────────────────────────────────

    def import_file(self, filepath: str, as_sequence: bool = False,
                     conform_fps: float = None) -> str:
        """
        导入文件 (footage/图片序列)。

        Args:
            filepath: 文件路径 (使用正斜杠)
            as_sequence: 是否作为图片序列导入
            conform_fps: 强制帧率 (导入后设置)
        """
        safe_path = filepath.replace('\\', '/')
        jsx = (
            f'var f=new File("{safe_path}");'
            f'if(!f.exists){{"NOT_FOUND"}}else{{'
            f'var io=new ImportOptions(f);'
        )
        if as_sequence:
            jsx += 'io.sequence=true;'
        jsx += 'var it=app.project.importFile(io);'
        if conform_fps:
            jsx += f'it.mainSource.conformFrameRate={conform_fps};'
        jsx += '"OK:"+it.name+",dur="+it.duration;}'
        return self.run_jsx(jsx, timeout=120000)

    # ── Render Queue ───────────────────────────────────────

    def add_to_render_queue(self, comp_name: str = None,
                             output_path: str = None,
                             template: str = None) -> str:
        """将合成添加到渲染队列"""
        jsx = 'var c=app.project.activeItem;'
        if comp_name:
            jsx = (
                f'var c=null;for(var i=1;i<=app.project.numItems;i++){{'
                f'var it=app.project.item(i);'
                f'if(it instanceof CompItem&&it.name=="{_esc(comp_name)}"){{c=it;break;}}}}'
            )
        jsx += 'if(!c){"no_comp"}else{'
        jsx += 'var rqi=app.project.renderQueue.items.add(c);'
        if output_path:
            safe_path = output_path.replace('\\', '/')
            jsx += f'rqi.outputModule(1).file=new File("{safe_path}");'
        if template:
            jsx += f'rqi.outputModule(1).applyTemplate("{template}");'
        jsx += '"queued";}'
        return self.run_jsx(jsx)

    # ── Composition Management ─────────────────────────────

    def create_comp(self, name: str, width: int, height: int,
                     fps: float = 30, duration: float = 10,
                     bg_color: List[float] = None) -> str:
        """创建新合成"""
        jsx = (
            f'var c=app.project.items.addComp("{_esc(name)}",'
            f'{width},{height},1,{duration},{fps});'
        )
        if bg_color:
            jsx += f'c.bgColor=[{bg_color[0]},{bg_color[1]},{bg_color[2]}];'
        jsx += 'c.openInViewer();c.name;'
        return self.run_jsx(jsx)

    def set_active_comp(self, name: str) -> str:
        """通过名称查找并打开合成"""
        return self.run_jsx(
            f'var found=false;for(var i=1;i<=app.project.numItems;i++){{'
            f'var it=app.project.item(i);'
            f'if(it instanceof CompItem&&it.name=="{_esc(name)}"){{it.openInViewer();found=true;break;}}}}'
            f'found?"opened":"not_found"'
        )

    # ── Utility: Execute Raw JSX File ──────────────────────

    def exec_jsx_file(self, filepath: str) -> str:
        """
        读取本地 JSX 文件并通过 HTTP 执行。
        不使用 $.evalFile() (在 AE Beta 中不稳定)，
        而是直接读取文件内容并作为 run_jsx 字符串发送。
        """
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            code = f.read()
        return self.run_jsx(code)

    # ── Effect Introspection ──────────────────────────────

    def list_available_effects(self) -> dict:
        """Return AE's complete live effect inventory without mutating a comp.

        ``app.effects`` is the authoritative application-level catalog and
        exposes the localized display name, localized category, stable
        matchName, and internal version for every installed effect. Unlike the
        legacy probe list, this works without an active composition and also
        discovers third-party and pseudo effects.
        """
        jsx = (
            '(function(){try{'
            'var out=[];var effects=app.effects||[];'
            'for(var i=0;i<effects.length;i++){var effect=effects[i];'
            'out.push({displayName:effect.displayName||"",'
            'matchName:effect.matchName||"",category:effect.category||"",'
            'version:effect.version||""});}'
            'return JSON.stringify(out);'
            '}catch(e){return JSON.stringify({error:e.toString(),line:e.line||null});}})()'
        )
        r = self.run_jsx(jsx, timeout=30000)
        try:
            data = json.loads(r)
        except json.JSONDecodeError:
            return {"error": r, "count": 0, "effects": []}
        if isinstance(data, dict) and data.get("error"):
            return {**data, "count": 0, "effects": []}
        if not isinstance(data, list):
            return {"error": "invalid_effect_inventory", "count": 0, "effects": []}

        unique: dict[tuple[str, str, str, str], dict[str, str]] = {}
        for effect in data:
            if not isinstance(effect, dict):
                continue
            normalized = {
                "displayName": str(effect.get("displayName", "")),
                "matchName": str(effect.get("matchName", "")),
                "category": str(effect.get("category", "")),
                "version": str(effect.get("version", "")),
            }
            key = (
                normalized["matchName"],
                normalized["displayName"],
                normalized["category"],
                normalized["version"],
            )
            unique[key] = normalized

        effects = sorted(
            unique.values(),
            key=lambda item: (
                item["category"].casefold(),
                item["displayName"].casefold(),
                item["matchName"].casefold(),
            ),
        )
        categories: dict[str, int] = {}
        for effect in effects:
            category = effect["category"] or "(hidden)"
            categories[category] = categories.get(category, 0) + 1
        return {
            "count": len(effects),
            "categoryCount": len(categories),
            "categories": categories,
            "effects": effects,
        }

    def search_effects(self, query: str = "", category: str = "",
                       include_hidden: bool = False, offset: int = 0,
                       limit: int = 100) -> dict:
        """Search and paginate the live effect inventory."""
        inventory = self.list_available_effects()
        if inventory.get("error"):
            return inventory
        query_key = query.strip().casefold()
        category_key = category.strip().casefold()
        matches = []
        for effect in inventory["effects"]:
            if not include_hidden and not effect["category"]:
                continue
            if category_key and effect["category"].casefold() != category_key:
                continue
            haystack = " ".join(
                (
                    effect["displayName"],
                    effect["matchName"],
                    effect["category"],
                    effect["version"],
                )
            ).casefold()
            if query_key and query_key not in haystack:
                continue
            matches.append(effect)

        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 500))
        return {
            "query": query,
            "category": category or None,
            "includeHidden": bool(include_hidden),
            "offset": offset,
            "limit": limit,
            "total": len(matches),
            "effects": matches[offset:offset + limit],
        }

    def describe_effect(self, match_name: str) -> dict:
        """
        自省指定效果的所有属性。
        临时添加效果到 probe solid，递归遍历属性树，返回结构化元数据后 undo。
        """
        match_json = json.dumps(match_name, ensure_ascii=False)
        jsx = (
            '(function(){'
            'var c=app.project.activeItem;'
            'if(!c||!(c instanceof CompItem))return JSON.stringify({error:"No active comp"});'
            'app.beginUndoGroup("__describe__");'
            'try{'
            'var solid=c.layers.addSolid([0,0,0],"__describe__",10,10,1);'
            'var efxG=solid.property("Effects");'
            'var mn=' + match_json + ';'
            'if(!efxG.canAddProperty(mn)){'
            'solid.remove();app.endUndoGroup();app.executeCommand(16);'
            'return JSON.stringify({error:"Effect not available",matchName:mn});}'
            'var eff=efxG.addProperty(mn);'
            'var VT={};'
            'VT[PropertyValueType.NO_VALUE]="NO_VALUE";'
            'VT[PropertyValueType.ThreeD_SPATIAL]="3D_SPATIAL";'
            'VT[PropertyValueType.ThreeD]="3D";'
            'VT[PropertyValueType.TwoD_SPATIAL]="2D_SPATIAL";'
            'VT[PropertyValueType.TwoD]="2D";'
            'VT[PropertyValueType.OneD]="1D";'
            'VT[PropertyValueType.COLOR]="COLOR";'
            'VT[PropertyValueType.CUSTOM_VALUE]="CUSTOM";'
            'VT[PropertyValueType.MARKER]="MARKER";'
            'VT[PropertyValueType.LAYER_INDEX]="LAYER_INDEX";'
            'VT[PropertyValueType.MASK_INDEX]="MASK_INDEX";'
            'VT[PropertyValueType.SHAPE]="SHAPE";'
            'VT[PropertyValueType.TEXT_DOCUMENT]="TEXT_DOCUMENT";'
            'var props=[];'
            'function walk(g,d){'
            'for(var i=1;i<=g.numProperties;i++){'
            'var p=g.property(i);'
            'var o={name:p.name,matchName:p.matchName,index:i,depth:d};'
            'if(p.propertyType==PropertyType.PROPERTY){'
            'o.valueType=VT[p.propertyValueType]||"UNKNOWN";'
            'o.canVaryOverTime=p.canVaryOverTime;'
            'try{if(p.propertyValueType!=PropertyValueType.NO_VALUE&&'
            'p.propertyValueType!=PropertyValueType.CUSTOM_VALUE){'
            'var v=p.value;'
            'if(typeof v=="object"&&v.length!==undefined){'
            'o.value=[];for(var j=0;j<v.length;j++)o.value.push(v[j]);'
            '}else{o.value=v;}}}catch(x){}'
            'try{o.minValue=p.minValue;}catch(x){}'
            'try{o.maxValue=p.maxValue;}catch(x){}'
            '}else if(p.numProperties>0){'
            'o.numChildren=p.numProperties;}'
            'props.push(o);'
            'if(p.numProperties>0&&p.propertyType!=PropertyType.PROPERTY){'
            'walk(p,d+1);}}}'
            'walk(eff,0);'
            'var result={displayName:eff.name,matchName:eff.matchName,'
            'numProperties:eff.numProperties,properties:props};'
            'solid.remove();app.endUndoGroup();app.executeCommand(16);'
            'return JSON.stringify(result);'
            '}catch(e){'
            'try{app.endUndoGroup();}catch(x){}'
            'try{app.executeCommand(16);}catch(x){}'
            'return JSON.stringify({error:e.toString()});'
            '}'
            '})()'
        )
        r = self.run_jsx(jsx, timeout=60000)
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return {"error": r}

    # ── Stable ID Addressing ──────────────────────────────

    def list_comps(self) -> list:
        """列出项目中所有合成 (含 stable id)"""
        r = self.run_jsx(
            'var out=[];for(var i=1;i<=app.project.numItems;i++){'
            'var it=app.project.item(i);'
            'if(it instanceof CompItem)out.push({id:it.id,name:it.name,'
            'width:it.width,height:it.height,duration:it.duration});}'
            'JSON.stringify(out);'
        )
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return []

    def set_active_comp_by_id(self, comp_id: int) -> str:
        """通过 stable ID 查找并打开合成"""
        return self.run_jsx(
            'try{var c=app.project.itemByID(' + str(int(comp_id)) + ');'
            'if(c instanceof CompItem){c.openInViewer();"opened:"+c.name}'
            'else{"not_a_comp"}}'
            'catch(e){"not_found"}'
        )

    def get_layer_by_id(self, layer_id: int, comp_id: int = None) -> dict:
        """通过 stable ID 查找图层 (避免名称重复/索引漂移)"""
        comp_jsx = (
            'app.project.itemByID(' + str(int(comp_id)) + ')'
            if comp_id else 'app.project.activeItem'
        )
        r = self.run_jsx(
            'var c=' + comp_jsx + ';'
            'if(!c||!(c instanceof CompItem))JSON.stringify({error:"no comp"});else{'
            'var found=null;for(var i=1;i<=c.numLayers;i++){'
            'if(c.layer(i).id==' + str(int(layer_id)) + '){found=c.layer(i);break;}}'
            'found?JSON.stringify({id:found.id,index:found.index,name:found.name,'
            'startTime:found.startTime,outPoint:found.outPoint,label:found.label})'
            ':JSON.stringify({error:"layer not found"})}'
        )
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return {"error": r}

    # ── Property Read-back ─────────────────────────────────

    def get_value(self, name: str, prop: str, at_time: float = None) -> Any:
        """
        Read a transform property value.

        Args:
            name: Layer name
            prop: Semantic property name ("position", "opacity", "scale",
                  "rotation", "anchor_point")
            at_time: Time in seconds (None = current comp time)
        """
        path = _resolve_prop(prop)
        if at_time is not None:
            jsx = (
                f'var c=app.project.activeItem;'
                f'var tl=c.layer("{_esc(name)}");'
                f'var p=tl.{path};'
                f'var v=p.valueAtTime({at_time},true);'
                f'JSON.stringify(v);'
            )
        else:
            jsx = (
                f'var c=app.project.activeItem;'
                f'var tl=c.layer("{_esc(name)}");'
                f'var p=tl.{path};'
                f'JSON.stringify(p.value);'
            )
        r = self.run_jsx(jsx)
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return r

    def get_keyframes(self, name: str, prop: str) -> List[Tuple[float, Any]]:
        """
        Read all keyframes of a transform property.

        Args:
            name: Layer name
            prop: Semantic property name
        Returns:
            [(time_sec, value), ...]
        """
        path = _resolve_prop(prop)
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var p=tl.{path};'
            f'var out=[];'
            f'for(var k=1;k<=p.numKeys;k++){{'
            f'out.push([p.keyTime(k),p.keyValue(k)]);'
            f'}}JSON.stringify(out);'
        )
        r = self.run_jsx(jsx)
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return []

    def get_effect_param(self, name: str, effect_index: int,
                          prop_key: str) -> Any:
        """
        Read an effect property value.

        Args:
            name: Layer name
            effect_index: 1-based effect index
            prop_key: Property key from EFFECTS registry
        """
        mn = self._resolve_effect_prop(prop_key)
        if mn is None:
            raise ValueError(f"Unknown effect prop_key '{prop_key}'")
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var ef=tl.property("Effects").property({effect_index});'
            f'if(!ef)"ERR:effect_not_found";'
            f'else{{var v=ef.property("{mn}").value;JSON.stringify(v);}}'
        )
        r = self.run_jsx(jsx)
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return r

    def get_effect_keyframes(self, name: str, effect_index: int,
                              prop_key: str) -> List[Tuple[float, Any]]:
        """
        Read keyframes of an effect property.

        Args:
            name: Layer name
            effect_index: 1-based effect index
            prop_key: Property key from EFFECTS registry
        """
        mn = self._resolve_effect_prop(prop_key)
        if mn is None:
            raise ValueError(f"Unknown effect prop_key '{prop_key}'")
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var ef=tl.property("Effects").property({effect_index});'
            f'if(!ef)"ERR:effect_not_found";else{{'
            f'var p=ef.property("{mn}");var out=[];'
            f'for(var k=1;k<=p.numKeys;k++){{'
            f'out.push([p.keyTime(k),p.keyValue(k)]);'
            f'}}JSON.stringify(out);}}'
        )
        r = self.run_jsx(jsx)
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return []

    # ── Shape Layers ───────────────────────────────────────

    def add_shape_layer(self, name: str = "Shape Layer", label: int = None) -> str:
        """创建空 Shape 图层"""
        jsx = (
            f'var c=app.project.activeItem;'
            f'var sl=c.layers.addShape();'
            f'sl.name="{_esc(name)}";'
        )
        if label is not None:
            jsx += f'sl.label={label};'
        jsx += 'sl.name;'
        return self.run_jsx(jsx)

    def add_shape_rect(self, name: str, size: List[float] = None,
                        position: List[float] = None, roundness: float = 0,
                        group_index: int = None) -> str:
        """在 Shape 图层中添加矩形。"""
        size = size or [100, 100]
        position = position or [0, 0]
        group_sel = (
            f'var grp=contents.property({group_index});'
            if group_index else
            'var grp=contents.addProperty("ADBE Vector Group");grp.name="Rectangle";'
        )
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var contents=tl.property("Contents");'
            f'{group_sel}'
            f'var rect=grp.property("Contents").addProperty("ADBE Vector Shape - Rect");'
            f'rect.property("Size").setValue({json.dumps(size)});'
            f'rect.property("Position").setValue({json.dumps(position)});'
            f'rect.property("Roundness").setValue({roundness});'
            f'"ok";'
        )
        return self.run_jsx(jsx)

    def add_shape_ellipse(self, name: str, size: List[float] = None,
                           position: List[float] = None,
                           group_index: int = None) -> str:
        """在 Shape 图层中添加椭圆"""
        size = size or [100, 100]
        position = position or [0, 0]
        group_sel = (
            f'var grp=contents.property({group_index});'
            if group_index else
            'var grp=contents.addProperty("ADBE Vector Group");grp.name="Ellipse";'
        )
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var contents=tl.property("Contents");'
            f'{group_sel}'
            f'var el=grp.property("Contents").addProperty("ADBE Vector Shape - Ellipse");'
            f'el.property("Size").setValue({json.dumps(size)});'
            f'el.property("Position").setValue({json.dumps(position)});'
            f'"ok";'
        )
        return self.run_jsx(jsx)

    def add_shape_path(self, name: str, vertices: List[List[float]],
                        in_tangents: List[List[float]] = None,
                        out_tangents: List[List[float]] = None,
                        closed: bool = True,
                        group_index: int = None) -> str:
        """在 Shape 图层中添加自定义路径。"""
        n = len(vertices)
        in_t = in_tangents or [[0, 0]] * n
        out_t = out_tangents or [[0, 0]] * n
        group_sel = (
            f'var grp=contents.property({group_index});'
            if group_index else
            'var grp=contents.addProperty("ADBE Vector Group");grp.name="Path";'
        )
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var contents=tl.property("Contents");'
            f'{group_sel}'
            f'var pathProp=grp.property("Contents").addProperty("ADBE Vector Shape - Group");'
            f'var shape=new Shape();'
            f'shape.vertices={json.dumps(vertices)};'
            f'shape.inTangents={json.dumps(in_t)};'
            f'shape.outTangents={json.dumps(out_t)};'
            f'shape.closed={"true" if closed else "false"};'
            f'pathProp.property("Path").setValue(shape);'
            f'"ok";'
        )
        return self.run_jsx(jsx)

    def add_shape_fill(self, name: str, color: List[float] = None,
                        opacity: float = 100, group_index: int = 1) -> str:
        """添加 Shape 填充"""
        color = color or [1, 1, 1]
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var grp=tl.property("Contents").property({group_index});'
            f'var fill=grp.property("Contents").addProperty("ADBE Vector Graphic - Fill");'
            f'fill.property("Color").setValue({json.dumps(color)});'
            f'fill.property("Opacity").setValue({opacity});'
            f'"ok";'
        )
        return self.run_jsx(jsx)

    def add_shape_stroke(self, name: str, color: List[float] = None,
                          width: float = 2, opacity: float = 100,
                          group_index: int = 1) -> str:
        """添加 Shape 描边"""
        color = color or [1, 1, 1]
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var grp=tl.property("Contents").property({group_index});'
            f'var stroke=grp.property("Contents").addProperty("ADBE Vector Graphic - Stroke");'
            f'stroke.property("Color").setValue({json.dumps(color)});'
            f'stroke.property("Stroke Width").setValue({width});'
            f'stroke.property("Opacity").setValue({opacity});'
            f'"ok";'
        )
        return self.run_jsx(jsx)

    # ── Pre-compose ────────────────────────────────────────

    def precompose(self, layer_names: List[str], comp_name: str = "PreComp",
                    move_attrs: bool = True) -> str:
        """将指定图层预合成。"""
        select_jsx = (
            'var c=app.project.activeItem;'
            'for(var i=1;i<=c.numLayers;i++)c.layer(i).selected=false;'
        )
        for ln in layer_names:
            select_jsx += f'try{{c.layer("{_esc(ln)}").selected=true;}}catch(e){{}}'
        select_jsx += (
            'var idxs=[];for(var i=1;i<=c.numLayers;i++){'
            'if(c.layer(i).selected)idxs.push(i);}'
        )
        move_flag = 1 if move_attrs else 2
        select_jsx += (
            f'if(idxs.length>0){{'
            f'c.layers.precompose(idxs,"{_esc(comp_name)}",{move_flag});"ok"}}'
            f'else{{"no_layers_selected"}}'
        )
        return self.run_jsx(select_jsx)

    def precompose_by_index(self, indices: List[int], comp_name: str = "PreComp",
                             move_attrs: bool = True) -> str:
        """将指定索引的图层预合成"""
        move_flag = 1 if move_attrs else 2
        jsx = (
            f'var c=app.project.activeItem;'
            f'c.layers.precompose({json.dumps(indices)},"{_esc(comp_name)}",{move_flag});'
            f'"ok";'
        )
        return self.run_jsx(jsx)

    def list_precomps(self) -> List[dict]:
        """列出项目中所有合成及是否被用作预合成"""
        r = self.run_jsx(
            'var out=[];for(var i=1;i<=app.project.numItems;i++){'
            'var it=app.project.item(i);'
            'if(it instanceof CompItem){var used=false;'
            'for(var j=1;j<=app.project.numItems&&!used;j++){'
            'var c2=app.project.item(j);if(c2 instanceof CompItem){'
            'for(var k=1;k<=c2.numLayers&&!used;k++){'
            'if(c2.layer(k).source&&c2.layer(k).source.id==it.id)used=true;}}}'
            'out.push({id:it.id,name:it.name,numLayers:it.numLayers,isPrecomp:used});}}'
            'JSON.stringify(out);'
        )
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return []

    def open_precomp(self, layer_name: str) -> str:
        """打开图层的源合成"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(layer_name)}");'
            f'if(tl.source instanceof CompItem){{tl.source.openInViewer();"opened:"+tl.source.name}}'
            f'else{{"not_a_precomp"}}'
        )

    def add_comp_to_comp(self, source_comp_name: str, target_comp_name: str = None) -> str:
        """将一个合成嵌套到另一个合成中"""
        jsx = 'var src=null,tgt=null;'
        jsx += 'for(var i=1;i<=app.project.numItems;i++){var it=app.project.item(i);'
        jsx += f'if(it instanceof CompItem&&it.name=="{_esc(source_comp_name)}")src=it;'
        if target_comp_name:
            jsx += f'if(it instanceof CompItem&&it.name=="{_esc(target_comp_name)}")tgt=it;'
        jsx += '}'
        if not target_comp_name:
            jsx += 'tgt=app.project.activeItem;'
        jsx += 'if(!src)"src_not_found";else if(!tgt)"tgt_not_found";else{'
        jsx += 'tgt.layers.add(src);"added";}'
        return self.run_jsx(jsx)

    # ── Masks ──────────────────────────────────────────────

    def add_mask(self, name: str, vertices: List[List[float]],
                  in_tangents: List[List[float]] = None,
                  out_tangents: List[List[float]] = None,
                  mode: str = "add", feather: float = 0,
                  opacity: float = 100, inverted: bool = False,
                  closed: bool = True) -> str:
        """为图层添加蒙版。mode: none/add/subtract/intersect/lighten/darken/difference"""
        n = len(vertices)
        in_t = in_tangents or [[0, 0]] * n
        out_t = out_tangents or [[0, 0]] * n
        mode_map = {
            "none": "MaskMode.NONE", "add": "MaskMode.ADD",
            "subtract": "MaskMode.SUBTRACT", "intersect": "MaskMode.INTERSECT",
            "lighten": "MaskMode.LIGHTEN", "darken": "MaskMode.DARKEN",
            "difference": "MaskMode.DIFFERENCE",
        }
        mode_jsx = mode_map.get(mode, "MaskMode.ADD")
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var masks=tl.property("Masks");'
            f'var m=masks.addProperty("ADBE Mask Atom");'
            f'var shape=new Shape();'
            f'shape.vertices={json.dumps(vertices)};'
            f'shape.inTangents={json.dumps(in_t)};'
            f'shape.outTangents={json.dumps(out_t)};'
            f'shape.closed={"true" if closed else "false"};'
            f'm.property("maskShape").setValue(shape);'
            f'm.property("maskFeather").setValue([{feather},{feather}]);'
            f'm.property("maskOpacity").setValue({opacity});'
            f'm.maskMode={mode_jsx};'
            f'm.inverted={"true" if inverted else "false"};'
            f'"mask_added";'
        )
        return self.run_jsx(jsx)

    def list_masks(self, name: str) -> List[dict]:
        """列出图层所有蒙版"""
        r = self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var masks=tl.property("Masks");var out=[];'
            f'for(var i=1;i<=masks.numProperties;i++){{'
            f'var m=masks.property(i);out.push({{index:i,name:m.name,'
            f'mode:m.maskMode,inverted:m.inverted,locked:m.locked}});}}'
            f'JSON.stringify(out);'
        )
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return []

    def set_mask_path(self, name: str, mask_index: int,
                       vertices: List[List[float]],
                       in_tangents: List[List[float]] = None,
                       out_tangents: List[List[float]] = None,
                       closed: bool = True) -> str:
        """修改蒙版路径"""
        n = len(vertices)
        in_t = in_tangents or [[0, 0]] * n
        out_t = out_tangents or [[0, 0]] * n
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var m=tl.property("Masks").property({mask_index});'
            f'var shape=new Shape();'
            f'shape.vertices={json.dumps(vertices)};'
            f'shape.inTangents={json.dumps(in_t)};'
            f'shape.outTangents={json.dumps(out_t)};'
            f'shape.closed={"true" if closed else "false"};'
            f'm.property("maskShape").setValue(shape);"ok";'
        )
        return self.run_jsx(jsx)

    def set_mask_feather(self, name: str, mask_index: int, feather: float) -> str:
        """设置蒙版羽化"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var m=c.layer("{_esc(name)}").property("Masks").property({mask_index});'
            f'm.property("maskFeather").setValue([{feather},{feather}]);"ok";'
        )

    def set_mask_opacity(self, name: str, mask_index: int, opacity: float) -> str:
        """设置蒙版不透明度"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var m=c.layer("{_esc(name)}").property("Masks").property({mask_index});'
            f'm.property("maskOpacity").setValue({opacity});"ok";'
        )

    def set_mask_expansion(self, name: str, mask_index: int, expansion: float) -> str:
        """设置蒙版扩展"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var m=c.layer("{_esc(name)}").property("Masks").property({mask_index});'
            f'm.property("maskExpansion").setValue({expansion});"ok";'
        )

    def animate_mask_path(self, name: str, mask_index: int,
                           keyframes: List[Tuple[float, List[List[float]]]]) -> str:
        """蒙版路径关键帧动画。keyframes: [(time, [[x,y], ...]), ...]"""
        jsx = (
            f'var c=app.project.activeItem;'
            f'var m=c.layer("{_esc(name)}").property("Masks").property({mask_index});'
            f'var mp=m.property("maskShape");'
        )
        for t, verts in keyframes:
            jsx += (
                f'var s=new Shape();s.vertices={json.dumps(verts)};'
                f's.closed=true;mp.setValueAtTime({t},s);'
            )
        jsx += '"ok";'
        return self.run_jsx(jsx)

    def remove_mask(self, name: str, mask_index: int) -> str:
        """删除指定蒙版"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(name)}").property("Masks").property({mask_index}).remove();"removed";'
        )

    # ── Markers ────────────────────────────────────────────

    def add_comp_marker(self, time: float, comment: str = "",
                         label: int = 0, duration: float = 0,
                         chapter: str = "", url: str = "") -> str:
        """添加合成级 Marker"""
        jsx = (
            f'var c=app.project.activeItem;'
            f'var m=new MarkerValue("{_esc(comment)}");'
        )
        if chapter:
            jsx += f'm.chapter="{_esc(chapter)}";'
        if url:
            jsx += f'm.url="{_esc(url)}";'
        if label:
            jsx += f'm.label={label};'
        if duration:
            jsx += f'm.duration={duration};'
        jsx += (
            f'var ms=c.markerProperty;'
            f'ms.setValueAtTime({time},m);"ok";'
        )
        return self.run_jsx(jsx)

    def list_comp_markers(self) -> List[dict]:
        """列出合成所有 Marker"""
        r = self.run_jsx(
            'var c=app.project.activeItem;'
            'var ms=c.markerProperty;var out=[];'
            'for(var i=1;i<=ms.numKeys;i++){'
            'var m=ms.keyValue(i);'
            'out.push({index:i,time:ms.keyTime(i),comment:m.comment,'
            'duration:m.duration,label:m.label,chapter:m.chapter});}'
            'JSON.stringify(out);'
        )
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return []

    def remove_comp_marker(self, index: int) -> str:
        """删除合成 Marker (1-based index)"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'c.markerProperty.removeKey({index});"removed";'
        )

    def add_layer_marker(self, name: str, time: float, comment: str = "",
                          label: int = 0, duration: float = 0) -> str:
        """添加图层级 Marker"""
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var m=new MarkerValue("{_esc(comment)}");'
        )
        if label:
            jsx += f'm.label={label};'
        if duration:
            jsx += f'm.duration={duration};'
        jsx += f'tl.property("Marker").setValueAtTime({time},m);"ok";'
        return self.run_jsx(jsx)

    def list_layer_markers(self, name: str) -> List[dict]:
        """列出图层所有 Marker"""
        r = self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var ms=c.layer("{_esc(name)}").property("Marker");var out=[];'
            f'for(var i=1;i<=ms.numKeys;i++){{'
            f'var m=ms.keyValue(i);'
            f'out.push({{index:i,time:ms.keyTime(i),comment:m.comment,'
            f'duration:m.duration,label:m.label}});}}'
            f'JSON.stringify(out);'
        )
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return []

    def remove_layer_marker(self, name: str, index: int) -> str:
        """删除图层 Marker"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(name)}").property("Marker").removeKey({index});"removed";'
        )

    # ── Parenting ──────────────────────────────────────────

    def set_parent(self, child_name: str, parent_name: str) -> str:
        """设置图层父子关系"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(child_name)}").parent=c.layer("{_esc(parent_name)}");'
            f'"ok";'
        )

    def remove_parent(self, name: str) -> str:
        """移除图层父级"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(name)}").parent=null;"ok";'
        )

    def get_parent(self, name: str) -> Optional[str]:
        """获取图层父级名称，无父级返回 None"""
        r = self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var p=c.layer("{_esc(name)}").parent;'
            f'p?p.name:"__null__";'
        )
        return None if r == "__null__" else r

    def create_null_control(self, name: str = "Null Control",
                             parent_to: List[str] = None,
                             position: List[float] = None) -> str:
        """创建 Null 对象并可选批量绑定子图层。"""
        jsx = (
            f'var c=app.project.activeItem;'
            f'var nl=c.layers.addNull();'
            f'nl.name="{_esc(name)}";'
        )
        if position:
            jsx += f'nl.property("Transform").property("Position").setValue({json.dumps(position)});'
        if parent_to:
            for child in parent_to:
                jsx += f'try{{c.layer("{_esc(child)}").parent=nl;}}catch(e){{}}'
        jsx += 'nl.name;'
        return self.run_jsx(jsx)

    # ── Blending Mode + Track Matte ────────────────────────

    def set_blending_mode(self, name: str, mode: str) -> str:
        """设置图层混合模式。mode: normal/multiply/screen/overlay/add/..."""
        bm = BLEND_MODES.get(mode)
        if not bm:
            raise ValueError(f"Unknown blend mode '{mode}'. Available: {list(BLEND_MODES.keys())}")
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(name)}").blendingMode={bm};"ok";'
        )

    def get_blending_mode(self, name: str) -> str:
        """获取图层混合模式"""
        r = self.run_jsx(
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(name)}").blendingMode.toString();'
        )
        return r

    def set_track_matte(self, name: str, matte_layer: str,
                         matte_type: str = "alpha") -> str:
        """设置轨道蒙版。matte_type: alpha/alpha_inverted/luma/luma_inverted"""
        tt = TRACK_MATTE_TYPES.get(matte_type, "TrackMatteType.ALPHA")
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'tl.trackMatteType={tt};"ok";'
        )

    def remove_track_matte(self, name: str) -> str:
        """移除轨道蒙版"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(name)}").trackMatteType=TrackMatteType.NO_TRACK_MATTE;"ok";'
        )

    def set_text_content(self, name: str, text: str) -> str:
        """
        Change the text content of an existing text layer.

        Args:
            name: Layer name
            text: New text content
        """
        safe_txt = _esc(text)
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var tp=tl.property("ADBE Text Properties").property("ADBE Text Document");'
            f'var td=tp.value;'
            f'td.text="{safe_txt}";'
            f'tp.setValue(td);'
            f'"ok";'
        )
        return self.run_jsx(jsx)

    def set_text_style(self, name: str, font: str = None,
                        font_size: int = None,
                        fill_color: List[float] = None,
                        stroke_color: List[float] = None,
                        stroke_width: float = None,
                        justification: str = None) -> str:
        """
        Set text styling properties on a text layer.

        Args:
            name: Layer name
            font: Font name (e.g. "SourceHanSansSC-Bold")
            font_size: Font size in px
            fill_color: [r, g, b] in 0-1 range
            stroke_color: [r, g, b] in 0-1 range
            stroke_width: Stroke width in px
            justification: "left", "center", or "right"
        """
        just_map = {
            "left": "ParagraphJustification.LEFT_JUSTIFY",
            "center": "ParagraphJustification.CENTER_JUSTIFY",
            "right": "ParagraphJustification.RIGHT_JUSTIFY",
        }

        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var tp=tl.property("ADBE Text Properties").property("ADBE Text Document");'
            f'var td=tp.value;'
        )
        if font_size is not None:
            jsx += f'td.fontSize={font_size};'
        if fill_color is not None:
            jsx += f'td.fillColor=[{fill_color[0]},{fill_color[1]},{fill_color[2]}];td.applyFill=true;'
        if stroke_color is not None:
            jsx += (f'td.strokeColor=[{stroke_color[0]},{stroke_color[1]},{stroke_color[2]}];'
                    f'td.applyStroke=true;td.strokeOverFill=false;')
        if stroke_width is not None:
            jsx += f'td.strokeWidth={stroke_width};'
        if font is not None:
            jsx += f'td.font="{font}";'
        if justification is not None and justification in just_map:
            jsx += f'td.justification={just_map[justification]};'
        jsx += 'tp.setValue(td);'
        jsx += '"ok";'
        return self.run_jsx(jsx)

    # ── Text Animator ──────────────────────────────────────

    def add_text_animator(self, name: str, properties: Dict[str, Any] = None) -> str:
        """
        为文本图层添加 Animator。
        properties keys: position, anchor_point, scale, skew, rotation,
                        opacity, fill_color, stroke_color, stroke_width,
                        tracking_type, tracking_amount, line_anchor, line_spacing,
                        character_offset, blur
        """
        prop_matchnames = {
            "position": "ADBE Text Position 3D",
            "anchor_point": "ADBE Text Anchor Point 3D",
            "scale": "ADBE Text Scale 3D",
            "skew": "ADBE Text Skew",
            "rotation": "ADBE Text Rotation",
            "opacity": "ADBE Text Opacity",
            "fill_color": "ADBE Text Fill Color",
            "stroke_color": "ADBE Text Stroke Color",
            "stroke_width": "ADBE Text Stroke Width",
            "tracking_type": "ADBE Text Tracking Type",
            "tracking_amount": "ADBE Text Tracking Amount",
            "line_anchor": "ADBE Text Line Anchor",
            "line_spacing": "ADBE Text Line Spacing",
            "character_offset": "ADBE Text Character Offset",
            "blur": "ADBE Text Blur",
        }
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var animators=tl.property("ADBE Text Properties").property("ADBE Text Animators");'
            f'var anim=animators.addProperty("ADBE Text Animator");'
        )
        if properties:
            jsx += 'var props=anim.property("ADBE Text Animator Properties");'
            for key, val in properties.items():
                mn = prop_matchnames.get(key)
                if not mn:
                    continue
                jsx += f'var p=props.addProperty("{mn}");'
                if isinstance(val, (list, tuple)):
                    jsx += f'p.setValue({json.dumps(val)});'
                else:
                    jsx += f'p.setValue({val});'
        jsx += '"animator_added";'
        return self.run_jsx(jsx)

    def set_text_animator_selector(self, name: str, animator_index: int = 1,
                                    start: float = 0, end: float = 100,
                                    offset: float = 0,
                                    shape: str = "square",
                                    based_on: str = "characters",
                                    mode: str = "add") -> str:
        """配置文本 Animator 的 Range Selector。如果不存在则自动创建。"""
        shape_map = {
            "square": 1, "ramp_up": 2, "ramp_down": 3,
            "triangle": 4, "round": 5, "smooth": 6,
        }
        based_map = {"characters": 1, "characters_excluding_spaces": 2, "words": 3, "lines": 4}
        mode_val = {"add": 1, "subtract": 2, "intersect": 3, "min": 4, "max": 5, "difference": 6}.get(mode, 1)
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var animators=tl.property("ADBE Text Properties").property("ADBE Text Animators");'
            f'var anim=animators.property({animator_index});'
            f'if(!anim)"ERR:no_animator";else{{'
            f'var sels=anim.property("ADBE Text Selectors");'
            f'var sel;'
            f'if(sels.numProperties<1){{sel=sels.addProperty("ADBE Text Selector");}}else{{sel=sels.property(1);}}'
            f'sel.property("ADBE Text Percent Start").setValue({start});'
            f'sel.property("ADBE Text Percent End").setValue({end});'
            f'sel.property("ADBE Text Percent Offset").setValue({offset});'
            f'var adv=sel.property("ADBE Text Range Advanced");'
            f'adv.property("ADBE Text Selector Mode").setValue({mode_val});'
            f'adv.property("ADBE Text Range Shape").setValue({shape_map.get(shape, 1)});'
            f'adv.property("ADBE Text Range Type2").setValue({based_map.get(based_on, 1)});'
            f'"selector_set";}}'
        )
        return self.run_jsx(jsx)

    def animate_text_selector(self, name: str, animator_index: int = 1,
                               selector_index: int = 1,
                               keyframes: Dict[str, List[Tuple[float, float]]] = None) -> str:
        """动画化文本 Selector 属性。keyframes: {"start": [(t, val), ...], "end": [...], "offset": [...]}"""
        prop_map = {
            "start": "ADBE Text Percent Start",
            "end": "ADBE Text Percent End",
            "offset": "ADBE Text Percent Offset",
        }
        jsx = (
            'var c=app.project.activeItem;'
            'var tl=c.layer("' + _esc(name) + '");'
            'var animators=tl.property("ADBE Text Properties").property("ADBE Text Animators");'
            'if(!animators||animators.numProperties<' + str(animator_index) + '){"ERR:no_animator"}else{'
            'var anim=animators.property(' + str(animator_index) + ');'
            'var sels=anim.property("ADBE Text Selectors");'
            'if(!sels||sels.numProperties<' + str(selector_index) + '){"ERR:no_selector"}else{'
            'var sel=sels.property(' + str(selector_index) + ');'
        )
        if keyframes:
            for prop_key, kfs in keyframes.items():
                mn = prop_map.get(prop_key)
                if not mn:
                    continue
                jsx += 'var p=sel.property("' + mn + '");'
                for t, val in kfs:
                    jsx += f'p.setValueAtTime({t},{val});'
        jsx += '"animated"}}'
        return self.run_jsx(jsx)

    # ── Layer Styles ───────────────────────────────────────

    def add_layer_style(self, name: str, style: str,
                         props: Dict[str, Any] = None) -> str:
        """
        [EXPERIMENTAL] Enable a Layer Style via AEGP SDK DynamicStreamSuite.

        WARNING: AE scripting support for Layer Styles is limited.
        Many styles return ERR:not_scriptable. Use at own risk.

        style: drop_shadow/inner_shadow/outer_glow/inner_glow/bevel_emboss/
               satin/color_overlay/gradient_overlay/pattern_overlay/stroke
        props: Property dict (key = AE matchName)
        """
        style_matchnames = {
            "drop_shadow": "dropShadow/enabled",
            "inner_shadow": "innerShadow/enabled",
            "outer_glow": "outerGlow/enabled",
            "inner_glow": "innerGlow/enabled",
            "bevel_emboss": "bevelEmboss/enabled",
            "satin": "chromeFX/enabled",
            "color_overlay": "solidFill/enabled",
            "gradient_overlay": "gradientFill/enabled",
            "pattern_overlay": "patternFill/enabled",
            "stroke": "frameFX/enabled",
        }
        mn = style_matchnames.get(style)
        if not mn:
            raise ValueError(f"Unknown layer style '{style}'. Available: {list(style_matchnames.keys())}")

        # Layer Styles 需要 AEGP SDK DynamicStreamSuite（C++ 链式调用），
        # 当前架构下从 HTTP 线程调用不稳定（idle hook 死锁风险）。
        # 需要手动通过 AE 菜单启用：Layer > Layer Styles > ...
        return ("ERR:not_scriptable — Layer Styles require AE menu: "
                "Layer > Layer Styles > " + style.replace('_', ' ').title())

    def enable_layer_style(self, name: str, style: str,
                            enabled: bool = True) -> str:
        """
        [EXPERIMENTAL] Toggle a Layer Style on/off.

        WARNING: AE's canSetEnabled returns false for most styles.
        This method may silently fail.
        """
        return ("ERR:not_scriptable — Layer Styles require AE menu")

    # ── 3D / Camera / Light ────────────────────────────────

    def set_3d_layer(self, name: str, enabled: bool = True) -> str:
        """启用/禁用图层 3D"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(name)}").threeDLayer={"true" if enabled else "false"};"ok";'
        )

    def create_camera(self, name: str = "Camera",
                       camera_type: str = "two_node",
                       zoom: float = None,
                       position: List[float] = None) -> str:
        """创建摄像机。camera_type: one_node/two_node"""
        jsx = (
            f'var c=app.project.activeItem;'
            f'var cam=c.layers.addCamera("{_esc(name)}",[c.width/2,c.height/2]);'
        )
        if camera_type == "one_node":
            jsx += 'cam.autoOrient=AutoOrientType.NO_AUTO_ORIENT;'
        if zoom is not None:
            jsx += f'cam.property("ADBE Camera Options Group").property("ADBE Camera Zoom").setValue({zoom});'
        if position:
            jsx += f'cam.property("ADBE Transform Group").property("ADBE Position").setValue({json.dumps(position)});'
        jsx += 'cam.name;'
        return self.run_jsx(jsx)

    def create_light(self, name: str = "Light",
                      light_type: str = "point",
                      intensity: float = 100,
                      color: List[float] = None,
                      position: List[float] = None) -> str:
        """创建灯光。light_type: parallel/spot/point/ambient"""
        type_map = {
            "parallel": "LightType.PARALLEL", "spot": "LightType.SPOT",
            "point": "LightType.POINT", "ambient": "LightType.AMBIENT",
        }
        lt_jsx = type_map.get(light_type, "LightType.POINT")
        jsx = (
            f'var c=app.project.activeItem;'
            f'var lyr=c.layers.addLight("{_esc(name)}",[c.width/2,c.height/2]);'
            f'lyr.lightType={lt_jsx};'
            f'lyr.property("ADBE Light Options Group").property("ADBE Light Intensity").setValue({intensity});'
        )
        if color:
            jsx += f'lyr.property("ADBE Light Options Group").property("ADBE Light Color").setValue({json.dumps(color)});'
        if position:
            jsx += f'lyr.property("ADBE Transform Group").property("ADBE Position").setValue({json.dumps(position)});'
        jsx += 'lyr.name;'
        return self.run_jsx(jsx)

    def set_camera_property(self, name: str, prop: str, value: Any) -> str:
        """设置摄像机属性 (zoom/focus_distance/aperture/blur_level)"""
        prop_map = {
            "zoom": "ADBE Camera Zoom",
            "focus_distance": "ADBE Camera Focus Distance",
            "aperture": "ADBE Camera Aperture",
            "blur_level": "ADBE Camera Blur Level",
        }
        ae_prop = prop_map.get(prop, prop)
        v = json.dumps(value) if isinstance(value, (list, tuple)) else str(value)
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(name)}").property("ADBE Camera Options Group").property("{ae_prop}").setValue({v});"ok";'
        )

    def set_light_property(self, name: str, prop: str, value: Any) -> str:
        """设置灯光属性 (intensity/color/cone_angle/cone_feather/shadow_darkness/shadow_diffusion)"""
        prop_map = {
            "intensity": "ADBE Light Intensity",
            "color": "ADBE Light Color",
            "cone_angle": "ADBE Light Cone Angle",
            "cone_feather": "ADBE Light Cone Feather",
            "shadow_darkness": "ADBE Light Shadow Darkness",
            "shadow_diffusion": "ADBE Light Shadow Diffusion",
        }
        ae_prop = prop_map.get(prop, prop)
        v = json.dumps(value) if isinstance(value, (list, tuple)) else str(value)
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(name)}").property("ADBE Light Options Group").property("{ae_prop}").setValue({v});"ok";'
        )

    # ── Time Remap ─────────────────────────────────────────

    def enable_time_remap(self, name: str) -> str:
        """启用图层时间重映射（仅对有 footage source 的图层有效）"""
        return self.run_jsx(
            f'var c=app.project.activeItem;var tl=c.layer("{_esc(name)}");'
            f'if(!tl.canSetTimeRemapEnabled){{"ERR:layer_not_supported"}}'
            f'else{{tl.timeRemapEnabled=true;"ok"}}'
        )

    def set_time_remap_keyframes(self, name: str,
                                  keyframes: List[Tuple[float, float]]) -> str:
        """设置时间重映射关键帧。keyframes: [(comp_time, source_time), ...]"""
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'if(!tl.canSetTimeRemapEnabled){{"ERR:layer_not_supported"}}else{{'
            f'if(!tl.timeRemapEnabled)tl.timeRemapEnabled=true;'
            f'var tr=tl.timeRemap;'
        )
        for comp_t, src_t in keyframes:
            jsx += f'tr.setValueAtTime({comp_t},{src_t});'
        jsx += '"ok"}'
        return self.run_jsx(jsx)

    def freeze_frame(self, name: str, at_time: float) -> str:
        """冻结帧（仅对有 footage source 的图层有效）"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'if(!tl.canSetTimeRemapEnabled){{"ERR:layer_not_supported"}}else{{'
            f'if(!tl.timeRemapEnabled)tl.timeRemapEnabled=true;'
            f'var tr=tl.timeRemap;'
            f'tr.setValueAtTime(tr.keyTime(1),{at_time});'
            f'tr.setValueAtTime(tr.keyTime(tr.numKeys),{at_time});'
            f'"frozen"}}'
        )

    def reverse_layer(self, name: str) -> str:
        """反转图层时间（仅对有 footage source 的图层有效）"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'if(!tl.canSetTimeRemapEnabled){{"ERR:layer_not_supported"}}else{{'
            f'if(!tl.timeRemapEnabled)tl.timeRemapEnabled=true;'
            f'var tr=tl.timeRemap;var dur=tl.source.duration;'
            f'tr.setValueAtTime(tr.keyTime(1),dur);'
            f'tr.setValueAtTime(tr.keyTime(tr.numKeys),0);'
            f'"reversed"}}'
        )

    # ── Render Queue Management ────────────────────────────

    def render_queue_info(self) -> List[dict]:
        """获取渲染队列状态"""
        r = self.run_jsx(
            'var rq=app.project.renderQueue;var out=[];'
            'for(var i=1;i<=rq.numItems;i++){var ri=rq.item(i);'
            'var om=ri.outputModule(1);'
            'out.push({index:i,comp:ri.comp.name,status:ri.status,'
            'outputPath:om.file?om.file.fsName:""});}'
            'JSON.stringify(out);'
        )
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return []

    def set_render_output(self, rq_index: int, output_path: str,
                           template: str = None) -> str:
        """设置渲染项输出路径和模板"""
        safe_path = output_path.replace('\\', '/')
        jsx = (
            f'var ri=app.project.renderQueue.item({rq_index});'
            f'var om=ri.outputModule(1);'
            f'om.file=new File("{safe_path}");'
        )
        if template:
            jsx += f'om.applyTemplate("{_esc(template)}");'
        jsx += '"ok";'
        return self.run_jsx(jsx)

    def remove_render_item(self, rq_index: int) -> str:
        """从渲染队列移除项目"""
        return self.run_jsx(
            f'app.project.renderQueue.item({rq_index}).remove();"removed";'
        )

    def clear_render_queue(self) -> str:
        """清空渲染队列"""
        return self.run_jsx(
            'var rq=app.project.renderQueue;'
            'for(var i=rq.numItems;i>=1;i--)rq.item(i).remove();'
            '"cleared:"+rq.numItems;'
        )

    def start_render(self) -> str:
        """开始渲染（阻塞直到完成）"""
        return self.run_jsx(
            'app.project.renderQueue.render();"render_complete";',
            timeout=600000
        )

    # ── Batch / Selection ──────────────────────────────────

    def set_layer_selected(self, name: str, selected: bool = True) -> str:
        """Set a single layer's selection state."""
        jsx = (
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(name)}").selected={str(selected).lower()};'
            f'"ok";'
        )
        return self.run_jsx(jsx)

    def deselect_all(self) -> str:
        """取消所有选择"""
        return self.run_jsx(
            'var c=app.project.activeItem;'
            'for(var i=1;i<=c.numLayers;i++)c.layer(i).selected=false;"ok";'
        )

    def get_selected_layers(self) -> List[dict]:
        """获取当前选中图层"""
        r = self.run_jsx(
            'var c=app.project.activeItem;var out=[];'
            'for(var i=1;i<=c.numLayers;i++){var l=c.layer(i);'
            'if(l.selected)out.push({name:l.name,index:i,id:l.id});}'
            'JSON.stringify(out);'
        )
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return []

    def duplicate_layer(self, name: str) -> str:
        """复制图层，返回新图层名"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var nl=c.layer("{_esc(name)}").duplicate();nl.name;'
        )

    def reorder_layer(self, name: str, new_index: int) -> str:
        """移动图层到指定索引 (1-based)"""
        return self.run_jsx(
            f'try{{var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'tl.moveToBeginning();'
            f'if({new_index}>1){{for(var i=1;i<{new_index};i++)tl.moveAfter(c.layer(i));}}'
            f'"ok"}}catch(e){{"ERR:"+e.toString()}}'
        )

    # ── Pixel Access (requires C++ renderFramePixels) ─────

    def sample_pixel(self, x: int, y: int, time: float = -1) -> dict:
        """精确采样单个像素，返回 {r, g, b, a}。"""
        return self.sample_pixels([[x, y]], time=time)[0]

    def sample_pixels(self, points: List[List[int]], time: float = -1) -> List[dict]:
        """精确批量采样多个像素点，points: [[x,y], ...]。"""
        pts = []
        for pt in points:
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                raise ValueError("points must be [[x, y], ...]")
            pts.append([int(pt[0]), int(pt[1])])

        pts_str = repr(pts)
        code = (
            f'comp=app.project.activeItem\n'
            f'if comp is None or type(comp).__name__ != "CompItem":\n'
            f'    raise RuntimeError("no active comp")\n'
            f'import json\n'
            f'px=comp.renderFramePixels({time})\n'
            f'height=int(px.shape[0])\n'
            f'width=int(px.shape[1])\n'
            f'pts={pts_str}\n'
            f'out=[]\n'
            f'for pt in pts:\n'
            f'    x,y=pt[0],pt[1]\n'
            f'    if x < 0 or y < 0 or x >= width or y >= height:\n'
            f'        raise IndexError(f\"pixel_out_of_bounds:{{x}},{{y}}:{{width}}x{{height}}\")\n'
            f'    out.append({{"r":int(px[y,x,0]),"g":int(px[y,x,1]),"b":int(px[y,x,2]),"a":int(px[y,x,3])}})\n'
            f'_result=json.dumps(out)'
        )
        r = self._run_py(code)
        return json.loads(r)

    def list_puppet_pins(self, layer: Union[str, int],
                         effect_index: int = None,
                         mesh_index: int = 1) -> Dict[str, Any]:
        """列出图层上的 Puppet Deform pins，返回 source/comp 两套坐标。"""
        name_to_index, index_to_name = self._get_layer_lookup_maps()
        layer_index, layer_name = self._resolve_layer_ref(
            layer,
            name_to_index=name_to_index,
            index_to_name=index_to_name,
        )
        if layer_index is None:
            return {"error": f"layer_not_found:{layer_name}"}

        jsx = (
            '(function(){'
            'function findPuppet(layer, requestedIndex){'
            '  var fxGroup=layer.property("ADBE Effect Parade");'
            '  var fx=null;'
            '  var fxIndex=0;'
            f'  var requested={(int(effect_index) if effect_index else 0)};'
            '  if(requested>0){'
            '    fx=fxGroup.property(requested);'
            '    if(!fx||fx.matchName!=="ADBE FreePin3"){'
            '      return {error:"puppet_effect_not_found"};'
            '    }'
            '    fxIndex=requested;'
            '  }else{'
            '    for(var i=1;i<=fxGroup.numProperties;i++){'
            '      var cand=fxGroup.property(i);'
            '      if(cand&&cand.matchName==="ADBE FreePin3"){fx=cand;fxIndex=i;break;}'
            '    }'
            '    if(!fx){return {error:"puppet_effect_not_found"};}'
            '  }'
            '  return {fx:fx, fxIndex:fxIndex};'
            '}'
            'var comp=app.project.activeItem;'
            'if(!comp||!(comp instanceof CompItem))return JSON.stringify({error:"no_comp"});'
            f'var layer=comp.layer({int(layer_index)});'
            'if(!layer)return JSON.stringify({error:"no_layer"});'
            'var info=findPuppet(layer);'
            'if(info.error)return JSON.stringify(info);'
            'var arap=info.fx.property("ADBE FreePin3 ARAP Group");'
            'if(!arap)return JSON.stringify({error:"puppet_arap_not_found"});'
            'var meshGroup=arap.property("ADBE FreePin3 Mesh Group");'
            'if(!meshGroup)return JSON.stringify({error:"puppet_mesh_group_not_found"});'
            'var mesh=null;'
            f'if(meshGroup.numProperties>={max(1, int(mesh_index))}){{mesh=meshGroup.property({max(1, int(mesh_index))});}}'
            'if(!mesh)return JSON.stringify({error:"puppet_mesh_not_found"});'
            'var posPins=mesh.property("ADBE FreePin3 PosPins");'
            'if(!posPins)return JSON.stringify({error:"puppet_pospins_not_found"});'
            'var out=[];'
            'for(var i=1;i<=posPins.numProperties;i++){'
            '  var pin=posPins.property(i);'
            '  var posProp=pin.property("ADBE FreePin3 PosPin Position");'
            '  if(!posProp)continue;'
            '  var sourcePos=posProp.value;'
            '  var compPos=layer.sourcePointToComp(sourcePos);'
            '  out.push({'
            '    index:i,'
            '    name:pin.name,'
            '    source_position:[sourcePos[0],sourcePos[1]],'
            '    comp_position:[compPos[0],compPos[1]],'
            '    rotation:pin.property("ADBE FreePin3 PosPin Rotation").value,'
            '    scale:pin.property("ADBE FreePin3 PosPin Scale").value'
            '  });'
            '}'
            'return JSON.stringify({'
            '  layer_index:layer.index,'
            '  layer_name:layer.name,'
            '  effect_index:info.fxIndex,'
            f'  mesh_index:{max(1, int(mesh_index))},'
            '  pin_count:out.length,'
            '  pins:out'
            '});'
            '})()'
        )
        return json.loads(self.run_jsx(jsx, timeout=30000))

    def remove_puppet_pins(self, layer: Union[str, int],
                           pin_indices: List[int],
                           effect_index: int = None,
                           mesh_index: int = 1) -> Dict[str, Any]:
        """删除指定的 Puppet Deform pins。"""
        if not isinstance(pin_indices, (list, tuple)) or not pin_indices:
            raise ValueError("pin_indices must be [index, ...]")

        normalized_indices = sorted(
            {max(1, int(idx)) for idx in pin_indices},
            reverse=True,
        )

        name_to_index, index_to_name = self._get_layer_lookup_maps()
        layer_index, layer_name = self._resolve_layer_ref(
            layer,
            name_to_index=name_to_index,
            index_to_name=index_to_name,
        )
        if layer_index is None:
            return {"error": f"layer_not_found:{layer_name}"}

        jsx = (
            '(function(){'
            'function findPuppet(layer, requestedIndex){'
            '  var fxGroup=layer.property("ADBE Effect Parade");'
            '  var fx=null;'
            '  var fxIndex=0;'
            f'  var requested={(int(effect_index) if effect_index else 0)};'
            '  if(requested>0){'
            '    fx=fxGroup.property(requested);'
            '    if(!fx||fx.matchName!=="ADBE FreePin3"){return {error:"puppet_effect_not_found"};}'
            '    fxIndex=requested;'
            '  }else{'
            '    for(var i=1;i<=fxGroup.numProperties;i++){'
            '      var cand=fxGroup.property(i);'
            '      if(cand&&cand.matchName==="ADBE FreePin3"){fx=cand;fxIndex=i;break;}'
            '    }'
            '    if(!fx){return {error:"puppet_effect_not_found"};}'
            '  }'
            '  return {fx:fx,fxIndex:fxIndex};'
            '}'
            'var comp=app.project.activeItem;'
            'if(!comp||!(comp instanceof CompItem))return JSON.stringify({error:"no_comp"});'
            f'var layer=comp.layer({int(layer_index)});'
            'if(!layer)return JSON.stringify({error:"no_layer"});'
            'var info=findPuppet(layer);'
            'if(info.error)return JSON.stringify(info);'
            'var arap=info.fx.property("ADBE FreePin3 ARAP Group");'
            'if(!arap)return JSON.stringify({error:"puppet_arap_not_found"});'
            'var meshGroup=arap.property("ADBE FreePin3 Mesh Group");'
            'if(!meshGroup)return JSON.stringify({error:"puppet_mesh_group_not_found"});'
            f'var mesh=meshGroup.numProperties>={max(1, int(mesh_index))}?meshGroup.property({max(1, int(mesh_index))}):null;'
            'if(!mesh)return JSON.stringify({error:"puppet_mesh_not_found"});'
            'var posPins=mesh.property("ADBE FreePin3 PosPins");'
            'if(!posPins)return JSON.stringify({error:"puppet_pospins_not_found"});'
            f'var requested={json.dumps(normalized_indices)};'
            'var removed=[];'
            'var skipped=[];'
            'var before=posPins.numProperties;'
            'app.beginUndoGroup("Remove Puppet Pins");'
            'try{'
            '  for(var i=0;i<requested.length;i++){'
            '    var idx=requested[i];'
            '    if(idx<1||idx>posPins.numProperties){skipped.push(idx);continue;}'
            '    var pin=posPins.property(idx);'
            '    if(!pin){skipped.push(idx);continue;}'
            '    try{pin.remove();removed.push(idx);}catch(e){skipped.push(idx);}'
            '  }'
            '  return JSON.stringify({'
            '    layer_index:layer.index,'
            '    layer_name:layer.name,'
            '    effect_index:info.fxIndex,'
            f'    mesh_index:{max(1, int(mesh_index))},'
            '    pin_count_before:before,'
            '    pin_count_after:posPins.numProperties,'
            '    removed:removed,'
            '    skipped:skipped'
            '  });'
            '}finally{'
            '  app.endUndoGroup();'
            '}'
            '})()'
        )
        return json.loads(self.run_jsx(jsx, timeout=30000))

    def set_puppet_pin_positions(self, layer: Union[str, int],
                                 points: List[List[float]],
                                 effect_index: int = None,
                                 mesh_index: int = 1,
                                 points_are_comp: bool = True,
                                 remove_extra: bool = False) -> Dict[str, Any]:
        """
        批量重定位现有 Puppet pins。

        适合“模板层里已经有 N 个真实 pins”的场景：
        - 复制模板层 / replaceSource
        - 后台把现有真实 pins 按检测结果重定位到新图层上
        """
        if not isinstance(points, (list, tuple)) or not points:
            raise ValueError("points must be [[x, y], ...]")

        normalized_points: List[List[float]] = []
        for pt in points:
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                raise ValueError("points must be [[x, y], ...]")
            normalized_points.append([float(pt[0]), float(pt[1])])

        name_to_index, index_to_name = self._get_layer_lookup_maps()
        layer_index, layer_name = self._resolve_layer_ref(
            layer,
            name_to_index=name_to_index,
            index_to_name=index_to_name,
        )
        if layer_index is None:
            return {"error": f"layer_not_found:{layer_name}"}

        source_points = normalized_points
        if points_are_comp:
            source_points = self._convert_comp_points_to_source_points(
                layer_index,
                normalized_points,
            )

        jsx = (
            '(function(){'
            'function findPuppet(layer, requestedIndex){'
            '  var fxGroup=layer.property("ADBE Effect Parade");'
            '  var fx=null;'
            '  var fxIndex=0;'
            f'  var requested={(int(effect_index) if effect_index else 0)};'
            '  if(requested>0){'
            '    fx=fxGroup.property(requested);'
            '    if(!fx||fx.matchName!=="ADBE FreePin3"){return {error:"puppet_effect_not_found"};}'
            '    fxIndex=requested;'
            '  }else{'
            '    for(var i=1;i<=fxGroup.numProperties;i++){'
            '      var cand=fxGroup.property(i);'
            '      if(cand&&cand.matchName==="ADBE FreePin3"){fx=cand;fxIndex=i;break;}'
            '    }'
            '    if(!fx){return {error:"puppet_effect_not_found"};}'
            '  }'
            '  return {fx:fx,fxIndex:fxIndex};'
            '}'
            'function setPropValue(prop, value, time){'
            '  if(!prop)return false;'
            '  try{'
            '    if(prop.numKeys && prop.numKeys > 0){prop.setValueAtTime(time, value);}else{prop.setValue(value);}'
            '    return true;'
            '  }catch(e){'
            '    try{prop.setValueAtTime(time, value);return true;}catch(_e){return false;}'
            '  }'
            '}'
            'var comp=app.project.activeItem;'
            'if(!comp||!(comp instanceof CompItem))return JSON.stringify({error:"no_comp"});'
            f'var layer=comp.layer({int(layer_index)});'
            'if(!layer)return JSON.stringify({error:"no_layer"});'
            'var info=findPuppet(layer);'
            'if(info.error)return JSON.stringify(info);'
            'var arap=info.fx.property("ADBE FreePin3 ARAP Group");'
            'if(!arap)return JSON.stringify({error:"puppet_arap_not_found"});'
            'var meshGroup=arap.property("ADBE FreePin3 Mesh Group");'
            'if(!meshGroup)return JSON.stringify({error:"puppet_mesh_group_not_found"});'
            f'var mesh=meshGroup.numProperties>={max(1, int(mesh_index))}?meshGroup.property({max(1, int(mesh_index))}):null;'
            'if(!mesh)return JSON.stringify({error:"puppet_mesh_not_found"});'
            'var posPins=mesh.property("ADBE FreePin3 PosPins");'
            'if(!posPins)return JSON.stringify({error:"puppet_pospins_not_found"});'
            f'var pts={json.dumps(source_points)};'
            'var limit=Math.min(posPins.numProperties, pts.length);'
            'var updated=[];'
            'for(var i=1;i<=limit;i++){'
            '  var pin=posPins.property(i);'
            '  var pos=pin?pin.property("ADBE FreePin3 PosPin Position"):null;'
            '  if(!pos)return JSON.stringify({error:"pospin_position_not_found",index:i});'
            '  if(!setPropValue(pos, pts[i-1], comp.time))return JSON.stringify({error:"pospin_set_failed",index:i});'
            '  var compPos=layer.sourcePointToComp(pts[i-1]);'
            '  updated.push({'
            '    index:i,'
            '    source_position:[pts[i-1][0],pts[i-1][1]],'
            '    comp_position:[compPos[0],compPos[1]]'
            '  });'
            '}'
            'return JSON.stringify({'
            '  layer_index:layer.index,'
            '  layer_name:layer.name,'
            '  effect_index:info.fxIndex,'
            f'  mesh_index:{max(1, int(mesh_index))},'
            '  existing_pin_count:posPins.numProperties,'
            '  updated_count:updated.length,'
            '  requested_point_count:pts.length,'
            '  updated:updated'
            '});'
            '})()'
        )
        result = json.loads(self.run_jsx(jsx, timeout=60000))
        if result.get("error"):
            return result

        if remove_extra and result.get("existing_pin_count", 0) > len(source_points):
            extras = list(range(len(source_points) + 1, int(result["existing_pin_count"]) + 1))
            result["removed_extra"] = self.remove_puppet_pins(
                layer=layer_index,
                pin_indices=extras,
                effect_index=result.get("effect_index"),
                mesh_index=result.get("mesh_index", max(1, int(mesh_index))),
            )

        result["requested_points"] = normalized_points
        result["source_points"] = source_points
        return result

    def add_puppet_pins(self, layer: Union[str, int],
                        points: List[List[float]],
                        effect_index: int = None,
                        mesh_index: int = 1,
                        clear_existing: bool = False,
                        points_are_comp: bool = True) -> Dict[str, Any]:
        """
        在图层上批量添加 Puppet Deform pins。

        注意：当前 ExtendScript / JSX 路线只能创建 `PosPin Atom` 外壳并设置位置，
        但无法写入隐藏的 `ADBE FreePin3 PosPin Vtx Index` 绑定字段。
        AE 会把这类 pin 视为未绑定（`Vtx Index == -1`），因此不会得到可靠的可见 mesh/pin。
        这里默认直接返回错误并附上坐标，避免误写入假成功结果。
        """
        if not isinstance(points, (list, tuple)) or not points:
            raise ValueError("points must be [[x, y], ...]")

        normalized_points: List[List[float]] = []
        for pt in points:
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                raise ValueError("points must be [[x, y], ...]")
            normalized_points.append([float(pt[0]), float(pt[1])])

        name_to_index, index_to_name = self._get_layer_lookup_maps()
        layer_index, layer_name = self._resolve_layer_ref(
            layer,
            name_to_index=name_to_index,
            index_to_name=index_to_name,
        )
        if layer_index is None:
            return {"error": f"layer_not_found:{layer_name}"}

        source_points = normalized_points
        if points_are_comp:
            source_points = self._convert_comp_points_to_source_points(
                layer_index,
                normalized_points,
            )

        resolved_name = index_to_name.get(layer_index) or layer_name or str(layer)
        return {
            "error": "puppet_pin_backend_unavailable:jsx_cannot_bind_vertices",
            "reason": (
                "Script-created PosPin Atom keeps `ADBE FreePin3 PosPin Vtx Index == -1`, "
                "and JSX cannot set that hidden binding property."
            ),
            "layer_index": layer_index,
            "layer_name": resolved_name,
            "requested_points": normalized_points,
            "source_points": source_points,
            "effect_index": effect_index,
            "mesh_index": max(1, int(mesh_index)),
            "clear_existing_requested": bool(clear_existing),
        }

    def instantiate_puppet_template_layer(self, target_layer: Union[str, int],
                                          template_layer: str,
                                          template_comp: str = None,
                                          new_name: str = None,
                                          disable_target: bool = False,
                                          move_after_target: bool = True) -> Dict[str, Any]:
        """
        复制一个“已经带真实 Puppet mesh”的模板层到当前合成，并替换成目标图层的 source。

        这条路线的核心用途是：
        - 模板层里预先有至少 1 个真实点击创建的 pin
        - 复制到当前合成后 `replaceSource(...)`
        - 后续新增的脚本 pin 会挂在 real mesh 上，而不是落到 shell mesh
        """
        if not template_layer:
            raise ValueError("template_layer is required")

        name_to_index, index_to_name = self._get_layer_lookup_maps()
        target_index, target_name = self._resolve_layer_ref(
            target_layer,
            name_to_index=name_to_index,
            index_to_name=index_to_name,
        )
        if target_index is None:
            return {"error": f"layer_not_found:{target_name}"}

        resolved_target_name = index_to_name.get(target_index) or target_name or str(target_layer)
        duplicate_name = str(new_name or f"{resolved_target_name}__puppet")
        template_layer_name = str(template_layer)
        template_comp_name = str(template_comp) if template_comp else ""

        jsx = (
            '(function(){'
            'var comp=app.project.activeItem;'
            'if(!comp||!(comp instanceof CompItem))return JSON.stringify({error:"no_comp"});'
            f'var target=comp.layer({int(target_index)});'
            'if(!target)return JSON.stringify({error:"no_layer"});'
            'var targetSource=null;'
            'try{targetSource=target.source;}catch(e){}'
            'if(!targetSource)return JSON.stringify({error:"target_source_not_found"});'
            f'var templateCompName="{_esc(template_comp_name)}";'
            f'var templateLayerName="{_esc(template_layer_name)}";'
            f'var duplicateName="{_esc(duplicate_name)}";'
            'var templateComp=null;'
            'if(templateCompName){'
            '  for(var i=1;i<=app.project.numItems;i++){'
            '    var cand=app.project.item(i);'
            '    if(cand instanceof CompItem && cand.name===templateCompName){templateComp=cand;break;}'
            '  }'
            '}else{'
            '  templateComp=comp;'
            '}'
            'if(!templateComp)return JSON.stringify({error:"template_comp_not_found",template_comp_name:templateCompName});'
            'var templateLayer=null;'
            'try{templateLayer=templateComp.layer(templateLayerName);}catch(e){}'
            'if(!templateLayer)return JSON.stringify({error:"template_layer_not_found",template_layer_name:templateLayerName,template_comp_name:templateComp.name});'
            'app.beginUndoGroup("Instantiate Puppet Template Layer");'
            'try{'
            '  function setPropValue(prop, value, time){'
            '    if(!prop)return;'
            '    try{'
            '      if(prop.numKeys && prop.numKeys > 0){prop.setValueAtTime(time, value);}else{prop.setValue(value);}'
            '    }catch(e){'
            '      try{prop.setValueAtTime(time, value);}catch(_e){}'
            '    }'
            '  }'
            '  templateLayer.copyToComp(comp);'
            '  var dup=comp.layer(1);'
            '  if(!dup)return JSON.stringify({error:"copy_to_comp_failed"});'
            f'  if({str(bool(move_after_target)).lower()}){{'
            '    try{dup.moveAfter(target);}catch(e){}'
            '  }'
            '  dup.name=duplicateName;'
            '  try{dup.replaceSource(targetSource,false);}catch(e){'
            '    try{dup.remove();}catch(_e){}'
            '    return JSON.stringify({error:"replace_source_failed",detail:e.toString()});'
            '  }'
            '  try{dup.parent=target.parent;}catch(e){}'
            '  try{dup.inPoint=target.inPoint;}catch(e){}'
            '  try{dup.outPoint=target.outPoint;}catch(e){}'
            '  try{dup.startTime=target.startTime;}catch(e){}'
            '  try{dup.stretch=target.stretch;}catch(e){}'
            '  setPropValue(dup.anchorPoint, target.anchorPoint.value, comp.time);'
            '  setPropValue(dup.position, target.position.value, comp.time);'
            '  setPropValue(dup.scale, target.scale.value, comp.time);'
            '  setPropValue(dup.rotation, target.rotation.value, comp.time);'
            '  setPropValue(dup.opacity, target.opacity.value, comp.time);'
            '  try{dup.enabled=true;}catch(e){}'
            '  try{dup.solo=false;}catch(e){}'
            f'  if({str(bool(disable_target)).lower()}){{'
            '    try{if(target.enabled){target.solo=false;}}catch(e){}'
            '    try{target.enabled=false;}catch(e){}'
            '  }'
            '  for(var li=1;li<=comp.numLayers;li++){'
            '    try{comp.layer(li).selected=(comp.layer(li)===dup);}catch(e){}'
            '  }'
            '  var fxGroup=dup.property("ADBE Effect Parade");'
            '  var fx=null;'
            '  var fxIndex=0;'
            '  for(var fi=1;fi<=fxGroup.numProperties;fi++){'
            '    var candFx=fxGroup.property(fi);'
            '    if(candFx&&candFx.matchName==="ADBE FreePin3"){fx=candFx;fxIndex=fi;break;}'
            '  }'
            '  if(!fx){'
            '    try{dup.remove();}catch(_e){}'
            '    return JSON.stringify({error:"template_puppet_not_found"});'
            '  }'
            '  var arap=fx.property("ADBE FreePin3 ARAP Group");'
            '  var meshGroup=arap?arap.property("ADBE FreePin3 Mesh Group"):null;'
            '  if(!meshGroup||meshGroup.numProperties<1){'
            '    try{dup.remove();}catch(_e){}'
            '    return JSON.stringify({error:"template_mesh_not_found"});'
            '  }'
            '  var mesh=null;'
            '  var meshIndex=0;'
            '  var pinCount=0;'
            '  for(var mi=1;mi<=meshGroup.numProperties;mi++){'
            '    var candMesh=meshGroup.property(mi);'
            '    var candPins=candMesh?candMesh.property("ADBE FreePin3 PosPins"):null;'
            '    if(candPins){mesh=candMesh;meshIndex=mi;pinCount=candPins.numProperties;break;}'
            '  }'
            '  if(!mesh){'
            '    try{dup.remove();}catch(_e){}'
            '    return JSON.stringify({error:"template_pospins_not_found"});'
            '  }'
            '  return JSON.stringify({'
            '    target_index:target.index,'
            '    target_name:target.name,'
            '    layer_index:dup.index,'
            '    layer_name:dup.name,'
            '    source_name:targetSource.name,'
            '    template_comp_name:templateComp.name,'
            '    template_layer_name:templateLayer.name,'
            '    effect_index:fxIndex,'
            '    mesh_index:meshIndex,'
            '    pin_count:pinCount'
            '  });'
            '}finally{'
            '  app.endUndoGroup();'
            '}'
            '})()'
        )
        return json.loads(self.run_jsx(jsx, timeout=60000))

    def add_puppet_pins_on_real_mesh(self, layer: Union[str, int],
                                     points: List[List[float]],
                                     effect_index: int = None,
                                     mesh_index: int = 1,
                                     points_are_comp: bool = True,
                                     reuse_first_pin: bool = True) -> Dict[str, Any]:
        """
        在“已经存在真实 mesh”的 Puppet 层上后台补 pin。

        约束：
        - 目标层必须先带有至少 1 个真实 pin（例如来自模板层）
        - 默认会把第 1 个已有 pin 移到 `points[0]`，然后再补剩余 pin
        """
        if not isinstance(points, (list, tuple)) or not points:
            raise ValueError("points must be [[x, y], ...]")

        normalized_points: List[List[float]] = []
        for pt in points:
            if not isinstance(pt, (list, tuple)) or len(pt) != 2:
                raise ValueError("points must be [[x, y], ...]")
            normalized_points.append([float(pt[0]), float(pt[1])])

        name_to_index, index_to_name = self._get_layer_lookup_maps()
        layer_index, layer_name = self._resolve_layer_ref(
            layer,
            name_to_index=name_to_index,
            index_to_name=index_to_name,
        )
        if layer_index is None:
            return {"error": f"layer_not_found:{layer_name}"}

        source_points = normalized_points
        if points_are_comp:
            source_points = self._convert_comp_points_to_source_points(
                layer_index,
                normalized_points,
            )

        requested_effect_index = int(effect_index) if effect_index else 0
        resolved_mesh_index = max(1, int(mesh_index))

        validate_jsx = (
            '(function(){'
            'function findPuppet(layer, requestedIndex){'
            '  var fxGroup=layer.property("ADBE Effect Parade");'
            '  var fx=null;'
            '  var fxIndex=0;'
            '  if(requestedIndex>0){'
            '    fx=fxGroup.property(requestedIndex);'
            '    if(!fx||fx.matchName!=="ADBE FreePin3"){return {error:"puppet_effect_not_found"};}'
            '    fxIndex=requestedIndex;'
            '  }else{'
            '    for(var i=1;i<=fxGroup.numProperties;i++){'
            '      var cand=fxGroup.property(i);'
            '      if(cand&&cand.matchName==="ADBE FreePin3"){fx=cand;fxIndex=i;break;}'
            '    }'
            '    if(!fx){return {error:"puppet_effect_not_found"};}'
            '  }'
            '  return {fx:fx,fxIndex:fxIndex};'
            '}'
            'var comp=app.project.activeItem;'
            'if(!comp||!(comp instanceof CompItem))return JSON.stringify({error:"no_comp"});'
            f'var layer=comp.layer({int(layer_index)});'
            'if(!layer)return JSON.stringify({error:"no_layer"});'
            f'var requestedEffectIndex={requested_effect_index};'
            'var info=findPuppet(layer, requestedEffectIndex);'
            'if(info.error)return JSON.stringify(info);'
            'var arap=info.fx.property("ADBE FreePin3 ARAP Group");'
            'if(!arap)return JSON.stringify({error:"puppet_arap_not_found"});'
            'var meshGroup=arap.property("ADBE FreePin3 Mesh Group");'
            'if(!meshGroup)return JSON.stringify({error:"puppet_mesh_group_not_found"});'
            f'var mesh=meshGroup.numProperties>={resolved_mesh_index}?meshGroup.property({resolved_mesh_index}):null;'
            'if(!mesh)return JSON.stringify({error:"puppet_mesh_not_found"});'
            'var posPins=mesh.property("ADBE FreePin3 PosPins");'
            'if(!posPins)return JSON.stringify({error:"puppet_pospins_not_found"});'
            'if(posPins.numProperties<1)return JSON.stringify({error:"template_seed_pin_missing"});'
            'return JSON.stringify({'
            '  layer_index:layer.index,'
            '  layer_name:layer.name,'
            '  effect_index:info.fxIndex,'
            f'  mesh_index:{resolved_mesh_index},'
            '  pin_count:posPins.numProperties'
            '});'
            '})()'
        )
        result = json.loads(self.run_jsx(validate_jsx, timeout=30000))
        if result.get("error"):
            return result

        moved: List[Dict[str, Any]] = []
        added: List[Dict[str, Any]] = []
        start_index = 0

        if reuse_first_pin and source_points:
            first_point = source_points[0]
            first_jsx = (
                '(function(){'
                'function setPropValue(prop, value, time){'
                '  if(!prop)return false;'
                '  try{'
                '    if(prop.numKeys && prop.numKeys > 0){prop.setValueAtTime(time, value);}else{prop.setValue(value);}'
                '    return true;'
                '  }catch(e){'
                '    try{prop.setValueAtTime(time, value);return true;}catch(_e){return false;}'
                '  }'
                '}'
                'var comp=app.project.activeItem;'
                'if(!comp||!(comp instanceof CompItem))return JSON.stringify({error:"no_comp"});'
                f'var layer=comp.layer({int(layer_index)});'
                'if(!layer)return JSON.stringify({error:"no_layer"});'
                f'var fx=layer.property("ADBE Effect Parade").property({int(result["effect_index"])});'
                'if(!fx)return JSON.stringify({error:"puppet_effect_not_found"});'
                'var meshGroup=fx.property("ADBE FreePin3 ARAP Group").property("ADBE FreePin3 Mesh Group");'
                'if(!meshGroup)return JSON.stringify({error:"puppet_mesh_group_not_found"});'
                f'var mesh=meshGroup.property({resolved_mesh_index});'
                'if(!mesh)return JSON.stringify({error:"puppet_mesh_not_found"});'
                'var posPins=mesh.property("ADBE FreePin3 PosPins");'
                'if(!posPins||posPins.numProperties<1)return JSON.stringify({error:"template_seed_pin_missing"});'
                'var firstPin=posPins.property(1);'
                'var pos=firstPin?firstPin.property("ADBE FreePin3 PosPin Position"):null;'
                'if(!pos)return JSON.stringify({error:"template_seed_position_not_found"});'
                f'var pt={json.dumps(first_point)};'
                'if(!setPropValue(pos, pt, comp.time))return JSON.stringify({error:"template_seed_set_failed"});'
                'var compPos=layer.sourcePointToComp(pt);'
                'return JSON.stringify({'
                '  index:1,'
                '  source_position:[pt[0],pt[1]],'
                '  comp_position:[compPos[0],compPos[1]]'
                '});'
                '})()'
            )
            first_result = json.loads(self.run_jsx(first_jsx, timeout=30000))
            if first_result.get("error"):
                return first_result
            moved.append(first_result)
            start_index = 1

        for pt in source_points[start_index:]:
            add_jsx = (
                '(function(){'
                'function setPropValue(prop, value, time){'
                '  if(!prop)return false;'
                '  try{'
                '    if(prop.numKeys && prop.numKeys > 0){prop.setValueAtTime(time, value);}else{prop.setValue(value);}'
                '    return true;'
                '  }catch(e){'
                '    try{prop.setValueAtTime(time, value);return true;}catch(_e){return false;}'
                '  }'
                '}'
                'var comp=app.project.activeItem;'
                'if(!comp||!(comp instanceof CompItem))return JSON.stringify({error:"no_comp"});'
                f'var layer=comp.layer({int(layer_index)});'
                'if(!layer)return JSON.stringify({error:"no_layer"});'
                f'var fx=layer.property("ADBE Effect Parade").property({int(result["effect_index"])});'
                'if(!fx)return JSON.stringify({error:"puppet_effect_not_found"});'
                'var meshGroup=fx.property("ADBE FreePin3 ARAP Group").property("ADBE FreePin3 Mesh Group");'
                'if(!meshGroup)return JSON.stringify({error:"puppet_mesh_group_not_found"});'
                f'var mesh=meshGroup.property({resolved_mesh_index});'
                'if(!mesh)return JSON.stringify({error:"puppet_mesh_not_found"});'
                'var posPins=mesh.property("ADBE FreePin3 PosPins");'
                'if(!posPins)return JSON.stringify({error:"puppet_pospins_not_found"});'
                'var pin=posPins.addProperty("ADBE FreePin3 PosPin Atom");'
                'if(!pin)return JSON.stringify({error:"add_pospin_failed"});'
                'var pos=pin.property("ADBE FreePin3 PosPin Position");'
                'if(!pos)return JSON.stringify({error:"pospin_position_not_found"});'
                f'var pt={json.dumps(pt)};'
                'if(!setPropValue(pos, pt, comp.time))return JSON.stringify({error:"pospin_set_failed"});'
                'var compPos=layer.sourcePointToComp(pt);'
                'return JSON.stringify({'
                '  index:posPins.numProperties,'
                '  source_position:[pt[0],pt[1]],'
                '  comp_position:[compPos[0],compPos[1]]'
                '});'
                '})()'
            )
            add_result = json.loads(self.run_jsx(add_jsx, timeout=30000))
            if add_result.get("error"):
                add_result["moved"] = moved
                add_result["added"] = added
                return add_result
            added.append(add_result)

        result["requested_point_count"] = len(source_points)
        result["reused_first_pin"] = bool(reuse_first_pin)
        result["moved"] = moved
        result["added"] = added
        result["pin_count"] = int(result.get("pin_count", 0)) + len(added)
        result["requested_points"] = normalized_points
        result["source_points"] = source_points
        return result

    def auto_place_puppet_pins_from_multi_pin_template(self, target_layer: Union[str, int],
                                                       template_layer: str,
                                                       template_comp: str = None,
                                                       pin_count: int = None,
                                                       time: float = -1,
                                                       alpha_threshold: int = 8,
                                                       edge_inset: float = 0,
                                                       band_expand: float = 1.0,
                                                       root_mode: str = "wide_to_narrow",
                                                       new_name: str = None,
                                                       disable_target: bool = True,
                                                       move_after_target: bool = True,
                                                       remove_extra: bool = True) -> Dict[str, Any]:
        """
        用“已经带足够真实 pins”的模板层走全后台自动打点。

        这条路线不会再尝试脚本新增 pin，而是：
        1. 复制真实模板层并 replaceSource 到目标 source
        2. 用边缘检测 + 像素读取得到目标点
        3. 直接重定位模板里已有的真实 pins

        适合需要 3 个及以上可用 pin 的稳定方案。
        """
        alpha_threshold = max(1, min(255, int(alpha_threshold)))
        band_expand = max(0.25, float(band_expand))
        edge_inset = max(0.0, float(edge_inset))
        root_mode = str(root_mode or "wide_to_narrow").strip().lower()
        if root_mode not in {"wide_to_narrow", "narrow_to_wide", "forward", "reverse"}:
            raise ValueError("root_mode must be wide_to_narrow/narrow_to_wide/forward/reverse")

        name_to_index, index_to_name = self._get_layer_lookup_maps()
        target_index, target_name = self._resolve_layer_ref(
            target_layer,
            name_to_index=name_to_index,
            index_to_name=index_to_name,
        )
        if target_index is None:
            return {"error": f"layer_not_found:{target_name}"}

        instantiate = self.instantiate_puppet_template_layer(
            target_layer=target_index,
            template_layer=template_layer,
            template_comp=template_comp,
            new_name=new_name,
            disable_target=disable_target,
            move_after_target=move_after_target,
        )
        if instantiate.get("error"):
            return instantiate

        template_pin_count = max(0, int(instantiate.get("pin_count", 0) or 0))
        requested_pin_count = template_pin_count if pin_count is None else max(1, int(pin_count))
        if template_pin_count < requested_pin_count:
            instantiate["error"] = "insufficient_template_pins"
            instantiate["reason"] = (
                "Template layer does not contain enough real Puppet pins for pure-backend "
                "repositioning. Provide a template with at least the requested pin count."
            )
            instantiate["template_pin_count"] = template_pin_count
            instantiate["requested_pin_count"] = requested_pin_count
            instantiate["target_layer_index"] = target_index
            instantiate["target_layer_name"] = index_to_name.get(target_index) or target_name
            return instantiate

        outline = self._detect_puppet_pin_targets(
            layer_index=target_index,
            pin_count=requested_pin_count,
            time=time,
            alpha_threshold=alpha_threshold,
            edge_inset=edge_inset,
            band_expand=band_expand,
            root_mode=root_mode,
        )
        if outline.get("error"):
            outline["instantiated"] = instantiate
            outline["target_layer_index"] = target_index
            outline["target_layer_name"] = index_to_name.get(target_index) or target_name
            return outline

        comp_points = [row["comp_position"] for row in outline.get("points", [])]
        if not comp_points:
            return {
                "error": "no_detected_points",
                "instantiated": instantiate,
                "target_layer_index": target_index,
                "target_layer_name": index_to_name.get(target_index) or target_name,
            }

        reposition = self.set_puppet_pin_positions(
            layer=instantiate["layer_index"],
            points=comp_points,
            effect_index=instantiate.get("effect_index"),
            mesh_index=instantiate.get("mesh_index", 1),
            points_are_comp=True,
            remove_extra=remove_extra,
        )
        reposition["strategy"] = "reposition_existing_real_pins"
        reposition["detected"] = outline
        reposition["suggested_comp_points"] = comp_points
        reposition["instantiated"] = instantiate
        reposition["template_pin_count"] = template_pin_count
        reposition["requested_pin_count"] = requested_pin_count
        reposition["target_layer_index"] = target_index
        reposition["target_layer_name"] = index_to_name.get(target_index) or target_name
        return reposition

    def auto_place_puppet_pins_from_template(self, target_layer: Union[str, int],
                                             template_layer: str,
                                             template_comp: str = None,
                                             pin_count: int = 3,
                                             time: float = -1,
                                             alpha_threshold: int = 8,
                                             edge_inset: float = 0,
                                             band_expand: float = 1.0,
                                             root_mode: str = "wide_to_narrow",
                                             new_name: str = None,
                                             disable_target: bool = True,
                                             move_after_target: bool = True) -> Dict[str, Any]:
        """
        用“真实模板层”走全后台自动打 Puppet pins：
        1. 对目标层做边缘检测 + 像素精确取点
        2. 复制真实模板层并 replaceSource 到目标 source
        3. 在 real mesh 上后台重定位第 1 个 pin 并补其余 pins

        注意：
        - 这条旧路线本质上仍是“seed pin + 后台补 pin”
        - 当前实测只确认“已有真实 mesh + 第 1 个脚本新增 pin”可形变
        - 如果需要 3 个及以上稳定可用 pins，改用
          `auto_place_puppet_pins_from_multi_pin_template(...)`
        """
        pin_count = max(1, int(pin_count))
        alpha_threshold = max(1, min(255, int(alpha_threshold)))
        band_expand = max(0.25, float(band_expand))
        edge_inset = max(0.0, float(edge_inset))
        root_mode = str(root_mode or "wide_to_narrow").strip().lower()
        if root_mode not in {"wide_to_narrow", "narrow_to_wide", "forward", "reverse"}:
            raise ValueError("root_mode must be wide_to_narrow/narrow_to_wide/forward/reverse")

        name_to_index, index_to_name = self._get_layer_lookup_maps()
        target_index, target_name = self._resolve_layer_ref(
            target_layer,
            name_to_index=name_to_index,
            index_to_name=index_to_name,
        )
        if target_index is None:
            return {"error": f"layer_not_found:{target_name}"}

        outline = self._detect_puppet_pin_targets(
            layer_index=target_index,
            pin_count=pin_count,
            time=time,
            alpha_threshold=alpha_threshold,
            edge_inset=edge_inset,
            band_expand=band_expand,
            root_mode=root_mode,
        )
        if outline.get("error"):
            return outline

        comp_points = [row["comp_position"] for row in outline.get("points", [])]
        if not comp_points:
            return {"error": "no_detected_points", "layer_index": target_index}

        instantiate = self.instantiate_puppet_template_layer(
            target_layer=target_index,
            template_layer=template_layer,
            template_comp=template_comp,
            new_name=new_name,
            disable_target=disable_target,
            move_after_target=move_after_target,
        )
        if instantiate.get("error"):
            instantiate["detected"] = outline
            instantiate["suggested_comp_points"] = comp_points
            return instantiate

        add_result = self.add_puppet_pins_on_real_mesh(
            layer=instantiate["layer_index"],
            points=comp_points,
            effect_index=instantiate.get("effect_index"),
            mesh_index=instantiate.get("mesh_index", 1),
            points_are_comp=True,
            reuse_first_pin=True,
        )
        add_result["detected"] = outline
        add_result["suggested_comp_points"] = comp_points
        add_result["instantiated"] = instantiate
        add_result["target_layer_index"] = target_index
        add_result["target_layer_name"] = index_to_name.get(target_index) or target_name
        return add_result

    def auto_place_puppet_pins(self, layer: Union[str, int],
                               pin_count: int = 3,
                               time: float = -1,
                               alpha_threshold: int = 8,
                               effect_index: int = None,
                               mesh_index: int = 1,
                               clear_existing: bool = False,
                               edge_inset: float = 0,
                               band_expand: float = 1.0,
                               root_mode: str = "wide_to_narrow") -> Dict[str, Any]:
        """
        用类似 Spine 的轮廓切片方式自动检测边缘并打 Puppet pins。

        `root_mode`:
        - `wide_to_narrow`: 自动把更宽的一端当 root
        - `narrow_to_wide`: 与上面相反
        - `forward`: 保持主轴正向顺序
        - `reverse`: 反转主轴顺序
        """
        pin_count = max(1, int(pin_count))
        alpha_threshold = max(1, min(255, int(alpha_threshold)))
        band_expand = max(0.25, float(band_expand))
        edge_inset = max(0.0, float(edge_inset))
        root_mode = str(root_mode or "wide_to_narrow").strip().lower()
        if root_mode not in {"wide_to_narrow", "narrow_to_wide", "forward", "reverse"}:
            raise ValueError("root_mode must be wide_to_narrow/narrow_to_wide/forward/reverse")

        name_to_index, index_to_name = self._get_layer_lookup_maps()
        layer_index, layer_name = self._resolve_layer_ref(
            layer,
            name_to_index=name_to_index,
            index_to_name=index_to_name,
        )
        if layer_index is None:
            return {"error": f"layer_not_found:{layer_name}"}

        outline = self._detect_puppet_pin_targets(
            layer_index=layer_index,
            pin_count=pin_count,
            time=time,
            alpha_threshold=alpha_threshold,
            edge_inset=edge_inset,
            band_expand=band_expand,
            root_mode=root_mode,
        )
        if outline.get("error"):
            return outline

        comp_points = [row["comp_position"] for row in outline.get("points", [])]
        if not comp_points:
            return {"error": "no_detected_points", "layer_index": layer_index}

        add_result = self.add_puppet_pins(
            layer=layer_index,
            points=comp_points,
            effect_index=effect_index,
            mesh_index=mesh_index,
            clear_existing=clear_existing,
            points_are_comp=True,
        )
        add_result["suggested_comp_points"] = comp_points
        add_result["detected"] = outline
        return add_result

    def detect_solid_background_layers(self, max_layers: int = 2,
                                       tolerance: int = 5) -> List[dict]:
        """检测合成底部的纯色图层（不限颜色/亮度/透明度，只要像素一致即为纯色）。"""
        max_layers = max(1, int(max_layers))
        tolerance = max(0, int(tolerance))

        matches = []
        for candidate in self._get_solid_bg_candidates(max_layers):
            if candidate.get("skipReason"):
                continue

            solid_rgb = candidate.get("solidColor8")
            if solid_rgb:
                matches.append({
                    "index": candidate["index"],
                    "name": candidate["name"],
                    "sourceName": candidate.get("sourceName", ""),
                    "method": "solid_source",
                    "rgba": solid_rgb + [255],
                })
                continue

            pixel_info = self._analyze_layer_pixels(
                int(candidate["index"]),
                tolerance=tolerance,
            )
            if pixel_info.get("uniform"):
                matches.append({
                    "index": candidate["index"],
                    "name": candidate["name"],
                    "sourceName": candidate.get("sourceName", ""),
                    "method": "pixel_check",
                    "rgba": pixel_info.get("rgba", []),
                })

        return matches

    def _get_layer_lookup_maps(self) -> tuple[Dict[str, int], Dict[int, str]]:
        """Build name/index lookup maps from the active comp layer list."""
        name_to_index: Dict[str, int] = {}
        index_to_name: Dict[int, str] = {}
        for row in self.list_layers():
            if "index" not in row:
                continue
            idx = int(row["index"])
            name = str(row.get("name", ""))
            index_to_name[idx] = name
            if name and name not in name_to_index:
                name_to_index[name] = idx
        return name_to_index, index_to_name

    def _resolve_layer_ref(self, layer: Union[str, int],
                           name_to_index: Optional[Dict[str, int]] = None,
                           index_to_name: Optional[Dict[int, str]] = None
                           ) -> tuple[Optional[int], Optional[str]]:
        """Resolve layer reference to (index, name)."""
        if isinstance(layer, int):
            layer_index = int(layer)
            layer_name = index_to_name.get(layer_index) if index_to_name else None
            return layer_index, layer_name

        layer_name = str(layer)
        if name_to_index is None:
            name_to_index, _ = self._get_layer_lookup_maps()
        layer_index = name_to_index.get(layer_name)
        if layer_index is None:
            return None, layer_name
        return layer_index, layer_name

    def approximate_layer_color(self, layer: Union[str, int],
                                time: float = -1,
                                max_dimension: int = 32,
                                tolerance: int = 5) -> Dict[str, Any]:
        """快速读取单层近似颜色统计，内部走 32x32 级别的 C++ renderFramePixels。"""
        name_to_index, index_to_name = self._get_layer_lookup_maps()
        layer_index, layer_name = self._resolve_layer_ref(
            layer,
            name_to_index=name_to_index,
            index_to_name=index_to_name,
        )
        if layer_index is None:
            return {"error": f"layer_not_found:{layer_name}"}

        stats = self._analyze_layer_pixels(
            layer_index,
            tolerance=tolerance,
            time=time,
            max_dimension=max_dimension,
        )
        stats["index"] = layer_index
        resolved_name = index_to_name.get(layer_index) or layer_name
        if resolved_name:
            stats["name"] = resolved_name
        return stats

    def approximate_layers_color(self, layers: List[Union[str, int]],
                                 time: float = -1,
                                 max_dimension: int = 32,
                                 tolerance: int = 5) -> List[Dict[str, Any]]:
        """批量快速读取多层近似颜色统计。"""
        if not isinstance(layers, (list, tuple)) or not layers:
            raise ValueError("layers must be [layer, ...]")

        name_to_index, index_to_name = self._get_layer_lookup_maps()
        results: List[Dict[str, Any]] = []

        for layer in layers:
            layer_index, layer_name = self._resolve_layer_ref(
                layer,
                name_to_index=name_to_index,
                index_to_name=index_to_name,
            )
            if layer_index is None:
                results.append({
                    "error": f"layer_not_found:{layer_name}",
                    "requested": layer_name,
                })
                continue

            stats = self._analyze_layer_pixels(
                layer_index,
                tolerance=tolerance,
                time=time,
                max_dimension=max_dimension,
            )
            stats["index"] = layer_index
            resolved_name = index_to_name.get(layer_index) or layer_name
            if resolved_name:
                stats["name"] = resolved_name
            results.append(stats)

        return results

    def remove_solid_background_layers(self, max_layers: int = 2,
                                       tolerance: int = 5) -> Dict[str, Any]:
        """检测并删除合成底部的纯色图层。"""
        matches = self.detect_solid_background_layers(
            max_layers=max_layers,
            tolerance=tolerance,
        )
        if not matches:
            return {"removed": 0, "layers": []}

        indices = sorted((int(item["index"]) for item in matches), reverse=True)
        jsx = (
            '(function(){'
            'var c=app.project.activeItem;'
            'if(!c||!(c instanceof CompItem))return"ERR:no_comp";'
            f'var idxs={json.dumps(indices)};'
            'var removed=0;'
            'app.beginUndoGroup("Remove Solid Background Layers");'
            'for(var i=0;i<idxs.length;i++){'
            '  try{c.layer(idxs[i]).remove();removed++;}catch(e){}'
            '}'
            'app.endUndoGroup();'
            'return JSON.stringify({removed:removed});'
            '})()'
        )
        raw = self.run_jsx(jsx)
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {"removed": len(indices)}
        result["layers"] = matches
        return result

    def _get_solid_bg_candidates(self, max_layers: int) -> List[dict]:
        jsx = (
            '(function(){'
            'var comp=app.project.activeItem;'
            'if(!comp||!(comp instanceof CompItem))return"ERR:no_comp";'
            'var out=[];'
            f'var start=Math.max(1,comp.numLayers-{max_layers}+1);'
            'for(var i=comp.numLayers;i>=start;i--){'
            '  var l=comp.layer(i);'
            '  var src=null;'
            '  try{src=l.source;}catch(e){}'
            '  var mainSource=null;'
            '  try{mainSource=src?src.mainSource:null;}catch(e){}'
            '  var row={'
            '    index:i,'
            '    name:l.name,'
            '    hasSource:!!src,'
            '    hasVideo:!!l.hasVideo,'
            '    isAdjustment:!!l.adjustmentLayer,'
            '    isCamera:(l instanceof CameraLayer),'
            '    isLight:(l instanceof LightLayer),'
            '    isNull:!!l.nullLayer,'
            '    sourceName:src?src.name:""'
            '  };'
            '  if(mainSource && mainSource instanceof SolidSource){'
            '    row.solidColor=[mainSource.color[0],mainSource.color[1],mainSource.color[2]];'
            '  }'
            '  out.push(row);'
            '}'
            'return JSON.stringify(out);'
            '})()'
        )
        raw = self.run_jsx(jsx)
        candidates = json.loads(raw)
        for row in candidates:
            if row.get("solidColor"):
                row["solidColor8"] = _normalize_rgb_255(row["solidColor"])
            if row.get("isCamera"):
                row["skipReason"] = "camera"
            elif row.get("isLight"):
                row["skipReason"] = "light"
            elif row.get("isNull"):
                row["skipReason"] = "null"
            elif row.get("isAdjustment"):
                row["skipReason"] = "adjustment"
            elif not row.get("hasVideo"):
                row["skipReason"] = "no_video"
            elif not row.get("hasSource"):
                row["skipReason"] = "no_source"
        return candidates

    def _analyze_layer_pixels(self, layer_index: int, tolerance: int = 5,
                              time: float = -1, max_dimension: int = 32) -> Dict[str, Any]:
        setup_jsx = (
            '(function(){'
            'var comp=app.project.activeItem;'
            'if(!comp||!(comp instanceof CompItem))return JSON.stringify({error:"no_comp"});'
            f'var target={int(layer_index)};'
            'if(target<1||target>comp.numLayers)return JSON.stringify({error:"no_layer"});'
            'var solos=[];'
            'for(var i=1;i<=comp.numLayers;i++){'
            '  var l=comp.layer(i);'
            '  var enabled=!!l.enabled;'
            '  solos.push(enabled ? !!l.solo : null);'
            '  if(enabled){'
            '    if(i===target){'
            '      l.solo=true;'
            '    }else if(l.solo){'
            '      l.solo=false;'
            '    }'
            '  }'
            '}'
            'return JSON.stringify({solo:solos,videoActive:!!comp.layer(target).enabled});'
            '})()'
        )
        setup = json.loads(self.run_jsx(setup_jsx, timeout=30000))
        if setup.get("error"):
            return {"uniform": False, "error": f"ERR:{setup['error']}"}

        py_code = (
            'import json\n'
            f'time_value={float(time)}\n'
            f'max_dim={max(1, int(max_dimension))}\n'
            f'tol={max(0, int(tolerance))}\n'
            'comp=app.project.activeItem\n'
            'if comp is None or type(comp).__name__ != "CompItem":\n'
            '    raise RuntimeError("no_active_comp")\n'
            'px=comp.renderFramePixels(time_value, max_dim)\n'
            'height=int(px.shape[0])\n'
            'width=int(px.shape[1])\n'
            'center_y=height//2\n'
            'center_x=width//2\n'
            'sample=[int(px[center_y,center_x,0]), int(px[center_y,center_x,1]), int(px[center_y,center_x,2]), int(px[center_y,center_x,3])]\n'
            'alpha_min=255\n'
            'alpha_max=0\n'
            'sum_r=sum_g=sum_b=sum_a=0\n'
            'uniform=True\n'
            'for y in range(height):\n'
            '    for x in range(width):\n'
            '        r=int(px[y,x,0]); g=int(px[y,x,1]); b=int(px[y,x,2]); a=int(px[y,x,3])\n'
            '        sum_r += r; sum_g += g; sum_b += b; sum_a += a\n'
            '        alpha_min=min(alpha_min, a)\n'
            '        alpha_max=max(alpha_max, a)\n'
            '        if abs(r-sample[0])>tol or abs(g-sample[1])>tol or abs(b-sample[2])>tol or abs(a-sample[3])>tol:\n'
            '            uniform=False\n'
            'count=max(1, width*height)\n'
            '_result=json.dumps({'
            '    "uniform":uniform,'
            '    "rgba":sample,'
            '    "avg_rgba":[round(sum_r/count,1), round(sum_g/count,1), round(sum_b/count,1), round(sum_a/count,1)],'
            '    "center_rgba":sample,'
            '    "alpha_min":alpha_min,'
            '    "alpha_max":alpha_max,'
            '    "width":width,'
            '    "height":height'
            '})\n'
        )
        try:
            pixel_info = json.loads(self._run_py(py_code, timeout=60))
        finally:
            restore_jsx = (
                '(function(){'
                'var comp=app.project.activeItem;'
                'if(!comp||!(comp instanceof CompItem))return"no_comp";'
                f'var solos={json.dumps(setup.get("solo", []))};'
                'for(var i=1;i<=comp.numLayers&&i<=solos.length;i++){'
                '  if(solos[i-1]!==null){comp.layer(i).solo=!!solos[i-1];}'
                '}'
                'return"ok";'
                '})()'
            )
            try:
                self.run_jsx(restore_jsx, timeout=30000)
            except Exception:
                pass

        pixel_info["video_active"] = bool(setup.get("videoActive"))
        return pixel_info

    def _convert_comp_points_to_source_points(self, layer_index: int,
                                              points: List[List[float]]) -> List[List[float]]:
        """Convert comp-space points into source/layer-space points for Puppet pins."""
        jsx = (
            '(function(){'
            'var comp=app.project.activeItem;'
            'if(!comp||!(comp instanceof CompItem))return JSON.stringify({error:"no_comp"});'
            f'var layer=comp.layer({int(layer_index)});'
            'if(!layer)return JSON.stringify({error:"no_layer"});'
            f'var pts={json.dumps(points)};'
            'var out=[];'
            'for(var i=0;i<pts.length;i++){'
            '  var src=layer.compPointToSource(pts[i]);'
            '  out.push([src[0],src[1]]);'
            '}'
            'return JSON.stringify({points:out});'
            '})()'
        )
        result = json.loads(self.run_jsx(jsx, timeout=30000))
        if result.get("error"):
            raise RuntimeError(result["error"])
        return result["points"]

    def _detect_puppet_pin_targets(self, layer_index: int,
                                   pin_count: int,
                                   time: float,
                                   alpha_threshold: int,
                                   edge_inset: float,
                                   band_expand: float,
                                   root_mode: str) -> Dict[str, Any]:
        """Detect cross-section centers from the rendered alpha silhouette."""
        setup_jsx = (
            '(function(){'
            'var comp=app.project.activeItem;'
            'if(!comp||!(comp instanceof CompItem))return JSON.stringify({error:"no_comp"});'
            f'var target={int(layer_index)};'
            'if(target<1||target>comp.numLayers)return JSON.stringify({error:"no_layer"});'
            'var states=[];'
            'for(var i=1;i<=comp.numLayers;i++){'
            '  var l=comp.layer(i);'
            '  states.push({enabled:!!l.enabled,solo:!!l.solo});'
            '  if(i===target){'
            '    l.enabled=true;'
            '    l.solo=true;'
            '  }else if(l.solo){'
            '    l.solo=false;'
            '  }'
            '}'
            'return JSON.stringify({states:states});'
            '})()'
        )
        setup = json.loads(self.run_jsx(setup_jsx, timeout=30000))
        if setup.get("error"):
            return {"error": f"ERR:{setup['error']}"}

        py_code = (
            'import json\n'
            'import math\n'
            f'time_value={float(time)}\n'
            f'pin_count={max(1, int(pin_count))}\n'
            f'alpha_threshold={max(1, min(255, int(alpha_threshold)))}\n'
            f'edge_inset={max(0.0, float(edge_inset))}\n'
            f'band_expand={max(0.25, float(band_expand))}\n'
            f'root_mode={json.dumps(root_mode)}\n'
            'comp=app.project.activeItem\n'
            'if comp is None or type(comp).__name__ != "CompItem":\n'
            '    raise RuntimeError("no_active_comp")\n'
            'px=comp.renderFramePixels(time_value)\n'
            'alpha=px[:,:,3]\n'
            'mask=alpha >= alpha_threshold\n'
            'ys, xs = mask.nonzero()\n'
            'if int(xs.size) == 0:\n'
            '    raise RuntimeError("layer_has_no_opaque_pixels")\n'
            'x_min=int(xs.min())\n'
            'x_max=int(xs.max())\n'
            'y_min=int(ys.min())\n'
            'y_max=int(ys.max())\n'
            'mx=float(xs.mean())\n'
            'my=float(ys.mean())\n'
            'dx=xs.astype("float64")-mx\n'
            'dy=ys.astype("float64")-my\n'
            'cov_xx=float((dx*dx).mean())\n'
            'cov_xy=float((dx*dy).mean())\n'
            'cov_yy=float((dy*dy).mean())\n'
            'bbox_w=max(1, x_max-x_min+1)\n'
            'bbox_h=max(1, y_max-y_min+1)\n'
            'if abs(cov_xy) < 1e-9 and abs(cov_xx-cov_yy) < 1e-9:\n'
            '    if bbox_h >= bbox_w:\n'
            '        axis_u=(0.0, 1.0)\n'
            '    else:\n'
            '        axis_u=(1.0, 0.0)\n'
            'else:\n'
            '    trace=cov_xx + cov_yy\n'
            '    diff=cov_xx - cov_yy\n'
            '    term=math.sqrt(diff*diff + 4.0*cov_xy*cov_xy)\n'
            '    lam=0.5*(trace + term)\n'
            '    vx=lam - cov_yy\n'
            '    vy=cov_xy\n'
            '    norm=math.hypot(vx, vy)\n'
            '    if norm < 1e-9:\n'
            '        vx=cov_xy\n'
            '        vy=lam - cov_xx\n'
            '        norm=math.hypot(vx, vy)\n'
            '    if norm < 1e-9:\n'
            '        if bbox_h >= bbox_w:\n'
            '            axis_u=(0.0, 1.0)\n'
            '        else:\n'
            '            axis_u=(1.0, 0.0)\n'
            '    else:\n'
            '        axis_u=(vx/norm, vy/norm)\n'
            'axis_v=(-axis_u[1], axis_u[0])\n'
            'proj_u=dx*axis_u[0] + dy*axis_u[1]\n'
            'proj_v=dx*axis_v[0] + dy*axis_v[1]\n'
            'u_min=float(proj_u.min())\n'
            'u_max=float(proj_u.max())\n'
            'if pin_count == 1:\n'
            '    targets=[0.5*(u_min+u_max)]\n'
            'else:\n'
            '    start=u_min + edge_inset\n'
            '    end=u_max - edge_inset\n'
            '    if end <= start:\n'
            '        start=u_min\n'
            '        end=u_max\n'
            '    step=(end-start)/max(1, pin_count-1)\n'
            '    targets=[start + step*i for i in range(pin_count)]\n'
            'total_span=max(1.0, u_max-u_min)\n'
            'band=max(2.0, (total_span/max(6.0, pin_count*4.0))*band_expand)\n'
            'points=[]\n'
            'for target in targets:\n'
            '    band_mask=abs(proj_u-target) <= band\n'
            '    if int(band_mask.sum()) == 0:\n'
            '        nearest=int(abs(proj_u-target).argmin())\n'
            '        band_mask=(abs(proj_u-target) <= abs(float(proj_u[nearest])-target) + 1e-9)\n'
            '    slice_x=xs[band_mask]\n'
            '    slice_y=ys[band_mask]\n'
            '    slice_u=proj_u[band_mask]\n'
            '    slice_v=proj_v[band_mask]\n'
            '    left_idx=int(slice_v.argmin())\n'
            '    right_idx=int(slice_v.argmax())\n'
            '    left=[int(slice_x[left_idx]), int(slice_y[left_idx])]\n'
            '    right=[int(slice_x[right_idx]), int(slice_y[right_idx])]\n'
            '    v_min=float(slice_v.min())\n'
            '    v_max=float(slice_v.max())\n'
            '    center_v=0.5*(v_min+v_max)\n'
            '    dist2=((slice_u-target)*(slice_u-target))+((slice_v-center_v)*(slice_v-center_v))\n'
            '    snap_idx=int(dist2.argmin())\n'
            '    center=[int(slice_x[snap_idx]), int(slice_y[snap_idx])]\n'
            '    points.append({'
            '        "comp_position":center,'
            '        "left_edge":left,'
            '        "right_edge":right,'
            '        "width":round(v_max-v_min, 2),'
            '        "axis_u":round(float(target), 3)'
            '    })\n'
            'sample_n=max(1, min(2, len(points)//2 if len(points) > 2 else 1))\n'
            'start_width=sum(p["width"] for p in points[:sample_n]) / sample_n\n'
            'end_width=sum(p["width"] for p in points[-sample_n:]) / sample_n\n'
            'reversed_order=False\n'
            'if root_mode == "wide_to_narrow":\n'
            '    if end_width > start_width:\n'
            '        points=list(reversed(points))\n'
            '        reversed_order=True\n'
            'elif root_mode == "narrow_to_wide":\n'
            '    if start_width > end_width:\n'
            '        points=list(reversed(points))\n'
            '        reversed_order=True\n'
            'elif root_mode == "reverse":\n'
            '    points=list(reversed(points))\n'
            '    reversed_order=True\n'
            'ordered_start_width=sum(p["width"] for p in points[:sample_n]) / sample_n\n'
            'ordered_end_width=sum(p["width"] for p in points[-sample_n:]) / sample_n\n'
            'for idx, point in enumerate(points, start=1):\n'
            '    point["index"]=idx\n'
            '_result=json.dumps({'
            '    "layer_index":int(' + str(int(layer_index)) + '),'
            '    "pin_count":len(points),'
            '    "bbox":[x_min,y_min,x_max,y_max],'
            '    "bbox_size":[bbox_w,bbox_h],'
            '    "axis":[round(axis_u[0],6), round(axis_u[1],6)],'
            '    "center":[round(mx,2), round(my,2)],'
            '    "slice_band":round(band,2),'
            '    "root_mode":root_mode,'
            '    "axis_start_width":round(start_width,2),'
            '    "axis_end_width":round(end_width,2),'
            '    "start_width":round(ordered_start_width,2),'
            '    "end_width":round(ordered_end_width,2),'
            '    "reversed":reversed_order,'
            '    "points":points'
            '})\n'
        )
        try:
            outline = json.loads(self._run_py(py_code, timeout=180))
        finally:
            restore_jsx = (
                '(function(){'
                'var comp=app.project.activeItem;'
                'if(!comp||!(comp instanceof CompItem))return"no_comp";'
                f'var states={json.dumps(setup.get("states", []))};'
                'for(var i=1;i<=comp.numLayers&&i<=states.length;i++){'
                '  var state=states[i-1];'
                '  try{comp.layer(i).enabled=!!state.enabled;}catch(e){}'
                '  try{comp.layer(i).solo=!!state.solo;}catch(e){}'
                '}'
                'return"ok";'
                '})()'
            )
            try:
                self.run_jsx(restore_jsx, timeout=30000)
            except Exception:
                pass

        return outline

    # ── Agent Property Graph ──────────────────────────────

    def property_batch(
        self,
        layer: Union[str, int, Dict[str, Any]],
        operations: List[Dict[str, Any]],
        dry_run: bool = False,
        undo_name: str = "AE2Claude Agent Batch",
        fail_fast: bool = True,
        backend: str = "auto",
    ) -> dict:
        """Execute generic matchName property operations in one AE dispatch."""
        from ae2claude_mcp.properties import property_batch

        return property_batch(
            self, layer, operations, dry_run, undo_name, fail_fast, backend
        )

    def get_property(
        self,
        layer: Union[str, int, Dict[str, Any]],
        path: List[Union[str, int]],
        at_time: float = None,
        pre_expression: bool = False,
        backend: str = "auto",
    ) -> Any:
        """Read an arbitrary property using stable layer and matchName paths."""
        result = self.property_batch(
            layer,
            [{"action": "get", "path": path, "time": at_time,
              "preExpression": pre_expression}],
            backend=backend,
        )
        entry = result.get("results", [{}])[0]
        if not entry.get("ok"):
            raise RuntimeError(entry.get("error", "property read failed"))
        return entry.get("value")

    def set_property(
        self,
        layer: Union[str, int, Dict[str, Any]],
        path: List[Union[str, int]],
        value: Any,
        at_time: float = None,
        undo_name: str = "AE2Claude Set Property",
        backend: str = "auto",
    ) -> dict:
        """Set an arbitrary property, optionally creating a keyframe."""
        result = self.property_batch(
            layer,
            [{"action": "set", "path": path, "value": value, "time": at_time}],
            undo_name=undo_name,
            backend=backend,
        )
        entry = result.get("results", [{}])[0]
        if not entry.get("ok"):
            raise RuntimeError(entry.get("error", "property write failed"))
        return result

    def inspect_properties(
        self,
        layer: Union[str, int, Dict[str, Any]],
        path: List[Union[str, int]] = None,
        max_depth: int = 3,
        max_nodes: int = 512,
        backend: str = "auto",
    ) -> dict:
        """Discover the live AE property graph with agent-addressable paths."""
        from ae2claude_mcp.properties import inspect_properties

        return inspect_properties(
            self, layer, path, max_depth, max_nodes, backend
        )

    @staticmethod
    def _resolve_effect_prop(prop_key: str) -> Optional[str]:
        """Resolve effect prop_key to matchName by scanning EFFECTS registry.

        Searches all registered effects for a matching prop_key and returns
        the matchName. Returns None if prop_key not found in any effect.
        """
        for fx_data in EFFECTS.values():
            mn = fx_data["props"].get(prop_key)
            if mn is not None:
                return mn
        return None

    def _run_py(self, code: str, timeout: int = 30) -> str:
        """执行 Python 代码并返回 result 变量的值"""
        data = code.encode('utf-8')
        req = urllib.request.Request(
            f'{self._base_url}/',
            data=data,
            headers={'Content-Type': 'text/plain; charset=utf-8'}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            r = json.loads(resp.read())
        if r.get("ok"):
            val = r.get("result", "")
            if isinstance(val, str):
                val = val.strip("'\"")
            return val
        raise RuntimeError(r.get("error", "unknown"))


# ╔══════════════════════════════════════════════════════════╗
# ║                    HELPER FUNCTIONS                     ║
# ╚══════════════════════════════════════════════════════════╝

def _esc(s: str) -> str:
    """转义字符串用于嵌入 ExtendScript 字符串字面量"""
    return (s
        .replace('\\', '\\\\')
        .replace('"', '\\"')
        .replace("'", "\\'")
        .replace('\n', '\\n')
        .replace('\r', ''))


def _normalize_rgb_255(values: List[Any]) -> List[int]:
    """Normalize float RGB [0-1] or integer RGB [0-255] into 8-bit ints."""
    rgb = []
    for value in values[:3]:
        num = float(value)
        if 0.0 <= num <= 1.0:
            num *= 255.0
        rgb.append(int(round(max(0.0, min(255.0, num)))))
    return rgb


def _is_grayish_rgb(values: List[int], tolerance: int, min_luma: int) -> bool:
    """Return True when RGB is near-neutral and bright enough to be a bg plate."""
    if len(values) < 3:
        return False
    lo = min(values[:3])
    hi = max(values[:3])
    return (hi - lo) <= tolerance and lo >= min_luma


# ╔══════════════════════════════════════════════════════════╗
# ║                   CLI QUICK-TEST                        ║
# ╚══════════════════════════════════════════════════════════╝

def main():
    """快速测试: python ae_bridge.py [jsx_code]"""
    print(f"AE2Claude Bridge v{__version__}")
    print("=" * 50)

    try:
        ae = AEBridge()
        print(f"[OK] Connected to {ae._base_url}")

        # 基础测试
        r = ae.run_jsx('"hello_from_ae"')
        print(f"[1] Basic: {r}")

        info = ae.comp_info()
        print(f"[2] Comp: {info}")

        if len(sys.argv) > 1:
            # 执行命令行传入的 JSX
            code = ' '.join(sys.argv[1:])
            print(f"[3] Custom: {ae.run_jsx(code)}")

        ae.close()
        print("[OK] Done")

    except Exception as e:
        print(f"[FAIL] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
