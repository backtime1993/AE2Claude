/*  Delete All Masks v1.3
    - 有选中图层：只处理选中
    - 无选中图层：处理当前合成内全部可处理图层
    - 跳过非 AV 图层与无蒙版图层
    - 按住 Alt：临时解锁后删除，完毕还原锁定
    - 无弹窗、可撤销
*/
(function deleteAllMasks(){
    var proj = app.project;
    var comp = proj && proj.activeItem;
    if (!(comp instanceof CompItem)) return;

    // __mode__: "default" = 跳过锁定层, "alt" = 强制解锁后删除再还原锁定
    var mode = (typeof __mode__ !== "undefined") ? __mode__ : "default";
    var forceUnlock = (mode === "alt"); // alt = 强制解锁处理

    var targets = comp.selectedLayers.length ? comp.selectedLayers : (function(){
        var arr = [];
        for (var i = 1; i <= comp.numLayers; i++) arr.push(comp.layer(i));
        return arr;
    })();

    app.beginUndoGroup("Delete All Masks");

    var totalRemoved = 0, touched = 0;

    for (var i = 0; i < targets.length; i++){
        var L = targets[i];

        // 只处理能挂蒙版的普通图层（跳过摄像机/灯光/空对象/形状组属性等）
        if (!(L instanceof AVLayer)) continue;

        var wasLocked = L.locked;
        if (L.locked && !forceUnlock) continue;         // 跳过锁定层
        if (L.locked && forceUnlock) L.locked = false;  // Alt 临时解锁

        try{
            var masks = L.property("ADBE Mask Parade");
            if (masks && masks.numProperties > 0){
                // 反向删除更安全
                for (var k = masks.numProperties; k >= 1; k--){
                    masks.property(k).remove();
                    totalRemoved++;
                }
                touched++;
            }
        }catch(e){}

        // 还原锁定状态
        if (forceUnlock && wasLocked) L.locked = true;
    }

    // 控制台输出（不打扰）
    $.writeln("[Delete All Masks] layers: " + touched + ", masks removed: " + totalRemoved);

    app.endUndoGroup();
})();
