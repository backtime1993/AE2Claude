(function(thisObj) {
    var win = (thisObj instanceof Panel) ? thisObj : new Window("palette", "Comp Pin", undefined, {resizeable: true});
    var btnAdd = win.add("button", undefined, "固定选中的合成");
    var scrollGroup = win.add("group", undefined, "ScrollGroup");
    scrollGroup.orientation = "column";
    scrollGroup.alignChildren = ["fill", "top"];

    btnAdd.onClick = function() {
        var items = app.project.selection;
        for (var i = 0; i < items.length; i++) {
            if (items[i] instanceof CompItem) {
                createCompBtn(items[i]);
            }
        }
        win.layout.layout(true);
    };

    function createCompBtn(comp) {
        var btn = scrollGroup.add("button", undefined, comp.name);
        btn.helpTip = "点击跳转至: " + comp.name;
        btn.onClick = function() {
            comp.openInViewer(); // 核心：一键响应打开
        };
    }

    win.onResizing = win.onResize = function() { this.layout.resize(); };
    if (win instanceof Window) win.show();
})(this);