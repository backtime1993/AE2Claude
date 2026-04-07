/* 效果: Boa (matchName: BAO_Boa) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add Boa");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("BAO_Boa"); } catch(e) {}
}
app.endUndoGroup();
return "added:Boa:" + sel.length;
})()
