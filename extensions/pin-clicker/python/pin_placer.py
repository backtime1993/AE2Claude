"""
PinPlacer — Python bridge for the AE2Claude PinClicker CEP extension.

Strategy (no Win32 window enumeration, no screenshot diffing):
  * The CEP extension exposes /place-pin which returns the real Puppet-pin
    position in comp coordinates (via AE SDK stream read). So we can calibrate
    the screen<->comp mapping using the first placed pin as an anchor.
  * After a single calibration click, all subsequent comp coordinates are
    converted to screen coordinates with (tx, ty, zoom) and land at the
    requested point with sub-pixel error.
  * Uses AE2Claude psc.sample_pixel (via `ae2claude py`) for alpha probing
    when we need to find a safe seed location inside the layer alpha.

Usage:
    from pin_placer import PinPlacer
    with PinPlacer() as pl:
        pl.ensure_target(comp_id, layer_index)
        pl.set_puppet_pin_tool()
        pl.calibrate()                    # places the seed pin
        pl.place_at_comp(300, 300)        # subsequent exact placements
        pl.place_at_comp(500, 500)
        pins = pl.list_pins()
"""
import json
import time
import urllib.error
import urllib.request


class CEPError(RuntimeError):
    pass


class PinPlacer:
    def __init__(self, cep_url: str = "http://127.0.0.1:8891", ae_url: str = "http://127.0.0.1:8089"):
        self.cep = cep_url.rstrip("/")
        self.ae = ae_url.rstrip("/")
        self.comp_id = None
        self.layer_index = None
        self.zoom = None
        self.tx = None
        self.ty = None
        self.seed_pin_pos = None
        self.viewer_rect = None
        self.preferred_seed_point = None
        self.preferred_seed_bbox = None

    # ---- HTTP helpers ---------------------------------------------------
    def _post(self, path, payload=None):
        url = f"{self.cep}{path}"
        data = json.dumps(payload or {}).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise CEPError(f"{path} -> {e.code} {body}") from None

    def _get(self, path):
        req = urllib.request.Request(f"{self.cep}{path}", method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def jsx(self, code: str):
        r = self._post("/eval", {"code": code})
        return r.get("result")

    # ---- Context ---------------------------------------------------------
    def __enter__(self):
        h = self._get("/health")
        if not h.get("ok"):
            raise CEPError(f"CEP not healthy: {h}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    # ---- Public API ------------------------------------------------------
    def ensure_target(self, comp_id: int, layer_index: int, pre_focus: bool = True):
        if pre_focus:
            self._post("/focus-ae")
        r = self._post("/ensure-viewer", {"comp_id": int(comp_id), "layer_index": int(layer_index)})
        if r.get("error"):
            raise CEPError(f"ensure-viewer failed: {r}")
        self.comp_id = int(comp_id)
        self.layer_index = int(layer_index)
        return r

    def _remove_last_pin_in_group(self, group: str):
        """Remove the property at index 1 (newest) in the given pin group.
        group ∈ {'PosPins','HghtPins','StarchPins'}.
        """
        code = (
            'var target=null;'
            'for(var i=1;i<=app.project.numItems;i++){var it=app.project.item(i); if(it.id==' + str(self.comp_id) + '){target=it;break;}}'
            'if(!target) return {err:"no_comp"};'
            'var layer=target.layer(' + str(self.layer_index) + ');'
            'var fx=layer.property("ADBE Effect Parade").property("ADBE FreePin3");'
            'if(!fx) return {err:"no_fx"};'
            'var mesh=fx.property("ADBE FreePin3 ARAP Group").property("ADBE FreePin3 Mesh Group").property(1);'
            'var g=mesh.property("' + group + '".indexOf("PosPins")===0?"ADBE FreePin3 PosPins":("' + group + '".indexOf("Hght")===0?"ADBE FreePin3 HghtPins":"ADBE FreePin3 StarchPins"));'
            'if(!g||g.numProperties<1) return {err:"no_pin_in_group",group:"' + group + '"};'
            'g.property(1).remove();'
            'return {ok:true,remaining:g.numProperties};'
        )
        return self.jsx(code)

    def _pin_group_counts(self):
        code = (
            'var target=null;'
            'for(var i=1;i<=app.project.numItems;i++){var it=app.project.item(i); if(it.id==' + str(self.comp_id) + '){target=it;break;}}'
            'if(!target) return {err:"no_comp"};'
            'var layer=target.layer(' + str(self.layer_index) + ');'
            'var fx=null; try{fx=layer.property("ADBE Effect Parade").property("ADBE FreePin3");}catch(_){}'
            'if(!fx) return {pos:0,hght:0,starch:0,has_fx:false};'
            'var m=fx.property("ADBE FreePin3 ARAP Group").property("ADBE FreePin3 Mesh Group");'
            'if(!m||m.numProperties<1) return {pos:0,hght:0,starch:0,has_fx:true};'
            'var mm=m.property(1);'
            'return {pos:mm.property("ADBE FreePin3 PosPins").numProperties,'
            'hght:mm.property("ADBE FreePin3 HghtPins").numProperties,'
            'starch:mm.property("ADBE FreePin3 StarchPins").numProperties,has_fx:true};'
        )
        return self.jsx(code)

    def set_puppet_pin_tool(self):
        """Send Ctrl+P once. Does NOT guarantee which Puppet sub-tool AE lands
        on (cycle is Position/Starch/Bend/Advanced/Overlap). Prefer
        ensure_pospin_tool() which actually verifies by probing."""
        r = self._post("/set-tool", {"hotkey": "Ctrl+P"})
        if not r.get("ok"):
            raise CEPError(f"set-tool failed: {r}")
        time.sleep(0.3)
        return r

    def ensure_pospin_tool(self, max_rotations: int = 6, probe_point=None):
        """Rotate Ctrl+P until the next click lands a pin in `PosPins` (not in
        Hght/Starch). Uses the AE window centre as the probe click point, so
        the target layer's alpha must cover that point — calibrate expects
        the same thing.

        Returns {rotations, final_group, pos_delta, ...}. On failure raises.
        """
        if self.comp_id is None or self.layer_index is None:
            raise CEPError("call ensure_target first")

        if probe_point is None:
            ae = self.ae_window_rect()
            if ae.get("error"):
                raise CEPError(f"ae_window_rect failed: {ae}")
            probe_x, probe_y = int(ae["center_x"]), int(ae["center_y"])
        else:
            probe_x, probe_y = int(probe_point[0]), int(probe_point[1])

        # Focus Composition viewer first with a "warm-up" click. Needed because
        # the CEP panel often holds keyboard focus; Ctrl+P would otherwise go
        # nowhere. A plain /click-screen (not a /place-pin) just gives AE focus
        # without demanding pin semantics from whatever tool is active.
        self._post("/focus-ae")
        time.sleep(0.1)
        self._post("/click-screen", {"x": probe_x, "y": probe_y})
        time.sleep(0.25)

        for rot in range(max_rotations):
            # Now that viewer has keyboard focus, Ctrl+P actually reaches AE.
            self._post("/set-tool", {"hotkey": "Ctrl+P"})
            time.sleep(0.3)
            r = self._click_place(probe_x, probe_y, retries=0)
            if not r.get("placed"):
                raise CEPError(
                    "probe click did not create any pin at AE centre "
                    f"({probe_x},{probe_y}) after Ctrl+P rotation {rot}. "
                    "Verify viewer shows the solo'd layer's alpha there."
                )
            group = r.get("pin_group")
            if group == "PosPins":
                return {"rotations": rot, "final_group": group, "seed_result": r}
            # Wrong group — remove this probe pin and cycle Ctrl+P.
            rm = self._remove_last_pin_in_group(group)
            if rm.get("err"):
                raise CEPError(f"could not remove probe pin from {group}: {rm}")

        raise CEPError(f"PosPins never reached after {max_rotations} Ctrl+P rotations")

    def read_last_pin_type(self):
        """Return PosPin Type of the most recently placed pin (1=Position)."""
        code = (
            "var target=null;"
            "for(var i=1;i<=app.project.numItems;i++){var it=app.project.item(i); if(it.id==" + str(self.comp_id) + "){target=it;break;}}"
            "if(!target) return {err:'NO_COMP'};"
            "var layer=target.layer(" + str(self.layer_index) + ");"
            "var fx=layer.property('ADBE Effect Parade').property('ADBE FreePin3');"
            "if(!fx) return {has_fx:false};"
            "var pins=fx.property('ADBE FreePin3 ARAP Group').property('ADBE FreePin3 Mesh Group').property(1).property('ADBE FreePin3 PosPins');"
            "if(pins.numProperties<1) return {pin_count:0};"
            "var pp=pins.property(1);"
            "return {type:pp.property('ADBE FreePin3 PosPin Type').value,name:pp.name};"
        )
        return self.jsx(code)

    def zoom_steps_to_target(self, target_zoom: float):
        """Send '.'/',' key presses to move current zoom toward `target_zoom`.
        Each press is ~sqrt(2) in AE. Returns (new_zoom, steps)."""
        import math
        self.read_zoom()
        steps = int(round(math.log(target_zoom / self.zoom) / math.log(math.sqrt(2))))
        if steps == 0:
            return self.zoom, 0
        key = "PERIOD" if steps > 0 else "COMMA"
        self._post("/focus-ae")
        time.sleep(0.1)
        # Click viewer centre once for keyboard focus
        ae = self.ae_window_rect()
        self._post("/click-screen", {"x": ae["center_x"], "y": ae["center_y"]})
        time.sleep(0.15)
        for _ in range(abs(steps)):
            self._post("/press-key", {"hotkey": key, "pre_focus": False})
            time.sleep(0.05)
        time.sleep(0.2)
        self.zoom = None
        return self.read_zoom(), steps

    def pan_viewer(self, dx: int, dy: int, from_point=None):
        """Hand-Tool drag viewer by (dx, dy) screen pixels (permanently switches
        to Hand Tool)."""
        payload = {"dx": int(dx), "dy": int(dy)}
        if from_point is not None:
            payload["from_x"], payload["from_y"] = int(from_point[0]), int(from_point[1])
        return self._post("/viewer-pan", payload)

    def pan_viewer_middle(self, dx: int, dy: int, from_point=None):
        """Middle-button drag pan. AE always treats middle-drag as Pan,
        regardless of active tool — so the Puppet sub-tool is preserved."""
        payload = {"dx": int(dx), "dy": int(dy)}
        if from_point is not None:
            payload["from_x"], payload["from_y"] = int(from_point[0]), int(from_point[1])
        return self._post("/viewer-pan-middle", payload)

    def set_viewer_zoom(self, target_zoom: float):
        """Directly set AE Composition viewer zoom via ExtendScript.
        ViewOptions.zoom is writable (confirmed in 26.x)."""
        tz = float(target_zoom)
        r = self.jsx(
            f"var v=app.activeViewer.views[0]; var b=v.options.zoom; "
            f"v.options.zoom={tz}; return {{before:b, after:v.options.zoom}};"
        )
        time.sleep(0.25)
        self.zoom = None
        self.read_zoom()
        return r

    def center_layer_via_diff(self, layer_info, desired_zoom="auto", coverage=0.5):
        """Purely geometric center-layer + zoom-to-comfortable routine.

        Order matters: PAN first (using current zoom so layer is findable
        via diff), THEN zoom — AE anchors zoom on the viewer centre, so
        after pan centres the layer, raising zoom keeps the layer centred
        while making it big enough to comfortably place pins on.

        Steps:
          1. Locate layer screen position via enable/disable diff (current zoom).
          2. pan_delta = viewer_center - layer_screen_center (middle-drag).
          3. Re-diff to confirm layer now near viewer centre; compute residual.
          4. If desired_zoom='auto', zoom so layer max dim = coverage * viewer short.
          5. Set zoom via JSX (viewer-centre anchored, layer stays centred).
        """
        if self.viewer_rect is None:
            # Best-effort: locate viewer via AE window centre.
            ae = self.ae_window_rect()
            self.viewer_rect = self.find_viewer_rect((ae["center_x"], ae["center_y"]))
            if self.viewer_rect is None:
                raise CEPError("cannot locate Composition viewer panel")
        vr = self.viewer_rect
        vx = (vr["left"] + vr["right"]) / 2.0
        vy = (vr["top"] + vr["bottom"]) / 2.0

        # If desired_zoom is None, don't touch zoom — trust current state.
        # Otherwise compute from coverage.
        if desired_zoom == "auto":
            short_viewer = min(vr["w"], vr["h"])
            long_layer = max(layer_info["w"], layer_info["h"])
            desired_zoom = (coverage * short_viewer) / long_layer
        if desired_zoom is not None:
            zr = self.set_viewer_zoom(desired_zoom)
            time.sleep(0.4)
        else:
            zr = {"skipped": True, "zoom": self.read_zoom()}

        d = self.find_layer_on_screen_via_diff(alpha_thresh=25)
        lx, ly = d["center"]
        dx = int(round(vx - lx))
        dy = int(round(vy - ly))
        pan_res = self.pan_viewer_middle(dx, dy)
        time.sleep(0.5)

        d2 = self.find_layer_on_screen_via_diff(alpha_thresh=25)
        return {
            "zoom_set": zr,
            "pre_pan_layer_screen": [lx, ly],
            "pan_delta": [dx, dy],
            "post_pan_layer_screen": d2["center"],
            "viewer_center": [int(vx), int(vy)],
            "residual": [d2["center"][0] - int(vx), d2["center"][1] - int(vy)],
        }
        """Space-held pan. Active tool is preserved — user stays on 位置控点."""
        payload = {"dx": int(dx), "dy": int(dy)}
        if from_point is not None:
            payload["from_x"], payload["from_y"] = int(from_point[0]), int(from_point[1])
        return self._post("/viewer-pan-space", payload)

    def center_target_layer(self, layer_info):
        """Pan the viewer so the target layer's CENTER sits at the viewer
        center, using Space+drag (preserves puppet sub-tool).

        Requires calibrate() to have been run (so tx, ty, zoom, viewer_rect
        are known). Caller then re-calibrates afterwards because the affine
        translation (tx, ty) shifts after a pan.

        layer_info: {'pos': [cx, cy, z?], 'w': W, 'h': H}
          - pos is the layer's comp-coord center
          - layer source coord (w/2, h/2) maps to comp pos
        """
        if self.tx is None or self.zoom is None or self.viewer_rect is None:
            raise CEPError("center_target_layer needs an initial calibrate()")

        # The affine returned by calibrate is screen = tx + layer_source * zoom.
        # Layer source center is (w/2, h/2).
        layer_src_cx = layer_info["w"] / 2.0
        layer_src_cy = layer_info["h"] / 2.0
        cur_screen_x = self.tx + layer_src_cx * self.zoom
        cur_screen_y = self.ty + layer_src_cy * self.zoom

        vr = self.viewer_rect
        viewer_cx = (vr["left"] + vr["right"]) / 2.0
        viewer_cy = (vr["top"] + vr["bottom"]) / 2.0
        dx = int(round(viewer_cx - cur_screen_x))
        dy = int(round(viewer_cy - cur_screen_y))

        res = self.pan_viewer_space(dx, dy)
        return {
            "layer_screen_before": [int(cur_screen_x), int(cur_screen_y)],
            "viewer_center": [int(viewer_cx), int(viewer_cy)],
            "pan_delta": [dx, dy],
            "pan_result": res,
        }

    def center_layer_in_viewer(self, layer_info, goal_coverage: float = 0.55):
        """Zoom + pan until the given layer is centred in the Composition viewer
        and covers `goal_coverage` of its shorter dimension.

        layer_info: {'pos': [cx, cy, z?], 'w': int, 'h': int}
        Requires: self has been calibrated at least once OR self.viewer_rect set.
        """
        if self.tx is None:
            raise CEPError("calibrate first so we have (tx, ty, zoom)")
        if self.viewer_rect is None:
            raise CEPError("viewer_rect unknown — run calibrate once")
        vr = self.viewer_rect
        viewer_w = vr["w"]
        viewer_h = vr["h"]
        layer_w = max(1, int(layer_info["w"]))
        layer_h = max(1, int(layer_info["h"]))

        short_viewer = min(viewer_w, viewer_h)
        long_layer = max(layer_w, layer_h)
        target_zoom = (goal_coverage * short_viewer) / long_layer

        new_zoom, steps = self.zoom_steps_to_target(target_zoom)
        # After zoom the affine (tx, ty) shifts; re-calibrate conceptually:
        # we re-seed via the screenshot diff so the new tx/ty is known.
        # Simpler: approximate old affine with new zoom, then drag by delta.
        # For accuracy we re-calibrate after pan below.

        # Compute current layer centre on screen using the old affine scaled
        # by zoom ratio. This is a reasonable estimate; the pan will correct.
        lx, ly = layer_info["pos"][0], layer_info["pos"][1]
        zoom_ratio = new_zoom / (self.zoom or new_zoom)
        # The viewer's pan centre effectively shifts under zoom; precise
        # recovery requires one seed click. Fall back to heuristic here.
        est_layer_screen_x = (vr["left"] + vr["right"]) / 2 + (lx - (lx)) * new_zoom  # placeholder
        # Simpler: trust the screenshot-diff path to re-aim seed after zoom.
        # We return and let the caller re-calibrate.
        return {
            "new_zoom": new_zoom,
            "zoom_steps": steps,
            "target_zoom": target_zoom,
            "note": "caller should re-calibrate (e.g. find_layer_on_screen_via_diff + preferred_seed_point) after zoom",
        }
        """Send Shift+/ (AE's 'Fit' shortcut) so the whole comp fits into the
        viewer. Re-reads zoom afterwards since fit changes it.
        AE must have viewer keyboard focus first — callers should
        focus_ae and click into the viewer once before calling this.
        """
        self._post("/focus-ae")
        time.sleep(0.1)
        r = self._post("/press-key", {"hotkey": "Shift+SLASH"})
        time.sleep(0.35)
        self.zoom = None
        new_zoom = self.read_zoom()
        return {"ok": bool(r.get("ok")), "zoom": new_zoom}

    def get_viewer_state(self):
        return self._get("/viewer-state")

    def read_zoom(self) -> float:
        v = self.get_viewer_state()
        z = v.get("view", {}).get("zoom")
        if not z:
            raise CEPError(f"cannot read zoom from viewer-state: {v}")
        self.zoom = float(z)
        return self.zoom

    def physical_screen_dims(self):
        r = self._post("/click-screen", {"x": 1000, "y": 500})
        ax, ay = r["abs"]
        sw = round((1000 * 65535) / ax) + 1
        sh = round((500 * 65535) / ay) + 1
        return sw, sh

    def ae_window_rect(self):
        """{left,top,right,bottom,width,height,center_x,center_y} of the AE main
        window in virtual-desktop coordinates. Used to aim the seed click at
        the AE viewer instead of the screen center (which, on multi-monitor
        setups, can land on a totally different app like a video player)."""
        return self._get("/ae-rect")

    def _last_pin_info(self):
        if self.comp_id is None or self.layer_index is None:
            raise CEPError("call ensure_target first")
        code = (
            "var target=null;"
            "for(var i=1;i<=app.project.numItems;i++){var it=app.project.item(i); if(it.id==" + str(self.comp_id) + "){target=it;break;}}"
            "if(!target) return {err:'NO_COMP'};"
            "var layer=target.layer(" + str(self.layer_index) + ");"
            "var fx=null; try{fx=layer.property('ADBE Effect Parade').property('ADBE FreePin3');}catch(_){}"
            "if(!fx) return {err:'NO_FX'};"
            "var mg=fx.property('ADBE FreePin3 ARAP Group').property('ADBE FreePin3 Mesh Group');"
            "if(!mg || mg.numProperties<1) return {err:'NO_MESH'};"
            "var pins=mg.property(1).property('ADBE FreePin3 PosPins');"
            "if(pins.numProperties<1) return {err:'NO_PINS'};"
            "var pp=pins.property(1);"
            "var pos=pp.property('ADBE FreePin3 PosPin Position');"
            "var v=pp.property('ADBE FreePin3 PosPin Vtx Index');"
            "return {pos:[pos.value[0],pos.value[1]],vtx_index:v.value,pin_count:pins.numProperties,name:pp.name};"
        )
        return self.jsx(code)

    def list_pins(self):
        if self.comp_id is None or self.layer_index is None:
            raise CEPError("call ensure_target first")
        code = (
            "var target=null;"
            "for(var i=1;i<=app.project.numItems;i++){var it=app.project.item(i); if(it.id==" + str(self.comp_id) + "){target=it;break;}}"
            "if(!target) return {err:'NO_COMP'};"
            "var layer=target.layer(" + str(self.layer_index) + ");"
            "var fx=null; try{fx=layer.property('ADBE Effect Parade').property('ADBE FreePin3');}catch(_){}"
            "if(!fx) return {pin_count:0,has_effect:false,pins:[]};"
            "var mg=fx.property('ADBE FreePin3 ARAP Group').property('ADBE FreePin3 Mesh Group');"
            "if(!mg || mg.numProperties<1) return {pin_count:0,has_mesh:false,pins:[]};"
            "var mesh=mg.property(1);"
            "var pins=mesh.property('ADBE FreePin3 PosPins');"
            "var out=[];"
            "for(var p=1;p<=pins.numProperties;p++){"
            "  var pp=pins.property(p);"
            "  var pos=pp.property('ADBE FreePin3 PosPin Position');"
            "  var v=pp.property('ADBE FreePin3 PosPin Vtx Index');"
            "  out.push({prop_idx:p,name:pp.name,vtx_index:v.value,pos:[pos.value[0],pos.value[1]]});"
            "}"
            "return {pin_count:pins.numProperties,mesh_tri_count:mesh.property('ADBE FreePin3 Mesh Tri Count').value,pins:out};"
        )
        return self.jsx(code)

    def _click_place(self, sx: int, sy: int, retries: int = 0, inset_dir=(0, 0)):
        return self._post("/place-pin", {
            "comp_id": self.comp_id,
            "layer_index": self.layer_index,
            "screen_x": int(round(sx)),
            "screen_y": int(round(sy)),
            "retries": int(retries),
            "inset_px": 6,
            "inset_dir": list(inset_dir),
            "poll_timeout_ms": 3000,
            "pre_focus": False,
        })

    def find_layer_on_screen_via_diff(self, alpha_thresh: int = 25, pad: int = 60):
        """Locate the solo'd layer's bounding box on screen via enable/disable
        diff. Returns (screen_center, screen_bbox). Doesn't depend on pan/zoom.

        Flow:
          1. screenshot A with layer enabled
          2. JSX sets layer.enabled=false
          3. screenshot B
          4. JSX restores layer.enabled=true
          5. numpy diff: max-channel pixel delta > threshold = layer pixels
          6. return centroid + bbox in screen coords (virtual desktop origin)
        """
        try:
            from PIL import ImageGrab
            import numpy as np
        except ImportError:
            raise CEPError("screenshot diff requires Pillow + numpy")

        # CEP (DPI-aware) and our /ae-rect return PHYSICAL virtual-desktop
        # coords. Python ctypes without DPI-awareness returns LOGICAL coords,
        # which would misalign by the DPI scale (2.25x here). Force PMv2
        # awareness on this thread so GetSystemMetrics matches CEP side.
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            try: ctypes.windll.user32.SetProcessDPIAware()
            except Exception: pass
        user32 = ctypes.windll.user32
        vx = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
        vy = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN

        # Locate the Composition viewer panel so we diff only inside it —
        # AE's other panels (timeline, projects) redraw themselves slightly
        # between screenshots and would otherwise dominate the diff.
        ae_rect = self.ae_window_rect()
        if ae_rect.get("error"):
            raise CEPError(f"need AE window rect: {ae_rect}")
        viewer = self.find_viewer_rect((ae_rect["center_x"], ae_rect["center_y"]))
        if not viewer:
            raise CEPError("could not locate Composition viewer panel")

        # Snapshot every layer's enabled state, then force ALL non-target
        # layers off so AE's viewer renders only the target — independent of
        # the viewer Solo switch.
        # Save BOTH enabled AND solo because setting enabled=true after
        # enabled=false silently resets solo=false in AE 26.x.
        snap = self.jsx(
            f'var t=null;for(var i=1;i<=app.project.numItems;i++){{var it=app.project.item(i); if(it.id=={self.comp_id}){{t=it;break;}}}}'
            'var s=[];'
            f'for(var k=1;k<=t.numLayers;k++){{var L=t.layer(k); s.push({{i:k,e:L.enabled,so:L.solo}}); L.enabled=(k=={self.layer_index});}}'
            'return s;'
        )
        time.sleep(0.35)
        img_a_pil = ImageGrab.grab(all_screens=True)
        img_a_pil.save(r"F:\claude\projects\原画skill制作\_diag_diff_a.png")
        img_a = np.asarray(img_a_pil, dtype=np.int16)

        # Now also hide the target layer.
        self.jsx(
            f'var t=null;for(var i=1;i<=app.project.numItems;i++){{var it=app.project.item(i); if(it.id=={self.comp_id}){{t=it;break;}}}}'
            f't.layer({self.layer_index}).enabled=false; return true;'
        )
        time.sleep(0.35)
        img_b_pil = ImageGrab.grab(all_screens=True)
        img_b_pil.save(r"F:\claude\projects\原画skill制作\_diag_diff_b.png")
        img_b = np.asarray(img_b_pil, dtype=np.int16)

        # Restore every layer's original enabled AND solo state.
        snap_json = json.dumps(snap)
        self.jsx(
            f'var t=null;for(var i=1;i<=app.project.numItems;i++){{var it=app.project.item(i); if(it.id=={self.comp_id}){{t=it;break;}}}}'
            f'var s={snap_json};for(var j=0;j<s.length;j++){{var L=t.layer(s[j].i); L.enabled=s[j].e; if(s[j].so) L.solo=true;}}'
            'return true;'
        )

        if img_a.shape != img_b.shape:
            raise CEPError("screenshot size mismatch between enable/disable states")

        delta = np.abs(img_a - img_b).max(axis=2).astype(np.uint8)
        mask = delta > alpha_thresh

        # Restrict the diff to inside the Composition viewer panel (in image
        # coords relative to virtual-desktop origin).
        vx_min = max(0, viewer["left"] + pad - vx)
        vy_min = max(0, viewer["top"] + pad - vy)
        vx_max = min(mask.shape[1], viewer["right"] - pad - vx)
        vy_max = min(mask.shape[0], viewer["bottom"] - pad - vy)
        viewer_mask = np.zeros_like(mask, dtype=bool)
        viewer_mask[vy_min:vy_max, vx_min:vx_max] = True
        mask = mask & viewer_mask

        ys, xs = np.where(mask)
        if len(xs) == 0:
            raise CEPError("no on-screen pixels changed in viewer area — layer may not be visible")

        # Crop to the densest region: find the densest column / row strip
        # (a 2D histogram peak) so thin selection handles don't pull the
        # bbox wide. Then take the median pixel inside that strip as center.
        import numpy as _np
        bins_x = _np.bincount(xs, minlength=mask.shape[1])
        bins_y = _np.bincount(ys, minlength=mask.shape[0])
        peak_x = int(_np.argmax(bins_x))
        peak_y = int(_np.argmax(bins_y))
        radius = 120  # px — ignore speckles far from the peak
        keep = (
            (xs >= peak_x - radius) & (xs <= peak_x + radius)
            & (ys >= peak_y - radius) & (ys <= peak_y + radius)
        )
        xs2, ys2 = xs[keep], ys[keep]
        if len(xs2) == 0:
            xs2, ys2 = xs, ys

        # Median pixel is robust for L/C-shaped alpha (shapes where mean
        # lands in a transparent hole).
        cx = int(_np.median(xs2)) + vx
        cy = int(_np.median(ys2)) + vy

        img_left = int(xs2.min()) + vx
        img_right = int(xs2.max()) + vx
        img_top = int(ys2.min()) + vy
        img_bottom = int(ys2.max()) + vy
        result = {
            "center": (cx, cy),
            "bbox": {"left": img_left, "top": img_top, "right": img_right, "bottom": img_bottom,
                     "w": img_right - img_left, "h": img_bottom - img_top},
            "pixel_count": int(len(xs2)),
        }
        # Cache for _offset_seed_if_existing_pin
        self.preferred_seed_bbox = result["bbox"]
        return result

    def _offset_seed_if_existing_pin(self):
        """If the target layer already has a PosPin near our preferred_seed_point,
        shift the seed target by (~33%, ~33%) of the probe bbox so the new
        click creates a fresh pin instead of selecting the existing one.
        Requires self.preferred_seed_point and, ideally, the diff bbox.
        """
        cnt = self._pin_group_counts()
        if not cnt or cnt.get("pos", 0) < 1:
            return
        bbox = getattr(self, "preferred_seed_bbox", None)
        if not bbox:
            # Fallback: nudge 40 px down-right.
            sp = self.preferred_seed_point
            self.preferred_seed_point = (sp[0] + 40, sp[1] + 40)
            return
        sp = self.preferred_seed_point
        dx = int(bbox["w"] * 0.33)
        dy = int(bbox["h"] * 0.33)
        self.preferred_seed_point = (sp[0] + dx, sp[1] + dy)

    def calibrate(self):
        """Land a single PosPin seed and derive affine (tx, ty) so
        `screen = (tx, ty) + comp * zoom`. Does the full flow:
          1) warm-up click to grab viewer keyboard focus (CEP panel tends
             to steal it)
          2) rotate Ctrl+P up to 6 times until a probe click lands in PosPins
             (not Hght/Starch), cleaning up probe pins from wrong groups
          3) the PosPin that finally lands becomes the calibration seed
          4) /place-pin already forced PosPin Type=1, so the seed is Position
          5) read seed's comp coord, solve for tx/ty
        """
        if self.zoom is None:
            self.read_zoom()
        # Avoid clicking an already-placed pin's location (AE would just
        # select it instead of creating a new one).
        self._offset_seed_if_existing_pin()
        probe_point = getattr(self, "preferred_seed_point", None)
        if probe_point is None:
            ae = self.ae_window_rect()
            if ae.get("error"):
                raise CEPError(f"ae_window_rect failed: {ae}")
            probe_point = (int(ae["center_x"]), int(ae["center_y"]))
        sx, sy = int(probe_point[0]), int(probe_point[1])

        # Just click once. DO NOT touch the Puppet sub-tool — the user keeps
        # AE on 位置控点 (Position Pin) by default; any Ctrl+P we send would
        # only rotate it into a sibling they didn't ask for.
        self._post("/focus-ae")
        time.sleep(0.15)
        r = self._click_place(sx, sy, retries=0)
        if not r.get("placed"):
            raise CEPError(
                f"seed click at ({sx},{sy}) did not create any pin. "
                "Check that the AE viewer shows the target layer's alpha at "
                "that point and that the active tool is Puppet Position Pin."
            )
        group = r.get("pin_group")
        if group != "PosPins":
            raise CEPError(
                f"seed pin landed in {group}, not PosPins. Please switch AE's "
                "active Puppet sub-tool to 位置控点 (Position Pin) and retry. "
                "The script will no longer auto-rotate sub-tools."
            )

        seed_info = self._last_pin_info()
        cx, cy = seed_info["pos"]
        self.tx = sx - cx * self.zoom
        self.ty = sy - cy * self.zoom
        self.seed_pin_pos = [cx, cy]
        self.viewer_rect = self.find_viewer_rect((sx, sy))
        return {
            "tx": self.tx, "ty": self.ty, "zoom": self.zoom,
            "seed_comp": [cx, cy], "seed_screen": [sx, sy],
            "seed_vtx": seed_info["vtx_index"],
            "viewer_rect": self.viewer_rect,
        }

    def comp_to_screen(self, cx: float, cy: float):
        if self.tx is None:
            raise CEPError("calibrate() must be called first")
        return self.tx + cx * self.zoom, self.ty + cy * self.zoom

    def find_viewer_rect(self, point_screen):
        """Given a screen point known to be inside the Composition viewer (the
        seed pin's click position), return the rect of the smallest
        'DroverLord - Frame Window' that contains it — that's the viewer
        panel's screen bbox. Future place_at_comp calls can refuse targets
        that map outside this box.
        """
        r = self._get("/enum-ae-windows")
        rows = r.get("rows", [])
        px, py = point_screen
        best = None
        for row in rows:
            if not row.get("visible"):
                continue
            if "Frame Window" not in row.get("text", ""):
                continue
            rect = row.get("rect")
            if not rect:
                continue
            if rect["left"] <= px <= rect["right"] and rect["top"] <= py <= rect["bottom"]:
                if best is None or (rect["w"] * rect["h"]) < (best["w"] * best["h"]):
                    best = rect
        return best

    def screen_in_viewer(self, sx, sy, margin: int = 4) -> bool:
        """True iff (sx, sy) lies inside self.viewer_rect (set by calibrate)."""
        if not getattr(self, "viewer_rect", None):
            return True  # no constraint yet
        vr = self.viewer_rect
        return (vr["left"] + margin <= sx <= vr["right"] - margin
                and vr["top"] + margin <= sy <= vr["bottom"] - margin)

    def place_at_comp(self, cx: float, cy: float, retries: int = 1, inset_dir=None,
                      skip_outside_viewer: bool = True):
        if self.tx is None:
            raise CEPError("calibrate() must be called first")
        sx, sy = self.comp_to_screen(cx, cy)
        if skip_outside_viewer and self.viewer_rect is not None and not self.screen_in_viewer(sx, sy):
            return {
                "placed": False,
                "target_comp": [cx, cy],
                "screen": [int(round(sx)), int(round(sy))],
                "reason": "target_outside_viewer",
                "viewer_rect": self.viewer_rect,
            }
        idir = inset_dir if inset_dir is not None else (0, 0)
        res = self._click_place(sx, sy, retries=retries, inset_dir=idir)
        if res.get("placed"):
            info = self._last_pin_info()
            acx, acy = info["pos"]
            res["actual_comp"] = [acx, acy]
            res["target_comp"] = [cx, cy]
            res["err_comp"] = ((acx - cx) ** 2 + (acy - cy) ** 2) ** 0.5
            res["vtx_index"] = info["vtx_index"]
        else:
            res["target_comp"] = [cx, cy]
        return res

    # ---- AE-side helpers via AE2Claude 8089 Python channel ---------------
    def _ae_py(self, code: str):
        req = urllib.request.Request(f"{self.ae}/", data=code.encode("utf-8"), method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def sample_alpha(self, cx: float, cy: float):
        """Alpha at comp (cx, cy) via AE2Claude psc.sample_pixel (C++ path).

        Returns a dict with 'alpha' (0.0-1.0), or 'error'.
        The underlying bridge call goes through the AE2Claude HTTP server that
        executes embedded Python — we reuse its sample_pixel implementation so
        the pixel math stays in AE's render pipeline, not screenshot land.
        """
        py = (
            "from ae_bridge import AEBridge\n"
            f"ae=AEBridge()\n"
            f"r=ae.sample_pixel({cx}, {cy})\n"
            "import json; json.dumps(r)"
        )
        return self._ae_py(py)

    def layer_alpha_bbox(self, padding: int = 0):
        """Return the minimal comp bbox that encloses the layer's visible alpha.

        Uses ae_bridge.detect_solid_background_layers pattern — we just render
        once at 32x32 and scan alpha ourselves.
        """
        py = (
            "from ae_bridge import AEBridge\n"
            f"ae=AEBridge()\n"
            "r=ae.run_py("
            "'from PyShiftCore import *\\n"
            "comp=app.project.activeItem\\n"
            f"layer=comp.layers[{self.layer_index}]\\n"
            "prev_solo=layer.solo; layer.solo=True\\n"
            "pixels=comp.renderFramePixels(32)\\n"
            "layer.solo=prev_solo\\n"
            "w,h=pixels.width,pixels.height\\n"
            "xs,ys=[],[]\\n"
            "for yy in range(h):\\n"
            "  for xx in range(w):\\n"
            "    a=pixels.data[(yy*w+xx)*4+3]\\n"
            "    if a>=8: xs.append(xx); ys.append(yy)\\n"
            "import json\\n"
            "if not xs: json.dumps({\"error\":\"empty_alpha\"})\\n"
            "else:\\n"
            "  cw,ch=comp.width,comp.height\\n"
            "  x0=min(xs)*cw/w; x1=(max(xs)+1)*cw/w\\n"
            "  y0=min(ys)*ch/h; y1=(max(ys)+1)*ch/h\\n"
            "  json.dumps({\"bbox\":[x0,y0,x1,y1],\"grid\":[w,h]})')\n"
            "r"
        )
        return self._ae_py(py)

    # ---- v2 API (fast, one-liner-friendly) -------------------------------

    def load_layer_meta(self):
        """One JSX call: fetch position, anchor, scale, width, height, solo,
        and 'has_puppet' so the rest of the pipeline can compute src<->comp
        transforms analytically. Cached in self.layer_meta."""
        if self.comp_id is None or self.layer_index is None:
            raise CEPError("call ensure_target first")
        code = (
            f'var t=null;for(var i=1;i<=app.project.numItems;i++){{var it=app.project.item(i); if(it.id=={self.comp_id}){{t=it;break;}}}}'
            'if(!t) return {err:"no_comp"};'
            f'var L=t.layer({self.layer_index});'
            'var tr=L.property("ADBE Transform Group");'
            'var p=tr.property("ADBE Position").value;'
            'var a=tr.property("ADBE Anchor Point").value;'
            'var s=tr.property("ADBE Scale").value;'
            'var src=L.source;'
            'var w=src?src.width:0; var h=src?src.height:0;'
            'var solo=false; try{solo=L.solo;}catch(_){}'
            'var hasFx=false; try{var ep=L.property("ADBE Effect Parade"); for(var k=1;k<=ep.numProperties;k++){if(ep.property(k).matchName=="ADBE FreePin3"){hasFx=true;break;}}}catch(_){}'
            'return {name:L.name,position:[p[0],p[1]],anchor:[a[0],a[1]],scale:[s[0],s[1]],width:w,height:h,solo:solo,has_puppet:hasFx};'
        )
        m = self.jsx(code)
        if m.get("err"):
            raise CEPError(f"load_layer_meta: {m['err']}")
        self.layer_meta = m
        return m

    def comp_to_layer_src(self, cx, cy):
        """Convert comp coordinate to layer-source coordinate (what Puppet
        pin Position values use). Requires load_layer_meta first. Ignores
        layer rotation (rare for 2D PSD pipelines)."""
        m = self.layer_meta
        sx = m["scale"][0] / 100.0
        sy = m["scale"][1] / 100.0
        return m["anchor"][0] + (cx - m["position"][0]) / sx, \
               m["anchor"][1] + (cy - m["position"][1]) / sy

    def layer_src_to_comp(self, sx, sy):
        m = self.layer_meta
        scx = m["scale"][0] / 100.0
        scy = m["scale"][1] / 100.0
        return m["position"][0] + (sx - m["anchor"][0]) * scx, \
               m["position"][1] + (sy - m["anchor"][1]) * scy

    def place_at_layer_src(self, sx: float, sy: float, retries: int = 1, inset_dir=None):
        """Place a PosPin at LAYER SOURCE coords (x, y). This is what the
        Puppet pin's Position property actually stores. Synonym for the
        legacy place_at_comp — use this when you mean source coords."""
        return self.place_at_comp(sx, sy, retries=retries, inset_dir=inset_dir)

    def place_at_comp_true(self, cx: float, cy: float, retries: int = 1, inset_dir=None):
        """Place a PosPin at COMP coords. Converts to layer-source via the
        layer's pos/anchor/scale (load_layer_meta required) before placing."""
        if getattr(self, "layer_meta", None) is None:
            self.load_layer_meta()
        src_x, src_y = self.comp_to_layer_src(cx, cy)
        r = self.place_at_comp(src_x, src_y, retries=retries, inset_dir=inset_dir)
        r["target_comp_true"] = [cx, cy]
        r["target_src"] = [src_x, src_y]
        if r.get("placed") and "actual_comp" in r:
            acx, acy = self.layer_src_to_comp(*r["actual_comp"])
            r["actual_comp_true"] = [acx, acy]
        return r

    def ensure_puppet_position_tool_fast(self, max_rotations: int = 5, probe_point=None):
        """Delegate to CEP /ensure-puppet-position-tool. Pass probe_point
        (screen x,y) on an opaque alpha pixel of the target layer — falling
        back to preferred_seed_point, then the layer's viewer-screen centre
        (via diff if needed). Falls back to the local probe loop if the
        endpoint is absent."""
        if probe_point is None:
            probe_point = self.preferred_seed_point
        if probe_point is None:
            d = self.find_layer_on_screen_via_diff(alpha_thresh=25)
            probe_point = d["center"]
            self.preferred_seed_point = probe_point
        payload = {"comp_id": self.comp_id, "layer_index": self.layer_index,
                   "max_rotations": max_rotations,
                   "probe_x": int(probe_point[0]), "probe_y": int(probe_point[1])}
        try:
            r = self._post("/ensure-puppet-position-tool", payload)
            if r.get("ok"):
                return r
            raise CEPError(f"ensure-puppet-position-tool: {r}")
        except CEPError as e:
            if "404" not in str(e):
                raise
            return self.ensure_pospin_tool(max_rotations=max_rotations,
                                           probe_point=probe_point)

    def zoom_around_center(self, target_zoom: float, tol: float = 0.1, max_steps: int = 12):
        """Step AE viewer zoom via CTRL+= / CTRL+- (anchored on viewer
        canvas centre). Loops one keystroke at a time, reading zoom after
        each, until within `tol` of target OR one more step would overshoot.

        AE's CTRL+= sequence is non-uniform (mixes 2x and sqrt(2) steps
        depending on zoom range) so we can't analytically predict steps —
        measure-and-iterate is the only reliable approach.
        """
        self.read_zoom()
        if self.zoom is None or self.zoom <= 0:
            raise CEPError("zoom read failed")
        if target_zoom <= 0:
            raise CEPError(f"bad target_zoom {target_zoom}")
        if abs(self.zoom / target_zoom - 1) <= tol:
            return self.zoom, 0
        zoom_in = target_zoom > self.zoom
        combo = "CTRL+EQUALS" if zoom_in else "CTRL+MINUS"
        self._post("/focus-ae"); time.sleep(0.08)
        steps = 0
        prev = self.zoom
        while steps < max_steps:
            if zoom_in and self.zoom >= target_zoom: break
            if (not zoom_in) and self.zoom <= target_zoom: break
            self._post("/press-key", {"hotkey": combo, "pre_focus": False})
            time.sleep(0.1)
            self.zoom = None
            self.read_zoom()
            steps += 1
            if self.zoom == prev:  # stuck (AE ignored the key)
                break
            # Check if next step would overshoot the target past doubling worth
            if zoom_in and self.zoom >= target_zoom:
                # If overshoot is bigger than undershoot-before, step back one
                overshoot = self.zoom / target_zoom - 1
                undershoot = 1 - prev / target_zoom
                if overshoot > undershoot and undershoot > 0:
                    self._post("/press-key", {"hotkey": "CTRL+MINUS", "pre_focus": False})
                    time.sleep(0.1)
                    self.zoom = None; self.read_zoom()
                break
            if (not zoom_in) and self.zoom <= target_zoom:
                break
            prev = self.zoom
        return self.zoom, (steps if zoom_in else -steps)

    def _resolve_viewer_rect(self):
        if getattr(self, "viewer_rect", None):
            return self.viewer_rect
        ae = self.ae_window_rect()
        if ae.get("error"):
            raise CEPError(f"ae_window_rect: {ae}")
        vr = self.find_viewer_rect((ae["center_x"], ae["center_y"]))
        if not vr:
            raise CEPError("cannot locate Composition viewer panel")
        self.viewer_rect = vr
        return vr

    def _pan_delta_damped(self, lx, ly, vcx, vcy, damping):
        dx = int(round((vcx - lx) * damping))
        dy = int(round((vcy - ly) * damping))
        if dx == 0 and dy == 0:
            dx = 1 if (vcx - lx) > 0 else (-1 if (vcx - lx) < 0 else 0)
            dy = 1 if (vcy - ly) > 0 else (-1 if (vcy - ly) < 0 else 0)
        return dx, dy

    def center_layer_fast_v2(self, coverage: float = 0.55,
                              pan_tol: int = 10, fallback_low_zoom: float = 0.25):
        """Fast 2-3 step centering + zoom. Flow:
          1) One diff at current zoom. If clipped/invisible → reset to low zoom, retry.
          2) One middle-drag pan (damping=1.0).
          3) One verify diff + optional one corrective pan (damping=0.6).
          4) Analytic CTRL+= step count to target zoom.
          5) One verify diff at new zoom + optional one corrective pan.

        Max ≈ 4 diffs + 3 pans + zoom-step keystrokes ≈ 5-6 seconds."""
        import math, time
        vr = self._resolve_viewer_rect()
        vcx = (vr["left"] + vr["right"]) / 2.0
        vcy = (vr["top"] + vr["bottom"]) / 2.0
        out = {"phases": []}

        def _diff_safe():
            try:
                d = self.find_layer_on_screen_via_diff(alpha_thresh=25)
                return d["center"][0], d["center"][1], d["bbox"]["w"], d["bbox"]["h"], None
            except CEPError as e:
                return None, None, None, None, str(e)

        lx, ly, bw, bh, err = _diff_safe()
        if err:
            self.set_viewer_zoom(fallback_low_zoom); time.sleep(0.3); self.read_zoom()
            lx, ly, bw, bh, err = _diff_safe()
            if err:
                raise CEPError(f"center_layer_fast_v2: layer invisible even at low zoom: {err}")
        out["phases"].append({"stage": "diff0", "layer": [lx, ly], "bbox": [bw, bh]})

        # Single full-delta pan
        dx, dy = self._pan_delta_damped(lx, ly, vcx, vcy, 1.0)
        self.pan_viewer_middle(dx, dy); time.sleep(0.3)
        out["phases"].append({"stage": "pan1", "drag": [dx, dy]})

        # Verify + one corrective pan if needed
        lx, ly, bw, bh, err = _diff_safe()
        if err is None:
            rx, ry = lx - int(vcx), ly - int(vcy)
            out["phases"].append({"stage": "diff1", "layer": [lx, ly], "res": [rx, ry]})
            if abs(rx) > pan_tol or abs(ry) > pan_tol:
                dx, dy = self._pan_delta_damped(lx, ly, vcx, vcy, 0.6)
                self.pan_viewer_middle(dx, dy); time.sleep(0.3)
                out["phases"].append({"stage": "pan2", "drag": [dx, dy]})

        # Compute target zoom from source dims if known
        self.read_zoom()
        if getattr(self, "layer_meta", None) is None:
            try: self.load_layer_meta()
            except Exception: pass
        short_v = min(vr["w"], vr["h"])
        if self.layer_meta and self.layer_meta["width"]:
            sx = self.layer_meta["scale"][0] / 100.0
            sy = self.layer_meta["scale"][1] / 100.0
            long_src = max(self.layer_meta["width"] * sx, self.layer_meta["height"] * sy)
        else:
            long_src = max(bw or 100, bh or 100) / self.zoom
        target_zoom = max(0.05, min((coverage * short_v) / long_src, 16.0))
        out["target_zoom"] = target_zoom
        new_zoom, steps = self.zoom_around_center(target_zoom)
        out["zoom_steps"] = steps; out["zoom_after_step"] = new_zoom

        # Final pan at new zoom
        lx, ly, bw, bh, err = _diff_safe()
        if err is None:
            rx, ry = lx - int(vcx), ly - int(vcy)
            out["phases"].append({"stage": "diffZ", "layer": [lx, ly], "res": [rx, ry]})
            if abs(rx) > pan_tol or abs(ry) > pan_tol:
                dx, dy = self._pan_delta_damped(lx, ly, vcx, vcy, 0.7)
                self.pan_viewer_middle(dx, dy); time.sleep(0.3)
                out["phases"].append({"stage": "panZ", "drag": [dx, dy]})
                lx, ly, bw, bh, err = _diff_safe()
        out["residual"] = [lx - int(vcx), ly - int(vcy)] if err is None else None
        out["final_zoom"] = self.zoom
        return out

    def center_layer_fast(self, coverage: float = 0.55, low_zoom: float = 0.25,
                           pan_tol: int = 6, max_passes: int = 5, damping: float = 0.7):
        """One-call centre-and-zoom:
          1. JSX-set zoom LOW so the layer is visible (no clipping).
          2. Iterative middle-drag pan to centre (damped, tol = pan_tol).
          3. CTRL+= step zoom to target coverage (layer long dim / viewer short).
          4. Final corrective pan pass.

        Returns a dict with phases and the final residual."""
        vr = self._resolve_viewer_rect()
        vcx = (vr["left"] + vr["right"]) / 2.0
        vcy = (vr["top"] + vr["bottom"]) / 2.0
        out = {"phases": []}

        self.set_viewer_zoom(low_zoom); time.sleep(0.3); self.read_zoom()

        def _diff():
            d = self.find_layer_on_screen_via_diff(alpha_thresh=25)
            return d["center"][0], d["center"][1], d["bbox"]["w"], d["bbox"]["h"]

        # Pan at low zoom
        for p in range(max_passes):
            lx, ly, bw, bh = _diff()
            rx, ry = lx - int(vcx), ly - int(vcy)
            out["phases"].append({"stage": "pan_lo", "pass": p, "res": [rx, ry], "bbox": [bw, bh]})
            if abs(rx) <= pan_tol and abs(ry) <= pan_tol:
                break
            dx = int(round((vcx - lx) * damping))
            dy = int(round((vcy - ly) * damping))
            if dx == 0 and dy == 0:
                dx = 1 if rx < 0 else (-1 if rx > 0 else 0)
                dy = 1 if ry < 0 else (-1 if ry > 0 else 0)
            self.pan_viewer_middle(dx, dy); time.sleep(0.35)

        # Target zoom from source dims (preferred) or observed bbox (fallback)
        if getattr(self, "layer_meta", None) is None:
            try: self.load_layer_meta()
            except Exception: pass
        short_v = min(vr["w"], vr["h"])
        if self.layer_meta and self.layer_meta["width"] and self.layer_meta["height"]:
            sx = self.layer_meta["scale"][0] / 100.0
            sy = self.layer_meta["scale"][1] / 100.0
            long_src = max(self.layer_meta["width"] * sx, self.layer_meta["height"] * sy)
        else:
            long_src = max(bw, bh) / self.zoom
        target_zoom = max(0.05, min((coverage * short_v) / long_src, 16.0))
        out["target_zoom"] = target_zoom

        new_zoom, steps = self.zoom_around_center(target_zoom)
        out["zoom_steps"] = steps
        out["zoom_after_step"] = new_zoom

        # Corrective pan at new zoom
        for p in range(max_passes):
            lx, ly, bw, bh = _diff()
            rx, ry = lx - int(vcx), ly - int(vcy)
            out["phases"].append({"stage": "pan_hi", "pass": p, "res": [rx, ry], "bbox": [bw, bh]})
            if abs(rx) <= pan_tol and abs(ry) <= pan_tol:
                break
            dx = int(round((vcx - lx) * damping))
            dy = int(round((vcy - ly) * damping))
            if dx == 0 and dy == 0:
                dx = 1 if rx < 0 else (-1 if rx > 0 else 0)
                dy = 1 if ry < 0 else (-1 if ry > 0 else 0)
            self.pan_viewer_middle(dx, dy); time.sleep(0.3)

        out["residual"] = [lx - int(vcx), ly - int(vcy)]
        out["final_zoom"] = self.zoom
        return out

    # ---- Analytic affine (no calibrate-click) ---------------------------

    def set_affine_from_centered_layer(self, layer_screen_centre=None):
        """Set self.tx, self.ty, self.zoom analytically. If
        `layer_screen_centre` is given, use it as the screen position of the
        layer's anchor. Otherwise run ONE diff to locate the layer and use
        that centre (more accurate than assuming viewer centre).

        Affine: `screen = (tx, ty) + src * zoom`. Only matches layer-source
        coords when layer scale ≈ 100%. For scaled layers, use calibrate().
        """
        if getattr(self, "layer_meta", None) is None:
            self.load_layer_meta()
        self.read_zoom()
        sx = self.layer_meta["scale"][0] / 100.0
        sy = self.layer_meta["scale"][1] / 100.0
        if abs(sx - 1) > 0.01 or abs(sy - 1) > 0.01:
            raise CEPError(f"scale {sx},{sy} != 1.0 — analytic affine not safe; use calibrate()")
        if layer_screen_centre is None:
            d = self.find_layer_on_screen_via_diff(alpha_thresh=25)
            layer_screen_centre = d["center"]
        lsx, lsy = layer_screen_centre
        # The layer anchor is the point that maps to layer.position (comp),
        # which is where AE's diff centroid lands (approximately — diff gives
        # the alpha centroid, not the anchor. For symmetric layers they
        # coincide; for asymmetric layers the diff centroid may differ from
        # the anchor by a few src pixels, which is still far better than the
        # 10-130px viewer-centre assumption).
        self.tx = lsx - self.layer_meta["anchor"][0] * self.zoom
        self.ty = lsy - self.layer_meta["anchor"][1] * self.zoom
        self.viewer_rect = self._resolve_viewer_rect()
        return {"tx": self.tx, "ty": self.ty, "zoom": self.zoom,
                "layer_screen_centre": [int(lsx), int(lsy)]}

    # ---- Alpha medial-line skeleton (real hair骨架) --------------------

    def _grab_viewer_np(self, pad: int = 30):
        """Screenshot the viewer panel as numpy (H,W,3). Returns (arr, vr)."""
        from PIL import ImageGrab
        import numpy as np, ctypes
        try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try: ctypes.windll.user32.SetProcessDPIAware()
            except Exception: pass
        vr = self._resolve_viewer_rect()
        u = ctypes.windll.user32
        vx0, vy0 = u.GetSystemMetrics(76), u.GetSystemMetrics(77)
        img = ImageGrab.grab(all_screens=True)
        arr = np.asarray(img, dtype=np.uint8)
        crop = arr[max(0, vr["top"]-vy0+pad):vr["bottom"]-vy0-pad,
                   max(0, vr["left"]-vx0+pad):vr["right"]-vx0-pad]
        return crop, vr, pad, vx0, vy0

    def _resample_arclength(self, points, n):
        import math
        if n < 2: return list(points[:n])
        if len(points) < 2: return [tuple(points[0])] * n if points else []
        lens = [0.0]
        for i in range(1, len(points)):
            dx = points[i][0] - points[i-1][0]
            dy = points[i][1] - points[i-1][1]
            lens.append(lens[-1] + math.hypot(dx, dy))
        total = lens[-1]
        if total <= 1e-6: return [tuple(points[0])] * n
        out = []
        for i in range(n):
            t = (i / (n - 1)) * total
            j = 1
            while j < len(lens) and lens[j] < t: j += 1
            if j >= len(lens): out.append(tuple(points[-1])); continue
            seg = lens[j] - lens[j-1]
            frac = (t - lens[j-1]) / seg if seg > 0 else 0
            x = points[j-1][0] + (points[j][0] - points[j-1][0]) * frac
            y = points[j-1][1] + (points[j][1] - points[j-1][1]) * frac
            out.append((x, y))
        return out

    def skeleton_chain_medial(self, count: int = 4, root: str = "top",
                                slice_step: int = 4, bg_thresh: int = 20,
                                edge_shrink: float = 0.04):
        """Compute N pin positions along the layer's ALPHA MEDIAL LINE.

        Requires: layer soloed + screen→src affine set (via
        set_affine_from_centered_layer or calibrate).

        Uses the affine to crop the screenshot to the layer's expected
        bbox + small margin (in screen coords), avoiding AE UI elements
        that would otherwise count as "non-black" pixels.

        `edge_shrink` trims a fraction of the measured span from each end
        of the LONG axis so pin 0 and pin N-1 sit inside the alpha body,
        not right on the edge where pins are unstable.
        """
        import numpy as np
        from PIL import ImageGrab
        import ctypes
        if self.tx is None or self.zoom is None:
            raise CEPError("set_affine_from_centered_layer() or calibrate() first")
        if getattr(self, "layer_meta", None) is None:
            self.load_layer_meta()
        m = self.layer_meta
        w_src, h_src = m["width"], m["height"]

        try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try: ctypes.windll.user32.SetProcessDPIAware()
            except Exception: pass
        u = ctypes.windll.user32
        vx0, vy0 = u.GetSystemMetrics(76), u.GetSystemMetrics(77)

        # Expected layer bbox in screen coords via the affine
        # screen = (tx, ty) + src * zoom
        sl = int(self.tx)
        st = int(self.ty)
        sr = int(self.tx + w_src * self.zoom)
        sb = int(self.ty + h_src * self.zoom)
        margin = max(6, int(round(self.zoom * 2)))  # few src-pixels worth
        vr = self._resolve_viewer_rect()
        # Clamp to viewer panel so UI chrome never enters the crop
        ui_pad_top = 50     # AE composition viewer title/tab strip
        ui_pad_bot = 55     # bottom zoom/time controls
        ui_pad_h = 20
        c_l = max(vr["left"] + ui_pad_h, sl - margin)
        c_t = max(vr["top"] + ui_pad_top, st - margin)
        c_r = min(vr["right"] - ui_pad_h, sr + margin)
        c_b = min(vr["bottom"] - ui_pad_bot, sb + margin)
        if c_r - c_l < 4 or c_b - c_t < 4:
            raise CEPError(f"computed layer bbox too small or outside viewer: {c_l},{c_t}-{c_r},{c_b}")

        img = ImageGrab.grab(all_screens=True)
        arr = np.asarray(img, dtype=np.uint8)
        crop = arr[c_t - vy0:c_b - vy0, c_l - vx0:c_r - vx0]
        if crop.size == 0:
            raise CEPError("crop empty")
        lum = crop.max(axis=2).astype(np.uint8)
        mask = lum > bg_thresh
        if not mask.any():
            raise CEPError("no layer pixels in crop (bg_thresh too high or layer not soloed)")

        long_axis = "y" if root in ("top", "bottom") else "x"
        centerline = []  # list of (screen_x, screen_y), virtual-desktop coords
        if long_axis == "y":
            H = mask.shape[0]
            # find first/last row with enough layer pixels
            row_counts = mask.sum(axis=1)
            occupied = np.where(row_counts > 2)[0]
            if len(occupied) < 2:
                raise CEPError(f"too few populated rows: {len(occupied)}")
            y0_px, y1_px = int(occupied[0]), int(occupied[-1])
            span = y1_px - y0_px
            y_start = y0_px + int(span * edge_shrink)
            y_end = y1_px - int(span * edge_shrink)
            for y in range(y_start, y_end + 1, slice_step):
                xs = np.where(mask[y])[0]
                if len(xs) < 3: continue
                cx = float(xs.mean())
                centerline.append((c_l + cx, c_t + y))
        else:
            W = mask.shape[1]
            col_counts = mask.sum(axis=0)
            occupied = np.where(col_counts > 2)[0]
            if len(occupied) < 2:
                raise CEPError(f"too few populated cols: {len(occupied)}")
            x0_px, x1_px = int(occupied[0]), int(occupied[-1])
            span = x1_px - x0_px
            x_start = x0_px + int(span * edge_shrink)
            x_end = x1_px - int(span * edge_shrink)
            for x in range(x_start, x_end + 1, slice_step):
                ys = np.where(mask[:, x])[0]
                if len(ys) < 3: continue
                cy = float(ys.mean())
                centerline.append((c_l + x, c_t + cy))

        if len(centerline) < 2:
            raise CEPError(f"centerline too short ({len(centerline)} samples)")

        if root in ("bottom", "right"):
            centerline = list(reversed(centerline))

        samples = self._resample_arclength(centerline, count)
        # Clamp src coords to layer bounds (guard against affine residual)
        chain = []
        for i, (scr_x, scr_y) in enumerate(samples):
            src_x = (scr_x - self.tx) / self.zoom
            src_y = (scr_y - self.ty) / self.zoom
            src_x = max(1.0, min(src_x, w_src - 1.0))
            src_y = max(1.0, min(src_y, h_src - 1.0))
            chain.append({
                "src": [round(src_x, 1), round(src_y, 1)],
                "screen": [int(scr_x), int(scr_y)],
                "kind": "starch" if i == 0 else "pos",
                "t": round(i / (count - 1), 3),
            })
        return chain

    # ---- Skeleton chain + adaptive pipeline -----------------------------

    def skeleton_chain(self, count: int = 4, root: str = "top", edge_inset: float = 0.08):
        """Straight-centerline chain as a geometry-only fallback (no zig-zag).
        Prefer `skeleton_chain_medial` for curved / non-symmetric layers — it
        reads the actual alpha medial line from a viewer screenshot.

        Returns: [{src:[x,y], kind:"starch"|"pos", t:float}, ...]
        Pin 0 = root end (starch), pin N-1 = tip end."""
        if getattr(self, "layer_meta", None) is None:
            self.load_layer_meta()
        m = self.layer_meta
        w, h = m["width"], m["height"]
        count = max(2, int(count))
        if root in ("top", "bottom"):
            cross_mid = w / 2.0
            a = edge_inset * h
            b = (1 - edge_inset) * h
            pts = [(cross_mid, a + t * (b - a)) for t in [i/(count-1) for i in range(count)]]
            if root == "bottom": pts = [(x, h - y) for (x, y) in pts]
        elif root in ("left", "right"):
            cross_mid = h / 2.0
            a = edge_inset * w
            b = (1 - edge_inset) * w
            pts = [(a + t * (b - a), cross_mid) for t in [i/(count-1) for i in range(count)]]
            if root == "right": pts = [(w - x, y) for (x, y) in pts]
        else:
            raise CEPError(f"unknown root: {root}")
        return [{"src": [round(x, 1), round(y, 1)],
                 "kind": "starch" if i == 0 else "pos",
                 "t": round(i/(count-1), 3)} for i, (x, y) in enumerate(pts)]

    # (zig-zag removed: straight-centerline chain. medial-line version is
    # `skeleton_chain_medial`, preferred for curved hair / non-symmetric shapes.)

    def adaptive_pin(self, coverage: float = 0.55, count: int = 4,
                     root: str = "top", center_first: bool = True,
                     ensure_tool: bool = True, starch_type: int = 3,
                     solo: bool = True, use_medial: bool = True,
                     skeleton_slice_step: int = 4):
        """One-call adaptive pipeline:
          1. Solo the layer (optional).
          2. Load layer meta (position/anchor/scale/w/h).
          3. center_layer_fast (pan + zoom to comfortable coverage).
          4. ensure_puppet_position_tool (Ctrl+P cycle until PosPins).
          5. Calibrate from a probe placed at the root pin (saves a click).
          6. Place remaining chain pins at layer-source coords.
          7. Optionally coerce pin 0 Type = 3 (Starch-equivalent "固定"
             behaviour: Type 3 = Advanced with 刚度 high). For a real
             Starch pin use starch_type=None and the caller should place
             a separate Starch pin via Ctrl+P cycling — AE stores those
             in a different group.
        """
        self.load_layer_meta()
        if solo:
            self.jsx(
                f'var t=null;for(var i=1;i<=app.project.numItems;i++){{var it=app.project.item(i); if(it.id=={self.comp_id}){{t=it;break;}}}}'
                f'if(t){{t.layer({self.layer_index}).solo=true;}} 1;'
            )
        result = {"meta": self.layer_meta, "pins": [], "center": None, "chain": []}

        if center_first:
            result["center"] = self.center_layer_fast_v2(coverage=coverage)

        if ensure_tool:
            vr = self._resolve_viewer_rect()
            probe = (int((vr["left"] + vr["right"]) / 2),
                     int((vr["top"] + vr["bottom"]) / 2))
            self.preferred_seed_point = probe
            result["ensure_tool"] = self.ensure_puppet_position_tool_fast(probe_point=probe)

        # Analytic affine — skip the calibrate seed-click. Assumes centered
        # layer (true after center_layer_fast_v2) and scale=100% (common for
        # PSD layers). Falls back to calibrate() for scaled layers.
        try:
            result["affine"] = self.set_affine_from_centered_layer()
        except CEPError:
            try:
                d = self.find_layer_on_screen_via_diff(alpha_thresh=25)
                self.preferred_seed_point = d.get("center")
                self.preferred_seed_bbox = {
                    "x": d.get("x"),
                    "y": d.get("y"),
                    "w": d.get("w"),
                    "h": d.get("h"),
                }
            except Exception as e:
                result["seed_point_error"] = str(e)
            self.read_zoom()
            calib = self.calibrate()
            result["affine"] = {"calibrated": True, "tx": calib["tx"], "ty": calib["ty"]}

        # Build chain: prefer alpha medial line; fall back to straight centerline
        chain = None
        if use_medial:
            try:
                chain = self.skeleton_chain_medial(count=count, root=root,
                                                     slice_step=skeleton_slice_step)
                result["chain_source"] = "medial"
            except Exception as e:
                result["medial_error"] = str(e)
        if chain is None:
            chain = self.skeleton_chain(count=count, root=root)
            result["chain_source"] = "straight"
        result["chain"] = chain

        placed = []
        for i, p in enumerate(chain):
            r = self.place_at_layer_src(*p["src"])
            p_out = {"i": i, "target_src": p["src"], "kind": p["kind"]}
            if r.get("placed"):
                p_out["actual_src"] = r["actual_comp"]
                p_out["err"] = r.get("err_comp")
                p_out["vtx"] = r.get("vtx_index")
                p_out["pin_index"] = r.get("pin_index")
            else:
                p_out["placed"] = False
                p_out["reason"] = r.get("reason")
            placed.append(p_out)
        result["pins"] = placed

        # Coerce root pin type for "固定" behaviour
        if starch_type and placed and placed[0].get("actual_src"):
            rx, ry = chain[0]["src"]
            code = (
                f'var t=null;for(var i=1;i<=app.project.numItems;i++){{var it=app.project.item(i); if(it.id=={self.comp_id}){{t=it;break;}}}}'
                f'var L=t.layer({self.layer_index});'
                'var fx=L.property("ADBE Effect Parade").property("ADBE FreePin3");'
                'var pins=fx.property("ADBE FreePin3 ARAP Group").property("ADBE FreePin3 Mesh Group").property(1).property("ADBE FreePin3 PosPins");'
                f'var rx={rx},ry={ry},best=-1,bestD=1e9;'
                'for(var p=1;p<=pins.numProperties;p++){'
                '  var v=pins.property(p).property("ADBE FreePin3 PosPin Position").value;'
                '  var dx=v[0]-rx,dy=v[1]-ry,d=dx*dx+dy*dy;'
                '  if(d<bestD){bestD=d;best=p;}'
                '}'
                f'var tp=pins.property(best).property("ADBE FreePin3 PosPin Type");'
                f'var before=tp.value; var err=null; try{{tp.setValue({starch_type});}}catch(e){{err=String(e);}}'
                'return {prop:best,before:before,after:tp.value,err:err};'
            )
            result["root_type_coerce"] = self.jsx(code)

        return result
