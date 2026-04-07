/* 效果: 反转 (matchName: ADBE Invert) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add 反转");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("ADBE Invert"); } catch(e) {}
}
app.endUndoGroup();
return "added:反转:" + sel.length;
})()
