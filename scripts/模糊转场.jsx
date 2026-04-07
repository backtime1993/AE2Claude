(function () {
    app.beginUndoGroup("调整层·镜头模糊 40 帧（含入/出点右移5f）");

    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) { app.endUndoGroup(); return; }
    if (comp.selectedLayers.length === 0) { app.endUndoGroup(); return; }

    // 选中里索引最小（最靠上）的那层
    var sel = comp.selectedLayers, topLayer = sel[0];
    for (var i = 1; i < sel.length; i++) if (sel[i].index < topLayer.index) topLayer = sel[i];

    var t  = comp.time;
    var fd = comp.frameDuration;
    var half = 20 * fd; // 20帧，合计40帧

    // 原始40帧窗口（居中在光标）
    var tIn  = Math.max(0, t - half);
    var tOut = Math.min(comp.duration, t + half);
    if (tIn >= tOut) { app.endUndoGroup(); return; }

    // 需要把入/出点整体右移5帧，但要保证：1) 不超出合成 2) 光标仍在层内
    var wantShift = 5 * fd;
    var maxShiftByDuration = Math.max(0, comp.duration - tOut);
    var maxShiftByCursor   = Math.max(0, t - tIn); // 移太多会把光标挤出层外
    var shift = Math.min(wantShift, maxShiftByDuration, maxShiftByCursor);

    // 新建调整层
    var solid = comp.layers.addSolid([0,0,0], "LensBlur_40f", comp.width, comp.height, comp.pixelAspect, comp.duration);
    solid.adjustmentLayer = true;
    try { solid.label = 5; } catch (e) {} // 淡粉：如果你的配色改过，按需改编号

    // 放到所选图层上方
    solid.moveBefore(topLayer);

    // 应用右移后的入/出点（总时长仍40帧）
    solid.inPoint  = tIn  + shift;
    solid.outPoint = tOut + shift;

    // 添加“摄像机镜头模糊”
    var fxGrp = solid.property("ADBE Effect Parade");
    var fx = fxGrp.addProperty("ADBE Camera Lens Blur")
          || fxGrp.addProperty("Camera Lens Blur")
          || fxGrp.addProperty("摄像机镜头模糊");
    if (!fx) { app.endUndoGroup(); return; }

    // 模糊半径（通常是属性1）
    var radius = fx.property(1);
    if (!radius) { app.endUndoGroup(); return; }

    // 在入点/光标/出点各打一针：0 → 20 → 0；强制线性
    var tK1 = solid.inPoint;   // 入点（已右移）
    var tK2 = Math.min(Math.max(t, solid.inPoint), solid.outPoint); // 确保在层内
    var tK3 = solid.outPoint;  // 出点（已右移）

    radius.setValueAtTime(tK1, 0);
    radius.setValueAtTime(tK2, 20);
    radius.setValueAtTime(tK3, 0);

    for (var k = 1; k <= radius.numKeys; k++) {
        radius.setInterpolationTypeAtKey(k, KeyframeInterpolationType.LINEAR, KeyframeInterpolationType.LINEAR);
    }

    app.endUndoGroup();
})();
