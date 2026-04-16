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

    def ensure_pospin_tool(self, max_rotations: int = 6):
        """Rotate Ctrl+P until the next click lands a pin in `PosPins` (not in
        Hght/Starch). Uses the AE window centre as the probe click point, so
        the target layer's alpha must cover that point — calibrate expects
        the same thing.

        Returns {rotations, final_group, pos_delta, ...}. On failure raises.
        """
        if self.comp_id is None or self.layer_index is None:
            raise CEPError("call ensure_target first")

        ae = self.ae_window_rect()
        if ae.get("error"):
            raise CEPError(f"ae_window_rect failed: {ae}")
        probe_x, probe_y = int(ae["center_x"]), int(ae["center_y"])

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

    def fit_to_viewer(self):
        """Invoke AE's 'Fit to Comp Panel' (Shift + / / Shift + Slash) so that
        the entire comp is inside the visible viewer area. Forces a zoom
        re-read afterwards because fit changes zoom."""
        # AE maps '/' to VK_OEM_2 = 0xBF. parseCombo in CEP recognizes only
        # named keys, so we use /press-key with a raw sequence by piggybacking
        # on the 'SLASH' alias we add server-side next. For now use a JSX
        # hack: app.activeViewer.setActive() + executeCommand via menu.
        r = self._post("/press-key", {"hotkey": "Shift+SLASH"})
        if not r.get("ok"):
            # Fallback: /eval a ZoomViewport command
            js = (
                "try{app.activeViewer.setActive();}catch(_){}"
                "try{app.executeCommand(app.findMenuCommandId('Fit'));}catch(_){}"
                "return {fallback:true};"
            )
            self.jsx(js)
        time.sleep(0.3)
        self.zoom = None
        return self.read_zoom()

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
        ens = self.ensure_pospin_tool()
        seed_result = ens["seed_result"]
        sx, sy = seed_result["tries"][-1]["screen"]
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
            "rotations": ens["rotations"],
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
