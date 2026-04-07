/* 效果: P_Gradient (matchName: PSOFT GRADIENT) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add P_Gradient");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("PSOFT GRADIENT"); } catch(e) {}
}
app.endUndoGroup();
return "added:P_Gradient:" + sel.length;
})()
