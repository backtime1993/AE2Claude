// 检查当前项目
if (app.project && app.project.activeItem && app.project.activeItem instanceof CompItem) {
    var comp = app.project.activeItem;

    app.beginUndoGroup("Add Yellow Solid");

    var selectedLayers = comp.selectedLayers;

    // 创建黄色纯色（#FFFF00）
    var yellowSolid = comp.layers.addSolid([1, 1, 0], "Yellow Solid", comp.width, comp.height, comp.pixelAspect);

    if (selectedLayers.length > 0) {
        var ctrlPressed = ScriptUI.environment.keyboardState.ctrlKey;
        var altPressed = ScriptUI.environment.keyboardState.altKey;

        if (ctrlPressed) {
            yellowSolid.moveToEnd(); // 底部
        } else if (altPressed) {
            yellowSolid.moveToBeginning(); // 顶部
            yellowSolid.inPoint  = selectedLayers[0].inPoint;
            yellowSolid.outPoint = selectedLayers[0].outPoint;
        } else {
            yellowSolid.moveBefore(selectedLayers[0]); // 置于所选图层上方
            yellowSolid.inPoint  = selectedLayers[0].inPoint;
            yellowSolid.outPoint = selectedLayers[0].outPoint;
        }
    }

    app.endUndoGroup();
}
