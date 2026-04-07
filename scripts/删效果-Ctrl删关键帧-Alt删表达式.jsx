(function () {
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) { alert("先进入一个合成。"); return; }

    var sel = comp.selectedLayers || [];
    if (!sel.length) { alert("请先选择一些图层。"); return; }

    var ks = null, isCtrl = false, isAlt = false;
    try {
        ks = ScriptUI.environment && ScriptUI.environment.keyboardState;
        isCtrl = !!(ks && ks.ctrlKey);
        isAlt  = !!(ks && ks.altKey);
    } catch (e) {}

    // Ctrl 清关键帧，Alt 清表达式
    var title = isCtrl ? "Clear Keyframes (Ctrl)" : (isAlt ? "Clear Expressions (Alt)" : "Remove Effects from Selected Layers");
    app.beginUndoGroup(title);

    function walk(p, fn){
        try{
            if (p.propertyType === PropertyType.PROPERTY){
                fn(p);
            }else{
                for (var i = 1; i <= p.numProperties; i++) walk(p.property(i), fn);
            }
        }catch(e){}
    }

    // Alt：清表达式（原来是 Ctrl）
    if (isAlt) {
        function clearExpr(prop){
            try{
                if (prop.canSetExpression && (prop.expressionEnabled || prop.expression !== "")){
                    prop.expression = "";
                }
            }catch(e){}
        }
        for (var k = 0; k < sel.length; k++) walk(sel[k], clearExpr);

    // Ctrl：清关键帧（原来是 Alt）
    } else if (isCtrl) {
        function clearKeys(prop){
            try{
                if (prop.numKeys && prop.numKeys > 0){
                    for (var n = prop.numKeys; n >= 1; n--) prop.removeKey(n);
                }
            }catch(e){}
        }
        for (var a = 0; a < sel.length; a++) walk(sel[a], clearKeys);

    } else {
        // 不带修饰键：移除效果
        for (var i = 0; i < sel.length; i++) {
            var layer = sel[i], fx = layer.property("Effects");
            if (fx) for (var j = fx.numProperties; j >= 1; j--) { try { fx.property(j).remove(); } catch (e) {} }
        }
    }

    app.endUndoGroup();
})();
