var comp = app.project.activeItem;

// 确保合成存在
if (comp && comp instanceof CompItem) {
    app.beginUndoGroup("智能取消父级");

    var selectedLayers = comp.selectedLayers;

    // 遍历每个选中的图层
    for (var i = 0; i < selectedLayers.length; i++) {
        var curLayer = selectedLayers[i];

        // 判断是否为空对象 (nullLayer 属性)
        if (curLayer.nullLayer) {
            // 如果是空对象：遍历全合成，找到所有以该空对象为父级的图层并断开
            for (var j = 1; j <= comp.numLayers; j++) {
                var targetLayer = comp.layer(j);
                if (targetLayer.parent == curLayer) {
                    targetLayer.parent = null;
                }
            }
        } else {
            // 如果是普通图层：保留原功能，取消自身的父级
            curLayer.parent = null; 
        }
    }

    app.endUndoGroup();
} else {
    alert("请确保有一个合成处于活动状态。");
}