// 检查当前项目
if (app.project && app.project.activeItem && app.project.activeItem instanceof CompItem) {
    var comp = app.project.activeItem;
    
    // 开始撤销组
    app.beginUndoGroup("Add Black Solid");

    // 获取选中的图层
    var selectedLayers = comp.selectedLayers;

    // 创建黑色纯色
    var blackSolid = comp.layers.addSolid([0, 0, 0], "Black Solid", comp.width, comp.height, comp.pixelAspect);

    if (selectedLayers.length > 0) {
        // __mode__: "default" = 选中层上方+修剪, "ctrl" = 最下方, "alt" = 最上方+修剪
        var mode = (typeof __mode__ !== "undefined") ? __mode__ : "default";
        var ctrlPressed = (mode === "ctrl");
        var altPressed = (mode === "alt");

        if (ctrlPressed) {
            // 将黑色纯色移至所有图层最下方
            blackSolid.moveToEnd();
        } else if (altPressed) {
            // 将黑色纯色移至所有图层最上方
            blackSolid.moveToBeginning();

            // 修剪时间长度对齐到所选图层
            blackSolid.inPoint = selectedLayers[0].inPoint;
            blackSolid.outPoint = selectedLayers[0].outPoint;
        } else {
            // 默认放置在所选图层上方
            blackSolid.moveBefore(selectedLayers[0]);

            // 修剪时间长度对齐到所选图层
            blackSolid.inPoint = selectedLayers[0].inPoint;
            blackSolid.outPoint = selectedLayers[0].outPoint;
        }
    }

    // 结束撤销组
    app.endUndoGroup();
}

