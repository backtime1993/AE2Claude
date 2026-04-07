/* 效果: 曲线 (matchName: ADBE CurvesCustom) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add 曲线");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("ADBE CurvesCustom"); } catch(e) {}
}
app.endUndoGroup();
return "added:曲线:" + sel.length;
})()
