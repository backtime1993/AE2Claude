/* 效果: CC Ball Action (matchName: CC Ball Action) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add CC Ball Action");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("CC Ball Action"); } catch(e) {}
}
app.endUndoGroup();
return "added:CC Ball Action:" + sel.length;
})()
