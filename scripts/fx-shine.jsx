/* 效果: Shine (matchName: tc Shine) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add Shine");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("tc Shine"); } catch(e) {}
}
app.endUndoGroup();
return "added:Shine:" + sel.length;
})()
