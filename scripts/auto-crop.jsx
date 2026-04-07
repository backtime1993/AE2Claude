/* Auto Crop — 自动裁剪合成到内容边界 (CLI版)
   ⚠️ 坑: 必须取消所有图层选择，否则报 "Invalid Selection"
   ⚠️ 坑: Shape 图层不支持，需要有像素内容的图层(solid/footage/预合成) */
(function(){
var id = app.findMenuCommandId("Auto Crop");
if (id === 0) return "ERR:Auto Crop plugin not installed";
var c = app.project.activeItem;
if (!c || !(c instanceof CompItem)) return "ERR:no_comp";
app.preferences.savePrefAsLong("Auto_Crop", "Menu_Cmd", id);
app.preferences.savePrefAsLong("Auto_Crop", "Panel_Run", 1);
for(var i=1;i<=c.numLayers;i++) c.layer(i).selected=false;
app.executeCommand(id);
return "auto_crop_done";
})()
