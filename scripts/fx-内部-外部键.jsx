/* 效果: 内部/外部键 (matchName: ADBE ATG Extract) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add 内部/外部键");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("ADBE ATG Extract"); } catch(e) {}
}
app.endUndoGroup();
return "added:内部/外部键:" + sel.length;
})()
