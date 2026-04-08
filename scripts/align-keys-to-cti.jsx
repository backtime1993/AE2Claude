/*  Align Keys to Current Time v1.0
    将选中关键帧整体移动到光标位置（以最早帧为锚点）。
    保留缓动/空间切线/插值类型。
*/
(function alignKeysToCTI(){
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) return;

    var selProps = comp.selectedProperties;
    if (!selProps || selProps.length === 0) return;

    // 1. 收集选中关键帧
    var collected = [];
    var earliest = null;

    for (var i = 0; i < selProps.length; i++){
        var prop = selProps[i];
        if (prop.propertyType === PropertyType.INDEXED_GROUP ||
            prop.propertyType === PropertyType.NAMED_GROUP) continue;
        var keys = prop.selectedKeys;
        if (!keys || keys.length === 0) continue;
        for (var k = 0; k < keys.length; k++){
            var info = _readKey(prop, keys[k]);
            collected.push({prop: prop, info: info});
            if (earliest === null || info.time < earliest) earliest = info.time;
        }
    }

    if (collected.length === 0) return;

    app.beginUndoGroup("Move Keys to Current Time");

    // 2. 删除旧关键帧（倒序避免 index 偏移）
    for (var n = collected.length - 1; n >= 0; n--){
        var ki = collected[n].prop.nearestKeyIndex(collected[n].info.time);
        collected[n].prop.removeKey(ki);
    }

    // 3. 在新位置写入关键帧
    for (var n = 0; n < collected.length; n++){
        var c = collected[n];
        var newTime = comp.time + (c.info.time - earliest);
        _writeKey(c.prop, c.info, newTime);
        var ni = c.prop.nearestKeyIndex(newTime);
        c.prop.setSelectedAtKey(ni, true);
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
