# AE Effect MatchName 参考表

> 从 AE Beta 26.1 中文版实测获取。matchName 在所有语言 AE 中通用。

## Gaussian Blur (高斯模糊)

| matchName | 中文 display name | 英文 display name | 类型 |
|-----------|-------------------|-------------------|------|
| `ADBE Gaussian Blur 2` | 高斯模糊 | Gaussian Blur | 效果 |
| `ADBE Gaussian Blur 2-0001` | 模糊度 | Blurriness | float |
| `ADBE Gaussian Blur 2-0002` | 模糊方向 | Blur Dimensions | enum |
| `ADBE Gaussian Blur 2-0003` | 重复边缘像素 | Repeat Edge Pixels | bool (0/1) |

## Drop Shadow (投影)

| matchName | 中文 display name | 英文 display name | 类型 |
|-----------|-------------------|-------------------|------|
| `ADBE Drop Shadow` | 投影 | Drop Shadow | 效果 |
| `ADBE Drop Shadow-0001` | 阴影颜色 | Shadow Color | color |
| `ADBE Drop Shadow-0002` | 不透明度 | Opacity | float 0-255 |
| `ADBE Drop Shadow-0003` | 方向 | Direction | float 0-360 |
| `ADBE Drop Shadow-0004` | 距离 | Distance | float |
| `ADBE Drop Shadow-0005` | 柔和度 | Softness | float |

## Transform (变换)

| matchName | 属性 | 缓动维度 | spatial |
|-----------|------|---------|---------|
| `ADBE Anchor Point` | 锚点 / Anchor Point | 2 (2D) / 3 (3D layer) | true |
| `ADBE Position` | 位置 / Position | **1** (spatial 属性!) | true |
| `ADBE Scale` | 缩放 / Scale | **3** (始终 3D!) | false |
| `ADBE Rotate Z` | 旋转 / Rotation | 1 | false |
| `ADBE Opacity` | 不透明度 / Opacity | 1 | false |

### 缓动维度说明

`setTemporalEaseAtKey(key, [inEase], [outEase])` 中数组长度必须匹配属性的维度:

- **Position**: spatial=true, 值虽然是 [x,y] 或 [x,y,z], 但缓动只需 **1 个** KeyframeEase
- **Scale**: 值是 [x,y,z] (即使 2D comp 也是 3D), 缓动需要 **3 个** KeyframeEase
- **Opacity/Rotation**: 1D, 缓动需要 **1 个** KeyframeEase

```javascript
// ✅ Position (spatial) - 1 element
pos.setTemporalEaseAtKey(k, [eI], [eO]);

// ✅ Scale (3D non-spatial) - 3 elements
scl.setTemporalEaseAtKey(k, [eI, eI, eI], [eO, eO, eO]);

// ✅ Opacity (1D) - 1 element
opa.setTemporalEaseAtKey(k, [eI], [eO]);
```

## Fill (填充)

| matchName | 属性 | 类型 |
|-----------|------|------|
| `ADBE Fill` | 填充 | 效果 |
| `ADBE Fill-0003` | 颜色 / Color | color [r,g,b] |
| `ADBE Fill-0007` | 不透明度 / Opacity | float |

## Glow (辉光)

| matchName | 属性 | 类型 |
|-----------|------|------|
| `ADBE Glo2` | 辉光 | 效果 |
| `ADBE Glo2-0001` | 阈值 / Threshold | float |
| `ADBE Glo2-0002` | 半径 / Radius | float |
| `ADBE Glo2-0003` | 强度 / Intensity | float |

## 枚举新效果的 matchName

在 AE 中通过 CDP Bridge 运行:

```javascript
// 枚举效果的所有属性 matchName
var tl = app.project.activeItem.layer("LayerName");
var fx = tl.property("Effects");
var out = [];
for (var i = 1; i <= fx.numProperties; i++) {
    var e = fx.property(i);
    var props = [];
    for (var j = 1; j <= e.numProperties; j++) {
        var p = e.property(j);
        props.push({name: p.name, matchName: p.matchName});
    }
    out.push({name: e.name, matchName: e.matchName, props: props});
}
JSON.stringify(out);
```

用 AEBridge:
```python
ae.run_jsx('var tl=app.project.activeItem.layer("LayerName");'
           'var fx=tl.property("Effects");var out=[];'
           'for(var i=1;i<=fx.numProperties;i++){'
           'var e=fx.property(i);var props=[];'
           'for(var j=1;j<=e.numProperties;j++){'
           'var p=e.property(j);props.push({name:p.name,matchName:p.matchName});}'
           'out.push({name:e.name,matchName:e.matchName,props:props});}'
           'JSON.stringify(out);')
```
