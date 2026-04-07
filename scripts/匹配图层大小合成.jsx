// Match Comp Size to Selected Layer (No UI)
// 以第一个选中图层的尺寸修改当前合成尺寸（不改任何图层位置）
#target aftereffects

(function () {
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) {
        return;
    }

    if (!comp.selectedLayers.length) {
        return;
    }

    var layer = comp.selectedLayers[0];
    var w, h;

    try {
        // 文本 / 形状：用内容尺寸
        if (layer.property("Source Text") || layer.matchName === "ADBE Vector Layer") {
            var r = layer.sourceRectAtTime(comp.time, false);
            w = Math.round(r.width);
            h = Math.round(r.height);
        } else if (layer.source) {
            // 普通素材 / 预合成 / 纯色
            w = Math.round(layer.source.width);
            h = Math.round(layer.source.height);
        }
    } catch (e) {}

    if (!w || !h) {
        return;
    }

    // AE 限制
    if (w < 4 || h < 4 || w > 32000 || h > 32000) {
        return;
    }

    app.beginUndoGroup("Match Comp to Selected Layer");

    comp.width  = w;
    comp.height = h;
    // 不改任何图层属性，Position 等保持不变

    app.endUndoGroup();
})();
