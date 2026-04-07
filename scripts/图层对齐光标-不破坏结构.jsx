(function () {
  app.beginUndoGroup("Shift to CTI (Smart)");
  var comp = app.project.activeItem;
  if (!comp || comp.selectedLayers.length === 0) return;

  var selectedLayers = comp.selectedLayers;
  // __mode__: "default" = 左对齐(最小inPoint→CTI), "ctrl" = 右对齐(最大outPoint→CTI)
  var mode = (typeof __mode__ !== "undefined") ? __mode__ : "default";
  var isCtrl = (mode === "ctrl");
  
  // 如果按 Ctrl 找最大 outPoint (右对齐)，否则找最小 inPoint (左对齐)
  var refTime = isCtrl ? -Infinity : Infinity;

  for (var i = 0; i < selectedLayers.length; i++) {
    var layer = selectedLayers[i];
    if (isCtrl) {
      if (layer.outPoint > refTime) refTime = layer.outPoint;
    } else {
      if (layer.inPoint < refTime) refTime = layer.inPoint;
    }
  }

  // 计算移动差值
  var diff = comp.time - refTime;

  // 应用位移
  for (var i = 0; i < selectedLayers.length; i++) {
    selectedLayers[i].startTime += diff;
  }

  app.endUndoGroup();
})();