(function () {
    var comp = app.project.activeItem;
    if (!comp || !(comp instanceof CompItem)) return;

    app.beginUndoGroup("Create Camera + Null Rig");

    var zoom = 702.42;

    // ========== 1. 创建空对象（承载所有位置信息） ==========
    var nullLayer = comp.layers.addNull();
    nullLayer.threeDLayer = true;
    nullLayer.name = "Camera Control";
    if (nullLayer.source) nullLayer.source.name = "Camera Control";
    nullLayer.transform.position.setValue([comp.width / 2, comp.height / 2, -zoom]);
    nullLayer.label = 2;
    nullLayer.inPoint  = 0;
    nullLayer.outPoint = comp.duration;

    // ========== 2. 创建摄像机，归零后绑定 ==========
    var cam = comp.layers.addCamera("Camera 28mm", [comp.width / 2, comp.height / 2]);
    cam.autoOrient = AutoOrientType.NO_AUTO_ORIENT;
    cam.property("ADBE Camera Options Group").property("ADBE Camera Zoom").setValue(zoom);
    cam.parent = nullLayer;
    cam.property("ADBE Transform Group").property("ADBE Position").setValue([0, 0, 0]);

    nullLayer.moveBefore(cam);

    // ========== 3. 开启所有图层3D ==========
    for (var i = 1; i <= comp.numLayers; i++) {
        var layer = comp.layer(i);
        if (layer instanceof CameraLayer || layer instanceof LightLayer || layer.adjustmentLayer) continue;
        if (!layer.threeDLayer) layer.threeDLayer = true;
    }

    app.endUndoGroup();
})();
