/* 效果: Furikake (matchName: One Chance Furikake) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add Furikake");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("One Chance Furikake"); } catch(e) {}
}
app.endUndoGroup();
return "added:Furikake:" + sel.length;
})()
