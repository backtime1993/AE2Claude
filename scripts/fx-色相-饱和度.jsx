/* 效果: 色相/饱和度 (matchName: ADBE HUE SATURATION) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add 色相/饱和度");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("ADBE HUE SATURATION"); } catch(e) {}
}
app.endUndoGroup();
return "added:色相/饱和度:" + sel.length;
})()
