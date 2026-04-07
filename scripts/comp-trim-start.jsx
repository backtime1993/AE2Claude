/* Comp Trimmer — 裁头 (CLI版，原版完整逻辑)
   选中预合成层: 裁预合成内部 + 偏移关键帧/marker + 保留父层timing
   无选中层: 裁当前合成 + 找父合成补偿 */
(function(){

// ===== 工具函数 (原版) =====
function saveKeyInterpolation(prop, keyIndex) {
    var ki = { inInterpolationType: prop.keyInInterpolationType(keyIndex),
        inSpatialTangent: null, inTemporalEase: prop.keyInTemporalEase(keyIndex),
        isSpatialContinuous: false, label: 0,
        outInterpolationType: prop.keyOutInterpolationType(keyIndex),
        outSpatialTangent: null, outTemporalEase: prop.keyOutTemporalEase(keyIndex),
        roving: false };
    if (prop.isSpatial) {
        try { ki.inSpatialTangent = prop.keyInSpatialTangent(keyIndex);
            ki.outSpatialTangent = prop.keyOutSpatialTangent(keyIndex);
            ki.isSpatialContinuous = prop.keySpatialContinuous(keyIndex);
            try { ki.roving = prop.keyRoving(keyIndex); } catch(e){} } catch(e){} }
    try { if (typeof prop.keyLabel === "function") ki.label = prop.keyLabel(keyIndex); } catch(e){}
    return ki;
}

function applyKeyInterpolation(prop, keyIndex, ki) {
    try { prop.setInterpolationTypeAtKey(keyIndex, ki.inInterpolationType, ki.outInterpolationType);
        if (ki.inInterpolationType === KeyframeInterpolationType.BEZIER || ki.outInterpolationType === KeyframeInterpolationType.BEZIER)
            try { prop.setTemporalEaseAtKey(keyIndex, ki.inTemporalEase, ki.outTemporalEase); } catch(e){}
        if (prop.isSpatial) {
            try { if (ki.inSpatialTangent && ki.outSpatialTangent)
                prop.setSpatialTangentsAtKey(keyIndex, ki.inSpatialTangent, ki.outSpatialTangent);
                if (ki.isSpatialContinuous) try { prop.setSpatialContinuousAtKey(keyIndex, ki.isSpatialContinuous); } catch(e){}
                if (ki.roving && typeof prop.setRovingAtKey === "function") try { prop.setRovingAtKey(keyIndex, ki.roving); } catch(e){} } catch(e){} }
        try { if (ki.label && typeof prop.setLabelAtKey === "function") prop.setLabelAtKey(keyIndex, ki.label); } catch(e){}
    } catch(e){}
}

function compensateKeyframes(prop, offset) {
    if (prop.numKeys > 0) {
        var keyData = [];
        for (var k = 1; k <= prop.numKeys; k++)
            keyData.push({ interpolation: saveKeyInterpolation(prop, k), time: prop.keyTime(k), value: prop.keyValue(k) });
        for (var k = prop.numKeys; k >= 1; k--) prop.removeKey(k);
        for (var k = 0; k < keyData.length; k++) {
            var newTime = keyData[k].time - offset;
            var newKeyIndex = prop.addKey(newTime);
            prop.setValueAtKey(newKeyIndex, keyData[k].value);
            applyKeyInterpolation(prop, newKeyIndex, keyData[k].interpolation);
        }
    }
}

function compensateLayerMarkers(layer, offset) {
    try {
        var mp = layer.property("Marker");
        if (mp && mp.numKeys > 0) {
            var md = [];
            for (var k = 1; k <= mp.numKeys; k++) md.push({ time: mp.keyTime(k), value: mp.keyValue(k) });
            for (var k = mp.numKeys; k >= 1; k--) mp.removeKey(k);
            for (var k = 0; k < md.length; k++) mp.setValueAtTime(md[k].time - offset, md[k].value);
        }
    } catch(e){}
}

function processPropertyGroup(propGroup, offset) {
    for (var p = 1; p <= propGroup.numProperties; p++) {
        var prop = propGroup.property(p);
        if (prop.propertyType === PropertyType.PROPERTY && prop.canSetExpression)
            compensateKeyframes(prop, offset);
        else if (prop.propertyType === PropertyType.INDEXED_GROUP || prop.propertyType === PropertyType.NAMED_GROUP)
            processPropertyGroup(prop, offset);
    }
}

function clearAllKeyframeSelection(propGroup) {
    for (var p = 1; p <= propGroup.numProperties; p++) {
        var prop = propGroup.property(p);
        if (prop.propertyType === PropertyType.PROPERTY) {
            if (prop.numKeys > 0) for (var k = 1; k <= prop.numKeys; k++) try { prop.setSelectedAtKey(k, false); } catch(e){}
        } else if (prop.propertyType === PropertyType.INDEXED_GROUP || prop.propertyType === PropertyType.NAMED_GROUP)
            clearAllKeyframeSelection(prop);
    }
}

// ===== 主逻辑 (原版 setStartPoint_Plain) =====
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var currentTime = comp.time;
if (currentTime <= 0) return "ERR:time_is_0";
var selectedLayers = comp.selectedLayers;

app.beginUndoGroup("Trim Comp Start");

if (selectedLayers.length > 0) {
    // ── 选中了图层：只裁选中的预合成 ──
    var layerTiming = [];
    var processedSourceComps = [];
    for (var i = 0; i < selectedLayers.length; i++) {
        var layer = selectedLayers[i];
        if (layer.source && layer.source instanceof CompItem) {
            var sourceComp = layer.source;
            var alreadyProcessed = false;
            for (var p = 0; p < processedSourceComps.length; p++)
                if (processedSourceComps[p] === sourceComp) { alreadyProcessed = true; break; }
            if (!alreadyProcessed) {
                processedSourceComps.push(sourceComp);
                layerTiming.push({ layer: layer, oriInPoint: layer.inPoint, oriOutPoint: layer.outPoint, oriStartTime: layer.startTime });
            }
        }
    }
    for (var i = 0; i < selectedLayers.length; i++) {
        var layer = selectedLayers[i];
        if (layer.source && layer.source instanceof CompItem) {
            var sourceComp = layer.source;
            var shouldProcess = false;
            for (var t = 0; t < layerTiming.length; t++)
                if (layerTiming[t].layer === layer) { shouldProcess = true; break; }
            if (!shouldProcess) continue;
            var layerStartTime = layer.startTime;
            var layerEndTime = layerStartTime + sourceComp.duration;
            if (currentTime >= layerEndTime) continue;
            var timeOffset = currentTime - layerStartTime;
            layer.startTime = currentTime;
            processPropertyGroup(layer, timeOffset);
            compensateLayerMarkers(layer, timeOffset);
            for (var j = 1; j <= sourceComp.numLayers; j++)
                sourceComp.layer(j).startTime -= timeOffset;
            for (var k = sourceComp.markerProperty.numKeys; k >= 1; k--) {
                var mt = sourceComp.markerProperty.keyTime(k);
                var mv = sourceComp.markerProperty.keyValue(k);
                sourceComp.markerProperty.removeKey(k);
                sourceComp.markerProperty.setValueAtTime(mt - timeOffset, mv);
            }
            if (timeOffset > 0) {
                sourceComp.workAreaStart = Math.max(0, sourceComp.workAreaStart - timeOffset);
                sourceComp.duration = Math.max(0.001, sourceComp.duration - timeOffset);
            } else {
                sourceComp.duration = sourceComp.duration - timeOffset;
                sourceComp.workAreaStart = Math.max(0, sourceComp.workAreaStart - timeOffset);
            }
        }
    }
    for (var i = 0; i < layerTiming.length; i++) {
        var data = layerTiming[i];
        if (data.oriStartTime !== data.oriInPoint) data.layer.inPoint = data.oriInPoint;
        data.layer.outPoint = data.oriOutPoint;
    }
} else {
    // ── 无选中层：裁当前合成 + 查找父合成补偿 ──
    var parentComp = null, targetLayer = null;
    var oriInPoint, oriOutPoint, oriStartTime;
    for (var k = 1; k <= app.project.numItems; k++) {
        var item = app.project.item(k);
        if (item instanceof CompItem && item !== comp) {
            for (var l = 1; l <= item.numLayers; l++) {
                var layer = item.layer(l);
                if (layer.source === comp) {
                    parentComp = item; targetLayer = layer;
                    oriInPoint = layer.inPoint; oriOutPoint = layer.outPoint; oriStartTime = layer.startTime;
                    break;
                }
            }
            if (parentComp) break;
        }
    }
    if (parentComp && targetLayer) {
        var layerStartTime = targetLayer.startTime;
        if (currentTime >= layerStartTime + comp.duration) { app.endUndoGroup(); return "ERR:past_end"; }
        var trimAmount = currentTime;
        targetLayer.startTime = layerStartTime + trimAmount;
        processPropertyGroup(targetLayer, trimAmount);
        compensateLayerMarkers(targetLayer, trimAmount);
        for (var m = 1; m <= comp.numLayers; m++) comp.layer(m).startTime -= trimAmount;
        for (var n = comp.markerProperty.numKeys; n >= 1; n--) {
            var mt = comp.markerProperty.keyTime(n); var mv = comp.markerProperty.keyValue(n);
            comp.markerProperty.removeKey(n); comp.markerProperty.setValueAtTime(mt - trimAmount, mv);
        }
        comp.workAreaStart = Math.max(0, comp.workAreaStart - trimAmount);
        comp.duration = Math.max(0.001, comp.duration - trimAmount);
        comp.time = 0;
        if (oriStartTime !== oriInPoint) targetLayer.inPoint = oriInPoint;
        targetLayer.outPoint = oriOutPoint;
    } else {
        var trimAmount = currentTime;
        for (var m = 1; m <= comp.numLayers; m++) comp.layer(m).startTime -= trimAmount;
        for (var n = comp.markerProperty.numKeys; n >= 1; n--) {
            var mt = comp.markerProperty.keyTime(n); var mv = comp.markerProperty.keyValue(n);
            comp.markerProperty.removeKey(n); comp.markerProperty.setValueAtTime(mt - trimAmount, mv);
        }
        comp.workAreaStart = Math.max(0, comp.workAreaStart - trimAmount);
        comp.duration = Math.max(0.001, comp.duration - trimAmount);
        comp.time = 0;
    }
}
for (var i = 1; i <= comp.numLayers; i++) clearAllKeyframeSelection(comp.layer(i));
try { comp.selectedProperties = []; } catch(e){}
app.endUndoGroup();
return "trimmed_start:" + currentTime;
})()
