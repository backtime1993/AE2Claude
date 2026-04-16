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
        """Hand-Tool drag viewer by (dx, dy) screen pixels."""
        payload = {"dx": int(dx), "dy": int(dy)}
        if from_point is not None:
            payload["from_x"], payload["from_y"] = int(from_point[0]), int(from_point[1])
        return self._post("/viewer-pan", payload)

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
        snap = self.jsx(
            f'var t=null;for(var i=1;i<=app.project.numItems;i++){{var it=app.project.item(i); if(it.id=={self.comp_id}){{t=it;break;}}}}'
            'var s=[];'
            f'for(var k=1;k<=t.numLayers;k++){{var L=t.layer(k); s.push({{i:k,e:L.enabled}}); L.enabled=(k=={self.layer_index});}}'
            'return s;'
        )
        time.sleep(1.2)
        img_a_pil = ImageGrab.grab(all_screens=True)
        img_a_pil.save(r"F:\claude\projects\原画skill制作\_diag_diff_a.png")
        img_a = np.asarray(img_a_pil, dtype=np.int16)

        # Now also hide the target layer.
        self.jsx(
            f'var t=null;for(var i=1;i<=app.project.numItems;i++){{var it=app.project.item(i); if(it.id=={self.comp_id}){{t=it;break;}}}}'
            f't.layer({self.layer_index}).enabled=false; return true;'
        )
        time.sleep(1.2)
        img_b_pil = ImageGrab.grab(all_screens=True)
        img_b_pil.save(r"F:\claude\projects\原画skill制作\_diag_diff_b.png")
        img_b = np.asarray(img_b_pil, dtype=np.int16)

        # Restore every layer's original enabled state.
        snap_json = json.dumps(snap)
        self.jsx(
            f'var t=null;for(var i=1;i<=app.project.numItems;i++){{var it=app.project.item(i); if(it.id=={self.comp_id}){{t=it;break;}}}}'
            f'var s={snap_json};for(var j=0;j<s.length;j++){{t.layer(s[j].i).enabled=s[j].e;}}'
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
