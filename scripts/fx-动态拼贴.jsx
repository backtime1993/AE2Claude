/* 效果: 动态拼贴 (matchName: ADBE Tile) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add 动态拼贴");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("ADBE Tile"); } catch(e) {}
}
app.endUndoGroup();
return "added:动态拼贴:" + sel.length;
})()
