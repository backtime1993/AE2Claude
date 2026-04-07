/* 效果: RSMB Pro (matchName: RS Motion Blur Pro A 3.x) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add RSMB Pro");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("RS Motion Blur Pro A 3.x"); } catch(e) {}
}
app.endUndoGroup();
return "added:RSMB Pro:" + sel.length;
})()
