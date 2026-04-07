/* Auto Crop — 自动裁剪合成到内容边界 (CLI版)
   调用 Auto Crop 原生插件，参数通过 __auto_crop_mode__ 传入:
   1 = Auto Crop (裁剪到内容)
   2 = Crop Duration (裁剪时长)
   3 = Mask Crop (蒙版裁剪)
   4 = Preferences */
(function(){
var mode = typeof __auto_crop_mode__ !== "undefined" ? __auto_crop_mode__ : 1;
var cmdNames = ["Auto Crop", "Auto Crop Duration", "Mask Crop", "Auto Crop Preferences"];
var id = 0;
var names = cmdNames.slice();
while (id === 0 && names.length) { id = app.findMenuCommandId(names.shift()); }
if (id === 0) return "ERR:Auto Crop plugin not installed";
app.preferences.savePrefAsLong("Auto_Crop", "Menu_Cmd", id);
app.preferences.savePrefAsLong("Auto_Crop", "Panel_Run", mode);
return "auto_crop_mode:" + mode;
})()
