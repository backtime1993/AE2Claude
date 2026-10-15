/*  Set Anchor Point v1.0
    移动选中图层的锚点到指定位置，保持图层视觉位置不变。
    · __mode__: "tl"/"tm"/"tr"/"ml"/"mm"/"mr"/"bl"/"bm"/"br"（默认 "mm"）
    · 支持 2D/3D 图层、旋转补偿、蒙版边界检测
    · 跳过摄像机/灯光图层
*/
(function setAnchorPoint(){
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem)) return;

    var sel = comp.selectedLayers;
    if (!sel || sel.length === 0) return;

    var pos = (typeof __mode__ !== "undefined") ? __mode__ : "mm";

    app.beginUndoGroup("Set Anchor Point");

    try {
        for (var i = 0; i < sel.length; i++){
            var layer = sel[i];
            if (layer instanceof CameraLayer || layer instanceof LightLayer) continue;
            _setAP(layer, pos);
        }
    } finally {
        app.endUndoGroup();
    }

    function _getBounds(layer){
        var rect = layer.sourceRectAtTime(comp.time, false);
        // 检测蒙版边界
        var numMasks = layer.mask.numProperties;
        if (numMasks === 0) return rect;
        if (numMasks === 1){
            var m = layer.mask(1);
            if (m.maskMode == MaskMode.SUBTRACT || m.maskMode == MaskMode.NONE || m.inverted)
                return rect;
            return _intersect(rect, _maskBounds(m));
        }
        // 多蒙版：合并边界
        var mb = [1e6, 1e6, -1e6, -1e6];
        for (var j = 1; j <= numMasks; j++){
            if (layer.mask(j).inverted) return rect;
            var b = _maskBoundsArr(layer.mask(j));
            if (b[0] < mb[0]) mb[0] = b[0];
            if (b[1] < mb[1]) mb[1] = b[1];
            if (b[2] > mb[2]) mb[2] = b[2];
            if (b[3] > mb[3]) mb[3] = b[3];
        }
        if (mb[0] === 1e6) return rect;
        return _intersectArr(rect, mb);
    }

    function _maskBoundsArr(mask){
        var verts = mask.maskShape.value.vertices;
        var minX = 1e6, minY = 1e6, maxX = -1e6, maxY = -1e6;
        for (var v = 0; v < verts.length; v++){
            if (verts[v][0] < minX) minX = verts[v][0];
            if (verts[v][0] > maxX) maxX = verts[v][0];
            if (verts[v][1] < minY) minY = verts[v][1];
            if (verts[v][1] > maxY) maxY = verts[v][1];
        }
        return [minX, minY, maxX, maxY];
    }

    function _maskBounds(mask){
        var b = _maskBoundsArr(mask);
        return {left: b[0], top: b[1], width: b[2] - b[0], height: b[3] - b[1]};
    }

    function _intersect(rect, mb){
        var r = {};
        r.left = mb.left > rect.left ? mb.left : rect.left;
        r.top = mb.top > rect.top ? mb.top : rect.top;
        var re = rect.left + rect.width;
        var me = mb.left + mb.width;
        r.width = (me < re ? me : re) - r.left;
        var rb = rect.top + rect.height;
        var mbb = mb.top + mb.height;
        r.height = (mbb < rb ? mbb : rb) - r.top;
        return r;
    }

    function _intersectArr(rect, mb){
        var r = {};
        r.left = mb[0] > rect.left ? mb[0] : rect.left;
        r.top = mb[1] > rect.top ? mb[1] : rect.top;
        r.width = (mb[2] < (rect.width + rect.left) ? mb[2] : (rect.width + rect.left)) - r.left;
        r.height = (mb[3] < (rect.height + rect.top) ? mb[3] : (rect.height + rect.top)) - r.top;
        return r;
    }

    function _rot2D(pt, center, deg){
        var d = [pt[0] - center[0], pt[1] - center[1]];
        var r = deg * Math.PI / 180;
        return [d[0]*Math.cos(r) - d[1]*Math.sin(r) + center[0],
                d[0]*Math.sin(r) + d[1]*Math.cos(r) + center[1]];
    }

    function _rot3D(pt, center, rot){
        var d = [pt[0]-center[0], pt[1]-center[1], pt[2]-center[2]];
        var ox=d[0], oy=d[1], oz=d[2];
        // Z rotation
        var rz = rot[2]*Math.PI/180;
        var nx = ox*Math.cos(rz) - oy*Math.sin(rz);
        var ny = ox*Math.sin(rz) + oy*Math.cos(rz);
        ox=nx; oy=ny;
        // Y rotation
        var ry = rot[1]*Math.PI/180;
        var nz = oz*Math.cos(ry) - ox*Math.sin(ry);
        nx = oz*Math.sin(ry) + ox*Math.cos(ry);
        ox=nx; oz=nz;
        // X rotation
        var rx = rot[0]*Math.PI/180;
        ny = oy*Math.cos(rx) - oz*Math.sin(rx);
        nz = oy*Math.sin(rx) + oz*Math.cos(rx);
        return [ox+center[0], ny+center[1], nz+center[2]];
    }

    function _getTL(layer){
        var t = comp.time;
        var bounds = _getBounds(layer);
        var sx = layer.scale.value[0]/100, sy = layer.scale.value[1]/100, sz = layer.scale.value[2]/100;
        var ap = layer.anchorPoint.value;
        var p = layer.position.value;
        if (!layer.threeDLayer){
            var tl = [p[0] - ap[0]*sx, p[1] - ap[1]*sy];
            var rot = layer.rotation.value;
            return _rot2D([tl[0] + bounds.left*sx, tl[1] + bounds.top*sy], p, rot);
        } else {
            var tl = [p[0] - ap[0]*sx, p[1] - ap[1]*sy, p[2] - ap[2]*sz];
            var rot = [layer.xRotation.value, layer.yRotation.value, layer.zRotation.value];
            var pt = _rot3D([tl[0] + bounds.left*sx, tl[1] + bounds.top*sy, tl[2]], p, rot);
            var ori = layer.orientation.value;
            return _rot3D(pt, p, ori);
        }
    }

    function _getTarget(layer, position){
        var bounds = _getBounds(layer);
        var sx = layer.scale.value[0]/100, sy = layer.scale.value[1]/100;
        var t = comp.time;
        var tl = _getTL(layer);
        var offsets = {
            "tl": [0, 0, 0],
            "tm": [bounds.width/2*sx, 0, 0],
            "tr": [bounds.width*sx, 0, 0],
            "ml": [0, bounds.height/2*sy, 0],
            "mm": [bounds.width/2*sx, bounds.height/2*sy, 0],
            "mr": [bounds.width*sx, bounds.height/2*sy, 0],
            "bl": [0, bounds.height*sy, 0],
            "bm": [bounds.width/2*sx, bounds.height/2*sy, 0],
            "br": [bounds.width*sx, bounds.height*sy, 0]
        };
        // bm 修正
        if (position === "bm") offsets["bm"] = [bounds.width/2*sx, bounds.height*sy, 0];

        var off = offsets[position] || offsets["mm"];

        if (!layer.threeDLayer){
            var p = layer.position.value;
            var rot = layer.rotation.value;
            return _rot2D([tl[0]+off[0], tl[1]+off[1]], tl, rot);
        } else {
            var p = layer.position.value;
            var rot = [layer.xRotation.value, layer.yRotation.value, layer.zRotation.value];
            var pt = _rot3D([tl[0]+off[0], tl[1]+off[1], tl[2]], tl, rot);
            var ori = layer.orientation.value;
            return _rot3D(pt, tl, ori);
        }
    }

    function _setAP(layer, position){
        // Refuse unsupported writes before moving Position; otherwise a failed
        // Anchor Point write can leave the artwork displaced.
        if (layer.locked) throw new Error("layer_is_locked");
        if (layer.anchorPoint.numKeys || layer.anchorPoint.expressionEnabled)
            throw new Error("animated_anchor_point_not_supported");
        if (layer.position.expressionEnabled)
            throw new Error("expression_driven_position");
        if (layer.position.dimensionsSeparated &&
            (layer.transform.xPosition.expressionEnabled || layer.transform.yPosition.expressionEnabled ||
             (layer.threeDLayer && layer.transform.zPosition.expressionEnabled)))
            throw new Error("expression_driven_position");

        var bounds = _getBounds(layer);
        var factors = {tl:[0,0],tm:[0.5,0],tr:[1,0],ml:[0,0.5],mm:[0.5,0.5],
                       mr:[1,0.5],bl:[0,1],bm:[0.5,1],br:[1,1]};
        var f = factors[position] || factors.mm;
        var newAP = [bounds.left + bounds.width*f[0], bounds.top + bounds.height*f[1]];
        var target = _getTarget(layer, position);
        var ap = layer.anchorPoint.value;
        var p = layer.position.value;
        var delta = [p[0] - target[0], p[1] - target[1]];
        if (!layer.threeDLayer){
            _updatePosition(layer, delta, newAP);
        } else {
            delta.push(p[2] - target[2]);
            _updatePosition3D(layer, delta, [newAP[0]-ap[0],newAP[1]-ap[1],-ap[2]]);
        }
    }

    function _updatePosition(layer, delta, newAP){
        try {
            if (!layer.position.dimensionsSeparated){
                if (layer.position.isTimeVarying){
                    for (var k = 1; k <= layer.position.numKeys; k++){
                        var v = layer.position.keyValue(k);
                        layer.position.setValueAtKey(k, [v[0]-delta[0], v[1]-delta[1]]);
                    }
                } else {
                    var v = layer.position.value;
                    layer.position.setValue([v[0]-delta[0], v[1]-delta[1]]);
                }
            } else {
                _offsetProp(layer.transform.xPosition, delta[0]);
                _offsetProp(layer.transform.yPosition, delta[1]);
            }
            layer.anchorPoint.setValue(newAP);
        } catch(e){throw e;}
    }

    function _updatePosition3D(layer, delta, apDelta){
        try {
            if (!layer.position.dimensionsSeparated){
                if (layer.position.isTimeVarying){
                    for (var k = 1; k <= layer.position.numKeys; k++){
                        var v = layer.position.keyValue(k);
                        layer.position.setValueAtKey(k, [v[0]-delta[0], v[1]-delta[1], v[2]-delta[2]]);
                    }
                } else {
                    var v = layer.position.value;
                    layer.position.setValue([v[0]-delta[0], v[1]-delta[1], v[2]-delta[2]]);
                }
            } else {
                _offsetProp(layer.transform.xPosition, delta[0]);
                _offsetProp(layer.transform.yPosition, delta[1]);
                if (layer.threeDLayer) _offsetProp(layer.transform.zPosition, delta[2]);
            }
            var ap = layer.anchorPoint.value;
            layer.anchorPoint.setValue([ap[0]+apDelta[0], ap[1]+apDelta[1], ap[2]+apDelta[2]]);
        } catch(e){throw e;}
    }

    function _offsetProp(prop, delta){
        if (prop.isTimeVarying){
            for (var k = 1; k <= prop.numKeys; k++)
                prop.setValueAtKey(k, prop.keyValue(k) - delta);
        } else {
            prop.setValue(prop.value - delta);
        }
    }
})();
