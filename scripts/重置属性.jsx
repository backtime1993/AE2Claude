(function(thisObj) {
    // 创建UI界面
    var win = (thisObj instanceof Panel) ? thisObj : new Window("palette", "Smart Camera Binder", undefined, {resizeable: true});
    win.orientation = "column";
    
    var btnStore = win.add("button", undefined, "1. 储存主摄像机 (源)");
    var btnBind = win.add("button", undefined, "2. 智能绑定/修复链接");
    var groupInfo = win.add("group");
    var infoText = groupInfo.add("statictext", undefined, "未选择源...");
    groupInfo.alignment = "left";
    
    // 全局变量用于储存源信息
    var sourceData = { compName: "", layerName: "" };

    // 1. 储存功能
    btnStore.onClick = function() {
        var comp = app.project.activeItem;
        if (!comp || !(comp instanceof CompItem)) return alert("请先打开一个合成");
        if (comp.selectedLayers.length === 0) return alert("请选择一个摄像机层");
        
        sourceData.compName = comp.name;
        sourceData.layerName = comp.selectedLayers[0].name;
        infoText.text = "源: " + sourceData.layerName;
    };

    // 封装函数：只在没有表达式时应用表达式（实现“其余不变”）
    function applySmartExpression(prop, expCode) {
        if (!prop) return;
        // 如果属性没有表达式，或者表达式被禁用了，则重新应用
        if (!prop.expressionEnabled || prop.expression === "") {
            prop.expression = expCode;
        }
        // 如果属性已有表达式，则跳过（保持不变）
    }

    // 2. 绑定/修复功能
    btnBind.onClick = function() {
        if (sourceData.compName === "") return alert("请先执行第一步储存信息");
        
        var comp = app.project.activeItem;
        var layers = comp.selectedLayers;
        if (!comp || layers.length === 0) return alert("请选择目标摄像机");

        app.beginUndoGroup("Smart Bind Camera");
        
        // 构建表达式前缀
        var expPrefix = 'comp("' + sourceData.compName + '").layer("' + sourceData.layerName + '")';

        for (var i = 0; i < layers.length; i++) {
            var layer = layers[i];
            
            // --- 变换属性 ---
            applySmartExpression(layer.transform.pointOfInterest, expPrefix + '.transform.pointOfInterest');
            applySmartExpression(layer.transform.position, expPrefix + '.transform.position');
            applySmartExpression(layer.transform.orientation, expPrefix + '.transform.orientation');
            
            // 旋转
            applySmartExpression(layer.transform.xRotation, expPrefix + '.transform.xRotation');
            applySmartExpression(layer.transform.yRotation, expPrefix + '.transform.yRotation');
            applySmartExpression(layer.transform.zRotation, expPrefix + '.transform.zRotation');

            // --- 缩放/变焦处理 ---
            // 注意：摄像机通常使用 "Zoom" (变焦) 作为缩放概念
            // 如果您指的是普通图层的 "Scale"，脚本也会尝试绑定
            applySmartExpression(layer.transform.scale, expPrefix + '.transform.scale');

            // --- 摄像机选项 ---
            if (layer.cameraOption) {
                applySmartExpression(layer.cameraOption.zoom, expPrefix + '.cameraOption.zoom'); // 变焦 (对应摄像机的缩放)
                applySmartExpression(layer.cameraOption.focusDistance, expPrefix + '.cameraOption.focusDistance');
                applySmartExpression(layer.cameraOption.aperture, expPrefix + '.cameraOption.aperture');
            }
        }
        
        app.endUndoGroup();
        // 更新提示但不弹窗打扰
        infoText.text = "链接已检查/修复";
    };

    if (win instanceof Window) { win.center(); win.show(); }

})(this);