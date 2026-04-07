(function() {
    var comp = app.project.activeItem;
    if (!(comp && comp instanceof CompItem)) return;
    var sel = comp.selectedLayers;
    if (sel.length === 0) return;

    app.beginUndoGroup("选中图层不透明度 & 裁剪时长");

    // 1. 新建控制层并命名
    var ctrl = comp.layers.addNull();
    ctrl.name = "不透明度控制";
    var fx = ctrl.property("Effects").addProperty("ADBE Slider Control");
    fx.name = "不透明度滑块";

    // 2. 给选中图层挂表达式
    var expr = "thisComp.layer('不透明度控制').effect('不透明度滑块')('滑块')";
    for (var i = 0; i < sel.length; i++) {
        sel[i].property("ADBE Transform Group").property("ADBE Opacity").expression = expr;
    }

    // 3. 计算选中图层的时间范围 (用 for 循环替代 Array.map)
    var start = Infinity, end = -Infinity;
    for (var i = 0; i < sel.length; i++) {
        if (sel[i].inPoint < start) start = sel[i].inPoint;
        if (sel[i].outPoint > end) end = sel[i].outPoint;
    }
    comp.workAreaStart = start;
    comp.workAreaDuration = end - start;

    app.endUndoGroup();
})();
