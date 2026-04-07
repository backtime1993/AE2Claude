/* 效果: FL Depth Of Field (matchName: DRFL Depth of Field) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add FL Depth Of Field");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("DRFL Depth of Field"); } catch(e) {}
}
app.endUndoGroup();
return "added:FL Depth Of Field:" + sel.length;
})()
