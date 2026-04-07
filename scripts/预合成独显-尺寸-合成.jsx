/* Solo Big Precomps + Shy Hide  v1.3b
   - 点一次：独显所有“尺寸>=当前合成”的预合成；其余层 shy，并开启 hideShyLayers
   - 再次点击且当前选中包含目标预合成：还原，但保留这些层为选中（方便你手动按 X）
   - Ctrl：全量还原（清 solo/shy，关闭 hideShyLayers）
*/
(function(){
    var TAG = "[SBP]";

    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) return;

    function bigEnough(pre, cur){
        try{
            return Math.round(pre.width)  >= Math.round(cur.width) &&
                   Math.round(pre.height) >= Math.round(cur.height);
        }catch(e){ return false; }
    }
    function isPrecompLayer(L){
        try{ return (L instanceof AVLayer) && (L.source instanceof CompItem); }catch(e){ return false; }
    }
    function hasTag(L){ try{ return (L.comment||"").indexOf(TAG)!==-1; }catch(e){ return false; } }
    function setTag(L,on){
        try{
            var c=L.comment||"";
            if(on){
                if(c.indexOf(TAG)===-1) L.comment=(c?c+" ":"")+TAG;
            }else{
                if(c.indexOf(TAG)!==-1) L.comment=c.split(TAG).join("").replace(/\s{2,}/g," ").trim();
            }
        }catch(e){}
    }

    var kb=null,isCtrl=false;
    try{ kb=ScriptUI.environment && ScriptUI.environment.keyboardState; isCtrl=kb&&kb.ctrlKey; }catch(e){}

    var sel = comp.selectedLayers||[];
    var selectedHasTaggedPre=false;
    for (var s=0;s<sel.length;s++){
        var Ls=sel[s];
        if (isPrecompLayer(Ls) && hasTag(Ls)){ selectedHasTaggedPre=true; break; }
    }

    app.beginUndoGroup(selectedHasTaggedPre ? "Restore (Toggle)" : (isCtrl?"Restore Visibility":"Solo Big Precomps (Shy)"));

    function restoreAll(){
        for (var i=1;i<=comp.numLayers;i++){
            var L=comp.layer(i);
            try{ L.solo=false; }catch(e){}
            try{ L.shy=false; }catch(e){}
            setTag(L,false);
        }
        try{ comp.hideShyLayers=false; }catch(e){}
    }

    if (isCtrl){
        restoreAll();
        app.endUndoGroup(); return;
    }

    if (selectedHasTaggedPre){
        // 记录当前选中的“目标层”
        var toReselect = [];
        for (var j=0;j<sel.length;j++){
            if (isPrecompLayer(sel[j]) && hasTag(sel[j])) toReselect.push(sel[j]);
        }
        restoreAll();
        // 清空后重新选中这些层，便于你手动按 X 置顶
        // 先全清，再选回
        for (var k=1;k<=comp.numLayers;k++){ try{ comp.layer(k).selected=false; }catch(e){} }
        for (var t=0;t<toReselect.length;t++){ try{ toReselect[t].selected=true; }catch(e){} }
        app.endUndoGroup(); return;
    }

    // 首次执行：清 solo，筛目标层
    for (var i=1;i<=comp.numLayers;i++){ try{ comp.layer(i).solo=false; }catch(e){} }

    var keep=[],hasTarget=false;
    for (var i=1;i<=comp.numLayers;i++){
        keep[i]=false;
        var L=comp.layer(i);
        if (isPrecompLayer(L) && bigEnough(L.source, comp)){ keep[i]=true; hasTarget=true; }
    }

    for (var i=1;i<=comp.numLayers;i++){
        var L=comp.layer(i), k=!!keep[i];
        try{ L.shy=!k; }catch(e){}
        try{ if(k) L.solo=true; }catch(e){}
        setTag(L,k);
    }
    try{ comp.hideShyLayers=true; }catch(e){}

    app.endUndoGroup();
})();
