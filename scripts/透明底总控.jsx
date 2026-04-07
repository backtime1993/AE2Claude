(function 批量选中图层透明度与裁剪时长() {
    var comp = app.project.activeItem;
    if (!(comp && comp instanceof CompItem)) {
        alert("兄弟，先选个合成再跑！");
        return;
    }
    var sel = comp.selectedLayers;
    if (sel.length === 0) {
        alert("兄弟，先选想要控制的图层！");
        return;
    }
    app.beginUndoGroup("选中图层不透明度 & 裁剪时长");

    // 1. 新建控制层并命名
    var ctrl = comp.layers.addNull();
    ctrl.name = "不透明度控制";
    var fx = ctrl.property("Effects").addProperty("ADBE Slider Control");
    fx.name = "不透明度滑块";

    // 2. 给选中图层挂表达式
    var expr = "thisComp.layer('不透明度控制').effect('不透明度滑块')('滑块')";
    for (var i = 0; i < sel.length; i++) {
        sel[i].property("Transform").property("Opacity").expression = expr;
    }

    // 3. 计算选中图层的时间范围，裁剪工作区
    var inPts = sel.map(function(L){ return L.inPoint; });
    var outPts = sel.map(function(L){ return L.outPoint; });
    var start = Math.min.apply(null, inPts);
    var end   = Math.max.apply(null, outPts);
    comp.workAreaStart    = start;
    comp.workAreaDuration = end - start;

    app.endUndoGroup();
})();
