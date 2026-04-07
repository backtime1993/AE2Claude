/* Go To Head / Tail Frame (Ctrl/Cmd = Head) */
(function () {
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) { return; }

    var layers = comp.selectedLayers;
    if (layers.length === 0) { return; }

    app.beginUndoGroup("Go To Head/Tail Frame");

    var fd = comp.frameDuration;

    // __mode__: "default" = 跳到最晚尾帧(outPoint-1f), "ctrl" = 跳到最早首帧(inPoint)
    var mode = (typeof __mode__ !== "undefined") ? __mode__ : "default";
    var useHead = (mode === "ctrl");

    var target;
    if (useHead) {
        // 跳到“最早的 inPoint”
        target = Number.POSITIVE_INFINITY;
        for (var i = 0; i < layers.length; i++) {
            var t = layers[i].inPoint; // 首帧就是 inPoint
            if (t < target) target = t;
        }
        target = Math.max(0, Math.min(target, comp.duration - fd));
    } else {
        // 跳到“最晚的 outPoint - 1 帧”
        target = 0;
        for (var j = 0; j < layers.length; j++) {
            var t2 = layers[j].outPoint - fd;
            if (t2 > target) target = t2;
        }
        target = Math.max(0, Math.min(target, comp.duration - fd));
    }

    comp.time = target;

    app.endUndoGroup();
})();

