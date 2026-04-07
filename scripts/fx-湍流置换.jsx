/* 效果: 湍流置换 (matchName: ADBE Turbulent Displace) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add 湍流置换");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("ADBE Turbulent Displace"); } catch(e) {}
}
app.endUndoGroup();
return "added:湍流置换:" + sel.length;
})()
