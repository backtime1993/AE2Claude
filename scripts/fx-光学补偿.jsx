/* 效果: 光学补偿 (matchName: ADBE Optics Compensation) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add 光学补偿");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("ADBE Optics Compensation"); } catch(e) {}
}
app.endUndoGroup();
return "added:光学补偿:" + sel.length;
})()
