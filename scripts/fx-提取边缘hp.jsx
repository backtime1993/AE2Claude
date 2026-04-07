/* 预设: 提取边缘(HP) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Apply 提取边缘(HP)");
var f = new File("C:/Program Files/Adobe/Adobe After Effects (Beta)/Support Files/Presets/提取边缘(HP).ffx");
if (!f.exists) return "ERR:preset_not_found";
for (var i = 0; i < sel.length; i++) {
    sel[i].applyPreset(f);
}
app.endUndoGroup();
return "applied:提取边缘(HP):" + sel.length;
})()
