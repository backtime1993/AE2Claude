(function () {
    var comp = app.project.activeItem;
    if (!(comp instanceof CompItem) || !comp.selectedLayers.length) return;

    app.beginUndoGroup("Replace Precomp with New Source");

    var sourceMap = {}; // 用于记录已复制过的源，防止重复创建

    function numToAlpha(n) {
        var s = "";
        while (n >= 0) { s = String.fromCharCode((n % 26) + 97) + s; n = Math.floor(n / 26) - 1; }
        return s;
    }

    function makeAlphaName(oldName) {
        var base = oldName.replace(/_[a-z]{1,2}$/, "");
        var counter = 1, candidate;
        do {
            candidate = base + "_" + numToAlpha(counter++);
        } while ((function(name){
            for (var i = 1; i <= app.project.numItems; i++) 
                if (app.project.item(i).name === name) return true;
            return false;
        })(candidate));
        return candidate;
    }

    var sel = comp.selectedLayers;
    for (var i = 0; i < sel.length; i++) {
        var L = sel[i];
        if (!(L instanceof AVLayer) || !(L.source instanceof CompItem)) continue;

        var src = L.source;
        var newComp;

        // 如果该源在此次操作中还没被复制过，则创建新源
        if (!sourceMap[src.id]) {
            newComp = src.duplicate();
            newComp.name = makeAlphaName(src.name);
            sourceMap[src.id] = newComp;
        } else {
            // 如果已存在，直接复用
            newComp = sourceMap[src.id];
        }

        // 直接替换原图层源，不复制图层
        L.replaceSource(newComp, true);
        L.name = newComp.name;
    }

    app.endUndoGroup();
})();