(function() {
    var comp = app.project.activeItem;
    // 检查选中项
    if (!comp || comp.selectedProperties.length === 0) {
        alert("请先选中属性（点击属性名称选中）！");
        return;
    }

    app.beginUndoGroup("Create Time Controller");

    var props = comp.selectedProperties;
    var minTime = 999999;
    var maxTime = -999999;
    var validProps = [];
    
    // 获取第一个选中属性所属的图层，确保空对象生成在这个图层上方
    var targetLayer = null;
    try {
        if (props[0].propertyGroup) {
            targetLayer = props[0].propertyGroup(props[0].propertyDepth); 
        }
    } catch(e) {
        // 如果获取失败，尝试用选中图层
        if(comp.selectedLayers.length > 0) targetLayer = comp.selectedLayers[0];
    }
    
    // 如果还是找不到（极少情况），默认放在第一层
    if (!targetLayer) targetLayer = comp.layer(1);


    // 1. 计算时间范围
    for (var i = 0; i < props.length; i++) {
        if (props[i].canSetExpression && props[i].numKeys > 0) {
            validProps.push(props[i]);
            minTime = Math.min(minTime, props[i].keyTime(1));
            maxTime = Math.max(maxTime, props[i].keyTime(props[i].numKeys));
        }
    }

    if (validProps.length === 0) {
        alert("未检测到关键帧，请确保选中的是包含关键帧的属性。");
        return;
    }

    // 2. 创建控制层
    var ctrlLayer = comp.layers.addNull();
    ctrlLayer.name = "Time_Ctrl";
    // 关键修正：精确移动到目标图层之前
    ctrlLayer.moveBefore(targetLayer); 
    
    // 3. 添加滑块
    var sliderEffect = ctrlLayer.Effects.addProperty("ADBE Slider Control");
    sliderEffect.name = "Progress";
    var sliderProp = sliderEffect.property(1);

    // 4. 设置滑块关键帧 (0对应最早时间，100对应最晚时间)
    // 这样初始状态下，动画看起来和原来一模一样
    sliderProp.setValueAtTime(minTime, 0);
    sliderProp.setValueAtTime(maxTime, 100);

    // 5. 添加表达式
    for (var i = 0; i < validProps.length; i++) {
        var p = validProps[i];
        
        var expr = 'var ctrl = thisComp.layer("' + ctrlLayer.name + '").effect("' + sliderEffect.name + '")(1);\n';
        expr += '// 记录原始关键帧范围\n';
        expr += 'var tStart = ' + minTime + ';\n';
        expr += 'var tEnd = ' + maxTime + ';\n';
        expr += 'var duration = tEnd - tStart;\n';
        expr += '// 线性重映射: 0->Start, 100->End\n';
        expr += 'var mappedTime = tStart + (ctrl / 100) * duration;\n';
        expr += 'valueAtTime(mappedTime);';

        p.expression = expr;
    }

    app.endUndoGroup();
})();