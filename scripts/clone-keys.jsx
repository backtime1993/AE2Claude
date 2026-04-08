/*  Clone Keys v1.0
    复制选中关键帧到光标位置，保留缓动/空间切线/插值类型。
    · 默认：以最早选中帧为锚点偏移到 CTI
    · Ctrl：以最晚选中帧为锚点偏移到 CTI（尾部对齐）
*/
(function cloneKeys(){
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) return;

    var sel = comp.selectedLayers;
    if (!sel || sel.length === 0) return;

    var mode = (typeof __mode__ !== "undefined") ? __mode__ : "default";
    var useLastAsAnchor = (mode === "ctrl");

    // 1. 收集所有选中关键帧
    var collected = [];
    var firstTime = null, lastTime = null;

    for (var i = 0; i < sel.length; i++){
        if (sel[i].stretch < 0) continue; // 跳过时间反转图层
        var props = sel[i].selectedProperties;
        for (var j = 0; j < props.length; j++){
            var prop = props[j];
            var keys = prop.selectedKeys;
            if (!keys || keys.length === 0) continue;
            for (var k = 0; k < keys.length; k++){
                var ki = keys[k];
                var info = _readKey(prop, ki);
                collected.push({prop: prop, info: info});
                if (firstTime === null || info.time < firstTime) firstTime = info.time;
                if (lastTime === null || info.time > lastTime) lastTime = info.time;
            }
        }
    }

    if (collected.length === 0) return;

    var anchor = useLastAsAnchor ? lastTime : firstTime;

    // 2. 写入新关键帧
    app.beginUndoGroup("Clone Keys");
    var newKeys = [];
    for (var n = 0; n < collected.length; n++){
        var c = collected[n];
        var newTime = comp.time + (c.info.time - anchor);
        _writeKey(c.prop, c.info, newTime);
        newKeys.push({prop: c.prop, time: newTime});
    }
    // 3. 选中新关键帧，取消选中旧关键帧
    for (var n = 0; n < newKeys.length; n++){
        var idx = newKeys[n].prop.nearestKeyIndex(newKeys[n].time);
        newKeys[n].prop.setSelectedAtKey(idx, true);
    }
    for (var n = 0; n < collected.length; n++){
        var idx = collected[n].prop.nearestKeyIndex(collected[n].info.time);
        collected[n].prop.setSelectedAtKey(idx, false);
    }
    app.endUndoGroup();

    // --- helpers ---
    function _readKey(prop, ki){
        var o = {};
        o.time = prop.keyTime(ki);
        o.value = prop.keyValue(ki);
        o.canInterp = prop.isInterpolationTypeValid(KeyframeInterpolationType.BEZIER)
                   || prop.isInterpolationTypeValid(KeyframeInterpolationType.HOLD)
                   || prop.isInterpolationTypeValid(KeyframeInterpolationType.LINEAR);
        if (o.canInterp){
            o.inType  = prop.keyInInterpolationType(ki);
            o.outType = prop.keyOutInterpolationType(ki);
            o.inEase  = prop.keyInTemporalEase(ki);
            o.outEase = prop.keyOutTemporalEase(ki);
        }
        o.isSpatial = prop.isSpatial
            && (prop.propertyValueType == PropertyValueType.ThreeD_SPATIAL
             || prop.propertyValueType == PropertyValueType.TwoD_SPATIAL);
        if (o.isSpatial){
            o.inTangent  = prop.keyInSpatialTangent(ki);
            o.outTangent = prop.keyOutSpatialTangent(ki);
        }
        try { o.label = prop.keyLabel(ki); } catch(e){ o.label = 0; }
        return o;
    }

    function _writeKey(prop, info, time){
        if (!prop.canVaryOverTime) return;
        prop.setValueAtTime(time, info.value);
        var ni = prop.nearestKeyIndex(time);
        if (info.canInterp){
            prop.setTemporalEaseAtKey(ni, info.inEase, info.outEase);
            prop.setInterpolationTypeAtKey(ni, info.inType, info.outType);
        }
        if (info.isSpatial){
            prop.setSpatialTangentsAtKey(ni, info.inTangent, info.outTangent);
        }
        try { if (info.label) prop.setLabelAtKey(ni, info.label); } catch(e){}
    }
})();
