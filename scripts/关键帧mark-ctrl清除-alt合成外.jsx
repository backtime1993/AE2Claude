(function () {
    app.beginUndoGroup("Generate & Copy Layer Markers");

    var a = app.project.activeItem;
    // __mode__: "default" = 从关键帧生成marker并向子合成传播, "ctrl" = 清除选中层marker, "alt" = 向父合成传播marker
    var mode = (typeof __mode__ !== "undefined") ? __mode__ : "default";
    var isCtrl = (mode === "ctrl");
    var isAlt  = (mode === "alt");

    function timesFromMarkerProp(m) {
        var map = {}; var c = m ? m.numKeys : 0;
        for (var i = 1; i <= c; i++) map[m.keyTime(i).toFixed(5)] = m.keyTime(i);
        return map;
    }
    function addMarkersAtTimes(l, map) {
        var m = l.property("Marker"); if (!m) return;
        for (var k in map) {
            var t = map[k]; if (t < l.inPoint || t > l.outPoint) continue;
            var exist = false; if (m.numKeys > 0) { var idx = m.nearestKeyIndex(t); if (Math.abs(m.keyTime(idx) - t) < 1e-4) exist = true; }
            if (!exist) { var mv = new MarkerValue(""); var i2 = m.addKey(t); m.setValueAtKey(i2, mv); }
        }
    }
    function traverse(g, map) {
        var n = 0; try { n = g.numProperties; } catch (e) {}
        for (var i = 1; i <= n; i++) {
            var p = g.property(i); if (!p) continue;
            if (p.propertyType === PropertyType.PROPERTY) {
                if (p.matchName === "ADBE Marker") continue;
                var nk = 0; try { nk = p.numKeys; } catch (e) { nk = 0; }
                for (var k = 1; k <= nk; k++) map[p.keyTime(k).toFixed(5)] = p.keyTime(k);
            } else traverse(p, map);
        }
    }
    function keyTimesFromLayer(l) { var map = {}; traverse(l, map); return map; }
    function applyTimesToCompLayers(comp, map) {
        var n = comp.numLayers;
        for (var i = 1; i <= n; i++) {
            var L = comp.layer(i);
            addMarkersAtTimes(L, map);
            if (L instanceof AVLayer) {
                var src = L.source;
                if (src && src instanceof CompItem) applyTimesToCompLayers(src, map);
            }
        }
    }
    function processLayerAndCopy(l) {
        var times = keyTimesFromLayer(l);
        addMarkersAtTimes(l, times);
        if (l instanceof AVLayer) {
            var src = l.source;
            if (src && src instanceof CompItem) {
                var mmap = timesFromMarkerProp(l.property("Marker"));
                if (Object.keys(mmap).length === 0) mmap = times;
                applyTimesToCompLayers(src, mmap);
            }
        }
    }
    function processCompRecursive(comp) {
        var n = comp.numLayers;
        for (var i = 1; i <= n; i++) processLayerAndCopy(comp.layer(i));
    }
    function parentTimeByStretch(layer, childT) {
        return layer.startTime + childT * (layer.stretch / 100.0);
    }
    function invertTimeRemap(layer, childT) {
        var p = layer.property("ADBE Time Remapping"); if (!p) return parentTimeByStretch(layer, childT);
        var lo = layer.inPoint, hi = layer.outPoint;
        var vLo = p.valueAtTime(lo, true), vHi = p.valueAtTime(hi, true);
        var minV = Math.min(vLo, vHi) - 1e-4, maxV = Math.max(vLo, vHi) + 1e-4;
        if (childT < minV || childT > maxV) return null;
        var asc = vHi >= vLo;
        for (var i = 0; i < 40; i++) {
            var mid = (lo + hi) * 0.5;
            var v = p.valueAtTime(mid, true);
            if ((asc && v > childT) || (!asc && v < childT)) hi = mid; else lo = mid;
        }
        return (lo + hi) * 0.5;
    }
    function addToParentsFromTimes(childComp, times) {
        var n = app.project.numItems;
        for (var i = 1; i <= n; i++) {
            var it = app.project.item(i);
            if (!(it instanceof CompItem)) continue;
            var Lc = it.numLayers;
            for (var j = 1; j <= Lc; j++) {
                var lay = it.layer(j);
                if (!(lay instanceof AVLayer)) continue;
                if (lay.source !== childComp) continue;
                var mp = lay.property("Marker"); if (!mp) continue;
                for (var k in times) {
                    var ct = times[k];
                    var pt = lay.timeRemapEnabled ? invertTimeRemap(lay, ct) : parentTimeByStretch(lay, ct);
                    if (pt === null) continue;
                    if (pt < lay.inPoint || pt > lay.outPoint) continue;
                    var exist = false; if (mp.numKeys > 0) { var idx = mp.nearestKeyIndex(pt); if (Math.abs(mp.keyTime(idx) - pt) < 1e-4) exist = true; }
                    if (!exist) { var mv = new MarkerValue(""); var i2 = mp.addKey(pt); mp.setValueAtKey(i2, mv); }
                }
            }
        }
    }

    if (isCtrl) {
        if (a && a instanceof CompItem) {
            var sel = a.selectedLayers;
            for (var i = 0; i < sel.length; i++) {
                var m = sel[i].property("Marker");
                if (m) { for (var j = m.numKeys; j >= 1; j--) m.removeKey(j); }
            }
        }
        app.endUndoGroup();
        return;
    }

    if (isAlt) {
        if (a && a instanceof CompItem && a.selectedLayers.length > 0) {
            var sel = a.selectedLayers;
            for (var i = 0; i < sel.length; i++) {
                var mm = timesFromMarkerProp(sel[i].property("Marker"));
                if (Object.keys(mm).length === 0) continue;
                addToParentsFromTimes(a, mm);
            }
        }
        app.endUndoGroup();
        return;
    }

    if (a && a instanceof CompItem) {
        var sel = a.selectedLayers;
        if (sel.length > 0) { for (var i = 0; i < sel.length; i++) processLayerAndCopy(sel[i]); }
        else processCompRecursive(a);
    } else {
        var s = app.project.selection;
        for (var i = 0; i < s.length; i++) if (s[i] instanceof CompItem) processCompRecursive(s[i]);
    }
    app.endUndoGroup();
})();