/* 效果: Bokeh (matchName: CROSSPHERE_Bokeh) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add Bokeh");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("CROSSPHERE_Bokeh"); } catch(e) {}
}
app.endUndoGroup();
return "added:Bokeh:" + sel.length;
})()
