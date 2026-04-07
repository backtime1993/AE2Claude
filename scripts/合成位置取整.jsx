(function () {
    var comp = app.project.activeItem;
    if (!(comp && comp instanceof CompItem)) {
        alert("请先进入一个合成。");
        return;
    }

    var sel = comp.selectedLayers;
    if (!sel || sel.length === 0) {
        alert("请先选中至少一个图层再运行脚本。");
        return;
    }

    app.beginUndoGroup("Round Pos & Anchor");

    for (var i = 0; i < sel.length; i++) {
        var lyr = sel[i];
        var tr  = lyr.property("ADBE Transform Group");
        if (!tr) continue;

        var pos = tr.property("ADBE Position");
        var anc = tr.property("ADBE Anchor Point");

        roundProp(pos);
        roundProp(anc);
    }

    app.endUndoGroup();

    function roundProp(prop) {
        if (!prop) return;

        if (prop.numKeys === 0) {
            var v = prop.value;
            if (v.length !== undefined) {
                for (var j = 0; j < v.length; j++) {
                    v[j] = Math.round(v[j]);
                }
            } else {
                v = Math.round(v);
            }
            prop.setValue(v);
        } else {
            for (var k = 1; k <= prop.numKeys; k++) {
                var kv = prop.keyValue(k);
                if (kv.length !== undefined) {
                    for (var m = 0; m < kv.length; m++) {
                        kv[m] = Math.round(kv[m]);
                    }
                } else {
                    kv = Math.round(kv);
                }
                prop.setValueAtKey(k, kv);
            }
        }
    }
})();
