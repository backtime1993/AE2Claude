/* 效果: BCC 波形 (matchName: BCC3Wave) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add BCC 波形");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("BCC3Wave"); } catch(e) {}
}
app.endUndoGroup();
return "added:BCC 波形:" + sel.length;
})()
