/* 效果: F's SelectColor (matchName: F's SelectColor) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add F's SelectColor");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("F's SelectColor"); } catch(e) {}
}
app.endUndoGroup();
return "added:F's SelectColor:" + sel.length;
})()
