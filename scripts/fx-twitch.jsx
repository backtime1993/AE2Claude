/* 效果: Twitch (matchName: Videocopilot Twitch) */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
app.beginUndoGroup("Add Twitch");
for (var i = 0; i < sel.length; i++) {
    try { sel[i].property("Effects").addProperty("Videocopilot Twitch"); } catch(e) {}
}
app.endUndoGroup();
return "added:Twitch:" + sel.length;
})()
