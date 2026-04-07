var comp = app.project.activeItem;

if (comp && comp.selectedLayers.length > 0) {
    app.beginUndoGroup("Auto-Link Position Fade");
    var layers = comp.selectedLayers;
    var successCount = 0;

    for (var i = 0; i < layers.length; i++) {
        var layer = layers[i];
        
        // --- 1. 自动判定驱动属性 ---
        // 优先找位置，兼容“单独尺寸”
        var driverCode = "";
        var pos = layer.transform.position;
        var xPos = layer.transform.xPosition;

        // 逻辑：如果是单独尺寸，追踪 X轴；否则追踪 Position 整体
        if (pos.dimensionsSeparated) {
            // 只要 X 或 Y 有关键帧，就以 X 为时间基准
            if (xPos.numKeys > 0 || layer.transform.yPosition.numKeys > 0) {
                driverCode = "transform.xPosition"; 
            }
        } else {
            if (pos.numKeys > 0) {
                driverCode = "transform.position";
            }
        }

        // 如果位置没关键帧，检查是否用户手动选了缩放或旋转
        if (driverCode === "") {
            var props = layer.selectedProperties;
            for (var p = 0; p < props.length; p++) {
                if (props[p].matchName === "ADBE Scale" && props[p].numKeys > 0) driverCode = "transform.scale";
                if (props[p].matchName === "ADBE Rotate Z" && props[p].numKeys > 0) driverCode = "transform.rotation";
            }
        }

        // --- 2. 设置标记 (仅初始化位置) ---
        // 为了确定标记放哪，我们需要读取一次关键帧时间
        var initStart = layer.inPoint;
        var initEnd = layer.outPoint;

        if (driverCode === "transform.position") {
            initStart = pos.key(1).time;
            initEnd = pos.key(pos.numKeys).time;
        } else if (driverCode === "transform.xPosition") {
            initStart = xPos.key(1).time;
            initEnd = xPos.key(xPos.numKeys).time;
        }
        
        // 放置 FI / FO 标记
        var fadeDur = 0.5;
        if (initEnd - initStart < 1.0) fadeDur = (initEnd - initStart) / 3;

        var markerProp = layer.property("Marker");
        var m1 = new MarkerValue("FI");
        var m2 = new MarkerValue("FO");

        // 删除旧标记防止堆积
        while (markerProp.numKeys > 0) markerProp.removeKey(1);
        
        markerProp.setValueAtTime(initStart + fadeDur, m1);
        markerProp.setValueAtTime(initEnd - fadeDur, m2);

        // --- 3. 写入可调透明度的表达式 ---
        var expr = "";
        
        if (driverCode !== "") {
            expr =
                "// 自动追踪: " + driverCode + "\n" +
                "try {\n" +
                "    var driver = " + driverCode + ";\n" +
                "    if (driver.numKeys > 0) {\n" +
                "        var tStart = driver.key(1).time;\n" +
                "        var tEnd = driver.key(driver.numKeys).time;\n" +
                "    } else {\n" +
                "        // 有属性但没关键帧，回退\n" +
                "        var tStart = inPoint; var tEnd = outPoint;\n" +
                "    }\n" +
                "} catch(e) { var tStart = inPoint; var tEnd = outPoint; }\n";
        } else {
            expr =
                "// 未检测到关键帧，使用图层入出点\n" +
                "var tStart = inPoint;\n" +
                "var tEnd = outPoint;\n";
        }

        // 新增：通过 Slider 控制透明度最小/最大
        expr +=
            "\n" +
            "var opMin = 0;\n" +
            "var opMax = 100;\n" +
            "try {\n" +
            "    if (effect(\"Fade Min\") != null) opMin = effect(\"Fade Min\")(\"Slider\");\n" +
            "    if (effect(\"Fade Max\") != null) opMax = effect(\"Fade Max\")(\"Slider\");\n" +
            "} catch (e) {}\n" +
            "\n";

        // 标记控制逻辑不变，只把 0/100 换成 opMin/opMax
        expr +=
            "if (marker.numKeys > 0) {\n" +
            "    var mIn = marker.key(1).time;\n" +
            "    // 找最后一个标记作为 FO\n" +
            "    var mOut = marker.key(marker.numKeys).time;\n" +
            "    if (marker.numKeys === 1) mOut = mIn;\n" +
            "\n" +
            "    if (time < mIn) linear(time, tStart, mIn, opMin, opMax);\n" +
            "    else if (time > mOut) linear(time, mOut, tEnd, opMax, opMin);\n" +
            "    else opMax;\n" +
            "} else {\n" +
            "    value;\n" +
            "}";

        layer.property("Opacity").expression = expr;
        successCount++;
    }
    app.endUndoGroup();
} else {
    alert("请先选择图层！");
}