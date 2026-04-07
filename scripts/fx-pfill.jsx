/* 效果: P_Fill (matchName: PSOFT FILL) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add P_Fill");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("PSOFT FILL"); } catch(e) {}
}
app.endUndoGroup();
return "added:P_Fill:" + sel.length;
})()
