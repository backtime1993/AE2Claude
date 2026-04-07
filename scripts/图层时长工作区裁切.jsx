/**  Set Comp Duration From Selected Layer(s)
 *   v1.0 – 2025-05-23
 *   作者：ChatGPT
 */

(function () {
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) {
        return;
    }

    if (comp.selectedLayers.length === 0) {
        return;
    }

    app.beginUndoGroup("Set Comp Duration From Layers");

    var minIn  = Number.MAX_VALUE;
    var maxOut = 0;

    for (var i = 0; i < comp.selectedLayers.length; i++) {
        var l = comp.selectedLayers[i];
        minIn  = Math.min(minIn,  l.inPoint);
        maxOut = Math.max(maxOut, l.outPoint);
    }

    comp.duration = maxOut - minIn;

    if (minIn > 0) {
        comp.time = 0;
        comp.displayStartTime += minIn;
        for (var j = 1; j <= comp.numLayers; j++) {
            comp.layer(j).startTime -= minIn;
        }
    }

    app.endUndoGroup();
})();
