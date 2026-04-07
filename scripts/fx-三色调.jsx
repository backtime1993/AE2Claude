/* 效果: 三色调 (matchName: ADBE Tritone) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add 三色调");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("ADBE Tritone"); } catch(e) {}
}
app.endUndoGroup();
return "added:三色调:" + sel.length;
})()
