/* Auto Crop — 自动裁剪合成到内容边界 (CLI版) */
(function(){
var id = app.findMenuCommandId("Auto Crop");
if (id === 0) return "ERR:Auto Crop plugin not installed";
app.preferences.savePrefAsLong("Auto_Crop", "Menu_Cmd", id);
app.preferences.savePrefAsLong("Auto_Crop", "Panel_Run", 1);
for(var i=1;i<=app.project.activeItem.numLayers;i++)app.project.activeItem.layer(i).selected=false;app.executeCommand(id);
return "auto_crop_done";
})()
