/* 效果: S_Posterize (matchName: S_Posterize) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add S_Posterize");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("S_Posterize"); } catch(e) {}
}
app.endUndoGroup();
return "added:S_Posterize:" + sel.length;
})()
