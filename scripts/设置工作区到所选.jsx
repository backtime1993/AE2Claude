/*  Match Work Area to Comp / Selected Pre-comp v1.4  */
(function matchWorkAreaAll() {
    app.beginUndoGroup("Match Work Area v1.4");

    var ANCHOR_MODE = "matchActive"; // "keep" | "matchActive" | "zero"
    function clamp(v, a, b){return Math.min(Math.max(v, a), b);}

    var comp = app.project.activeItem;
    var waStart = 0, waDur = 0, haveRef = false;

    if (comp instanceof CompItem) {
        var sel = comp.selectedLayers, minIn = 9e9, maxOut = -9e9;

        if (sel.length === 0) {
            minIn = 0; maxOut = comp.duration;
        } else {
            for (var i = 0; i < sel.length; i++) {
                var L = sel[i]; if (!L) continue; // 不再排除“眼睛关了”的图层
                if (L.inPoint < minIn)  minIn  = L.inPoint;
                if (L.outPoint > maxOut) maxOut = L.outPoint;
            }
            if (minIn === 9e9) { minIn = 0; maxOut = comp.duration; }
        }

        waStart = clamp(minIn, 0, Math.max(0, comp.duration));
        waDur   = Math.max(0.001, maxOut - minIn);
        comp.workAreaStart    = clamp(waStart, 0, Math.max(0, comp.duration));
        comp.workAreaDuration = clamp(waDur,  0.001, Math.max(0.001, comp.duration - comp.workAreaStart));
        comp.time = comp.workAreaStart;

        haveRef = true;
    }

    if (!haveRef) {
        var projSel = app.project.selection || [];
        for (var s = 0; s < projSel.length; s++) {
            var it = projSel[s];
            if (it instanceof CompItem) {
                waStart = it.workAreaStart || 0;
                waDur   = (it.workAreaDuration > 0 ? it.workAreaDuration : Math.max(0.001, it.duration));
                haveRef = true;
                break;
            }
        }
        if (!haveRef) { alert("请先进入一个合成，或在项目面板选中至少一个合成~"); app.endUndoGroup(); return; }
    }

    function alignCompWorkArea(tComp, refStart, refDur) {
        if (!(tComp instanceof CompItem)) return;

        var start = (ANCHOR_MODE === "matchActive") ? refStart
                  : (ANCHOR_MODE === "zero")       ? 0
                  :                                  tComp.workAreaStart;

        start = clamp(start, 0, Math.max(0, tComp.duration - 0.001));
        var maxDur = Math.max(0, tComp.duration - start);
        var dur = Math.min(Math.max(0.001, refDur), Math.max(0.001, maxDur));

        if (dur <= 0.001 && maxDur <= 0 && tComp.duration > 0 && ANCHOR_MODE === "keep") {
            start = Math.max(0, tComp.duration - 0.001);
            maxDur = Math.max(0, tComp.duration - start);
            dur = Math.max(0.001, Math.min(refDur, maxDur));
        }

        start = clamp(start, 0, Math.max(0, tComp.duration));
        dur   = clamp(dur,   0.001, Math.max(0.001, tComp.duration - start));

        tComp.workAreaStart    = start;
        tComp.workAreaDuration = dur;
    }

    if (comp instanceof CompItem) {
        var layers = comp.selectedLayers || [];
        for (var j = 0; j < layers.length; j++) {
            var Lj = layers[j];
            if (Lj && Lj.source && (Lj.source instanceof CompItem)) {
                alignCompWorkArea(Lj.source, waStart, waDur);
            }
        }
    }

    var items = app.project.selection || [];
    for (var k = 0; k < items.length; k++) {
        if (items[k] instanceof CompItem) {
            alignCompWorkArea(items[k], waStart, waDur);
        }
    }

    app.endUndoGroup();
})(); 