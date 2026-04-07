// Trim Each Layer to Keyframes.jsx
(function trimToKeys() {
    function getKeyBounds(layer) {
        var earliest =  9e9, latest = -9e9;

        function scan(propGroup) {
            for (var i = 1; i <= propGroup.numProperties; i++) {
                var p = propGroup.property(i);
                if (p.numKeys && p.numKeys > 0) {
                    earliest = Math.min(earliest, p.keyTime(1));
                    latest   = Math.max(latest,   p.keyTime(p.numKeys));
                }
                // 递归扫描子属性
                if (p.propertyType === PropertyType.INDEXED_GROUP || p.propertyType === PropertyType.NAMED_GROUP) {
                    scan(p);
                }
            }
        }
        scan(layer);
        return (latest >= earliest) ? [earliest, latest] : null;
    }

    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) { alert("先打开合成哈～"); return; }

    var sel = comp.selectedLayers;
    if (sel.length === 0) { alert("先选几个图层再说"); return; }

    app.beginUndoGroup("Trim to Keyframes");
    for (var i = 0; i < sel.length; i++) {
        var bounds = getKeyBounds(sel[i]);
        if (bounds) {
            sel[i].inPoint  = bounds[0];
            sel[i].outPoint = bounds[1];
        }
    }
    app.endUndoGroup();
})();
