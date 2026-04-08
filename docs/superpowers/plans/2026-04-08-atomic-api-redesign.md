# AE2Claude v3.0 Atomic API Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure ae_bridge.py from ~65 methods to ~50 atomic methods following "one method = one AE action" + "Agent orchestrates" principles.

**Architecture:** Breaking refactor of `AEBridge` class in a single file (`ae_bridge.py`), with matching CLI shell update (`ae2claude`). No new dependencies. All registries (EFFECTS, BLEND_MODES, TRACK_MATTE_TYPES, KNOWN_EFFECT_MATCHNAMES) unchanged. New `PROP_MAP` registry added.

**Tech Stack:** Python 3.10+ stdlib only (urllib, json). Tests are integration tests requiring running AE instance.

**Spec:** `docs/superpowers/specs/2026-04-08-atomic-api-redesign.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `ae_bridge.py` | Modify | All AEBridge method changes — the core of this refactor |
| `ae2claude` (in `~/bin/`) | Modify | CLI shell — update help text, remove deleted commands, add new ones |
| `test_jsx.py` | Modify | Integration tests — update to match new method signatures |

No new files created. This is a pure refactor of existing code.

---

## Important Context for Workers

- **AE must be running** with AE2Claude plugin loaded to run any test. Tests call `ae2claude` CLI which hits `http://127.0.0.1:8089`.
- **`_esc()` helper** (line 2354) escapes strings for JSX embedding. Always use it for user-supplied strings.
- **JSX execution pattern**: Every method builds a JSX string and calls `self.run_jsx(jsx)`. The JSX runs inside AE's ExtendScript engine. AE object references are NOT stable across calls — each method must re-acquire `app.project.activeItem` etc.
- **`TRANSFORM_PROPS` registry** (line 128) maps semantic names to paths + ease dimensions. This is the source of truth for transform property resolution.
- **`EFFECTS` registry** (line 42) maps effect_type keys to matchName + prop matchNames. This stays unchanged.
- **Effect index**: When JSX adds an effect via `addProperty()`, the returned property's `.propertyIndex` gives its 1-based index among effects on that layer.
- **All method signatures** are consumed by the CLI shell's `_call_method()` function which uses `inspect.signature()` to dynamically dispatch. New methods are auto-discovered.

---

## Task 1: Add PROP_MAP and update version

**Files:**
- Modify: `ae_bridge.py:1-10` (version), `ae_bridge.py:158-160` (after TRANSFORM_PROPS)

- [ ] **Step 1: Bump version to 3.0.0**

In `ae_bridge.py`, change:
```python
__version__ = "2.0.0"
```
to:
```python
__version__ = "3.0.0"
```

- [ ] **Step 2: Add PROP_MAP registry after TRANSFORM_PROPS**

Insert after line 159 (after the closing `}` of TRANSFORM_PROPS), before BLEND_MODES:

```python
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
```

- [ ] **Step 3: Update class docstring**

Replace the `AEBridge` class docstring (line 293-308) with:
```python
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
```

- [ ] **Step 4: Commit**

```bash
cd F:/claude/longterm/AE2Claude
git add ae_bridge.py
git commit -m "feat(v3): add PROP_MAP registry, bump version to 3.0.0"
```

---

## Task 2: Transform domain — merge 7 methods into 4

**Files:**
- Modify: `ae_bridge.py` — remove `set_position_keyframes` (line 721), `set_opacity_keyframes` (740), `set_scale_keyframes` (759), `set_rotation_keyframes` (781), `set_property_keyframes` (794), `get_transform_value` (1245), `get_property_value` (1304), `get_property_keyframes` (1328), `get_keyframes` (1281). Replace with 4 unified methods.

- [ ] **Step 1: Replace set_position/opacity/scale/rotation/property_keyframes with unified set_keyframes**

Delete these 5 methods (`set_position_keyframes`, `set_opacity_keyframes`, `set_scale_keyframes`, `set_rotation_keyframes`, `set_property_keyframes`). Replace with one method in the same location (Keyframes section):

```python
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
```

- [ ] **Step 2: Replace get_transform_value + get_property_value with unified get_value**

Delete `get_transform_value` (line 1245) and `get_property_value` (line 1304). Replace with:

```python
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
```

- [ ] **Step 3: Replace get_keyframes + get_property_keyframes with unified get_keyframes**

Delete `get_keyframes` (line 1281) and `get_property_keyframes` (line 1328). Replace with:

```python
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
```

- [ ] **Step 4: Add set_value method**

Add next to `get_value`:

```python
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
```

- [ ] **Step 5: Commit**

```bash
cd F:/claude/longterm/AE2Claude
git add ae_bridge.py
git commit -m "feat(v3): merge transform methods into set_value/get_value/set_keyframes/get_keyframes"
```

---

## Task 3: Effect domain — slim add_effect, add set_effect_props/set_effect_keyframes, switch to effect_index

**Files:**
- Modify: `ae_bridge.py` — `add_effect` (line 905), `get_effect_param` (1347), `get_effect_keyframes` (1367)

- [ ] **Step 1: Rewrite add_effect to only add, return effect_index**

Replace the `add_effect` method (lines 905-959) with:

```python
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
```

- [ ] **Step 2: Add set_effect_props method**

Add after `add_effect`:

```python
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
            # Resolve prop_key to matchName by scanning EFFECTS registry
            mn = self._resolve_effect_prop(key)
            if mn is None:
                continue
            if isinstance(val, (list, tuple)):
                jsx += f'ef.property("{mn}").setValue({json.dumps(val)});'
            else:
                jsx += f'ef.property("{mn}").setValue({val});'
        jsx += '"ok";}}'
        jsx += f'}}catch(e){{"FX_ERR:"+e.toString()}}'
        return self.run_jsx(jsx)
```

- [ ] **Step 3: Add set_effect_keyframes method**

Add after `set_effect_props`:

```python
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
        jsx += '"ok";}}'
        jsx += f'}}catch(e){{"FX_ERR:"+e.toString()}}'
        return self.run_jsx(jsx)
```

- [ ] **Step 4: Add _resolve_effect_prop helper**

Add as a private method on AEBridge (e.g. after `_run_py`):

```python
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
```

- [ ] **Step 5: Update get_effect_param to use effect_index**

Replace `get_effect_param` (line 1347) with:

```python
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
```

- [ ] **Step 6: Update get_effect_keyframes to use effect_index**

Replace `get_effect_keyframes` (line 1367) with:

```python
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
```

- [ ] **Step 7: Commit**

```bash
cd F:/claude/longterm/AE2Claude
git add ae_bridge.py
git commit -m "feat(v3): effect domain — atomic add_effect returns index, new set_effect_props/keyframes"
```

---

## Task 4: Easing domain — split into transform + effect

**Files:**
- Modify: `ae_bridge.py` — `apply_easing` (line 819), `apply_effect_easing` (line 862)

- [ ] **Step 1: Replace apply_easing with apply_transform_easing (single-prop)**

Delete `apply_easing` (lines 819-860). Replace with:

```python
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
```

- [ ] **Step 2: Rewrite apply_effect_easing to use effect_index**

Delete `apply_effect_easing` (lines 862-901). Replace with:

```python
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
```

- [ ] **Step 3: Commit**

```bash
cd F:/claude/longterm/AE2Claude
git add ae_bridge.py
git commit -m "feat(v3): split easing into apply_transform_easing + apply_effect_easing"
```

---

## Task 5: Layer domain — slim add_text_layer, add new methods, remove fat methods

**Files:**
- Modify: `ae_bridge.py` — `add_text_layer` (line 640), `remove_layers_by_prefix` (589), `layer_exists` (563), `select_layers` (2244)

- [ ] **Step 1: Slim add_text_layer**

Replace `add_text_layer` (lines 640-706) with:

```python
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
```

- [ ] **Step 2: Add add_solid method**

Add after `add_text_layer`:

```python
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
```

- [ ] **Step 3: Replace select_layers with set_layer_selected**

Delete `select_layers` (lines 2244-2251). Replace with:

```python
    def set_layer_selected(self, name: str, selected: bool = True) -> str:
        """Set a single layer's selection state."""
        jsx = (
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(name)}").selected={str(selected).lower()};'
            f'"ok";'
        )
        return self.run_jsx(jsx)
```

- [ ] **Step 4: Delete remove_layers_by_prefix**

Delete the `remove_layers_by_prefix` method (lines 589-601). Agent will do: `list_layers` → filter → `remove_layer` per layer.

- [ ] **Step 5: Delete layer_exists**

Delete the `layer_exists` method (lines 563-570). Agent will do: `list_layers` → check name in result.

- [ ] **Step 6: Commit**

```bash
cd F:/claude/longterm/AE2Claude
git add ae_bridge.py
git commit -m "feat(v3): layer domain — slim add_text_layer, add add_solid/set_layer_selected, remove orchestration methods"
```

---

## Task 6: Text domain — add set_text_content and set_text_style

**Files:**
- Modify: `ae_bridge.py` — add two new methods in the Text section (near line 1896)

- [ ] **Step 1: Add set_text_content**

Add before `add_text_animator`:

```python
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
```

- [ ] **Step 2: Add set_text_style**

Add after `set_text_content`:

```python
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
```

- [ ] **Step 3: Commit**

```bash
cd F:/claude/longterm/AE2Claude
git add ae_bridge.py
git commit -m "feat(v3): text domain — add set_text_content and set_text_style"
```

---

## Task 7: Cleanup — remove remaining orchestration methods, mark experimental

**Files:**
- Modify: `ae_bridge.py` — delete `batch_jsx` (2232), `render_comp` (2224), `add_mask_rect` (1625), `add_mask_ellipse` (1632); mark `add_layer_style`/`enable_layer_style` as experimental

- [ ] **Step 1: Delete batch_jsx**

Delete `batch_jsx` method (lines 2232-2242). Agent decides call sequence.

- [ ] **Step 2: Delete render_comp**

Delete `render_comp` method (lines 2224-2228). Agent orchestrates: `add_to_render_queue` → `set_render_output` → `start_render`.

- [ ] **Step 3: Delete add_mask_rect and add_mask_ellipse**

Delete `add_mask_rect` (lines 1625-1630) and `add_mask_ellipse` (lines 1632-1642). Agent computes vertices and calls `add_mask`.

- [ ] **Step 4: Mark Layer Style methods as experimental**

Update docstrings of `add_layer_style` (line 2002) and `enable_layer_style` (line 2033):

For `add_layer_style`:
```python
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
```

For `enable_layer_style`:
```python
    def enable_layer_style(self, name: str, style: str,
                            enabled: bool = True) -> str:
        """
        [EXPERIMENTAL] Toggle a Layer Style on/off.

        WARNING: AE's canSetEnabled returns false for most styles.
        This method may silently fail.
        """
```

- [ ] **Step 5: Commit**

```bash
cd F:/claude/longterm/AE2Claude
git add ae_bridge.py
git commit -m "feat(v3): remove orchestration methods (batch_jsx/render_comp/mask sugar), mark layer styles experimental"
```

---

## Task 8: CLI shell rewrite

**Files:**
- Modify: `~/bin/ae2claude`

- [ ] **Step 1: Update version and help text**

In the CLI file (`~/bin/ae2claude`), update:

1. The `__doc__` string at the top — remove deleted commands, add new ones:
   - Remove: `layer_exists`, `get_transform_value`, `get_property_value`, `get_property_keyframes`, `set_position_keyframes`, `set_opacity_keyframes`, `set_scale_keyframes`, `set_rotation_keyframes`, `apply_easing` (old), `batch_jsx`, `render_comp`, `remove_layers_by_prefix`, `select_layers`, `add_mask_rect`
   - Add: `set_value`, `get_value`, `set_keyframes`, `get_keyframes`, `set_effect_props`, `set_effect_keyframes`, `apply_transform_easing`, `set_layer_selected`, `add_solid`, `set_text_content`, `set_text_style`
   - Rename: `apply_easing` → `apply_transform_easing`, `apply_effect_easing` now takes `effect_index`

2. Version string: `"ae2claude 2.0.0"` → `"ae2claude 3.0.0"`

Replace the full `__doc__` with:

```python
"""AE2Claude CLI v3.0 - talk to After Effects from the terminal.

Built-in:
  ae2claude                              health check
  ae2claude jsx <code>                   run ExtendScript
  ae2claude py <code>                    run Python (PyShiftCore)
  ae2claude version                      AE version
  ae2claude comps                        list compositions
  ae2claude layers                       list layers in active comp
  ae2claude run <name>                   run user script
  ae2claude scripts                      list all user scripts
  ae2claude snapshot [path]              save current frame as PNG
  ae2claude methods                      list all bridge methods
  ae2claude help                         this help

Bridge (ae2claude call <method> [args...] [--key value]):
  Query:
    comp_info                            active comp info
    project_info                         project info
    list_layers                          all layers
    list_comps                           all compositions
    get_layer_info <name>                layer detail
    get_layer_by_id <id>                 layer by ID
    get_selected_layers                  selected layers
    list_masks <name>                    layer masks
    list_comp_markers                    comp markers
    list_layer_markers <name>            layer markers
    list_precomps                        precomp list
    enumerate_effects <name>             layer effects
    render_queue_info                    render queue
    list_available_effects               available effects
    describe_effect <matchName>          effect detail

  Read Properties:
    get_value <name> <prop>              transform value (position/scale/...)
    get_keyframes <name> <prop>          transform keyframes
    get_effect_param <name> <idx> <key>  effect value by index
    get_effect_keyframes <n> <idx> <key> effect keyframes by index
    get_blending_mode <name>             blend mode
    get_parent <name>                    parent layer

  Create:
    add_text_layer <text>                text layer (use set_text_style for styling)
    add_solid <name> <color>             solid layer
    add_shape_layer <name>               shape layer
    add_shape_rect <name> --size [w,h]   rectangle
    add_shape_ellipse <name> --size [w,h] ellipse
    add_shape_path <name> <verts>        freeform path
    add_shape_fill <name> --color [r,g,b] fill
    add_shape_stroke <name>              stroke
    create_comp <name> <w> <h>           new comp
    create_camera <name>                 camera
    create_light <name>                  light
    create_null_control <name>           null + parent
    import_file <path>                   import footage

  Transform:
    set_value <name> <prop> <val>        set property value
    set_keyframes <name> <prop> <kfs>    set keyframes (JSON)
    apply_transform_easing <name> <prop> ease transform property

  Effect:
    add_effect <name> <type>             add effect → returns index
    set_effect_props <n> <idx> <props>   set effect values by index
    set_effect_keyframes <n> <idx> <kfs> set effect keyframes by index
    apply_effect_easing <n> <idx> <key>  ease effect property

  Layer:
    set_blending_mode <name> <mode>      blend mode
    set_parent <child> <parent>          parenting
    remove_parent <name>                 unparent
    set_3d_layer <name>                  enable 3D
    set_track_matte <name> <matte> <type> track matte
    set_layer_timing <name>              in/out point
    set_layer_label <name> <label>       label color
    set_layer_selected <name> <bool>     selection state
    rename_layer <old> <new>             rename
    reorder_layer <name> <index>         reorder
    duplicate_layer <name>               duplicate
    remove_layer <name>                  delete
    deselect_all                         deselect all

  Text:
    set_text_content <name> <text>       change text
    set_text_style <name> --font X ...   font/color/size
    add_text_animator <name>             text animator
    animate_text_selector <name>         selector KFs

  Mask:
    add_mask <name> <verts>              custom mask
    set_mask_feather <name> <idx> <val>  feather
    set_mask_opacity <name> <idx> <val>  mask opacity
    animate_mask_path <name> <idx> <kfs> animate mask
    remove_mask <name> <idx>             delete mask

  Marker:
    add_comp_marker <time>               comp marker
    add_layer_marker <name> <time>       layer marker
    remove_comp_marker <idx>             delete marker

  Time:
    enable_time_remap <name>             enable remap
    freeze_frame <name> <time>           freeze
    reverse_layer <name>                 reverse
    set_expression <name> <path> <expr>  expression
    clear_expression <name> <path>       clear expr

  Render:
    add_to_render_queue                  queue active comp
    start_render                         start render
    set_render_output <idx> <path>       set output
    clear_render_queue                   clear queue

  Comp:
    precompose <names> <comp_name>       precompose
    open_precomp <name>                  open precomp
    add_comp_to_comp <src> [target]      nest comp

  Undo:
    begin_undo <name>                    start undo group
    end_undo                             end undo group
"""
```

- [ ] **Step 2: Update version string**

Change:
```python
    elif cmd == "--version":
        print("ae2claude 2.0.0")
```
to:
```python
    elif cmd == "--version":
        print("ae2claude 3.0.0")
```

- [ ] **Step 3: Commit**

```bash
cd F:/claude/longterm/AE2Claude
git add ~/bin/ae2claude
git commit -m "feat(v3): update CLI shell help text and version for v3.0 API"
```

---

## Task 9: Update integration tests

**Files:**
- Modify: `test_jsx.py`

- [ ] **Step 1: Read current test_jsx.py completely**

Read the full file to understand all test cases that reference deleted/renamed methods.

- [ ] **Step 2: Update test calls to match v3 API**

The key changes needed:
- `call("layer_exists", ...)` → remove test (method deleted)
- `call("remove_layers_by_prefix", ...)` → remove test
- `call("select_layers", ...)` → change to `call("set_layer_selected", name, "true")`
- `call("set_position_keyframes", ...)` → change to `call("set_keyframes", name, "position", kfs)`
- `call("set_opacity_keyframes", ...)` → change to `call("set_keyframes", name, "opacity", kfs)`
- `call("set_scale_keyframes", ...)` → change to `call("set_keyframes", name, "scale", kfs)`
- `call("set_rotation_keyframes", ...)` → change to `call("set_keyframes", name, "rotation", kfs)`
- `call("get_transform_value", ...)` → change to `call("get_value", name, prop)`
- `call("get_property_value", ...)` → change to `call("get_value", name, prop)`
- `call("get_property_keyframes", ...)` → change to `call("get_keyframes", name, prop)`
- `call("apply_easing", ...)` → change to `call("apply_transform_easing", name, prop)`
- `call("apply_effect_easing", ...)` → update args to use effect_index
- `call("add_effect", name, type, props)` → split into `call("add_effect", name, type)` then `call("set_effect_props", name, idx, props)`
- `call("batch_jsx", ...)` → remove test
- `call("render_comp", ...)` → remove test
- `call("add_mask_rect", ...)` → remove test
- `call("add_mask_ellipse", ...)` → remove test

Add new tests for:
- `call("set_text_content", name, "new text")`
- `call("set_text_style", name, "--font_size", "56", "--fill_color", "[1,1,1]")`
- `call("add_solid", "TestSolid", "[1,0,0]")`
- `call("set_value", name, "opacity", "50")`
- `call("set_layer_selected", name, "true")`

(Exact test code depends on the full current content of test_jsx.py — the worker must read it first.)

- [ ] **Step 3: Commit**

```bash
cd F:/claude/longterm/AE2Claude
git add test_jsx.py
git commit -m "test(v3): update integration tests for v3.0 atomic API"
```

---

## Task 10: Final verification and tag

- [ ] **Step 1: Verify ae_bridge.py loads without errors**

```bash
cd F:/claude/longterm/AE2Claude
python -c "from ae_bridge import AEBridge, PROP_MAP, _resolve_prop; print('OK, version:', AEBridge.__doc__[:30])"
```

Expected: prints OK with v3.0 in docstring, no import errors.

- [ ] **Step 2: Verify _resolve_prop rejects unknown props**

```bash
cd F:/claude/longterm/AE2Claude
python -c "from ae_bridge import _resolve_prop; _resolve_prop('bogus')" 2>&1
```

Expected: `ValueError: Unknown property 'bogus'...`

- [ ] **Step 3: Verify method count**

```bash
cd F:/claude/longterm/AE2Claude
python -c "
from ae_bridge import AEBridge
ae_methods = [m for m in dir(AEBridge) if not m.startswith('_') and callable(getattr(AEBridge, m))]
print(f'Method count: {len(ae_methods)}')
for m in sorted(ae_methods): print(f'  {m}')
"
```

Expected: ~50 methods. Verify no deleted methods appear (no `batch_jsx`, `render_comp`, `remove_layers_by_prefix`, `layer_exists`, `select_layers`, `set_position_keyframes`, etc.).

- [ ] **Step 4: Run full integration test with AE** (requires AE running)

```bash
cd F:/claude/longterm/AE2Claude
python test_jsx.py
```

Expected: All tests pass.

- [ ] **Step 5: Tag release**

```bash
cd F:/claude/longterm/AE2Claude
git tag -a v3.0.0 -m "v3.0.0 — Atomic API redesign

Breaking changes:
- add_text_layer slimmed (use set_text_style for styling)
- add_effect returns effect_index (use set_effect_props/set_effect_keyframes)
- Transform methods unified (set_keyframes/get_keyframes/set_value/get_value)
- Easing split: apply_transform_easing + apply_effect_easing
- Removed: batch_jsx, render_comp, remove_layers_by_prefix, layer_exists,
  select_layers, add_mask_rect, add_mask_ellipse
- New: add_solid, set_text_content, set_text_style, set_layer_selected
- Layer Styles marked experimental"
```

- [ ] **Step 6: Commit plan**

```bash
cd F:/claude/longterm/AE2Claude
git add -f docs/superpowers/plans/2026-04-08-atomic-api-redesign.md
git commit -m "docs: add v3.0 implementation plan"
```
