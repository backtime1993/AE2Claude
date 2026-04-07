// 无 UI、无提示，直接运行：keepSelected_removeOthers_silent.jsx
(function(){
    app.beginUndoGroup("Keep Selected, Remove Others (Silent)");
    try{
        var active = app.project.activeItem;
        // 情况一：在合成内选中了图层 -> 删除合成内除选中外的所有图层
        if(active && active instanceof CompItem && active.selectedLayers && active.selectedLayers.length > 0){
            var sel = active.selectedLayers;
            var keepIdx = [];
            for(var i=0;i<sel.length;i++) keepIdx.push(sel[i].index);
            for(var i = active.numLayers; i >= 1; i--){
                if(keepIdx.indexOf(i) === -1){
                    active.layer(i).remove();
                }
            }
            app.endUndoGroup();
            return;
        }
        // 情况二：在项目面板选中了预合成 -> 删除项目中除所选合成外的所有合成
        var psel = app.project.selection;
        if(psel && psel.length > 0){
            var keepIds = [];
            for(var k=0;k<psel.length;k++){
                if(psel[k] instanceof CompItem) keepIds.push(psel[k].id);
            }
            if(keepIds.length > 0){
                for(var i = app.project.numItems; i >= 1; i--){
                    var it = app.project.item(i);
                    if(it instanceof CompItem){
                        if(keepIds.indexOf(it.id) === -1){
                            it.remove();
                        }
                    }
                }
                app.endUndoGroup();
                return;
            }
        }
        // 无有效选择时直接结束（静默）
        app.endUndoGroup();
    }catch(e){
        try{ app.endUndoGroup(); }catch(err){}
        // 静默处理错误，不弹窗
    }
})();
