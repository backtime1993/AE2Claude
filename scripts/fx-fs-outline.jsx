/* 效果: F's OutLine (matchName: F's OutLine) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add F's OutLine");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("F's OutLine"); } catch(e) {}
}
app.endUndoGroup();
return "added:F's OutLine:" + sel.length;
})()
