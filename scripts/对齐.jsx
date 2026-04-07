/* Bridge Two Layers v1.7
     基于 v1.6_fast 优化：
     - 贝塞尔 ease speed 随时间缩放等比调整，保持曲线形状
     - 清理冗余变量和数组预分配
  */
  (function () {
      app.beginUndoGroup("Bridge Two Layers v1.7");

      var comp = app.project.activeItem;
      if (!(comp && comp instanceof CompItem)) { app.endUndoGroup(); return; }

      var fd = comp.frameDuration;
      var T  = Math.round(comp.time / fd) * fd;
      var eps = 2 * fd;

      var sel = comp.selectedLayers;
      if (!sel || sel.length < 2) { app.endUndoGroup(); return; }

      function pickTwoAroundTime(layers, t) {
          var before = null, after = null, d1 = 1e9, d2 = 1e9;
          for (var i = 0; i < layers.length; i++) {
              var L = layers[i];
              if (!L || L.locked || !L.enabled) continue;
              var db = t - L.outPoint; if (db >= 0 && db < d1) { d1 = db; before
   = L; }
              var da = L.inPoint - t;  if (da >= 0 && da < d2) { d2 = da; after
   = L; }
          }
          if (!before || !after) {
              layers.sort(function (a, b) { return a.inPoint - b.inPoint; });
              return [layers[0], layers[1]];
          }
          return [before, after];
      }

      var pair = (sel.length === 2) ? [sel[0], sel[1]] : pickTwoAroundTime(sel,
  T);
      pair.sort(function (a, b) { return a.inPoint - b.inPoint; });
      var A = pair[0], B = pair[1];

      if (T <= A.inPoint + fd) { app.endUndoGroup(); return; }
      if (T >= B.outPoint - fd) { app.endUndoGroup(); return; }

      var A_in0 = A.inPoint, A_out0 = A.outPoint;
      var B_in0 = B.inPoint, B_out0 = B.outPoint;
      var A_oldDur = A_out0 - A_in0, B_oldDur = B_out0 - B_in0;
      if (A_oldDur <= 0 || B_oldDur <= 0) { app.endUndoGroup(); return; }

      var A_newDur = T - A_in0, B_newDur = B_out0 - T;
      var A_scale = A_newDur / A_oldDur, B_scale = B_newDur / B_oldDur;

      function mapA(t0) { return Math.abs(t0 - A_out0) <= eps ? T : A_in0 + (t0
  - A_in0) * A_scale; }
      function mapB(t0) { return Math.abs(t0 - B_in0)  <= eps ? T : B_out0 + (t0
   - B_out0) * B_scale; }

      function forAnimatedProps(group, fn) {
          for (var i = 1; i <= group.numProperties; i++) {
              var p = group.property(i);
              if (!p) continue;
              try {
                  if (p.propertyType === PropertyType.PROPERTY) {
                      if (p.isTimeVarying && p.numKeys > 0) fn(p);
                  } else if (p.numProperties) {
                      forAnimatedProps(p, fn);
                  }
              } catch (e) {}
          }
      }

      // ease speed 等比缩放：压缩时间 → speed 加快，拉伸 → 减慢
      function scaleEase(easeArr, s) {
          var r = [];
          for (var i = 0; i < easeArr.length; i++)
              r.push(new KeyframeEase(easeArr[i].speed / s,
  easeArr[i].influence));
          return r;
      }

      function rebuildKeys(prop, mapTime, timeScale) {
          try {
              if (!prop.isTimeVarying || prop.numKeys < 1) return;

              var ks = [];
              for (var i = 1; i <= prop.numKeys; i++) {
                  var o = { t: prop.keyTime(i) };
                  try { o.v = prop.keyValue(i); } catch (e) { o.v =
  prop.valueAtTime(o.t, true); }
                  o.inType  = prop.keyInInterpolationType(i);
                  o.outType = prop.keyOutInterpolationType(i);

                  var isBez = (o.inType === KeyframeInterpolationType.BEZIER ||
  o.outType === KeyframeInterpolationType.BEZIER);
                  if (isBez) {
                      try { o.inEase  = prop.keyInTemporalEase(i);  } catch (e)
  {}
                      try { o.outEase = prop.keyOutTemporalEase(i); } catch (e)
  {}
                      if (prop.isSpatial) {
                          try { o.inTan  = prop.keyInSpatialTangent(i);  } catch
   (e) {}
                          try { o.outTan = prop.keyOutSpatialTangent(i); } catch
   (e) {}
                          try { o.autoS  = prop.keySpatialAutoBezier(i); } catch
   (e) {}
                          try { o.contS  = prop.keySpatialContinuous(i); } catch
   (e) {}
                          try { o.roving = prop.keyRoving(i);            } catch
   (e) {}
                      }
                      try { o.autoT = prop.keyTemporalAutoBezier(i); } catch (e)
   {}
                      try { o.contT = prop.keyTemporalContinuous(i); } catch (e)
   {}
                  }
                  o.t1 = mapTime(o.t);
                  ks.push(o);
              }

              ks.sort(function (a, b) { return a.t1 - b.t1; });
              var minDelta = fd / 200;
              for (var j = 1; j < ks.length; j++) {
                  if (ks[j].t1 - ks[j - 1].t1 < 1e-7) ks[j].t1 = ks[j - 1].t1 +
  minDelta;
              }

              for (var r = prop.numKeys; r >= 1; r--) { try { prop.removeKey(r);
   } catch (e) {} }

              for (var k = 0; k < ks.length; k++) {
                  var it = ks[k];
                  try {
                      var idx = prop.addKey(it.t1);
                      try { prop.setValueAtKey(idx, it.v); } catch (e) {}
                      try { prop.setInterpolationTypeAtKey(idx, it.inType,
  it.outType); } catch (e) {}

                      var isBez = (it.inType ===
  KeyframeInterpolationType.BEZIER || it.outType ===
  KeyframeInterpolationType.BEZIER);
                      if (isBez) {
                          if (it.inEase && it.outEase) {
                              try { prop.setTemporalEaseAtKey(idx,
  scaleEase(it.inEase, timeScale), scaleEase(it.outEase, timeScale)); } catch
  (e) {}
                          }
                          try { prop.setTemporalAutoBezierAtKey(idx,
  !!it.autoT); } catch (e) {}
                          try { prop.setTemporalContinuousAtKey(idx,
  !!it.contT); } catch (e) {}
                          if (prop.isSpatial) {
                              if (it.inTan && it.outTan) { try {
  prop.setSpatialTangentsAtKey(idx, it.inTan, it.outTan); } catch (e) {} }
                              if (it.autoS !== undefined) { try {
  prop.setSpatialAutoBezierAtKey(idx, !!it.autoS); } catch (e) {} }
                              if (it.contS !== undefined) { try {
  prop.setSpatialContinuousAtKey(idx, !!it.contS); } catch (e) {} }
                              if (it.roving !== undefined) { try {
  prop.setRovingAtKey(idx, !!it.roving); } catch (e) {} }
                          }
                      } else {
                          try { prop.setTemporalAutoBezierAtKey(idx, false); }
  catch (e) {}
                          try { prop.setTemporalContinuousAtKey(idx, false); }
  catch (e) {}
                      }
                  } catch (e) {}
              }
          } catch (e) {}
      }

      forAnimatedProps(A, function (p) { rebuildKeys(p, mapA, A_scale); });
      A.outPoint = T;

      forAnimatedProps(B, function (p) { rebuildKeys(p, mapB, B_scale); });
      B.inPoint  = T;
      B.outPoint = B_out0;

      app.endUndoGroup();
  })();