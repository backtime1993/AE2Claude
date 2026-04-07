(function() {
    var comp = app.project.activeItem;

    // 1. 基本检查
    if (!comp || comp.selectedLayers.length === 0) {
        alert("请先选择一个图层。");
        return;
    }

    // 2. 数量检查 (原生限制：保留属性只能选1个层)
    if (comp.selectedLayers.length > 1) {
        alert("【保留属性】模式仅支持选中 1 个图层。\n(这是 AE 自身的机制限制)");
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
        alert("操作失败：\n该图层类型不支持“保留属性”预合成。\n\n(文本层、形状层、空对象必须移动所有属性)");
    }

    app.endUndoGroup();
})();