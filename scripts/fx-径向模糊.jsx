/* 效果: 径向模糊 (matchName: ADBE Radial Blur) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add 径向模糊");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("ADBE Radial Blur"); } catch(e) {}
}
app.endUndoGroup();
return "added:径向模糊:" + sel.length;
})()
