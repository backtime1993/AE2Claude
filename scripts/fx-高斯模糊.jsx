/* 效果: 高斯模糊 (matchName: ADBE Gaussian Blur 2) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add 高斯模糊");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("ADBE Gaussian Blur 2"); } catch(e) {}
}
app.endUndoGroup();
return "added:高斯模糊:" + sel.length;
})()
