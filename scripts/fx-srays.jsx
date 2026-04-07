/* 效果: S_Rays (matchName: S_Rays) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add S_Rays");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("S_Rays"); } catch(e) {}
}
app.endUndoGroup();
return "added:S_Rays:" + sel.length;
})()
