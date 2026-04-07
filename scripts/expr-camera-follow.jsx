/* 表达式: 摄像机跟随 — 应用到选中属性 */
(function(){
var comp = app.project.activeItem;
if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";
var sel = comp.selectedLayers;
if (sel.length === 0) return "ERR:no_selection";
var expr = "try {\n    var L = comp(\"\u5408\u6210\").layer(\"\u6444\u50cf\u673a\");\n} catch(e) { value; }\nfunction getLocalPos(worldPos) {\n    if (thisLayer.hasParent) return thisLayer.parent.fromWorld(worldPos);\n    return worldPos;\n}\nif (typeof L !== \"undefined\") {\n    getLocalPos(L.toWorld([0,0,0]));\n} else { value; }";
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
