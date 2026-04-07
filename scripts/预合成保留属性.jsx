(function() {
    var comp = app.project.activeItem;

    // 1. 基本检查
    if (!comp || comp.selectedLayers.length === 0) {
        return;
    }

    // 2. 数量检查 (原生限制：保留属性只能选1个层)
    if (comp.selectedLayers.length > 1) {
        return;
    }

    app.beginUndoGroup("快速预合成(保留属性)");

    try {
        var layer = comp.selectedLayers[0];
        var indices = [layer.index]; // 获取图层索引数组
        var newName = layer.name + " Comp";

        // 3. 核心命令：参数 false 代表“不移动属性”
        // precompose(图层索引数组, 新名字, 是否移动属性)
        comp.layers.precompose(indices, newName, false);
        
    } catch (err) {
        // 4. 捕捉常见错误 (如对文本/形状层操作)
    }

    app.endUndoGroup();
})();