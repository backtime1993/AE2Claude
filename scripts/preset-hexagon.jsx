/* 预设: Shape_六边形平铺 */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
for (var i = 0; i < sel.length; i++) {
    sel[i].applyPreset(new File("C:/Program Files/Adobe/Adobe After Effects (Beta)/Support Files/Presets/Shape_六边形平铺.ffx"));
}
return "preset_applied:" + sel.length;
})()
