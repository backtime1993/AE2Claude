/* 效果: Optical Flares (matchName: VIDEOCOPILOT OpticalFlares) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add Optical Flares");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("VIDEOCOPILOT OpticalFlares"); } catch(e) {}
}
app.endUndoGroup();
return "added:Optical Flares:" + sel.length;
})()
