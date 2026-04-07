/*  Trim Layers to Edge Neighbor v2.2
    · 单选：默认对齐下邻；按 Ctrl 对齐上邻
    · 多选：默认全体对齐“所选最下层”的下邻；按 Ctrl 全体对齐“所选最上层”的上邻
*/
(function trimSmart(){
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) return;

    var sel = comp.selectedLayers;
    if (!sel || sel.length === 0) return;

    app.beginUndoGroup("Smart Trim v2.2");

    var up = false;
    try{
        var kb = ScriptUI.environment.keyboardState;
        up = !!(kb && kb.ctrlKey);
    }catch(e){}

    // 计算参考邻居
    var refIx = -1;
    if (sel.length === 1){
        var tgtIx = sel[0].index;
        refIx = tgtIx + (up ? -1 : +1);
    }else{
        var minIx = 1e9, maxIx = -1e9;
        for (var i=0;i<sel.length;i++){
            var idx = sel[i].index;
            if (idx < minIx) minIx = idx;
            if (idx > maxIx) maxIx = idx;
        }
        refIx = (up ? (minIx - 1) : (maxIx + 1));
    }

    if (refIx >= 1 && refIx <= comp.numLayers){
        var ref = comp.layer(refIx);
        if (ref){
            var tIn = ref.inPoint, tOut = ref.outPoint;
            for (var j=0;j<sel.length;j++){
                try{
                    sel[j].inPoint  = tIn;
                    sel[j].outPoint = tOut;
                }catch(e2){}
            }
        }
    }

    app.endUndoGroup();
})();
