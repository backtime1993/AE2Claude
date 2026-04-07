/* 表达式: 循环100 — 应用到选中属性 */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
var expr = "time*100";
var count = 0;
for (var i = 0; i < sel.length; i++) {
    var props = sel[i].selectedProperties;
    if (props.length > 0) {
        for (var p = 0; p < props.length; p++) {
            if (props[p].canSetExpression) { props[p].expression = expr; count++; }
        }
    }
}
if (count === 0) return "ERR:no_property_selected";
return "applied:" + count;
})()
