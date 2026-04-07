/* Comp Trimmer — 裁尾：合成结束点→光标+1帧 (CLI版，无GUI) */
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
        return "trimmed_to:" + currentTime;
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
} catch (e) {}
app.endUndoGroup();
return "trimmed_end:" + currentTime;
})()
