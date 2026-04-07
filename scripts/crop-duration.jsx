/* Crop Duration — 裁剪合成时长到内容范围 (CLI版)
   ⚠️ 坑: 同 auto-crop，必须取消选择 */
(function(){
var id = app.findMenuCommandId("Auto Crop");
if (id === 0) return "ERR:Auto Crop plugin not installed";
var c = app.project.activeItem;
if (!c || !(c instanceof CompItem)) return "ERR:no_comp";
app.preferences.savePrefAsLong("Auto_Crop", "Menu_Cmd", id);
app.preferences.savePrefAsLong("Auto_Crop", "Panel_Run", 2);
for(var i=1;i<=c.numLayers;i++) c.layer(i).selected=false;
app.executeCommand(id);
return "crop_duration_done";
})()
