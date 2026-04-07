(function() {
    var comp = app.project.activeItem;
    if (!comp || !(comp instanceof CompItem)) {
        alert("请先打开一个合成");
        return;
    }

    var selectedLayers = comp.selectedLayers;
    if (selectedLayers.length < 2) {
        alert("请至少选择两个图层：\n1. 先选接收蒙版的图层\n2. 再选来源图层");
        return;
    }

    app.beginUndoGroup("Copy Masks and Set Subtract");

    // 第一个选择的图层作为接收层
    var targetLayer = selectedLayers[0];

    // 遍历后续选择的图层作为来源
    for (var i = 1; i < selectedLayers.length; i++) {
        var sourceLayer = selectedLayers[i];
        var maskGroup = sourceLayer.property("ADBE Mask Parade");

        // 如果来源层有蒙版
        if (maskGroup && maskGroup.numProperties > 0) {
            for (var m = 1; m <= maskGroup.numProperties; m++) {
                var sourceMask = maskGroup.property(m);
                var sourceMaskShape = sourceMask.property("ADBE Mask Shape").value;

                // 在目标层创建新蒙版
                var newMask = targetLayer.property("ADBE Mask Parade").addProperty("ADBE Mask Atom");
                
                // 复制路径形状
                newMask.property("ADBE Mask Shape").setValue(sourceMaskShape);
                
                // 设置为相减模式
                newMask.maskMode = MaskMode.SUBTRACT;
                
                // 可选：复制蒙版羽化 (如果需要复制羽化请取消下面注释)
                // newMask.property("ADBE Mask Feather").setValue(sourceMask.property("ADBE Mask Feather").value);
            }
        }
    }

    app.endUndoGroup();
})();