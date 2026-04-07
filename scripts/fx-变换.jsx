/* 效果: 变换 (matchName: ADBE Geometry2) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add 变换");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("ADBE Geometry2"); } catch(e) {}
}
app.endUndoGroup();
return "added:变换:" + sel.length;
})()
