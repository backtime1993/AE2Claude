/* 效果: Quick Chromatic Aberration 3 (matchName: PEQCAGL) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add Quick Chromatic Aberration 3");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("PEQCAGL"); } catch(e) {}
}
app.endUndoGroup();
return "added:Quick Chromatic Aberration 3:" + sel.length;
})()
