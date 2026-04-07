/* Comp Trimmer — 裁尾 (CLI版，完整原版逻辑)
   无选中层: 裁合成duration到光标+1帧
   选中预合成层: 裁预合成内部duration
   ⚠️ 坑: 选中非预合成层(solid/text等)会返回 ERR:not_all_comps
   ⚠️ 用法: 要裁合成本身就不选任何层；要裁嵌套预合成就选中预合成层 */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var currentTime = comp.time + comp.frameDuration;
var selectedLayers = comp.selectedLayers;
if (selectedLayers.length === 0) {
    if (comp.time > 0) {
        app.beginUndoGroup("Trim End");
        comp.duration = currentTime;
        app.endUndoGroup();
        return "trimmed_comp:" + currentTime;
    }
    return "ERR:time_is_0";
}
var allAreCompLayers = true;
for (var i = 0; i < selectedLayers.length; i++) {
    if (!(selectedLayers[i].source instanceof CompItem)) { allAreCompLayers = false; break; }
}
if (!allAreCompLayers) return "ERR:not_all_comps";
app.beginUndoGroup("Trim Comp End");
try {
    for (var i = 0; i < selectedLayers.length; i++) {
        var layer = selectedLayers[i];
        var layerStartTime = layer.startTime;
        if (currentTime <= layerStartTime) continue;
        var layerOutPoint = layer.outPoint;
        var oriEndTime = layerStartTime + layer.source.duration;
        layer.source.duration = currentTime - layerStartTime;
        if (Math.abs(layerOutPoint - oriEndTime) < 0.001) {
            layer.outPoint = currentTime;
        }
    }
} catch (e) { return "ERR:" + e.toString(); }
app.endUndoGroup();
return "trimmed_end:" + currentTime;
})()
