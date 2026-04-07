/* Mask Crop — 按蒙版裁剪合成 (CLI版) */
(function(){
var cmdNames = ["Auto Crop", "Auto Crop Duration", "Mask Crop", "Auto Crop Preferences"];
var id = 0;
var names = cmdNames.slice();
while (id === 0 && names.length) { id = app.findMenuCommandId(names.shift()); }
if (id === 0) return "ERR:Auto Crop plugin not installed";
app.preferences.savePrefAsLong("Auto_Crop", "Menu_Cmd", id);
app.preferences.savePrefAsLong("Auto_Crop", "Panel_Run", 3);
return "mask_crop_triggered";
})()
