/* 效果: loopFlow (matchName: irrealix loopFlow) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add loopFlow");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("irrealix loopFlow"); } catch(e) {}
}
app.endUndoGroup();
return "added:loopFlow:" + sel.length;
})()
