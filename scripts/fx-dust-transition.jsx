/* 效果: Dust Transition (matchName: irrealix Dust Transition) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add Dust Transition");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("irrealix Dust Transition"); } catch(e) {}
}
app.endUndoGroup();
return "added:Dust Transition:" + sel.length;
})()
