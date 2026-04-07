/* Un-Trim: 还原图层/合成原始长度（按当前拉伸系数） */
(function () {
    var a = app.project.activeItem;
    if (!(a instanceof CompItem)) return;

    app.beginUndoGroup("Un-Trim");

    function fullSrcDur(layer){
        // 源时长（含 stretch）；无源时长的层（文字/形状/纯色/静帧）用合成时长
        try{
            var src = layer.source;
            var d = (src && src.duration && src.duration > 0) ? src.duration : a.duration;
            return d * (layer.stretch/100.0);
        }catch(e){
            return a.duration * (layer.stretch/100.0);
        }
    }

    var sel = a.selectedLayers;

    if (sel && sel.length){
        for (var i=0;i<sel.length;i++){
            var L = sel[i];
            var d = fullSrcDur(L);
            // 还原到：入点 = startTime；出点 = startTime + 完整时长
            try{
                L.inPoint  = L.startTime;
                L.outPoint = L.startTime + d;
            }catch(e){}
        }
    }else{
        // 无选中图层：用“各层完整时长”估算合成应有范围
        var minStart = Infinity, maxEnd = -Infinity, hasLayer = false;
        for (var j=1;j<=a.numLayers;j++){
            var L2 = a.layer(j);
            hasLayer = true;
            var s = L2.startTime;
            var e = s + fullSrcDur(L2);
            if (s < minStart) minStart = s;
            if (e > maxEnd)   maxEnd   = e;
        }
        if (hasLayer && isFinite(minStart) && isFinite(maxEnd) && maxEnd > minStart){
            a.displayStartTime = minStart;
            a.duration = maxEnd - minStart;
        }
    }

    app.endUndoGroup();
})();
