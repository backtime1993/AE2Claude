// 创建空对象并设置父级 (Ctrl/Alt 逻辑切换 – comp-center / layer-center)
var comp = app.project.activeItem;

if (comp && comp instanceof CompItem) {
    app.beginUndoGroup("创建空对象并设置父级 (Ctrl/Alt 逻辑)");

    var sel       = comp.selectedLayers;
    var kb        = ScriptUI.environment.keyboardState;
    var isCtrl    = kb.ctrlKey;   // Layer-center & trim
    var isAlt     = kb.altKey;    // Top & full-length
    var nullLayer = comp.layers.addNull();      // 先建出来
    var need3D    = false;

    // ---------- 判断是否要 3D ----------
    for (var i = 0; i < sel.length; i++) {
        if (sel[i] instanceof CameraLayer || sel[i].threeDLayer) { 
            need3D = true; 
            break; 
        }
    }
    nullLayer.threeDLayer = need3D;

    // ---------- 用第一个选中层的名称命名空对象（图层名 + 源名） ----------
    if (sel.length > 0) {
        var baseName = sel[0].name;          // 第一个选中层的图层名
        nullLayer.name = baseName;           // 改空对象图层名
        if (nullLayer.source) {
            nullLayer.source.name = baseName; // 改空对象的源名称（项目面板里的 Solid 名）
        }
    }

    // ---------- 计算中心点 ----------
    var centerPos, avgZ = 0, avgX = 0, avgY = 0;
    if (isCtrl && sel.length > 0) {                 // 仅 Ctrl 要用“图层中心”
        for (var j = 0; j < sel.length; j++) {
            var p = sel[j].transform.position.value;
            avgX += p[0]; 
            avgY += p[1]; 
            avgZ += (need3D ? p[2] : 0);
        }
        avgX /= sel.length; 
        avgY /= sel.length; 
        avgZ /= sel.length;
        centerPos = need3D ? [avgX, avgY, avgZ] : [avgX, avgY];
    } else {                                        // Alt 或无键：合成中心
        if (need3D && sel.length > 0) {
            for (var k = 0; k < sel.length; k++) 
                avgZ += sel[k].transform.position.value[2];
            avgZ /= sel.length;
            centerPos = [comp.width / 2, comp.height / 2, avgZ];
        } else {
            centerPos = [comp.width / 2, comp.height / 2];
        }
    }
    nullLayer.transform.position.setValue(centerPos);

    // ---------- 绑定父级 ----------
    for (var m = 0; m < sel.length; m++) 
        sel[m].parent = nullLayer;

    // ---------- 层级 & 时长 ----------
    if (isAlt) {                                    // Alt：顶置 + 全长
        nullLayer.moveToBeginning();
        nullLayer.inPoint  = 0;
        nullLayer.outPoint = comp.duration;
    } else {
        if (sel.length > 0) 
            nullLayer.moveBefore(sel[0]);

        var minIn  = sel.length ? sel[0].inPoint  : 0;
        var maxOut = sel.length ? sel[0].outPoint : comp.duration;

        for (var n = 1; n < sel.length; n++) {
            if (sel[n].inPoint  < minIn)  minIn  = sel[n].inPoint;
            if (sel[n].outPoint > maxOut) maxOut = sel[n].outPoint;
        }
        nullLayer.inPoint  = minIn;
        nullLayer.outPoint = maxOut;
    }

    // ---------- 标签 ----------
    nullLayer.label = 2;    // 黄色

    app.endUndoGroup();
} else {
    alert("请确保有一个合成处于活动状态。");
}
