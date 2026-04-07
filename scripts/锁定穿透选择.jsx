/* Lock / Global Unlock (Ctrl)
 * - Ctrl：解锁当前合成内所有层
 * - 有选中：无条件锁选中层（预合成也当普通层处理）
 * - 无选中：只锁预合成层，且需尺寸 >= 当前合成
 */
(function () {
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) return;

    function bigEnough(pre, cur){
        try{
            return Math.round(pre.width)  >= Math.round(cur.width) &&
                   Math.round(pre.height) >= Math.round(cur.height);
        }catch(e){ return false; }
    }

    var isCtrl = false;
    try { isCtrl = !!(ScriptUI.environment && ScriptUI.environment.keyboardState.ctrlKey); } catch(e){}

    app.beginUndoGroup(isCtrl ? "Unlock ALL Layers" : "Lock Layers");

    if (isCtrl){
        for (var i = 1; i <= comp.numLayers; i++){
            try { comp.layer(i).locked = false; } catch(e){}
        }
        app.endUndoGroup(); return;
    }

    var sel = comp.selectedLayers || [];
    if (sel.length > 0){
        // 选中就直接锁，不做尺寸判断（预合成当普通层处理）
        for (var s = 0; s < sel.length; s++){
            var L = sel[s]; if (!L) continue;
            try { L.locked = true; } catch(e){}
        }
    } else {
        // 无选中：只锁“尺寸≥当前合成”的预合成层
        for (var k = 1; k <= comp.numLayers; k++){
            var A = comp.layer(k);
            if (A instanceof AVLayer && A.source instanceof CompItem){
                if (bigEnough(A.source, comp)){
                    try { A.locked = true; } catch(e){}
                }
            }
        }
    }

    app.endUndoGroup();
})();
