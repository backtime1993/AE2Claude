(function() {
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) return;

    var sel = comp.selectedLayers;
    if (sel.length === 0) return;

    app.beginUndoGroup("匹配父合成分辨率并回正");

    var parentW = comp.width;
    var parentH = comp.height;

    for (var i = 0; i < sel.length; i++) {
        var layer = sel[i];
        if (!layer.source) continue;

        var t = layer.property("ADBE Transform Group");
        if (layer.source instanceof CompItem) {
            layer.source.width = parentW;
            layer.source.height = parentH;
            t.property("ADBE Scale").setValue([100, 100]);
            t.property("ADBE Anchor Point").setValue([parentW / 2, parentH / 2]);
            t.property("ADBE Position").setValue([parentW / 2, parentH / 2]);
        } else {
            var srcW = layer.source.width;
            var srcH = layer.source.height;
            t.property("ADBE Scale").setValue([(parentW / srcW) * 100, (parentH / srcH) * 100]);
            t.property("ADBE Anchor Point").setValue([srcW / 2, srcH / 2]);
            t.property("ADBE Position").setValue([parentW / 2, parentH / 2]);
        }
    }

    app.endUndoGroup();
})();
