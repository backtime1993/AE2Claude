(function () {
    app.beginUndoGroup("Copy/Paste Markers");

    var S = "MarkerClipboard", K = "data", E = 1e-4;
    var a = app.project.activeItem;
    var kb = ScriptUI.environment ? ScriptUI.environment.keyboardState : null;
    var isCtrl = kb && kb.ctrlKey;

    function readClip() {
        if (!app.settings.haveSetting(S, K)) return null;
        try { return JSON.parse(app.settings.getSetting(S, K)); } catch (e) { return null; }
    }
    function writeClip(obj) {
        try { app.settings.saveSetting(S, K, JSON.stringify(obj)); } catch (e) {}
    }
    function collectFromMarkerProp(mp) {
        if (!mp) return [];
        var n = mp.numKeys, out = [];
        for (var i = 1; i <= n; i++) {
            var t = mp.keyTime(i);
            var mv = mp.keyValue(i);
            var o = { t: t, c: mv.comment || "", d: 0, ch: "", u: "", ft: "", cp: "", pa: null };
            try { o.d = mv.duration || 0; } catch (e) {}
            try { o.ch = mv.chapter || ""; } catch (e) {}
            try { o.u  = mv.url || ""; } catch (e) {}
            try { o.ft = mv.frameTarget || ""; } catch (e) {}
            try { o.cp = mv.cuePointName || ""; } catch (e) {}
            try { o.pa = mv.getParameters ? mv.getParameters() : null; } catch (e) {}
            out.push(o);
        }
        return out;
    }
    function collectFromLayer(l) { return collectFromMarkerProp(l && l.property("Marker")); }
    function collectFromComp(c) { return collectFromMarkerProp(c && c.markerProperty); }
    function uniqSort(list) {
        var map = {}, out = [];
        for (var i = 0; i < list.length; i++) {
            var k = list[i].t.toFixed(5);
            if (!(k in map)) { map[k] = list[i]; out.push(list[i]); }
        }
        out.sort(function (a, b) { return a.t - b.t; });
        return out;
    }
    function buildMV(o) {
        var mv = new MarkerValue(o.c || "");
        try { mv.duration = o.d || 0; } catch (e) {}
        try { mv.chapter = o.ch || ""; } catch (e) {}
        try { mv.url = o.u || ""; } catch (e) {}
        try { mv.frameTarget = o.ft || ""; } catch (e) {}
        try { mv.cuePointName = o.cp || ""; } catch (e) {}
        try { if (o.pa) mv.setParameters(o.pa); } catch (e) {}
        return mv;
    }
    function addToMarkerProp(mp, arr) {
        if (!mp || !arr || arr.length === 0) return;
        for (var i = 0; i < arr.length; i++) {
            var t = arr[i].t;
            var exist = false;
            if (mp.numKeys > 0) {
                var idx = mp.nearestKeyIndex(t);
                if (Math.abs(mp.keyTime(idx) - t) < E) exist = true;
            }
            if (!exist) {
                var k = mp.addKey(t);
                mp.setValueAtKey(k, buildMV(arr[i]));
            }
        }
    }
    function pasteToLayers(layers, arr) {
        for (var i = 0; i < layers.length; i++) {
            var l = layers[i];
            var mp = l.property("Marker");
            if (!mp) continue;
            var fit = [];
            for (var j = 0; j < arr.length; j++) {
                var t = arr[j].t;
                if (t < l.inPoint || t > l.outPoint) continue;
                fit.push(arr[j]);
            }
            addToMarkerProp(mp, fit);
        }
    }
    function pasteToComps(comps, arr) {
        for (var i = 0; i < comps.length; i++) addToMarkerProp(comps[i].markerProperty, arr);
    }

    if (isCtrl) {
        var collected = [];
        if (a && a instanceof CompItem) {
            var selL = a.selectedLayers;
            if (selL && selL.length > 0) {
                for (var i = 0; i < selL.length; i++) {
                    var part = collectFromLayer(selL[i]);
                    for (var j = 0; j < part.length; j++) collected.push(part[j]);
                }
            } else {
                collected = collectFromComp(a);
            }
        } else {
            var s = app.project.selection, got = false;
            for (var i = 0; i < s.length; i++) {
                if (s[i] instanceof CompItem) {
                    var partc = collectFromComp(s[i]);
                    for (var j = 0; j < partc.length; j++) collected.push(partc[j]);
                    got = true;
                }
            }
            if (!got && a && a instanceof CompItem) collected = collectFromComp(a);
        }
        collected = uniqSort(collected);
        writeClip({ items: collected });
        app.endUndoGroup();
        return;
    }

    var data = readClip();
    if (data && data.items && data.items.length > 0) {
        if (a && a instanceof CompItem) {
            var sel = a.selectedLayers;
            if (sel && sel.length > 0) pasteToLayers(sel, data.items);
            else pasteToComps([a], data.items);
        } else {
            var ps = app.project.selection, comps = [];
            for (var i = 0; i < ps.length; i++) if (ps[i] instanceof CompItem) comps.push(ps[i]);
            if (comps.length > 0) pasteToComps(comps, data.items);
        }
    }

    app.endUndoGroup();
})();
