/* 效果: Deep Glow 2 (matchName: PEDG2) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add Deep Glow 2");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("PEDG2"); } catch(e) {}
}
app.endUndoGroup();
return "added:Deep Glow 2:" + sel.length;
})()
