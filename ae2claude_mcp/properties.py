"""Agent-facing, locale-independent access to AE's live property graph."""
from __future__ import annotations

import json
import math
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ae_bridge import AEBridge


LayerRef = str | int | dict[str, Any]
PropertyPath = list[str | int]


def normalize_layer_ref(layer: LayerRef) -> dict[str, Any]:
    if isinstance(layer, dict):
        supplied = [key for key in ("id", "index", "name") if key in layer]
        if len(supplied) != 1:
            raise ValueError("layer ref must contain exactly one of id, index, or name")
        key = supplied[0]
        value = layer[key]
    elif isinstance(layer, int) and not isinstance(layer, bool):
        key, value = "id", layer
    elif isinstance(layer, str) and layer:
        key, value = "name", layer
    else:
        raise ValueError("layer must be a stable id, name, or selector object")

    if key in {"id", "index"}:
        if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
            value = int(value)
        if type(value) is not int:
            raise ValueError(f"layer {key} must be an integer, not a boolean or fraction")
        if value < 1:
            raise ValueError(f"layer {key} must be >= 1")
    elif not isinstance(value, str) or not value:
        raise ValueError("layer name must be a non-empty string")
    return {key: value}


def normalize_path(path: PropertyPath) -> list[str | int]:
    if not isinstance(path, (list, tuple)) or not 1 <= len(path) <= 64:
        raise ValueError("property path must contain 1..64 matchName/index items")
    normalized: list[str | int] = []
    for step in path:
        if isinstance(step, bool):
            raise ValueError("boolean is not a valid property path index")
        if isinstance(step, int):
            if step < 0:
                raise ValueError("property path indices are zero-based and must be >= 0")
            normalized.append(step)
        elif isinstance(step, str) and step:
            normalized.append(step)
        else:
            raise ValueError("property path items must be matchNames or zero-based indices")
    return normalized


def normalize_operations(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(operations, list) or not 1 <= len(operations) <= 256:
        raise ValueError("property batch must contain 1..256 operations")
    normalized: list[dict[str, Any]] = []
    for index, source in enumerate(operations):
        if not isinstance(source, dict):
            raise ValueError(f"property operation {index} must be an object")
        action = str(source.get("action", "")).lower()
        if action not in {"get", "set"}:
            raise ValueError(f"property operation {index} action must be get or set")
        at_time = source.get("time")
        if at_time is not None and (type(at_time) not in (int, float) or not math.isfinite(at_time)):
            raise ValueError(f"property operation {index} time must be a finite number")
        pre_expression = source.get("preExpression", False)
        if type(pre_expression) is not bool:
            raise ValueError(f"property operation {index} preExpression must be boolean")
        item: dict[str, Any] = {
            "action": action,
            "path": normalize_path(source.get("path")),
            "time": at_time,
            "preExpression": pre_expression,
        }
        if action == "set":
            if "value" not in source:
                raise ValueError(f"property operation {index} is missing value")
            value = source["value"]
            components = value if isinstance(value, (list, tuple)) else [value]
            if any(isinstance(v, float) and not math.isfinite(v) for v in components):
                raise ValueError(f"property operation {index} value must be finite")
            item["value"] = value
        normalized.append(item)
    return normalized


def _missing_native_export(exc: Exception, name: str) -> bool:
    # Transport and deadline failures have unknown outcomes, even if their text
    # happens to mention this API. Never replay them through the JSX backend.
    if type(exc) is not RuntimeError:
        return False
    last_line = str(exc).strip().splitlines()[-1] if str(exc).strip() else ""
    expected = "AttributeError: module 'PyShiftCore' has no attribute '" + name + "'"
    return last_line == expected


def _python_layer_prelude(selector: dict[str, Any]) -> str:
    return (
        f"selector={selector!r}\n"
        "comp=app.project.activeItem\n"
        "if comp is None or type(comp).__name__ != 'CompItem':\n"
        "    raise RuntimeError('no_active_comp')\n"
        "layers=list(comp.layers)\n"
        "layer=None\n"
        "if 'id' in selector:\n"
        "    layer=next((x for x in layers if int(x.layerID)==int(selector['id'])),None)\n"
        "elif 'index' in selector:\n"
        "    idx=int(selector['index'])-1\n"
        "    layer=layers[idx] if 0 <= idx < len(layers) else None\n"
        "else:\n"
        "    layer=next((x for x in layers if x.name==selector['name']),None)\n"
        "if layer is None:\n"
        "    raise RuntimeError('layer_not_found')\n"
    )


def property_batch(
    bridge: "AEBridge",
    layer: LayerRef,
    operations: list[dict[str, Any]],
    dry_run: bool = False,
    undo_name: str = "AE2Claude Agent Batch",
    fail_fast: bool = True,
    backend: str = "auto",
) -> dict[str, Any]:
    selector = normalize_layer_ref(layer)
    normalized = normalize_operations(operations)
    backend = str(backend).lower()
    if backend not in {"auto", "native", "jsx"}:
        raise ValueError("backend must be auto, native, or jsx")

    native_values = all(
        item["action"] == "get"
        or (
            isinstance(item.get("value"), (int, float, list, tuple))
            and not isinstance(item.get("value"), bool)
        )
        for item in normalized
    )
    if backend == "jsx" or (backend == "auto" and not native_values):
        return _property_batch_jsx(
            bridge, selector, normalized, dry_run, undo_name, fail_fast
        )

    code = (
        "import json\n"
        + _python_layer_prelude(selector)
        + f"operations={normalized!r}\n"
        + "for operation in operations:\n"
        + "    if operation.get('time') is None and operation.get('action')=='get':\n"
        + "        operation['time']=float(comp.time)\n"
        + f"result=psc.agent_stream_batch(layer,operations,{bool(dry_run)!r},"
        + f"{str(undo_name)!r},{bool(fail_fast)!r})\n"
        + "_result=json.dumps(result,ensure_ascii=False)\n"
    )
    try:
        return json.loads(bridge._run_py(code, timeout=max(bridge.timeout, 120)))
    except Exception as exc:
        if backend == "native" or not _missing_native_export(exc, "agent_stream_batch"):
            raise
        result = _property_batch_jsx(
            bridge, selector, normalized, dry_run, undo_name, fail_fast
        )
        result["fallbackReason"] = "native_agent_api_unavailable"
        return result


def inspect_properties(
    bridge: "AEBridge",
    layer: LayerRef,
    path: PropertyPath | None = None,
    max_depth: int = 3,
    max_nodes: int = 512,
    backend: str = "auto",
) -> dict[str, Any]:
    selector = normalize_layer_ref(layer)
    normalized_path = [] if path is None else normalize_path(path)
    max_depth = max(1, min(int(max_depth), 16))
    max_nodes = max(1, min(int(max_nodes), 4096))
    backend = str(backend).lower()
    if backend not in {"auto", "native", "jsx"}:
        raise ValueError("backend must be auto, native, or jsx")
    if backend != "jsx":
        code = (
            "import json\n"
            + _python_layer_prelude(selector)
            + f"result=psc.agent_inspect_streams(layer,{normalized_path!r},"
            + f"{max_depth},{max_nodes})\n"
            + "_result=json.dumps(result,ensure_ascii=False)\n"
        )
        try:
            return json.loads(bridge._run_py(code, timeout=max(bridge.timeout, 120)))
        except Exception as exc:
            if backend == "native" or not _missing_native_export(exc, "agent_inspect_streams"):
                raise
    return _inspect_properties_jsx(
        bridge, selector, normalized_path, max_depth, max_nodes
    )


def _property_batch_jsx(
    bridge: "AEBridge",
    selector: dict[str, Any],
    operations: list[dict[str, Any]],
    dry_run: bool,
    undo_name: str,
    fail_fast: bool,
) -> dict[str, Any]:
    payload = json.dumps(
        {
            "selector": selector,
            "operations": operations,
            "dryRun": bool(dry_run),
            "undoName": str(undo_name),
            "failFast": bool(fail_fast),
        },
        ensure_ascii=True,
    )
    code = "(function(){var cfg=" + payload + ";" + r"""
function pick(c,s){var i,l;if(s.id!==undefined){for(i=1;i<=c.numLayers;i++){l=c.layer(i);if(l.id==s.id)return l;}}
    else if(s.index!==undefined){return c.layer(s.index);}else{return c.layer(s.name);}return null;}
function resolve(root,path){var p=root;for(var i=0;i<path.length;i++){var step=path[i];
    p=(typeof step==='number')?p.property(step+1):p.property(step);if(!p)throw new Error('path_not_found:'+step);}return p;}
function finite(v){return typeof v==='number'&&isFinite(v);}
function validate(p,op){
    if(p.propertyType!==PropertyType.PROPERTY||p.propertyValueType===PropertyValueType.NO_VALUE)
        throw new Error('not_a_value_property');
    if(op.action!=='set')return;
    var timed=op.time!==null&&op.time!==undefined;
    if(timed&&!p.canVaryOverTime)throw new Error('property_cannot_animate');
    if(!timed&&p.numKeys>0)throw new Error('animated_property_requires_time');
    var v=op.value,t=p.propertyValueType,n=0;
    if(t===PropertyValueType.OneD||t===PropertyValueType.LAYER_INDEX||t===PropertyValueType.MASK_INDEX){if(!finite(v))throw new Error('expected_scalar');
        if(t!==PropertyValueType.OneD&&(v<0||Math.floor(v)!==v))throw new Error('expected_nonnegative_index');}
    else if(t===PropertyValueType.TwoD||t===PropertyValueType.TwoD_SPATIAL)n=2;
    else if(t===PropertyValueType.ThreeD||t===PropertyValueType.ThreeD_SPATIAL)n=3;
    else if(t===PropertyValueType.COLOR){n=4;if(v instanceof Array&&v.length===3)v=op.value=v.concat([1]);}
    else if(t===PropertyValueType.TEXT_DOCUMENT){if(typeof v!=='string')throw new Error('expected_text');}
    else throw new Error('unsupported_write_value_type');
    if(n){if(!(v instanceof Array)||v.length!==n)throw new Error('expected_'+n+'d_value');
        for(var j=0;j<n;j++)if(!finite(v[j]))throw new Error('expected_finite_components');}
    if(t===PropertyValueType.OneD||t===PropertyValueType.LAYER_INDEX||t===PropertyValueType.MASK_INDEX){if(p.hasMin&&v<p.minValue)throw new Error('value_below_minimum');
        if(p.hasMax&&v>p.maxValue)throw new Error('value_above_maximum');}
}
function skipped(i,why){return {index:i,ok:false,executed:false,skipped:true,error:why};}
function response(out,dry){var ok=true;for(var i=0;i<out.length;i++)ok=ok&&out[i].ok;
    return JSON.stringify({ok:ok,backend:'jsx-single-dispatch',dryRun:dry,operationCount:cfg.operations.length,results:out});}
function safe(v){try{return JSON.parse(JSON.stringify(v));}catch(e){return String(v);}}
var c=app.project.activeItem;if(!c||!(c instanceof CompItem))return JSON.stringify({ok:false,error:'no_active_comp'});
var layer=pick(c,cfg.selector);if(!layer)return JSON.stringify({ok:false,error:'layer_not_found'});
var out=[],resolved=[],hasWrites=false,i,preflightFailed=false;
for(i=0;i<cfg.operations.length;i++)out[i]=skipped(i,'not_started');
for(i=0;i<cfg.operations.length;i++){
    try{var op=cfg.operations[i],prop=resolve(layer,op.path);validate(prop,op);resolved[i]=prop;
        hasWrites=hasWrites||op.action==='set';out[i]={index:i,ok:true,executed:false,validated:true};}
    catch(e){out[i]={index:i,ok:false,executed:false,error:String(e)};preflightFailed=true;if(cfg.failFast)break;}
}
if(cfg.dryRun)return response(out,true);
if(preflightFailed&&cfg.failFast){for(i=0;i<out.length;i++)if(out[i].ok)out[i]=skipped(i,'batch_preflight_failed');return response(out,false);}
var undoOpen=false;
try{
    if(hasWrites){app.beginUndoGroup(cfg.undoName);undoOpen=true;}
    for(i=0;i<cfg.operations.length;i++){
        if(!out[i].ok)continue;
        try{var item=cfg.operations[i],p=resolved[i];out[i].executed=true;
            var t=item.time===null||item.time===undefined?c.time:item.time;
            if(item.action==='get')out[i].value=safe(p.valueAtTime(t,item.preExpression));
            else{var value=item.value;if(p.propertyValueType===PropertyValueType.TEXT_DOCUMENT){value=p.valueAtTime(t,true);value.text=item.value;}
                if(item.time===null||item.time===undefined)p.setValue(value);else p.setValueAtTime(item.time,value);}}
        catch(inner){out[i].ok=false;out[i].error=String(inner);if(cfg.failFast){
            for(var j=i+1;j<out.length;j++)if(out[j].ok)out[j]=skipped(j,'skipped_after_failure');break;}}
    }
}finally{if(undoOpen)app.endUndoGroup();}
return response(out,false);})()
"""
    raw = bridge.run_jsx(code, timeout=max(60000, bridge.timeout * 1000))
    return json.loads(raw)


def _inspect_properties_jsx(
    bridge: "AEBridge",
    selector: dict[str, Any],
    path: list[str | int],
    max_depth: int,
    max_nodes: int,
) -> dict[str, Any]:
    payload = json.dumps(
        {"selector": selector, "path": path, "maxDepth": max_depth, "maxNodes": max_nodes},
        ensure_ascii=True,
    )
    code = (
        "(function(){var cfg=" + payload + ";"
        "function pick(c,s){var i,l;if(s.id!==undefined){for(i=1;i<=c.numLayers;i++){l=c.layer(i);if(l.id==s.id)return l;}}"
        "else if(s.index!==undefined){return c.layer(s.index);}else{return c.layer(s.name);}return null;}"
        "function resolve(root,path){var p=root;for(var i=0;i<path.length;i++){var step=path[i];"
        "p=(typeof step==='number')?p.property(step+1):p.property(step);if(!p)return null;}return p;}"
        "var c=app.project.activeItem;if(!c||!(c instanceof CompItem))return JSON.stringify({ok:false,error:'no_active_comp'});"
        "var layer=pick(c,cfg.selector),base=layer&&resolve(layer,cfg.path);if(!base)return JSON.stringify({ok:false,error:'property_root_not_found'});"
        "var q=[],out=[];function children(parent,parentPath,depth){if(!parent||!parent.numProperties)return;"
        "for(var j=1;j<=parent.numProperties;j++){var child=parent.property(j);if(!child)continue;"
        "var indexed=parent.propertyType===PropertyType.INDEXED_GROUP;var step=indexed?j-1:(child.matchName||j-1);"
        "q.push({p:child,path:parentPath.concat([step]),depth:depth,index:j-1});}}children(base,cfg.path,0);"
        "while(q.length&&out.length<cfg.maxNodes){var n=q.shift(),p=n.p;out.push({depth:n.depth,index:n.index,name:p.name||'',"
        "matchName:p.matchName||'',propertyType:p.propertyType,valueType:p.propertyValueType,numChildren:p.numProperties||0,"
        "canVary:!!p.canVaryOverTime,path:n.path});if(n.depth+1<cfg.maxDepth)children(p,n.path,n.depth+1);}"
        "return JSON.stringify({ok:true,backend:'jsx-single-dispatch',count:out.length,truncated:q.length>0,streams:out});})()"
    )
    raw = bridge.run_jsx(code, timeout=max(60000, bridge.timeout * 1000))
    return json.loads(raw)
