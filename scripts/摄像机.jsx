(function () {
    var comp = app.project.activeItem;
    if (!comp || !(comp instanceof CompItem)) return;

    app.beginUndoGroup("Create 28mm Camera");

    var zoom = 702.42;
    var cam = comp.layers.addCamera("Camera 28mm", [comp.width / 2, comp.height / 2]);
    cam.autoOrient = AutoOrientType.NO_AUTO_ORIENT;
    cam.property("ADBE Camera Options Group").property("ADBE Camera Zoom").setValue(zoom);
    // Z = -zoom 保证 Z=0 的图层显示原始大小
    cam.property("ADBE Transform Group").property("ADBE Position").setValue([comp.width / 2, comp.height / 2, -zoom]);

    // 开启3D，不动位置
    for (var i = 1; i <= comp.numLayers; i++) {
        var layer = comp.layer(i);
        if (layer instanceof CameraLayer || layer instanceof LightLayer) continue;
        if (!layer.threeDLayer) {
            layer.threeDLayer = true;
        }
    }

    app.endUndoGroup();
})();