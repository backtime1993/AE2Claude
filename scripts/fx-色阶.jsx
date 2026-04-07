/* 效果: 色阶 (matchName: ADBE Easy Levels2) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add 色阶");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("ADBE Easy Levels2"); } catch(e) {}
}
app.endUndoGroup();
return "added:色阶:" + sel.length;
})()
