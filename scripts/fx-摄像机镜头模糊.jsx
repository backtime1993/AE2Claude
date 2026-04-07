/* 效果: 摄像机镜头模糊 (matchName: ADBE Camera Lens Blur) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add 摄像机镜头模糊");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("ADBE Camera Lens Blur"); } catch(e) {}
}
app.endUndoGroup();
return "added:摄像机镜头模糊:" + sel.length;
})()
