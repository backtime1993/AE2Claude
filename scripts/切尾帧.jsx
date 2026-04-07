(function () {
    app.beginUndoGroup("CTI裁切（不位移）");

    var comp = app.project.activeItem;
    if (!(comp && comp instanceof CompItem)) {
        alert("兄弟，先选中一个合成~");
        return;
    }
    var sel = comp.selectedLayers;
    if (sel.length === 0) {
        alert("兄弟，先选要裁切的图层~");
        return;
    }

    var t = comp.time;                         // CTI  
    var ctrl = ScriptUI.environment.keyboardState.ctrlKey;

    // 倒序处理，防止索引变化
    for (var i = sel.length - 1; i >= 0; i--) {
        var L = sel[i];
        if (t <= L.inPoint || t >= L.outPoint) continue;

        if (ctrl) {
            // 复制＋保留后半段
            var dup = L.duplicate();          
            dup.inPoint  = t;                 
            dup.outPoint = L.outPoint;        
            L.remove();                       
        } else {
            // 直接保留前半段
            L.outPoint = t;                   
        }
    }

    app.endUndoGroup();
})(); 