/* Go To Head / Tail Frame (Ctrl/Cmd = Head) */
(function () {
    app.beginUndoGroup("Go To Head/Tail Frame");

    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) { alert("兄弟，先点进一个合成~"); return; }

    var layers = comp.selectedLayers;
    if (layers.length === 0) { alert("先选中至少一个图层哈"); return; }

    var fd = comp.frameDuration;

    // 读修饰键（Windows: Ctrl；Mac: Cmd）
    var useHead = false;
    try {
        var ks = ScriptUI.environment.keyboardState;
        useHead = ks.ctrlKey || ks.metaKey;
    } catch (e) {
        // 某些环境下可能没有 ScriptUI（极少数情况），那就默认尾帧
        useHead = false;
    }

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

