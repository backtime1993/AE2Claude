(function(thisObj) {

    function buildUI(container) {

        var panel = (container instanceof Panel) ? container : new Window("palette", "FastCopy", undefined, {resizeable: true});

        panel.orientation = "column";

        panel.margins = 10;

        panel.spacing = 8;



        var btnGroup = panel.add("group");

        var btnCopy = btnGroup.add("button", [0, 0, 80, 30], "复制");

        var btnPaste = btnGroup.add("button", [0, 0, 80, 30], "粘贴");



        // 确保宽度足够显示“缓存 X”

        var statusLabel = panel.add("statictext", [0, 0, 160, 20], "准备就绪");

        statusLabel.justify = "center"; 



        // 复制：记录图层和绝对入点基准

        btnCopy.onClick = function() {

            var comp = app.project.activeItem;

            if (comp && comp instanceof CompItem && comp.selectedLayers.length > 0) {

                $._layerBuffer = comp.selectedLayers;

                

                // 找到这一组图层中最靠左的视觉入点 (refTime)

                var minIn = Infinity;

                for (var i = 0; i < $._layerBuffer.length; i++) {

                    if ($._layerBuffer[i].inPoint < minIn) minIn = $._layerBuffer[i].inPoint;

                }

                $._layerRefTime = minIn; 

                

                statusLabel.text = "缓存 " + $._layerBuffer.length;

            } else {

                statusLabel.text = "未选中图层";

            }

        };



        // 粘贴：应用你提供的 diff 算法

        btnPaste.onClick = function() {

            var targetComp = app.project.activeItem;

            if (targetComp && targetComp instanceof CompItem && $._layerBuffer && $._layerBuffer.length > 0) {

                app.beginUndoGroup("Fast Paste Align");

                

                // 计算移动差值：当前时间轴位置 - 复制时的基准入点

                var diff = targetComp.time - $._layerRefTime;



                // 倒序粘贴以保持原始上下层级

                for (var i = $._layerBuffer.length - 1; i >= 0; i--) {

                    try {

                        var sourceLayer = $._layerBuffer[i];

                        var newLayer = sourceLayer.copyToComp(targetComp);

                        

                        // 直接应用你给出的位移逻辑

                        newLayer.startTime += diff;

                    } catch (e) {

                        continue; // 防止源图层被删除导致脚本报错

                    }

                }

                

                app.endUndoGroup();

                statusLabel.text = "粘贴完成";

            } else {

                statusLabel.text = "缓存为空";

            }

        };



        panel.layout.layout(true);

        return panel;

    }



    var myPanel = buildUI(thisObj);

    if (myPanel instanceof Window) myPanel.show();

})(this);