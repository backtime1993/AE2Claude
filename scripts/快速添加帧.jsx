(function addVisibleKeyframes() {
    app.beginUndoGroup("插入当前显示属性关键帧");

    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) {
        alert("兄弟，先点进合成再运行！");
        return;
    }

    var curTime = comp.time;

    // 遍历所有选中的图层
    for (var i = 0; i < comp.selectedLayers.length; i++) {
        var layer = comp.selectedLayers[i];

        // 遍历所有属性组（比如Transform、Effects）
        function processProperties(group) {
            for (var j = 1; j <= group.numProperties; j++) {
                var prop = group.property(j);

                if (prop instanceof PropertyGroup) {
                    // 如果是属性组，递归进去
                    processProperties(prop);
                } else if (prop.isModified && prop.isTimeVarying) {
                    try {
                        prop.setValueAtTime(curTime, prop.value);
                    } catch (e) {
                        // 忽略不能设关键帧的属性
                    }
                }
            }
        }

        processProperties(layer);
    }

    app.endUndoGroup();
})();
