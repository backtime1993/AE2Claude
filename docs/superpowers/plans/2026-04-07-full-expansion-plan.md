# AE2Claude 全面扩展实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 AE2Claude 从 JSX 透传工具升级为 AE 全能 Python SDK — ae_bridge.py 补齐 13 个方法类别 + C++ PyShiftCore 新增 Stream/Keyframe Suite + 已有 CoreSDK 函数全面接入 pybind11。

**Architecture:** 双层并进 — ae_bridge.py 通过 JSX 提供即时可用的高层 API；C++ 层新建 Stream/Keyframe Suite wrapper 并把已有的 Comp/Layer/Effect CoreSDK 函数暴露到 Python，为未来高性能批量操作铺路。

**Tech Stack:** Python 3.12 (embedded in AE)、ExtendScript、C++ (VS2022 v143)、pybind11 v2.13.6、AE SDK 25.6、HTTP (port 8089)

**Spec:** `docs/superpowers/specs/2026-04-07-full-expansion-design.md`

**测试方式:** 本项目运行在 AE 嵌入 Python 中，无 pytest。每个 Task 的验证步骤是通过 `curl` 调用 HTTP 端点执行 Python/JSX 代码验证。需要 AE 打开且 AE2Claude 插件加载。

---

## 文件结构

### Phase 1 修改文件
```
F:\claude\longterm\AE2Claude\ae_bridge.py                    — 新增 ~60 个方法
F:\claude\longterm\AE2Claude\ae2claude_server.py              — 无修改
~\.claude\skills\ae2claude-bridge\scripts\ae_bridge.py        — 同步更新
~\.claude\skills\ae2claude-bridge\SKILL.md                    — 新 API 文档
```

### Phase 2 新增/修改文件（C++ 源码路径前缀省略为 `src/`）
```
src = F:\claude\ae workspace\AE_agent-harness\PyShiftAE重编译AE26\PyShiftAE\src\PyShiftAE

新增:
  src/CoreSDK/StreamSuites.h
  src/CoreSDK/StreamSuites.cpp
  src/CoreSDK/KeyframeSuites.h
  src/CoreSDK/KeyframeSuites.cpp
  src/CoreSDK/MaskSuites.h
  src/CoreSDK/MaskSuites.cpp

修改:
  src/CoreLib/ItemManager.h          — Layer/CompItem 类扩展
  src/CoreLib/ItemManager.cpp        — 新方法实现
  src/CoreLib/PyCore.cpp             — 大量新增 pybind11 绑定
  src/Win/PyShiftAE.vcxproj          — 注册新 .cpp/.h
```

---

# Phase 1: ae_bridge.py JSX 层全面扩展

所有新方法添加到 `AEBridge` 类中（`ae_bridge.py`），插入位置在现有方法之后、`_esc()` 辅助函数之前（约 line 1197）。

每个 Task 完成后将 ae_bridge.py 复制到 skill 目录同步。

---

### Task 1: 属性回读 — Transform 值 + 关键帧列表

**Files:**
- Modify: `F:\claude\longterm\AE2Claude\ae_bridge.py` (在 `get_layer_by_id` 方法后插入)

- [ ] **Step 1: 添加 get_transform_value 方法**

```python
    def get_transform_value(self, name: str, prop: str, at_time: float = None) -> Any:
        """
        读取 Transform 属性当前值或指定时间的值。

        Args:
            name: 图层名
            prop: 属性名 ("position"/"scale"/"rotation"/"opacity"/"anchor_point")
            at_time: 指定时间(秒)，None 表示当前时间

        Returns:
            属性值 — [x,y]/[x,y,z] (position/scale/anchor), float (rotation/opacity)
        """
        info = TRANSFORM_PROPS.get(prop)
        if not info:
            raise ValueError(f"Unknown transform prop: {prop}. Available: {list(TRANSFORM_PROPS.keys())}")
        path = info["path"]
        if at_time is not None:
            jsx = (
                f'var c=app.project.activeItem;'
                f'var tl=c.layer("{_esc(name)}");'
                f'var p=tl.{path};'
                f'var v=p.valueAtTime({at_time},false);'
                f'JSON.stringify(v instanceof Array?v:[v]);'
            )
        else:
            jsx = (
                f'var c=app.project.activeItem;'
                f'var tl=c.layer("{_esc(name)}");'
                f'var p=tl.{path};'
                f'var v=p.value;'
                f'JSON.stringify(v instanceof Array?v:[v]);'
            )
        r = self.run_jsx(jsx)
        try:
            val = json.loads(r)
            return val[0] if len(val) == 1 and prop in ("rotation", "opacity") else val
        except json.JSONDecodeError:
            return r
```

- [ ] **Step 2: 添加 get_keyframes 方法**

```python
    def get_keyframes(self, name: str, prop: str) -> List[Tuple[float, Any]]:
        """
        读取 Transform 属性的所有关键帧。

        Returns:
            [(time_sec, value), ...] — 无关键帧返回空列表
        """
        info = TRANSFORM_PROPS.get(prop)
        if not info:
            raise ValueError(f"Unknown transform prop: {prop}")
        path = info["path"]
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var p=tl.{path};'
            f'var out=[];'
            f'for(var i=1;i<=p.numKeys;i++){{'
            f'var t=p.keyTime(i);var v=p.keyValue(i);'
            f'out.push({{t:t,v:v}});}}'
            f'JSON.stringify(out);'
        )
        r = self.run_jsx(jsx)
        try:
            data = json.loads(r)
            return [(kf["t"], kf["v"]) for kf in data]
        except json.JSONDecodeError:
            return []
```

- [ ] **Step 3: 添加通用属性回读方法**

```python
    def get_property_value(self, name: str, prop_path: str, at_time: float = None) -> Any:
        """
        读取任意属性值。

        Args:
            name: 图层名
            prop_path: 属性路径，如 'property("Transform").property("Opacity")'
            at_time: 指定时间(秒)
        """
        if at_time is not None:
            jsx = (
                f'var c=app.project.activeItem;'
                f'var tl=c.layer("{_esc(name)}");'
                f'var p=tl.{prop_path};'
                f'var v=p.valueAtTime({at_time},false);'
                f'JSON.stringify(v instanceof Array?v:[v]);'
            )
        else:
            jsx = (
                f'var c=app.project.activeItem;'
                f'var tl=c.layer("{_esc(name)}");'
                f'var p=tl.{prop_path};'
                f'var v=p.value;'
                f'JSON.stringify(v instanceof Array?v:[v]);'
            )
        r = self.run_jsx(jsx)
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return r

    def get_property_keyframes(self, name: str, prop_path: str) -> List[Tuple[float, Any]]:
        """读取任意属性的所有关键帧。"""
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var p=tl.{prop_path};'
            f'var out=[];'
            f'for(var i=1;i<=p.numKeys;i++){{'
            f'var t=p.keyTime(i);var v=p.keyValue(i);'
            f'out.push({{t:t,v:v}});}}'
            f'JSON.stringify(out);'
        )
        r = self.run_jsx(jsx)
        try:
            data = json.loads(r)
            return [(kf["t"], kf["v"]) for kf in data]
        except json.JSONDecodeError:
            return []
```

- [ ] **Step 4: 添加效果属性回读方法**

```python
    def get_effect_param(self, name: str, effect_match_name: str,
                          param_match_name: str, at_time: float = None) -> Any:
        """
        读取效果属性值。

        Args:
            name: 图层名
            effect_match_name: 效果 matchName (如 "ADBE Gaussian Blur 2")
            param_match_name: 参数 matchName (如 "ADBE Gaussian Blur 2-0001")
            at_time: 指定时间(秒)
        """
        time_part = f'.valueAtTime({at_time},false)' if at_time is not None else '.value'
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var fx=tl.property("Effects");'
            f'var ef=null;for(var i=fx.numProperties;i>=1;i--){{'
            f'if(fx.property(i).matchName=="{effect_match_name}"){{ef=fx.property(i);break;}}}}'
            f'if(!ef)JSON.stringify({{error:"effect_not_found"}});else{{'
            f'var v=ef.property("{param_match_name}"){time_part};'
            f'JSON.stringify(v instanceof Array?v:[v]);}}'
        )
        r = self.run_jsx(jsx)
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return r

    def get_effect_keyframes(self, name: str, effect_match_name: str,
                              param_match_name: str) -> List[Tuple[float, Any]]:
        """读取效果属性的所有关键帧。"""
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var fx=tl.property("Effects");'
            f'var ef=null;for(var i=fx.numProperties;i>=1;i--){{'
            f'if(fx.property(i).matchName=="{effect_match_name}"){{ef=fx.property(i);break;}}}}'
            f'if(!ef)JSON.stringify([]);else{{'
            f'var p=ef.property("{param_match_name}");var out=[];'
            f'for(var k=1;k<=p.numKeys;k++){{'
            f'out.push({{t:p.keyTime(k),v:p.keyValue(k)}});}}'
            f'JSON.stringify(out);}}'
        )
        r = self.run_jsx(jsx)
        try:
            data = json.loads(r)
            return [(kf["t"], kf["v"]) for kf in data]
        except json.JSONDecodeError:
            return []
```

- [ ] **Step 5: 验证**

```bash
# 先在 AE 中打开一个含有文本图层(含 opacity 关键帧)的合成
curl -s -X POST http://127.0.0.1:8089/ -d "
import sys; sys.path.insert(0, r'F:\\claude\\longterm\\AE2Claude')
from ae_bridge import AEBridge
ae = AEBridge()
print('transform:', ae.get_transform_value(ae.list_layers()[0]['name'], 'position'))
print('keyframes:', ae.get_keyframes(ae.list_layers()[0]['name'], 'opacity'))
"
```
Expected: 返回位置数组和关键帧列表

- [ ] **Step 6: Commit**

```bash
cd "F:/claude/longterm/AE2Claude"
git add ae_bridge.py
git commit -m "feat: add property read-back methods (transform, keyframes, effects)"
```

---

### Task 2: Shape 图层

**Files:**
- Modify: `F:\claude\longterm\AE2Claude\ae_bridge.py`

- [ ] **Step 1: 添加 Shape 图层方法**

```python
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
        """
        在 Shape 图层中添加矩形。

        Args:
            name: 图层名
            size: [width, height] 默认 [100, 100]
            position: [x, y] 默认 [0, 0]
            roundness: 圆角半径
            group_index: 目标 Shape Group 索引 (1-based)，None = 自动
        """
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
        """
        在 Shape 图层中添加自定义路径。

        Args:
            vertices: [[x,y], ...] 顶点列表
            in_tangents: 入切线，None = 全零
            out_tangents: 出切线，None = 全零
            closed: 是否闭合
        """
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
```

- [ ] **Step 2: 验证**

```bash
curl -s -X POST http://127.0.0.1:8089/ -d "
import sys; sys.path.insert(0, r'F:\\claude\\longterm\\AE2Claude')
from ae_bridge import AEBridge
ae = AEBridge()
ae.begin_undo('Shape Test')
ae.add_shape_layer('TestShape')
ae.add_shape_rect('TestShape', size=[200,100], roundness=15)
ae.add_shape_fill('TestShape', color=[1,0,0.5])
ae.add_shape_stroke('TestShape', color=[1,1,1], width=3)
ae.end_undo()
print('shape ok')
"
```

- [ ] **Step 3: Commit**

```bash
cd "F:/claude/longterm/AE2Claude" && git add ae_bridge.py && git commit -m "feat: add Shape layer methods (rect/ellipse/path/fill/stroke)"
```

---

### Task 3: 预合成

**Files:**
- Modify: `F:\claude\longterm\AE2Claude\ae_bridge.py`

- [ ] **Step 1: 添加预合成方法**

```python
    def precompose(self, layer_names: List[str], comp_name: str = "PreComp",
                    move_attrs: bool = True) -> str:
        """
        将指定图层预合成。

        Args:
            layer_names: 图层名列表
            comp_name: 新合成名
            move_attrs: True = 移动所有属性到新合成
        """
        # 先选中目标图层，再预合成
        select_jsx = (
            f'var c=app.project.activeItem;'
            f'for(var i=1;i<=c.numLayers;i++)c.layer(i).selected=false;'
        )
        for ln in layer_names:
            select_jsx += f'try{{c.layer("{_esc(ln)}").selected=true;}}catch(e){{}}'

        # 收集选中图层索引
        select_jsx += (
            f'var idxs=[];for(var i=1;i<=c.numLayers;i++){{'
            f'if(c.layer(i).selected)idxs.push(i);}}'
        )
        move_flag = 1 if move_attrs else 2  # 1=MoveAllAttributes, 2=LeaveAttributes
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
        """列出项目中作为预合成使用的合成"""
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
        """打开图层的源合成（如果是预合成）"""
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
```

- [ ] **Step 2: 验证 + Commit**

```bash
curl -s -X POST http://127.0.0.1:8089/ -d "
import sys; sys.path.insert(0, r'F:\\claude\\longterm\\AE2Claude')
from ae_bridge import AEBridge
ae = AEBridge()
print('precomps:', ae.list_precomps()[:3])
"
```

```bash
cd "F:/claude/longterm/AE2Claude" && git add ae_bridge.py && git commit -m "feat: add precompose methods"
```

---

### Task 4: 蒙版 / Mask

**Files:**
- Modify: `F:\claude\longterm\AE2Claude\ae_bridge.py`

- [ ] **Step 1: 添加 Mask 方法**

```python
    def add_mask(self, name: str, vertices: List[List[float]],
                  in_tangents: List[List[float]] = None,
                  out_tangents: List[List[float]] = None,
                  mode: str = "add", feather: float = 0,
                  opacity: float = 100, inverted: bool = False,
                  closed: bool = True) -> str:
        """
        为图层添加蒙版。

        Args:
            name: 图层名
            vertices: [[x,y], ...] 顶点
            mode: "none"/"add"/"subtract"/"intersect"/"lighten"/"darken"/"difference"
            feather: 羽化值
            opacity: 蒙版不透明度 (0-100)
            inverted: 是否反转
        """
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

    def add_mask_rect(self, name: str, top: float, left: float,
                       width: float, height: float, **kwargs) -> str:
        """矩形蒙版快捷方法"""
        verts = [[left, top], [left + width, top],
                 [left + width, top + height], [left, top + height]]
        return self.add_mask(name, verts, **kwargs)

    def add_mask_ellipse(self, name: str, center: List[float],
                          size: List[float], segments: int = 32, **kwargs) -> str:
        """椭圆蒙版快捷方法 (多边形近似)"""
        import math
        rx, ry = size[0] / 2, size[1] / 2
        cx, cy = center
        verts = []
        for i in range(segments):
            angle = 2 * math.pi * i / segments
            verts.append([cx + rx * math.cos(angle), cy + ry * math.sin(angle)])
        return self.add_mask(name, verts, **kwargs)

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
        """
        蒙版路径关键帧动画。

        Args:
            keyframes: [(time, [[x,y], ...]), ...] — 每帧的顶点列表
        """
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
```

- [ ] **Step 2: 验证 + Commit**

```bash
curl -s -X POST http://127.0.0.1:8089/ -d "
import sys; sys.path.insert(0, r'F:\\claude\\longterm\\AE2Claude')
from ae_bridge import AEBridge
ae = AEBridge()
layers = ae.list_layers()
if layers:
    ln = layers[0]['name']
    ae.begin_undo('Mask Test')
    ae.add_mask_rect(ln, 100, 100, 400, 300, feather=10)
    print('masks:', ae.list_masks(ln))
    ae.end_undo()
"
```

```bash
cd "F:/claude/longterm/AE2Claude" && git add ae_bridge.py && git commit -m "feat: add mask methods (create/modify/animate/remove)"
```

---

### Task 5: Marker

**Files:**
- Modify: `F:\claude\longterm\AE2Claude\ae_bridge.py`

- [ ] **Step 1: 添加 Marker 方法**

```python
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
```

- [ ] **Step 2: 验证 + Commit**

```bash
curl -s -X POST http://127.0.0.1:8089/ -d "
import sys; sys.path.insert(0, r'F:\\claude\\longterm\\AE2Claude')
from ae_bridge import AEBridge
ae = AEBridge()
ae.add_comp_marker(1.0, comment='Beat 1', label=2)
ae.add_comp_marker(2.5, comment='Beat 2', duration=0.5)
print(ae.list_comp_markers())
"
```

```bash
cd "F:/claude/longterm/AE2Claude" && git add ae_bridge.py && git commit -m "feat: add marker methods (comp + layer)"
```

---

### Task 6: 图层父子关系

**Files:**
- Modify: `F:\claude\longterm\AE2Claude\ae_bridge.py`

- [ ] **Step 1: 添加 Parent 方法**

```python
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
        """
        创建 Null 对象并可选批量绑定子图层。

        Args:
            name: Null 名称
            parent_to: 要绑定的子图层名列表
            position: Null 位置 [x, y]
        """
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
```

- [ ] **Step 2: 验证 + Commit**

```bash
curl -s -X POST http://127.0.0.1:8089/ -d "
import sys; sys.path.insert(0, r'F:\\claude\\longterm\\AE2Claude')
from ae_bridge import AEBridge
ae = AEBridge()
layers = ae.list_layers()
if len(layers) >= 2:
    ae.begin_undo('Parent Test')
    ae.create_null_control('Controller', parent_to=[layers[0]['name']], position=[540, 960])
    print('parent:', ae.get_parent(layers[0]['name']))
    ae.end_undo()
"
```

```bash
cd "F:/claude/longterm/AE2Claude" && git add ae_bridge.py && git commit -m "feat: add parenting methods (set/remove/null control)"
```

---

### Task 7: 混合模式 + Track Matte

**Files:**
- Modify: `F:\claude\longterm\AE2Claude\ae_bridge.py`

- [ ] **Step 1: 添加混合模式常量表和方法**

在 `TRANSFORM_PROPS` 字典之后（约 line 159），添加混合模式映射：

```python
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
```

然后在 AEBridge 类中添加方法：

```python
    # ── Blending Mode + Track Matte ────────────────────────

    def set_blending_mode(self, name: str, mode: str) -> str:
        """
        设置图层混合模式。

        Args:
            mode: "normal"/"multiply"/"screen"/"overlay"/"add"等 (见 BLEND_MODES)
        """
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
        """
        设置轨道蒙版。

        Args:
            name: 被蒙版的图层
            matte_layer: 蒙版图层 (必须在目标图层的正上方)
            matte_type: "alpha"/"alpha_inverted"/"luma"/"luma_inverted"
        """
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
```

- [ ] **Step 2: 验证 + Commit**

```bash
curl -s -X POST http://127.0.0.1:8089/ -d "
import sys; sys.path.insert(0, r'F:\\claude\\longterm\\AE2Claude')
from ae_bridge import AEBridge
ae = AEBridge()
layers = ae.list_layers()
if layers:
    ae.set_blending_mode(layers[0]['name'], 'multiply')
    print('mode:', ae.get_blending_mode(layers[0]['name']))
"
```

```bash
cd "F:/claude/longterm/AE2Claude" && git add ae_bridge.py && git commit -m "feat: add blending mode + track matte methods"
```

---

### Task 8: Text Animator

**Files:**
- Modify: `F:\claude\longterm\AE2Claude\ae_bridge.py`

- [ ] **Step 1: 添加 Text Animator 方法**

```python
    # ── Text Animator ──────────────────────────────────────

    def add_text_animator(self, name: str, properties: Dict[str, Any] = None) -> str:
        """
        为文本图层添加 Animator。

        Args:
            name: 文本图层名
            properties: 动画属性 {"position": [0,-20], "opacity": 0, "tracking": 10, ...}
                可用 key: position, anchor_point, scale, skew, rotation,
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
            f'var animators=tl.property("Source Text").property("ADBE Text Animators");'
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
        """
        配置文本 Animator 的 Range Selector。

        Args:
            animator_index: Animator 索引 (1-based)
            shape: "square"/"ramp_up"/"ramp_down"/"triangle"/"round"/"smooth"
        """
        shape_map = {
            "square": 1, "ramp_up": 2, "ramp_down": 3,
            "triangle": 4, "round": 5, "smooth": 6,
        }
        based_map = {"characters": 1, "characters_excluding_spaces": 2, "words": 3, "lines": 4}
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var animators=tl.property("Source Text").property("ADBE Text Animators");'
            f'var anim=animators.property({animator_index});'
            f'var sel=anim.property("ADBE Text Selectors").property(1);'
            f'sel.property("ADBE Text Percent Start").setValue({start});'
            f'sel.property("ADBE Text Percent End").setValue({end});'
            f'sel.property("ADBE Text Percent Offset").setValue({offset});'
            f'sel.property("ADBE Text Selector Mode").setValue({{"add":1,"subtract":2,"intersect":3,"min":4,"max":5,"difference":6}}.get("{mode}",1)||1);'
            f'sel.property("ADBE Text Range Shape").setValue({shape_map.get(shape, 1)});'
            f'sel.property("ADBE Text Range Type2").setValue({based_map.get(based_on, 1)});'
            f'"selector_set";'
        )
        return self.run_jsx(jsx)

    def animate_text_selector(self, name: str, animator_index: int = 1,
                               selector_index: int = 1,
                               keyframes: Dict[str, List[Tuple[float, float]]] = None) -> str:
        """
        动画化文本 Selector 属性。

        Args:
            keyframes: {"start": [(t, val), ...], "end": [...], "offset": [...]}
        """
        prop_map = {
            "start": "ADBE Text Percent Start",
            "end": "ADBE Text Percent End",
            "offset": "ADBE Text Percent Offset",
        }
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var animators=tl.property("Source Text").property("ADBE Text Animators");'
            f'var anim=animators.property({animator_index});'
            f'var sel=anim.property("ADBE Text Selectors").property({selector_index});'
        )
        if keyframes:
            for prop_key, kfs in keyframes.items():
                mn = prop_map.get(prop_key)
                if not mn:
                    continue
                jsx += f'var p=sel.property("{mn}");'
                for t, val in kfs:
                    jsx += f'p.setValueAtTime({t},{val});'
        jsx += '"animated";'
        return self.run_jsx(jsx)
```

- [ ] **Step 2: 验证 + Commit**

```bash
curl -s -X POST http://127.0.0.1:8089/ -d "
import sys; sys.path.insert(0, r'F:\\claude\\longterm\\AE2Claude')
from ae_bridge import AEBridge
ae = AEBridge()
# 需要一个已有文本图层的合成
layers = ae.list_layers()
text_layer = next((l for l in layers if 'text' in l.get('name','').lower()), layers[0] if layers else None)
if text_layer:
    ae.begin_undo('Animator Test')
    ae.add_text_animator(text_layer['name'], {'opacity': 0, 'position': [0, -20]})
    ae.animate_text_selector(text_layer['name'], keyframes={'offset': [(0, 0), (1, 100)]})
    ae.end_undo()
    print('text animator ok')
"
```

```bash
cd "F:/claude/longterm/AE2Claude" && git add ae_bridge.py && git commit -m "feat: add text animator methods"
```

---

### Task 9: Layer Styles

**Files:**
- Modify: `F:\claude\longterm\AE2Claude\ae_bridge.py`

- [ ] **Step 1: 添加 Layer Styles 常量和方法**

在 `TRACK_MATTE_TYPES` 之后添加映射，然后在 AEBridge 类中添加方法：

```python
LAYER_STYLE_MATCHNAMES = {
    "drop_shadow": "dropShadow/enabled",
    "inner_shadow": "innerShadow/enabled",
    "outer_glow": "outerGlow/enabled",
    "inner_glow": "innerGlow/enabled",
    "bevel_emboss": "bevelEmboss/enabled",
    "satin": "chromeFX/enabled",
    "color_overlay": "solidFill/enabled",
    "gradient_overlay": "gradientFill/enabled",
    "stroke": "frameFX/enabled",
}
```

```python
    # ── Layer Styles ───────────────────────────────────────

    def add_layer_style(self, name: str, style: str,
                         props: Dict[str, Any] = None) -> str:
        """
        为图层添加 Layer Style。

        Args:
            name: 图层名
            style: "drop_shadow"/"inner_shadow"/"outer_glow"/"inner_glow"/
                   "bevel_emboss"/"satin"/"color_overlay"/"gradient_overlay"/"stroke"
            props: 样式属性字典 (属性名用 AE 英文名)
        """
        # 启用 Layer Styles (如果未启用)
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'var ls=tl.property("Layer Styles");'
            f'if(!ls.canSetEnabled){{tl.property("Layer Styles").addProperty("ADBE Blend Options Group");}}'
        )
        style_names = {
            "drop_shadow": "ADBE Drop Shadow",
            "inner_shadow": "ADBE Inner Shadow",
            "outer_glow": "ADBE Outer Glow",
            "inner_glow": "ADBE Inner Glow",
            "bevel_emboss": "ADBE Bevel Emboss",
            "satin": "ADBE Satin",
            "color_overlay": "ADBE Color Overlay",
            "gradient_overlay": "ADBE Gradient Overlay",
            "stroke": "ADBE Stroke",
        }
        mn = style_names.get(style)
        if not mn:
            return f"ERR: unknown style '{style}'. Available: {list(style_names.keys())}"

        jsx += f'var sty=ls.addProperty("{mn}");'
        if props:
            for k, v in props.items():
                if isinstance(v, (list, tuple)):
                    jsx += f'try{{sty.property("{k}").setValue({json.dumps(v)});}}catch(e){{}}'
                else:
                    jsx += f'try{{sty.property("{k}").setValue({v});}}catch(e){{}}'
        jsx += f'sty.enabled=true;"style_added";'
        return self.run_jsx(jsx)

    def enable_layer_style(self, name: str, style_index: int,
                            enabled: bool = True) -> str:
        """启用/禁用指定 Layer Style"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var ls=c.layer("{_esc(name)}").property("Layer Styles");'
            f'ls.property({style_index}).enabled={"true" if enabled else "false"};"ok";'
        )
```

- [ ] **Step 2: 验证 + Commit**

```bash
curl -s -X POST http://127.0.0.1:8089/ -d "
import sys; sys.path.insert(0, r'F:\\claude\\longterm\\AE2Claude')
from ae_bridge import AEBridge
ae = AEBridge()
layers = ae.list_layers()
if layers:
    ae.begin_undo('Style Test')
    ae.add_layer_style(layers[0]['name'], 'drop_shadow')
    ae.end_undo()
    print('layer style ok')
"
```

```bash
cd "F:/claude/longterm/AE2Claude" && git add ae_bridge.py && git commit -m "feat: add layer style methods"
```

---

### Task 10: 3D + Camera + Light

**Files:**
- Modify: `F:\claude\longterm\AE2Claude\ae_bridge.py`

- [ ] **Step 1: 添加 3D/Camera/Light 方法**

```python
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
        """
        创建摄像机。

        Args:
            camera_type: "one_node" 或 "two_node"
            zoom: 缩放值
            position: [x, y, z]
        """
        jsx = (
            f'var c=app.project.activeItem;'
            f'var cam=c.layers.addCamera("{_esc(name)}",[c.width/2,c.height/2]);'
        )
        if camera_type == "one_node":
            jsx += 'cam.autoOrient=AutoOrientType.NO_AUTO_ORIENT;'
        if zoom is not None:
            jsx += f'cam.property("Camera Options").property("Zoom").setValue({zoom});'
        if position:
            jsx += f'cam.property("Transform").property("Position").setValue({json.dumps(position)});'
        jsx += 'cam.name;'
        return self.run_jsx(jsx)

    def create_light(self, name: str = "Light",
                      light_type: str = "point",
                      intensity: float = 100,
                      color: List[float] = None,
                      position: List[float] = None) -> str:
        """
        创建灯光。

        Args:
            light_type: "parallel"/"spot"/"point"/"ambient"
            intensity: 强度百分比
            color: [r, g, b] 0-1
            position: [x, y, z]
        """
        jsx = (
            f'var c=app.project.activeItem;'
            f'var lt=c.layers.addLight("{_esc(name)}",[c.width/2,c.height/2]);'
        )
        type_map = {"parallel": 1, "spot": 2, "point": 3, "ambient": 4}
        lt = type_map.get(light_type, 3)
        jsx += f'lt.property("Light Options").property("Light Type").setValue({lt});'
        jsx += f'lt.property("Light Options").property("Intensity").setValue({intensity});'
        if color:
            jsx += f'lt.property("Light Options").property("Color").setValue({json.dumps(color)});'
        if position:
            jsx += f'lt.property("Transform").property("Position").setValue({json.dumps(position)});'
        jsx += 'lt.name;'
        # 修正变量名冲突
        jsx = jsx.replace('var lt=c.layers', 'var lyr=c.layers').replace('lt.property', 'lyr.property').replace('lt.name', 'lyr.name')
        return self.run_jsx(jsx)

    def set_camera_property(self, name: str, prop: str, value: Any) -> str:
        """设置摄像机属性 (zoom/focus_distance/aperture/blur_level)"""
        prop_map = {
            "zoom": "Zoom",
            "focus_distance": "Focus Distance",
            "aperture": "Aperture",
            "blur_level": "Blur Level",
        }
        ae_prop = prop_map.get(prop, prop)
        v = json.dumps(value) if isinstance(value, (list, tuple)) else str(value)
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(name)}").property("Camera Options").property("{ae_prop}").setValue({v});"ok";'
        )

    def set_light_property(self, name: str, prop: str, value: Any) -> str:
        """设置灯光属性 (intensity/color/cone_angle/cone_feather/shadow_darkness/shadow_diffusion)"""
        prop_map = {
            "intensity": "Intensity",
            "color": "Color",
            "cone_angle": "Cone Angle",
            "cone_feather": "Cone Feather",
            "shadow_darkness": "Shadow Darkness",
            "shadow_diffusion": "Shadow Diffusion",
        }
        ae_prop = prop_map.get(prop, prop)
        v = json.dumps(value) if isinstance(value, (list, tuple)) else str(value)
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(name)}").property("Light Options").property("{ae_prop}").setValue({v});"ok";'
        )
```

- [ ] **Step 2: 验证 + Commit**

```bash
curl -s -X POST http://127.0.0.1:8089/ -d "
import sys; sys.path.insert(0, r'F:\\claude\\longterm\\AE2Claude')
from ae_bridge import AEBridge
ae = AEBridge()
ae.begin_undo('3D Test')
ae.create_camera('TestCam', zoom=1200, position=[540, 960, -1500])
ae.create_light('TestLight', light_type='point', intensity=80)
ae.end_undo()
print('3d ok')
"
```

```bash
cd "F:/claude/longterm/AE2Claude" && git add ae_bridge.py && git commit -m "feat: add 3D/camera/light methods"
```

---

### Task 11: Time Remap

**Files:**
- Modify: `F:\claude\longterm\AE2Claude\ae_bridge.py`

- [ ] **Step 1: 添加 Time Remap 方法**

```python
    # ── Time Remap ─────────────────────────────────────────

    def enable_time_remap(self, name: str) -> str:
        """启用图层时间重映射"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(name)}").timeRemapEnabled=true;"ok";'
        )

    def set_time_remap_keyframes(self, name: str,
                                  keyframes: List[Tuple[float, float]]) -> str:
        """
        设置时间重映射关键帧。

        Args:
            keyframes: [(comp_time, source_time), ...] — 在 comp_time 播放 source_time 的内容
        """
        jsx = (
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'if(!tl.timeRemapEnabled)tl.timeRemapEnabled=true;'
            f'var tr=tl.property("Time Remap");'
            # 先清除默认关键帧
            f'while(tr.numKeys>0)tr.removeKey(1);'
        )
        for comp_t, src_t in keyframes:
            jsx += f'tr.setValueAtTime({comp_t},{src_t});'
        jsx += '"ok";'
        return self.run_jsx(jsx)

    def freeze_frame(self, name: str, at_time: float) -> str:
        """冻结帧 — 在 at_time 的画面静止不动"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'if(!tl.timeRemapEnabled)tl.timeRemapEnabled=true;'
            f'var tr=tl.property("Time Remap");'
            f'while(tr.numKeys>0)tr.removeKey(1);'
            f'tr.setValueAtTime(tl.inPoint,{at_time});'
            f'tr.setValueAtTime(tl.outPoint,{at_time});'
            f'"frozen";'
        )

    def reverse_layer(self, name: str) -> str:
        """反转图层时间"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'var tl=c.layer("{_esc(name)}");'
            f'if(!tl.timeRemapEnabled)tl.timeRemapEnabled=true;'
            f'var tr=tl.property("Time Remap");'
            f'var dur=tl.source.duration;'
            f'while(tr.numKeys>0)tr.removeKey(1);'
            f'tr.setValueAtTime(tl.inPoint,dur);'
            f'tr.setValueAtTime(tl.outPoint,0);'
            f'"reversed";'
        )
```

- [ ] **Step 2: 验证 + Commit**

```bash
cd "F:/claude/longterm/AE2Claude" && git add ae_bridge.py && git commit -m "feat: add time remap methods (freeze/reverse)"
```

---

### Task 12: 渲染队列管理

**Files:**
- Modify: `F:\claude\longterm\AE2Claude\ae_bridge.py`

- [ ] **Step 1: 添加渲染队列方法**

```python
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
            timeout=600000  # 10分钟超时
        )

    def render_comp(self, comp_name: str = None, output_path: str = None,
                     template: str = None) -> str:
        """快捷方法：加入队列 + 设置输出 + 开始渲染"""
        self.add_to_render_queue(comp_name, output_path, template)
        return self.start_render()
```

- [ ] **Step 2: 验证 + Commit**

```bash
curl -s -X POST http://127.0.0.1:8089/ -d "
import sys; sys.path.insert(0, r'F:\\claude\\longterm\\AE2Claude')
from ae_bridge import AEBridge
ae = AEBridge()
print('render queue:', ae.render_queue_info())
"
```

```bash
cd "F:/claude/longterm/AE2Claude" && git add ae_bridge.py && git commit -m "feat: add render queue management methods"
```

---

### Task 13: 批量操作 + 选择 + 同步 Skill

**Files:**
- Modify: `F:\claude\longterm\AE2Claude\ae_bridge.py`
- Modify: `C:\Users\kensei\.claude\skills\ae2claude-bridge\scripts\ae_bridge.py` (复制)
- Modify: `C:\Users\kensei\.claude\skills\ae2claude-bridge\SKILL.md` (更新文档)

- [ ] **Step 1: 添加批量 / 选择方法**

```python
    # ── Batch / Selection ──────────────────────────────────

    def batch_jsx(self, scripts: List[str]) -> List[Any]:
        """
        批量执行多段 JSX（一次 HTTP 调用）。

        Args:
            scripts: JSX 代码列表

        Returns:
            结果列表
        """
        # 包装为数组返回
        wrapped = 'var _results=[];'
        for i, s in enumerate(scripts):
            wrapped += f'try{{_results.push({s})}}catch(e){{_results.push("ERR:"+e.toString())}}'
        wrapped += 'JSON.stringify(_results);'
        r = self.run_jsx(wrapped)
        try:
            return json.loads(r)
        except json.JSONDecodeError:
            return [r]

    def select_layers(self, names: List[str]) -> str:
        """选中指定图层"""
        jsx = 'var c=app.project.activeItem;'
        jsx += 'for(var i=1;i<=c.numLayers;i++)c.layer(i).selected=false;'
        for n in names:
            jsx += f'try{{c.layer("{_esc(n)}").selected=true;}}catch(e){{}}'
        jsx += '"ok";'
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
        """移动图层到指定索引"""
        return self.run_jsx(
            f'var c=app.project.activeItem;'
            f'c.layer("{_esc(name)}").moveTo({new_index});"ok";'
        )
```

- [ ] **Step 2: 更新 __version__**

在 ae_bridge.py 的 `__version__` 行（约 line 33）改为：

```python
__version__ = "2.0.0"
```

- [ ] **Step 3: 同步到 Skill 目录**

```bash
cp "F:/claude/longterm/AE2Claude/ae_bridge.py" "$HOME/.claude/skills/ae2claude-bridge/scripts/ae_bridge.py"
```

- [ ] **Step 4: 更新 SKILL.md**

在 SKILL.md 的 API 表格中追加新方法类别。具体内容参照 spec 文件中的方法签名列表。主要新增节：

```markdown
### 属性回读
| `ae.get_transform_value(name, prop, at_time)` | 读取 Transform 属性值 |
| `ae.get_keyframes(name, prop)` | 读取关键帧列表 |
| `ae.get_property_value(name, path, at_time)` | 读取任意属性 |
| `ae.get_effect_param(name, fx_mn, param_mn)` | 读取效果参数 |

### Shape 图层
| `ae.add_shape_layer(name)` | 创建 Shape 图层 |
| `ae.add_shape_rect(name, size, position, roundness)` | 添加矩形 |
| `ae.add_shape_ellipse(name, size, position)` | 添加椭圆 |
| `ae.add_shape_path(name, vertices, closed)` | 添加自定义路径 |
| `ae.add_shape_fill/stroke(name, color, ...)` | 填充/描边 |

### 预合成
| `ae.precompose(names, comp_name)` | 预合成 |
| `ae.list_precomps()` | 列出预合成 |

### 蒙版
| `ae.add_mask(name, vertices, mode, feather)` | 添加蒙版 |
| `ae.add_mask_rect/ellipse(...)` | 快捷蒙版 |
| `ae.animate_mask_path(name, idx, keyframes)` | 蒙版动画 |

### Marker
| `ae.add_comp_marker/layer_marker(...)` | 添加标记 |
| `ae.list_comp_markers/layer_markers(...)` | 列出标记 |

### 父子关系
| `ae.set_parent(child, parent)` | 设置父级 |
| `ae.create_null_control(name, parent_to)` | 创建 Null + 绑定 |

### 混合模式 + Track Matte
| `ae.set_blending_mode(name, mode)` | 设置混合模式 |
| `ae.set_track_matte(name, matte, type)` | 设置轨道蒙版 |

### Text Animator
| `ae.add_text_animator(name, properties)` | 添加文本动画器 |

### Layer Styles
| `ae.add_layer_style(name, style, props)` | 添加图层样式 |

### 3D / Camera / Light
| `ae.set_3d_layer(name)` | 启用 3D |
| `ae.create_camera/light(...)` | 创建摄像机/灯光 |

### Time Remap
| `ae.enable_time_remap(name)` | 启用时间重映射 |
| `ae.freeze_frame(name, at_time)` | 冻结帧 |
| `ae.reverse_layer(name)` | 反转时间 |

### 渲染队列
| `ae.render_queue_info()` | 渲染队列状态 |
| `ae.render_comp(name, path)` | 快捷渲染 |

### 批量 / 选择
| `ae.batch_jsx(scripts)` | 批量 JSX |
| `ae.select_layers(names)` | 选中图层 |
| `ae.get_selected_layers()` | 获取选中 |
| `ae.duplicate_layer(name)` | 复制图层 |
| `ae.reorder_layer(name, index)` | 移动图层 |
```

- [ ] **Step 5: Commit Phase 1 完成**

```bash
cd "F:/claude/longterm/AE2Claude"
git add ae_bridge.py
git commit -m "feat: batch/selection methods + bump to v2.0.0 — Phase 1 complete"
```

---

# Phase 2: C++ PyShiftCore 扩展

**前置条件**：
- VS 2022 Build Tools v143 安装
- vcpkg boost x64-windows-static
- pybind11 v2.13.6
- AE SDK 25.6 Headers 在 `F:\claude\ae workspace\AE_agent-harness\PyShiftAE重编译AE26\PyShiftAE\Headers\`

**源码根路径**：`F:\claude\ae workspace\AE_agent-harness\PyShiftAE重编译AE26\PyShiftAE\src\PyShiftAE\`

**编译命令**：
```bash
cd "F:/claude/ae workspace/AE_agent-harness/PyShiftAE重编译AE26/PyShiftAE/src/PyShiftAE/Win"
MSBuild PyShiftAE.vcxproj /p:Configuration=Release /p:Platform=x64
```

**部署命令**：
```bash
gsudo cmd /c rename "C:\Program Files\Adobe\Adobe After Effects (Beta)\Support Files\Plug-ins\AE2Claude.aex" "AE2Claude.aex.old"
cp "F:/claude/ae workspace/AE_agent-harness/PyShiftAE重编译AE26/PyShiftAE/src/PyShiftAE/Win/x64/Release/PyShiftAE.aex" "C:/Program Files/Adobe/Adobe After Effects (Beta)/Support Files/Plug-ins/AE2Claude.aex"
# 然后重启 AE
```

---

### Task 14: StreamSuites — CoreSDK 层

**Files:**
- Create: `src/CoreSDK/StreamSuites.h`
- Create: `src/CoreSDK/StreamSuites.cpp`

- [ ] **Step 1: 创建 StreamSuites.h**

```cpp
#pragma once
#include "Core.h"

// ── Layer Stream 获取 ──
Result<AEGP_StreamRefH> getNewLayerStream(
    Result<AEGP_LayerH> layerH, AEGP_LayerStream which_stream);

// ── Stream 值读取 ──
Result<AEGP_StreamValue2> getNewStreamValue(
    Result<AEGP_StreamRefH> streamH,
    AEGP_LTimeMode time_mode,
    A_Time timeT,
    A_Boolean pre_expression);

// ── Stream 值设置 ──
Result<void> setStreamValue(
    Result<AEGP_StreamRefH> streamH,
    AEGP_StreamValue2* valueP);

// ── Stream 元数据 ──
Result<AEGP_StreamType> getStreamType(Result<AEGP_StreamRefH> streamH);
Result<A_Boolean> canVaryOverTime(Result<AEGP_StreamRefH> streamH);
Result<A_Boolean> isStreamTimevarying(Result<AEGP_StreamRefH> streamH);

// ── 释放 ──
Result<void> disposeStream(Result<AEGP_StreamRefH> streamH);
Result<void> disposeStreamValue(AEGP_StreamValue2* valueP);

// ── Dynamic Stream (效果参数/蒙版属性等) ──
Result<int> getNumStreamsInGroup(Result<AEGP_StreamRefH> groupH);
Result<AEGP_StreamRefH> getNewStreamByIndex(
    Result<AEGP_StreamRefH> groupH, int index);
Result<AEGP_StreamRefH> getNewStreamByMatchname(
    Result<AEGP_StreamRefH> groupH, const std::string& matchname);
```

- [ ] **Step 2: 创建 StreamSuites.cpp**

```cpp
#include "StreamSuites.h"

Result<AEGP_StreamRefH> getNewLayerStream(
    Result<AEGP_LayerH> layerH, AEGP_LayerStream which_stream)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
    A_Err err = A_Err_NONE;
    AEGP_StreamRefH streamH = NULL;

    ERR(suites.StreamSuite6()->AEGP_GetNewLayerStream(
        *pluginIDPtr, layerH.value, which_stream, &streamH));

    Result<AEGP_StreamRefH> result;
    result.value = streamH;
    result.error = err;
    return result;
}

Result<AEGP_StreamValue2> getNewStreamValue(
    Result<AEGP_StreamRefH> streamH,
    AEGP_LTimeMode time_mode,
    A_Time timeT,
    A_Boolean pre_expression)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
    A_Err err = A_Err_NONE;
    AEGP_StreamValue2 val = {};

    ERR(suites.StreamSuite6()->AEGP_GetNewStreamValue(
        *pluginIDPtr, streamH.value, time_mode, &timeT, pre_expression, &val));

    Result<AEGP_StreamValue2> result;
    result.value = val;
    result.error = err;
    return result;
}

Result<void> setStreamValue(
    Result<AEGP_StreamRefH> streamH,
    AEGP_StreamValue2* valueP)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
    A_Err err = A_Err_NONE;

    ERR(suites.StreamSuite6()->AEGP_SetStreamValue(
        *pluginIDPtr, streamH.value, valueP));

    Result<void> result;
    result.error = err;
    return result;
}

Result<AEGP_StreamType> getStreamType(Result<AEGP_StreamRefH> streamH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    AEGP_StreamType type;

    ERR(suites.StreamSuite6()->AEGP_GetStreamType(streamH.value, &type));

    Result<AEGP_StreamType> result;
    result.value = type;
    result.error = err;
    return result;
}

Result<A_Boolean> canVaryOverTime(Result<AEGP_StreamRefH> streamH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    A_Boolean can_vary = FALSE;

    ERR(suites.StreamSuite6()->AEGP_CanVaryOverTime(streamH.value, &can_vary));

    Result<A_Boolean> result;
    result.value = can_vary;
    result.error = err;
    return result;
}

Result<A_Boolean> isStreamTimevarying(Result<AEGP_StreamRefH> streamH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    A_Boolean is_tv = FALSE;

    ERR(suites.StreamSuite6()->AEGP_IsStreamTimevarying(streamH.value, &is_tv));

    Result<A_Boolean> result;
    result.value = is_tv;
    result.error = err;
    return result;
}

Result<void> disposeStream(Result<AEGP_StreamRefH> streamH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;

    ERR(suites.StreamSuite6()->AEGP_DisposeStream(streamH.value));

    Result<void> result;
    result.error = err;
    return result;
}

Result<void> disposeStreamValue(AEGP_StreamValue2* valueP)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
    A_Err err = A_Err_NONE;

    ERR(suites.StreamSuite6()->AEGP_DisposeStreamValue(valueP));

    Result<void> result;
    result.error = err;
    return result;
}

// ── Dynamic Stream ──

Result<int> getNumStreamsInGroup(Result<AEGP_StreamRefH> groupH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    A_long num = 0;

    ERR(suites.DynamicStreamSuite4()->AEGP_GetNumStreamsInGroup(groupH.value, &num));

    Result<int> result;
    result.value = static_cast<int>(num);
    result.error = err;
    return result;
}

Result<AEGP_StreamRefH> getNewStreamByIndex(
    Result<AEGP_StreamRefH> groupH, int index)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
    A_Err err = A_Err_NONE;
    AEGP_StreamRefH streamH = NULL;

    ERR(suites.DynamicStreamSuite4()->AEGP_GetNewStreamRefByIndex(
        *pluginIDPtr, groupH.value, index, &streamH));

    Result<AEGP_StreamRefH> result;
    result.value = streamH;
    result.error = err;
    return result;
}

Result<AEGP_StreamRefH> getNewStreamByMatchname(
    Result<AEGP_StreamRefH> groupH, const std::string& matchname)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
    A_Err err = A_Err_NONE;
    AEGP_StreamRefH streamH = NULL;

    ERR(suites.DynamicStreamSuite4()->AEGP_GetNewStreamRefByMatchname(
        *pluginIDPtr, groupH.value, matchname.c_str(), &streamH));

    Result<AEGP_StreamRefH> result;
    result.value = streamH;
    result.error = err;
    return result;
}
```

- [ ] **Step 3: Commit**

```bash
cd "F:/claude/ae workspace/AE_agent-harness/PyShiftAE重编译AE26/PyShiftAE"
git add src/PyShiftAE/CoreSDK/StreamSuites.h src/PyShiftAE/CoreSDK/StreamSuites.cpp
git commit -m "feat: add StreamSuites CoreSDK wrapper (StreamSuite6 + DynamicStreamSuite4)"
```

---

### Task 15: KeyframeSuites — CoreSDK 层

**Files:**
- Create: `src/CoreSDK/KeyframeSuites.h`
- Create: `src/CoreSDK/KeyframeSuites.cpp`

- [ ] **Step 1: 创建 KeyframeSuites.h**

```cpp
#pragma once
#include "Core.h"

Result<int> getStreamNumKFs(Result<AEGP_StreamRefH> streamH);

Result<A_Time> getKeyframeTime(
    Result<AEGP_StreamRefH> streamH, int kf_index, AEGP_LTimeMode time_mode);

Result<int> insertKeyframe(
    Result<AEGP_StreamRefH> streamH, AEGP_LTimeMode time_mode, A_Time timeT);

Result<void> setKeyframeValue(
    Result<AEGP_StreamRefH> streamH, int kf_index, AEGP_StreamValue2* valueP);

Result<AEGP_StreamValue2> getKeyframeValue(
    Result<AEGP_StreamRefH> streamH, int kf_index);

Result<void> deleteKeyframe(Result<AEGP_StreamRefH> streamH, int kf_index);

Result<void> setKeyframeInterpolation(
    Result<AEGP_StreamRefH> streamH, int kf_index,
    AEGP_KeyframeInterpolationType in_type,
    AEGP_KeyframeInterpolationType out_type);

Result<void> setKeyframeTemporalEase(
    Result<AEGP_StreamRefH> streamH, int kf_index, A_long num_dims,
    AEGP_KeyframeEase* in_ease, AEGP_KeyframeEase* out_ease);

Result<void> setKeyframeSpatialTangents(
    Result<AEGP_StreamRefH> streamH, int kf_index,
    A_FloatPoint3* in_tangent, A_FloatPoint3* out_tangent);

Result<std::string> getExpression(Result<AEGP_StreamRefH> streamH);
Result<void> setExpression(Result<AEGP_StreamRefH> streamH, const std::string& expr);
```

- [ ] **Step 2: 创建 KeyframeSuites.cpp**

```cpp
#include "KeyframeSuites.h"

Result<int> getStreamNumKFs(Result<AEGP_StreamRefH> streamH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    A_long num = 0;

    ERR(suites.KeyframeSuite5()->AEGP_GetStreamNumKFs(streamH.value, &num));

    Result<int> result;
    result.value = static_cast<int>(num);
    result.error = err;
    return result;
}

Result<A_Time> getKeyframeTime(
    Result<AEGP_StreamRefH> streamH, int kf_index, AEGP_LTimeMode time_mode)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    A_Time timeT = {};

    ERR(suites.KeyframeSuite5()->AEGP_GetKeyframeTime(
        streamH.value, static_cast<AEGP_KeyframeIndex>(kf_index), time_mode, &timeT));

    Result<A_Time> result;
    result.value = timeT;
    result.error = err;
    return result;
}

Result<int> insertKeyframe(
    Result<AEGP_StreamRefH> streamH, AEGP_LTimeMode time_mode, A_Time timeT)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    AEGP_KeyframeIndex new_index = 0;

    ERR(suites.KeyframeSuite5()->AEGP_InsertKeyframe(
        streamH.value, time_mode, &timeT, &new_index));

    Result<int> result;
    result.value = static_cast<int>(new_index);
    result.error = err;
    return result;
}

Result<void> setKeyframeValue(
    Result<AEGP_StreamRefH> streamH, int kf_index, AEGP_StreamValue2* valueP)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;

    ERR(suites.KeyframeSuite5()->AEGP_SetKeyframeValue(
        streamH.value, static_cast<AEGP_KeyframeIndex>(kf_index), valueP));

    Result<void> result;
    result.error = err;
    return result;
}

Result<AEGP_StreamValue2> getKeyframeValue(
    Result<AEGP_StreamRefH> streamH, int kf_index)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;
    AEGP_StreamValue2 val = {};

    ERR(suites.KeyframeSuite5()->AEGP_GetNewKeyframeValue(
        *SuiteManager::GetInstance().GetPluginID(),
        streamH.value, static_cast<AEGP_KeyframeIndex>(kf_index), &val));

    Result<AEGP_StreamValue2> result;
    result.value = val;
    result.error = err;
    return result;
}

Result<void> deleteKeyframe(Result<AEGP_StreamRefH> streamH, int kf_index)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;

    ERR(suites.KeyframeSuite5()->AEGP_DeleteKeyframe(
        streamH.value, static_cast<AEGP_KeyframeIndex>(kf_index)));

    Result<void> result;
    result.error = err;
    return result;
}

Result<void> setKeyframeInterpolation(
    Result<AEGP_StreamRefH> streamH, int kf_index,
    AEGP_KeyframeInterpolationType in_type,
    AEGP_KeyframeInterpolationType out_type)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;

    ERR(suites.KeyframeSuite5()->AEGP_SetKeyframeInterpolation(
        streamH.value, static_cast<AEGP_KeyframeIndex>(kf_index), in_type, out_type));

    Result<void> result;
    result.error = err;
    return result;
}

Result<void> setKeyframeTemporalEase(
    Result<AEGP_StreamRefH> streamH, int kf_index, A_long num_dims,
    AEGP_KeyframeEase* in_ease, AEGP_KeyframeEase* out_ease)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;

    ERR(suites.KeyframeSuite5()->AEGP_SetKeyframeTemporalEase(
        streamH.value, static_cast<AEGP_KeyframeIndex>(kf_index),
        num_dims, in_ease, out_ease));

    Result<void> result;
    result.error = err;
    return result;
}

Result<void> setKeyframeSpatialTangents(
    Result<AEGP_StreamRefH> streamH, int kf_index,
    A_FloatPoint3* in_tangent, A_FloatPoint3* out_tangent)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;

    ERR(suites.KeyframeSuite5()->AEGP_SetKeyframeSpatialTangents(
        streamH.value, static_cast<AEGP_KeyframeIndex>(kf_index),
        in_tangent, out_tangent));

    Result<void> result;
    result.error = err;
    return result;
}

Result<std::string> getExpression(Result<AEGP_StreamRefH> streamH)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    AEGP_PluginID* pluginIDPtr = SuiteManager::GetInstance().GetPluginID();
    A_Err err = A_Err_NONE;
    AEGP_MemHandle expressionHZ = NULL;

    ERR(suites.StreamSuite6()->AEGP_GetExpressionString(
        *pluginIDPtr, streamH.value, &expressionHZ));

    std::string expr;
    if (expressionHZ) {
        A_UTF16Char* exprP = NULL;
        ERR(suites.MemorySuite1()->AEGP_LockMemHandle(expressionHZ, (void**)&exprP));
        if (exprP) {
            expr = convertUTF16ToUTF8(exprP);
        }
        ERR(suites.MemorySuite1()->AEGP_UnlockMemHandle(expressionHZ));
        ERR(suites.MemorySuite1()->AEGP_FreeMemHandle(expressionHZ));
    }

    Result<std::string> result;
    result.value = expr;
    result.error = err;
    return result;
}

Result<void> setExpression(Result<AEGP_StreamRefH> streamH, const std::string& expr)
{
    AEGP_SuiteHandler& suites = SuiteManager::GetInstance().GetSuiteHandler();
    A_Err err = A_Err_NONE;

    auto utf16 = convertUTF8ToUTF16(expr);
    ERR(suites.StreamSuite6()->AEGP_SetExpressionString(
        *SuiteManager::GetInstance().GetPluginID(),
        streamH.value, utf16.data()));

    Result<void> result;
    result.error = err;
    return result;
}
```

- [ ] **Step 3: Commit**

```bash
cd "F:/claude/ae workspace/AE_agent-harness/PyShiftAE重编译AE26/PyShiftAE"
git add src/PyShiftAE/CoreSDK/KeyframeSuites.h src/PyShiftAE/CoreSDK/KeyframeSuites.cpp
git commit -m "feat: add KeyframeSuites CoreSDK wrapper (KeyframeSuite5)"
```

---

### Task 16: CompItem/Layer PyCore pybind11 补全

**Files:**
- Modify: `src/CoreLib/ItemManager.h` — 新增 Layer/CompItem 方法声明
- Modify: `src/CoreLib/ItemManager.cpp` — 实现
- Modify: `src/CoreLib/PyCore.cpp` — pybind11 绑定

- [ ] **Step 1: Layer 类扩展 (ItemManager.h)**

在 `Layer` 类中 `std::shared_ptr<Item> getSource();` 之后添加：

```cpp
    // ── Phase 2 新增 ──
    std::shared_ptr<Layer> getParentLayer();
    void setParentLayer(std::shared_ptr<Layer> parent);
    void removeParent();
    int getLabel();
    void setLabel(int label);
    int getLayerID();
    bool isLayer3D();
    std::string getTransferMode();
    void setTransferMode(int mode);
    float getStretch();
```

- [ ] **Step 2: Layer 方法实现 (ItemManager.cpp)**

```cpp
std::shared_ptr<Layer> Layer::getParentLayer() {
    auto& msg = enqueueSyncTask(GetLayerParent, layerHandle_);
    msg->wait();
    Result<AEGP_LayerH> result = msg->getResult();
    if (result.error != A_Err_NONE || result.value == NULL) return nullptr;
    return std::make_shared<Layer>(result);
}

void Layer::setParentLayer(std::shared_ptr<Layer> parent) {
    AEGP_LayerH parentH = parent ? parent->getLayerHandle().value : NULL;
    auto& msg = enqueueSyncTask(SetLayerParent, layerHandle_, parentH);
    msg->wait();
}

void Layer::removeParent() {
    auto& msg = enqueueSyncTask(SetLayerParent, layerHandle_, (AEGP_LayerH)NULL);
    msg->wait();
}

int Layer::getLabel() {
    auto& msg = enqueueSyncTask(GetLayerLabel, layerHandle_);
    msg->wait();
    return static_cast<int>(msg->getResult().value);
}

void Layer::setLabel(int label) {
    auto& msg = enqueueSyncTask(SetLayerLabel, layerHandle_, static_cast<AEGP_LabelID>(label));
    msg->wait();
}

int Layer::getLayerID() {
    auto& msg = enqueueSyncTask(GetLayerID, layerHandle_);
    msg->wait();
    return msg->getResult().value;
}

bool Layer::isLayer3D() {
    auto& msg = enqueueSyncTask(IsLayer3D, layerHandle_);
    msg->wait();
    return msg->getResult().value != 0;
}
```

- [ ] **Step 3: PyCore.cpp Layer 绑定扩展**

在 `bindLayer()` 函数中 `.def("duplicate", &Layer::duplicate);` 之后添加：

```cpp
        .def_property("parent",
            &Layer::getParentLayer,
            &Layer::setParentLayer,
            py::return_value_policy::reference)
        .def("removeParent", &Layer::removeParent)
        .def_property("label", &Layer::getLabel, &Layer::setLabel)
        .def_property_readonly("layerID", &Layer::getLayerID)
        .def_property_readonly("is3D", &Layer::isLayer3D);
```

- [ ] **Step 4: CompItem 扩展 (同样三步)**

在 CompItem 类中添加声明（ItemManager.h）：

```cpp
    std::shared_ptr<Layer> addSolid(std::string name, float w, float h,
                                     float r, float g, float b, float a, float dur);
    std::shared_ptr<Layer> addNull(std::string name, float dur);
    std::shared_ptr<Layer> addCamera(std::string name, float x, float y);
    std::shared_ptr<Layer> addLight(std::string name, float x, float y);
    std::shared_ptr<Layer> addText(bool select = true);
    std::shared_ptr<Layer> addShape();
```

CompItem 方法实现（ItemManager.cpp）— 以 addNull 为例：

```cpp
std::shared_ptr<Layer> CompItem::addNull(std::string name, float dur) {
    auto& compMsg = enqueueSyncTask(getCompFromItem, itemHandle_);
    compMsg->wait();
    Result<AEGP_CompH> compH = compMsg->getResult();

    auto& msg = enqueueSyncTask(CreateNullInComp, name, compH, dur);
    msg->wait();
    Result<AEGP_LayerH> result = msg->getResult();
    if (result.error != A_Err_NONE || result.value == NULL)
        throw std::runtime_error("Failed to create null layer");
    return std::make_shared<Layer>(result);
}
```

PyCore.cpp CompItem 绑定：

```cpp
        .def("addSolid", &CompItem::addSolid,
            py::arg("name"), py::arg("w"), py::arg("h"),
            py::arg("r"), py::arg("g"), py::arg("b"), py::arg("a"), py::arg("dur"),
            py::return_value_policy::reference)
        .def("addNull", &CompItem::addNull,
            py::arg("name") = "Null", py::arg("dur") = 0,
            py::return_value_policy::reference)
        .def("addCamera", &CompItem::addCamera,
            py::arg("name"), py::arg("x"), py::arg("y"),
            py::return_value_policy::reference)
        .def("addLight", &CompItem::addLight,
            py::arg("name"), py::arg("x"), py::arg("y"),
            py::return_value_policy::reference)
        .def("addText", &CompItem::addText,
            py::arg("select") = true,
            py::return_value_policy::reference)
        .def("addShape", &CompItem::addShape,
            py::return_value_policy::reference);
```

- [ ] **Step 5: 更新 vcxproj**

在 `Win/PyShiftAE.vcxproj` 的 `<ItemGroup>` 中添加新文件引用：

```xml
<ClCompile Include="..\CoreSDK\StreamSuites.cpp" />
<ClCompile Include="..\CoreSDK\KeyframeSuites.cpp" />
<ClInclude Include="..\CoreSDK\StreamSuites.h" />
<ClInclude Include="..\CoreSDK\KeyframeSuites.h" />
```

- [ ] **Step 6: 编译测试**

```bash
cd "F:/claude/ae workspace/AE_agent-harness/PyShiftAE重编译AE26/PyShiftAE/src/PyShiftAE/Win"
MSBuild PyShiftAE.vcxproj /p:Configuration=Release /p:Platform=x64 2>&1 | tail -20
```
Expected: `Build succeeded. 0 Error(s)`

- [ ] **Step 7: Commit**

```bash
cd "F:/claude/ae workspace/AE_agent-harness/PyShiftAE重编译AE26/PyShiftAE"
git add -A
git commit -m "feat: Layer/CompItem pybind11 expansion (parent/label/3D/addSolid/addNull/addCamera/addLight/addText/addShape)"
```

---

### Task 17: 部署 + AE 集成验证

**Files:**
- Deploy: `AE2Claude.aex` to AE Plug-ins

- [ ] **Step 1: 备份 + 部署**

```bash
# 确认 AE 已关闭!
gsudo cmd /c rename "C:\Program Files\Adobe\Adobe After Effects (Beta)\Support Files\Plug-ins\AE2Claude.aex" "AE2Claude.aex.old"
cp "F:/claude/ae workspace/AE_agent-harness/PyShiftAE重编译AE26/PyShiftAE/src/PyShiftAE/Win/x64/Release/PyShiftAE.aex" "C:/Program Files/Adobe/Adobe After Effects (Beta)/Support Files/Plug-ins/AE2Claude.aex"
```

- [ ] **Step 2: 启动 AE + 验证**

启动 AE，等待插件加载，验证 HTTP 端点：

```bash
curl -s http://127.0.0.1:8089/ | jq .
```
Expected: `{"status": "ok", "engine": "PyShiftAE", ...}`

- [ ] **Step 3: 验证新 pybind11 绑定**

```bash
curl -s -X POST http://127.0.0.1:8089/ -d "
import PyShiftCore as psc
comp = psc.app.project.activeItem
if comp:
    print('comp:', comp.name)
    print('layers:', comp.numLayers)
    if comp.numLayers > 0:
        layer = comp.layers[0]
        print('layer:', layer.name)
        print('label:', layer.label)
        print('is3D:', layer.is3D)
        print('layerID:', layer.layerID)
        print('parent:', layer.parent)
"
```

- [ ] **Step 4: 复制部署文件到 longterm 目录**

```bash
cp "F:/claude/ae workspace/AE_agent-harness/PyShiftAE重编译AE26/PyShiftAE/src/PyShiftAE/Win/x64/Release/PyShiftAE.aex" "F:/claude/longterm/AE2Claude/AE2Claude.aex"
```

- [ ] **Step 5: Commit longterm**

```bash
cd "F:/claude/longterm/AE2Claude"
git add AE2Claude.aex
git commit -m "chore: deploy AE2Claude.aex with Phase 2 bindings"
```

---

### Task 18: 更新 HANDOFF + 清理

**Files:**
- Delete: `F:\claude\longterm\AE2Claude\HANDOFF.md`
- Modify: memory file (if needed)

- [ ] **Step 1: 删除 HANDOFF.md（任务完成）**

```bash
rm "F:/claude/longterm/AE2Claude/HANDOFF.md"
```

- [ ] **Step 2: Final commit**

```bash
cd "F:/claude/longterm/AE2Claude"
git add -A
git commit -m "chore: remove HANDOFF.md — Phase 1+2 expansion complete"
```

---

## 自检清单

- [x] Spec 中 13 个 ae_bridge.py 方法类别全部有对应 Task (Tasks 1-13)
- [x] C++ StreamSuites + KeyframeSuites 有完整代码 (Tasks 14-15)
- [x] PyCore pybind11 补全覆盖 Layer parent/label/3D/ID 和 CompItem addSolid/Null/Camera/Light/Text/Shape (Task 16)
- [x] vcxproj 更新包含在内 (Task 16 Step 5)
- [x] 部署和验证步骤完整 (Task 17)
- [x] 方法签名在所有 Task 间一致（get_transform_value/get_keyframes/BLEND_MODES/TRACK_MATTE_TYPES 等）
- [x] 每个 Task 有验证步骤
