(function() {
      var comp = app.project.activeItem;
      if (!(comp instanceof CompItem)) return;

      var sel = comp.selectedLayers;
      if (sel.length === 0) return;

      app.beginUndoGroup("匹配父合成分辨率并回正");

      var parentW = comp.width;
      var parentH = comp.height;

      for (var i = 0; i < sel.length; i++) {
          var layer = sel[i];
          if (!layer.source) continue;

          if (layer.source instanceof CompItem) {
              layer.source.width = parentW;
              layer.source.height = parentH;
              layer.scale.setValue([100, 100]);
              layer.anchorPoint.setValue([parentW / 2, parentH / 2]);
              layer.position.setValue([parentW / 2, parentH / 2]);
          } else {
              var srcW = layer.source.width;
              var srcH = layer.source.height;
              layer.scale.setValue([(parentW / srcW) * 100, (parentH / srcH) *
  100]);
              layer.anchorPoint.setValue([srcW / 2, srcH / 2]);
              layer.position.setValue([parentW / 2, parentH / 2]);
          }
      }

      app.endUndoGroup();
  })();
