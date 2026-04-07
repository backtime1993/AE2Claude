/* Comp Trimmer — 裁头：合成起始点→光标 (CLI版，无GUI)
   包含完整的关键帧偏移、marker补偿逻辑 */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var currentTime = comp.time;
if (currentTime <= 0) return "ERR:time_is_0";

function saveKeyInterpolation(prop, keyIndex) {
    var ki = { inInterpolationType: prop.keyInInterpolationType(keyIndex),
        inSpatialTangent: null, inTemporalEase: prop.keyInTemporalEase(keyIndex),
        outInterpolationType: prop.keyOutInterpolationType(keyIndex),
        outSpatialTangent: null, outTemporalEase: prop.keyOutTemporalEase(keyIndex) };
    if (prop.isSpatial) { try { ki.inSpatialTangent = prop.keyInSpatialTangent(keyIndex);
        ki.outSpatialTangent = prop.keyOutSpatialTangent(keyIndex); } catch(e){} }
    return ki;
}

function applyKeyInterpolation(prop, keyIndex, ki) {
    try { prop.setInterpolationTypeAtKey(keyIndex, ki.inInterpolationType, ki.outInterpolationType);
        if (ki.inInterpolationType === KeyframeInterpolationType.BEZIER)
            try { prop.setTemporalEaseAtKey(keyIndex, ki.inTemporalEase, ki.outTemporalEase); } catch(e){}
        if (prop.isSpatial && ki.inSpatialTangent)
            try { prop.setSpatialTangentsAtKey(keyIndex, ki.inSpatialTangent, ki.outSpatialTangent); } catch(e){}
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
            if (newTime < 0) continue;
            try { prop.setValueAtTime(newTime, keyData[k].value);
                var ni = prop.nearestKeyIndex(newTime);
                applyKeyInterpolation(prop, ni, keyData[k].interpolation); } catch(e){}
        }
    }
}

function processPropertyGroup(layer, offset) {
    function walk(group) {
        for (var i = 1; i <= group.numProperties; i++) {
            var p = group.property(i);
            if (p.propertyType === PropertyType.PROPERTY) {
                if (p.numKeys > 0 && p.canVaryOverTime) compensateKeyframes(p, offset);
            } else if (p.numProperties > 0) walk(p);
        }
    }
    walk(layer);
}

function compensateLayerMarkers(layer, offset) {
    var mp = layer.property("Marker");
    if (!mp || mp.numKeys === 0) return;
    var md = [];
    for (var k = 1; k <= mp.numKeys; k++) md.push({ time: mp.keyTime(k), value: mp.keyValue(k) });
    for (var k = mp.numKeys; k >= 1; k--) mp.removeKey(k);
    for (var k = 0; k < md.length; k++) {
        var nt = md[k].time - offset;
        if (nt >= 0) mp.setValueAtTime(nt, md[k].value);
    }
}

app.beginUndoGroup("Trim Comp Start");
var trimAmount = currentTime;
for (var m = 1; m <= comp.numLayers; m++) comp.layer(m).startTime -= trimAmount;
for (var n = comp.markerProperty.numKeys; n >= 1; n--) {
    var mt = comp.markerProperty.keyTime(n); var mv = comp.markerProperty.keyValue(n);
    comp.markerProperty.removeKey(n); comp.markerProperty.setValueAtTime(mt - trimAmount, mv);
}
comp.workAreaStart = Math.max(0, comp.workAreaStart - trimAmount);
comp.duration = Math.max(0.001, comp.duration - trimAmount);
comp.time = 0;
app.endUndoGroup();
return "trimmed_start:" + trimAmount;
})()
