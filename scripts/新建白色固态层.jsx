// 检查当前项目
if (app.project && app.project.activeItem && app.project.activeItem instanceof CompItem) {
    var comp = app.project.activeItem;
    
    // 开始撤销组
    app.beginUndoGroup("Add White Solid");

    // 获取选中的图层
    var selectedLayers = comp.selectedLayers;

    // 创建白色纯色
    var whiteSolid = comp.layers.addSolid([1, 1, 1], "White Solid", comp.width, comp.height, comp.pixelAspect);

    if (selectedLayers.length > 0) {
        var ctrlPressed = ScriptUI.environment.keyboardState.ctrlKey;
        var altPressed = ScriptUI.environment.keyboardState.altKey;

        if (ctrlPressed) {
            // 将白色纯色移至所有图层最下方
            whiteSolid.moveToEnd();
        } else if (altPressed) {
            // 将白色纯色移至所有图层最上方
            whiteSolid.moveToBeginning();

            // 修剪时间长度对齐到所选图层
            whiteSolid.inPoint = selectedLayers[0].inPoint;
            whiteSolid.outPoint = selectedLayers[0].outPoint;
        } else {
            // 默认放置在所选图层上方
            whiteSolid.moveBefore(selectedLayers[0]);

            // 修剪时间长度对齐到所选图层
            whiteSolid.inPoint = selectedLayers[0].inPoint;
            whiteSolid.outPoint = selectedLayers[0].outPoint;
        }
    }

    // 结束撤销组
    app.endUndoGroup();
} else {
    alert("请先打开一个合成。");
}
