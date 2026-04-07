/* 效果: Grow Bounds */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add Grow Bounds");
for (var i = 0; i < sel.length; i++) {
    sel[i].property("Effects").addProperty("Red Giant GrowBounds");
}
app.endUndoGroup();
return "added:" + sel.length;
})()
