// Match Comp Size to Selected Layer (No UI)
// 以第一个选中图层的尺寸修改当前合成尺寸（不改任何图层位置）
#target aftereffects

(function () {
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) {
        alert("请先进入一个合成。");
        return;
    }

    if (!comp.selectedLayers.length) {
        alert("请先选择一个图层。");
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
        alert("无法获取图层尺寸。");
        return;
    }

    // AE 限制
    if (w < 4 || h < 4 || w > 32000 || h > 32000) {
        alert("目标尺寸不合法: " + w + " x " + h);
        return;
    }

    app.beginUndoGroup("Match Comp to Selected Layer");

    comp.width  = w;
    comp.height = h;
    // 不改任何图层属性，Position 等保持不变

    app.endUndoGroup();
})();
