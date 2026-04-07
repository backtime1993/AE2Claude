/* Flip Layer v1.0 */
(function flipLayer() {
    var comp = app.project.activeItem;
    if (!(comp && comp instanceof CompItem)) return;

    var sel = comp.selectedLayers;
    if (sel.length === 0) return;

    app.beginUndoGroup("Flip Layer");

    var kb = ScriptUI.environment.keyboardState;
    var isCtrl = kb.ctrlKey;

    for (var i = 0; i < sel.length; i++) {
        var layer = sel[i];
        if (!layer.property("ADBE Transform Group")) continue;

        var scale = layer.property("ADBE Transform Group").property("ADBE Scale");
        var val = scale.value;

        if (isCtrl) {
            // 上下翻转：Y轴取反
            val[1] = -val[1];
        } else {
            // 左右翻转：X轴取反
            val[0] = -val[0];
        }
        scale.setValue(val);
    }

    app.endUndoGroup();
})();
