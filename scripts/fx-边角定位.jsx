/* 效果: 边角定位 (matchName: ADBE Corner Pin) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add 边角定位");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("ADBE Corner Pin"); } catch(e) {}
}
app.endUndoGroup();
return "added:边角定位:" + sel.length;
})()
