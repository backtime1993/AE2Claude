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
import os
import re
import urllib.request
import urllib.error
from typing import Optional, List, Dict, Any, Tuple, Union

__version__ = "3.0.0"

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
    # --- Stroke ---
    "stroke_effect": {
        "matchName": "ADBE Stroke",
        "props": {}
    },
    # --- Levels ---
    "levels": {
        "matchName": "ADBE Easy Levels2",
        "props": {}
    },
    # --- Curves ---
    "curves": {
        "matchName": "ADBE CurvesCustom",
        "props": {}
    },
    # --- Hue/Saturation ---
    "hue_saturation": {
        "matchName": "ADBE HUE SATURATION",
        "props": {}
    },
    # --- CC Toner ---
    "cc_toner": {
        "matchName": "CC Toner",
        "props": {}
    },
    # --- Ramp/Gradient ---
    "gradient_ramp": {
        "matchName": "ADBE Ramp",
        "props": {}
    },
    # --- Turbulent Displace ---
    "turbulent_displace": {
        "matchName": "ADBE Turbulent Displace",
        "props": {}
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
# ║           KNOWN EFFECT MATCHNAMES (PROBE LIST)          ║
# ╠══════════════════════════════════════════════════════════╣
# ║ 用于 list_available_effects() 动态探测当前 AE 安装中    ║
# ║ 实际可用的效果。canAddProperty() 测试后返回。            ║
# ╚══════════════════════════════════════════════════════════╝

KNOWN_EFFECT_MATCHNAMES = [
    # ── Blur & Sharpen ──
    "ADBE Gaussian Blur 2", "ADBE Box Blur2", "ADBE Camera Lens Blur",
    "ADBE Radial Blur", "ADBE Sharpen", "ADBE Unsharp Mask2",
    "ADBE Channel Blur", "ADBE Compound Blur", "ADBE Directional Blur",
    "ADBE Motion Blur", "ADBE Smart Blur", "ADBE Bilateral",
    "CC Cross Blur", "CC Radial Blur", "CC Radial Fast Blur", "CC Vector Blur",
    # ── Color Correction ──
    "ADBE Brightness & Contrast 2", "ADBE CurvesCustom", "ADBE Easy Levels2",
    "ADBE HUE SATURATION", "ADBE Vibrance", "ADBE Color Balance (HLS)",
    "ADBE Color Balance 2", "ADBE Tint", "ADBE Tritone", "ADBE Pro Levels2",
    "ADBE Photo Filter", "ADBE Black&White", "ADBE Exposure2",
    "ADBE Change To Color", "ADBE Change Color", "ADBE Lumetri",
    "ADBE Leave Color", "ADBE Equalize", "ADBE Selective Color",
    "ADBE Shadow/Highlight",
    "CC Color Neutralizer", "CC Color Offset", "CC Toner",
    # ── Distort ──
    "ADBE Turbulent Displace", "ADBE Displacement Map", "ADBE LIQUIFY",
    "ADBE Ripple", "ADBE Twirl", "ADBE WRPMESH", "ADBE Spherize",
    "ADBE Polar Coordinates", "ADBE Bulge", "ADBE Wave Warp",
    "ADBE Reshape", "ADBE Mirror", "ADBE Offset", "ADBE Magnify",
    "ADBE Transform", "ADBE Optics Compensation",
    "CC Bend It", "CC Bender", "CC Blobbylize", "CC Flo Motion",
    "CC Griddler", "CC Lens", "CC Page Turn", "CC Power Pin",
    "CC Ripple Pulse", "CC Slant", "CC Smear", "CC Split", "CC Split 2", "CC Tiler",
    # ── Generate ──
    "ADBE Fill", "ADBE Ramp", "ADBE Stroke", "ADBE Checkerboard",
    "ADBE Grid", "ADBE Fractal", "ADBE Cell Pattern", "ADBE Ellipse",
    "ADBE 4ColorGradient", "ADBE Lightning 2", "ADBE Scribble Fill",
    "ADBE AudiSpek", "ADBE AudiWave", "ADBE Laser", "ADBE Write-on",
    "CC Glue Gun", "CC Light Burst 2.5", "CC Light Rays", "CC Light Sweep", "CC Threads",
    # ── Noise & Grain ──
    "ADBE Fractal Noise", "ADBE Noise Alpha2", "ADBE Noise HLS2",
    "ADBE Add Grain", "ADBE Remove Grain", "ADBE Match Grain",
    "ADBE Dust & Scratches", "ADBE Median",
    # ── Stylize ──
    "ADBE Glo2", "ADBE Drop Shadow", "ADBE Emboss", "ADBE Find Edges",
    "ADBE Mosaic", "ADBE Posterize", "ADBE Roughen Edges", "ADBE Scatter",
    "ADBE Tile", "ADBE Texturize", "ADBE Brush Strokes", "ADBE Color Emboss",
    "CC Glass", "CC HexTile", "CC Kaleida", "CC Mr. Smoothie",
    "CC Plastic", "CC RepeTile", "CC Vignette",
    # ── Transition ──
    "ADBE Block Dissolve", "ADBE Gradient Wipe", "ADBE Linear Wipe",
    "ADBE Radial Wipe", "ADBE Venetian Blinds", "ADBE Iris Wipe",
    "CC Glass Wipe", "CC Grid Wipe", "CC Image Wipe", "CC Jaws",
    "CC Light Wipe", "CC Line Sweep", "CC Scale Wipe", "CC Twister", "CC WarpoMatic",
    # ── Channel ──
    "ADBE Set Channels", "ADBE Set Matte3", "ADBE Shift Channels",
    "ADBE Minimax", "ADBE Invert", "ADBE Arithmetic",
    "ADBE Channel Combiner", "ADBE Calculations", "ADBE Remove Color Matting",
    # ── Keying ──
    "ADBE KEYLIGHT", "ADBE SPILL2", "ADBE Extract", "ADBE ATG Extract",
    "ADBE Color Range", "ADBE Difference Matte", "ADBE Inner Outer Key",
    "ADBE Linear Color Key2",
    # ── Matte ──
    "ADBE Simple Choker", "ADBE Matte Choker", "ADBE Refine Soft Matte",
    # ── Perspective ──
    "ADBE 3D Glasses2", "ADBE Bevel Alpha",
    "CC Cylinder", "CC Environment", "CC Sphere", "CC Spotlight",
    # ── Time ──
    "ADBE Echo", "ADBE Posterize Time", "ADBE Timewarp", "ADBE Time Difference",
    "CC Force Motion Blur", "CC Wide Time",
    # ── Utility ──
    "ADBE Apply Color LUT2", "ADBE Cineon Converter2",
    "ADBE Color Profile Converter", "ADBE Grow Bounds",
    # ── Simulation ──
    "CC Ball Action", "CC Bubbles", "CC Drizzle", "CC Hair",
    "CC Mr. Mercury", "CC Particle Systems II", "CC Particle World",
    "CC Pixel Polly", "CC Rain", "CC Scatterize", "CC Snow", "CC Star Burst",
    # ── Expression Controls ──
    "ADBE Angle Control", "ADBE Checkbox Control", "ADBE Color Control",
    "ADBE Layer Control", "ADBE Point Control", "ADBE Slider Control",
    "ADBE Dropdown Control", "ADBE Point3D Control",
]

# ╔══════════════════════════════════════════════════════════╗
# ║                  AE BRIDGE CLASS                    ║
# ╚══════════════════════════════════════════════════════════╝

class AEBridge:
    """
    AE2Claude Bridge v3.0 - Atomic API for After Effects.

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
        self._dismiss_thread = None
        self._dismiss_running = False

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
        data = code.encode('utf-8')
        req = urllib.request.Request(
            f'{self._base_url}/jsx',
            data=data,
            headers={'Content-Type': 'text/plain; charset=utf-8'}
        )
        try:
            with urllib.request.urlopen(req, timeout=max(timeout / 1000, 5)) as resp:
                r = json.loads(resp.read())
        except (urllib.error.URLError, OSError) as e:
            raise ConnectionError(f"PyShiftAE request failed: {e}")

        if r.get('ok'):
            return r.get('result', '')
        error = r.get('error', 'Unknown JSX error')
        raise RuntimeError(f"JSX error: {error}")

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
        self.run_jsx(f'app.beginUndoGroup("{name}");')

    def end_undo(self):
        """结束 undo 组"""
        self.run_jsx('app.endUndoGroup();')

    # ── Layer Queries ──────────────────────────────────────

    def list_layers(self) -> List[dict]:
        """列出当前合成所有图层"""
        r = self.run_jsx(
            'var c=app.project.activeItem;var out=[];'
            'for(var i=1;i<=c.numLayers;i++){'
            'var l=c.layer(i);out.push({id:l.id,index:i,name:l.name,'
            'startTime:l.startTime,outPoint:l.outPoint,label:l.label});}'
            'JSON.stringify(out);'
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
        mn = fx["matchName"]
        jsx = (
            f'try{{'
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var ef=tl.property("Effects").addProperty("{mn}");'
            f'ef.propertyIndex;'
            f'}}catch(e){{"ERR:"+e.toString()}}'
        )
        r = self.run_jsx(jsx)
        if r.startswith("ERR:"):
            raise RuntimeError(r)
        return int(r)

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
        jsx += f'}}catch(e){{"FX_ERR:"+e.toString()}}'
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
        jsx += f'}}catch(e){{"FX_ERR:"+e.toString()}}'
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
        """
        探测当前 AE 中所有可用效果。
        创建临时 solid，对 KNOWN_EFFECT_MATCHNAMES 逐一 canAddProperty + addProperty
        获取 displayName，完成后 undo 清理。
        """
        mn_json = json.dumps(KNOWN_EFFECT_MATCHNAMES)
        jsx = (
            '(function(){'
            'var c=app.project.activeItem;'
            'if(!c||!(c instanceof CompItem))return JSON.stringify({error:"No active comp"});'
            'app.beginUndoGroup("__probe__");'
            'try{'
            'var solid=c.layers.addSolid([0,0,0],"__effect_probe__",10,10,1);'
            'var efx=solid.property("Effects");'
            'var mns=' + mn_json + ';'
            'var out=[];'
            'for(var i=0;i<mns.length;i++){'
            'try{if(efx.canAddProperty(mns[i])){'
            'var e=efx.addProperty(mns[i]);'
            'out.push({matchName:mns[i],displayName:e.name});'
            '}}catch(x){}}'
            'solid.remove();'
            'app.endUndoGroup();'
            'app.executeCommand(16);'
            'return JSON.stringify(out);'
            '}catch(e){'
            'app.endUndoGroup();'
            'try{app.executeCommand(16);}catch(x){}'
            'return JSON.stringify({error:e.toString()});'
            '}'
            '})()'
        )
        r = self.run_jsx(jsx, timeout=120000)
        try:
            data = json.loads(r)
            if isinstance(data, dict) and 'error' in data:
                return data
            return {"count": len(data), "effects": data}
        except json.JSONDecodeError:
            return {"error": r}

    def describe_effect(self, match_name: str) -> dict:
        """
        自省指定效果的所有属性。
        临时添加效果到 probe solid，递归遍历属性树，返回结构化元数据后 undo。
        """
        safe_mn = match_name.replace('"', '\\"')
        jsx = (
            '(function(){'
            'var c=app.project.activeItem;'
            'if(!c||!(c instanceof CompItem))return JSON.stringify({error:"No active comp"});'
            'app.beginUndoGroup("__describe__");'
            'try{'
            'var solid=c.layers.addSolid([0,0,0],"__describe__",10,10,1);'
            'var efxG=solid.property("Effects");'
            'var mn="' + safe_mn + '";'
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
            f'var grp=contents.addProperty("ADBE Vector Group");grp.name="Rectangle";'
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
            f'var grp=contents.addProperty("ADBE Vector Group");grp.name="Ellipse";'
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
            f'var grp=contents.addProperty("ADBE Vector Group");grp.name="Path";'
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
            f'var c=app.project.activeItem;'
            f'for(var i=1;i<=c.numLayers;i++)c.layer(i).selected=false;'
        )
        for ln in layer_names:
            select_jsx += f'try{{c.layer("{_esc(ln)}").selected=true;}}catch(e){{}}'
        select_jsx += (
            f'var idxs=[];for(var i=1;i<=c.numLayers;i++){{'
            f'if(c.layer(i).selected)idxs.push(i);}}'
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
            return f"ERR: unknown mode '{mode}'. Available: {list(BLEND_MODES.keys())}"
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
        """配置文本 Animator 的 Range Selector。"""
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
            f'var sel=anim.property("ADBE Text Selectors").property(1);'
            f'sel.property("ADBE Text Percent Start").setValue({start});'
            f'sel.property("ADBE Text Percent End").setValue({end});'
            f'sel.property("ADBE Text Percent Offset").setValue({offset});'
            f'sel.property("ADBE Text Selector Mode").setValue({mode_val});'
            f'sel.property("ADBE Text Range Shape").setValue({shape_map.get(shape, 1)});'
            f'sel.property("ADBE Text Range Type2").setValue({based_map.get(based_on, 1)});'
            f'"selector_set";'
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
            return f"ERR: unknown style '{style}'. Available: {list(style_matchnames.keys())}"

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
        """采样单个像素，返回 {r, g, b, a}"""
        code = (
            f'p=app.project\n'
            f'comp=None\n'
            f'for i in p.items:\n'
            f'    if type(i).__name__=="CompItem":\n'
            f'        comp=i; break\n'
            f'if comp is None: raise RuntimeError("no comp")\n'
            f'px=comp.renderFramePixels({time})\n'
            f'r=int(px[{y},{x},0]); g=int(px[{y},{x},1]); b=int(px[{y},{x},2]); a=int(px[{y},{x},3])\n'
            f'_result=f"{{r}},{{g}},{{b}},{{a}}"'
        )
        r = self._run_py(code)
        parts = r.split(",")
        return {"r": int(parts[0]), "g": int(parts[1]),
                "b": int(parts[2]), "a": int(parts[3])}

    def sample_pixels(self, points: List[List[int]], time: float = -1) -> List[dict]:
        """批量采样多个像素点，points: [[x,y], ...]"""
        pts_str = repr(points)
        code = (
            f'p=app.project\n'
            f'comp=None\n'
            f'for i in p.items:\n'
            f'    if type(i).__name__=="CompItem":\n'
            f'        comp=i; break\n'
            f'if comp is None: raise RuntimeError("no comp")\n'
            f'import json\n'
            f'px=comp.renderFramePixels({time})\n'
            f'pts={pts_str}\n'
            f'out=[]\n'
            f'for pt in pts:\n'
            f'    x,y=pt[0],pt[1]\n'
            f'    out.append({{"r":int(px[y,x,0]),"g":int(px[y,x,1]),"b":int(px[y,x,2]),"a":int(px[y,x,3])}})\n'
            f'_result=json.dumps(out)'
        )
        r = self._run_py(code)
        return json.loads(r)

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

    def _run_py(self, code: str) -> str:
        """执行 Python 代码并返回 result 变量的值"""
        data = code.encode('utf-8')
        req = urllib.request.Request(
            f'{self._base_url}/',
            data=data,
            headers={'Content-Type': 'text/plain; charset=utf-8'}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
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
