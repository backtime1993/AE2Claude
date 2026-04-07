/* 效果: Twixtor Pro (matchName: Twixtor 45) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add Twixtor Pro");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("Twixtor 45"); } catch(e) {}
}
app.endUndoGroup();
return "added:Twixtor Pro:" + sel.length;
})()
