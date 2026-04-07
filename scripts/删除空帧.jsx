/*
  Remove Single-Keyframe Properties  v1.1
  ▸ 选了属性 → 处理所选属性
  ▸ 否则选了图层 → 处理这些图层
  ▸ 否则 → 处理当前合成全部图层
  ▸ 条件：numKeys == 1（无论是否开启表达式，都删掉该唯一关键帧；不改表达式）
  ▸ 无弹窗
*/

(function removeSingleKeys(){
    app.beginUndoGroup("Remove Single-Keyframe Props");

    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) { app.endUndoGroup(); return; }

    var removed = 0;

    function isProperty(obj){
        return obj && obj.propertyType === PropertyType.PROPERTY;
    }

    function safeNumProperties(group){
        try { return group.numProperties || 0; } catch(e){ return 0; }
    }

    function hasSingleKey(p){
        try { return p.numKeys === 1; } catch(e){ return false; }
    }

    function removeFirstKey(p){
        try { p.removeKey(1); removed++; } catch(e){}
    }

    function processProperty(prop){
        if (isProperty(prop)){
            // 不再因为 expressionEnabled 而跳过；仅删除唯一关键帧，不改表达式本身
            if (hasSingleKey(prop)) removeFirstKey(prop);
        }else if (prop){ // PropertyGroup / Layer
            var n = safeNumProperties(prop);
            for (var i = 1; i <= n; i++){
                var child = prop.property(i);
                if (child) processProperty(child);
            }
        }
    }

    function processLayer(layer){
        var n = safeNumProperties(layer);
        for (var i = 1; i <= n; i++){
            var p = layer.property(i);
            if (p) processProperty(p);
        }
    }

    // ------- Routing -------
    var selProps = comp.selectedProperties || [];
    if (selProps.length > 0){
        for (var i = 0; i < selProps.length; i++){
            processProperty(selProps[i]);
        }
    }else{
        var layers = comp.selectedLayers.length ? comp.selectedLayers : comp.layers;
        if (layers.length){ // selectedLayers: array, 0-based
            for (var i = 0; i < layers.length; i++) processLayer(layers[i]);
        }else{ // comp.layers: collection, 1-based
            var len = layers.numItems || 0;
            for (var j = 1; j <= len; j++) processLayer(layers[j]);
        }
    }

    $.writeln("Removed single-keyframe properties: " + removed);
    app.endUndoGroup();
})();
