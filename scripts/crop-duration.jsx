/* Crop Duration — 裁剪合成时长到内容 (CLI版) */
(function(){
var id = app.findMenuCommandId("Auto Crop");
if (id === 0) return "ERR:Auto Crop plugin not installed";
app.preferences.savePrefAsLong("Auto_Crop", "Menu_Cmd", id);
app.preferences.savePrefAsLong("Auto_Crop", "Panel_Run", 2);
for(var i=1;i<=app.project.activeItem.numLayers;i++)app.project.activeItem.layer(i).selected=false;app.executeCommand(id);
return "crop_duration_done";
})()
