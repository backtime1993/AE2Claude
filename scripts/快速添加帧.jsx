(function addVisibleKeyframes() {
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) return;
    if (comp.selectedLayers.length === 0) return;

    app.beginUndoGroup("插入当前显示属性关键帧");

    var curTime = comp.time;

    for (var i = 0; i < comp.selectedLayers.length; i++) {
        var layer = comp.selectedLayers[i];

        function processProperties(group) {
            for (var j = 1; j <= group.numProperties; j++) {
                var prop = group.property(j);

                if (prop.propertyType === PropertyType.INDEXED_GROUP || prop.propertyType === PropertyType.NAMED_GROUP) {
                    processProperties(prop);
                } else if (prop.propertyType === PropertyType.PROPERTY && prop.canVaryOverTime && prop.isTimeVarying) {
                    try {
                        prop.setValueAtTime(curTime, prop.value);
                    } catch (e) {}
                }
            }
        }

        processProperties(layer);
    }

    app.endUndoGroup();
})();
