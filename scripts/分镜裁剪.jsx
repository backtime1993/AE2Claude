(function outToNextIn() {
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) { return; }

    app.beginUndoGroup("出点接下一层入点");

    // 目标层：有选层就用选层，否则用全部
    var targets = comp.selectedLayers.length ? comp.selectedLayers : (function () {
        var a = []; for (var i = 1; i <= comp.layers.length; i++) a.push(comp.layers[i]); return a;
    })();

    // 跳过锁定层
    var layers = [];
    for (var i = 0; i < targets.length; i++) if (!targets[i].locked) layers.push(targets[i]);
    if (layers.length < 2) { app.endUndoGroup(); return; }

    // 按“入点时间”排序，入点相同则按图层索引
    layers.sort(function (a, b) {
        if (a.inPoint === b.inPoint) return a.index - b.index;
        return a.inPoint - b.inPoint;
    });

    var fd = comp.frameDuration;

    // 逐个把当前层的出点对齐到下一层的入点
    for (var i = 0; i < layers.length - 1; i++) {
        var L = layers[i];
        var nextIn = layers[i + 1].inPoint;

        // 确保出点始终晚于入点（避免零/负时长）
        var newOut = nextIn <= L.inPoint ? (L.inPoint + fd) : nextIn;
        L.outPoint = newOut;
    }

    // 最后一层怎么处理：默认不改。想延长到合成末尾就把下行改为 true
    var extendLastToCompEnd = false;
    if (extendLastToCompEnd) {
        var last = layers[layers.length - 1];
        last.outPoint = Math.max(last.outPoint, comp.duration);
    }

    // 方便起见，最后把处理过的层选中
    for (var j = 1; j <= comp.layers.length; j++) comp.layers[j].selected = false;
    for (var k = 0; k < layers.length; k++) layers[k].selected = true;

    app.endUndoGroup();
})();
