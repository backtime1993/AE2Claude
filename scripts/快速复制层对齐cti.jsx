// 复制所选图层到 CTI；若仅选中两个图层：复制第一个并放在第二个上方
(function () {
    var comp = app.project.activeItem;
    if (!(comp && comp instanceof CompItem)) { return; }

    var sel = comp.selectedLayers;
    if (!sel.length) { return; }

    app.beginUndoGroup("复制到CTI / 两层插入上方");

    var fd = comp.frameDuration;
    var T  = Math.round(comp.time / fd) * fd; // 帧对齐
    var alignFirstKeyframe = false;           // ← 需要把“首个关键帧”对齐到 CTI 时改为 true

    function earliestKeyTime(L){
        var t = Number.POSITIVE_INFINITY;
        function ck(p){ if (p && p.isTimeVarying && p.numKeys>0) t = Math.min(t, p.keyTime(1)); }
        var tr = L.property("ADBE Transform Group");
        if (tr){
            ck(tr.property("ADBE Anchor Point"));
            ck(tr.property("ADBE Position"));
            ck(tr.property("ADBE Position_0"));
            ck(tr.property("ADBE Position_1"));
            ck(tr.property("ADBE Position_2"));
            ck(tr.property("ADBE Scale"));
            ck(tr.property("ADBE Rotate X"));
            ck(tr.property("ADBE Rotate Y"));
            ck(tr.property("ADBE Rotate Z"));
            ck(tr.property("ADBE Opacity"));
        }
        return isFinite(t) ? t : L.inPoint;
    }
    function alignLayerToT(L){
        var ref = alignFirstKeyframe ? earliestKeyTime(L) : L.inPoint;
        var offset = T - ref;
        L.startTime += offset; // 平移整层（含关键帧）
    }

    if (sel.length === 2) {
        // 以时间轴堆叠顺序为准：sel[0]在上，sel[1]在下
        var src = sel[0], target = sel[1];
        var dup = src.duplicate();
        dup.moveBefore(target);     // 放到第二个图层上方
        alignLayerToT(dup);         // 仍按规则对齐到 CTI
    } else {
        // 常规：逐个复制并对齐到 CTI
        for (var i = 0; i < sel.length; i++){
            var d = sel[i].duplicate();
            alignLayerToT(d);
        }
    }

    app.endUndoGroup();
})();
