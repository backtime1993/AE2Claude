/* Mask Crop — 按蒙版边界裁剪合成 (CLI版)
   ⚠️ 坑: 同 auto-crop，必须取消选择
   ⚠️ 用法: 先给图层画好蒙版，再执行此命令 */
(function(){
var id = app.findMenuCommandId("Auto Crop");
if (id === 0) return "ERR:Auto Crop plugin not installed";
var c = app.project.activeItem;
if (!c || !(c instanceof CompItem)) return "ERR:no_comp";
app.preferences.savePrefAsLong("Auto_Crop", "Menu_Cmd", id);
app.preferences.savePrefAsLong("Auto_Crop", "Panel_Run", 3);
for(var i=1;i<=c.numLayers;i++) c.layer(i).selected=false;
app.executeCommand(id);
return "mask_crop_done";
})()
