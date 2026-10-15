"""Bounded, fixed read-only collectors and reproducible PV/QC reports."""
from __future__ import annotations

import json
import math
from typing import Any, Callable


# This collector only reads the DOM. It never changes activeItem, time, work
# area, fonts, output settings or the project, and never renders/saves a frame.
PREFLIGHT_JSX = r'''(function(){
var cfg=SETTINGS,p=app.project,out={ok:true,project:{file:p.file?p.file.fsName:null,dirty:p.dirty,
workingSpace:p.workingSpace,bitsPerChannel:p.bitsPerChannel,linearBlending:p.linearBlending},
comps:[],footage:[],fonts:[],outputs:[],expressionErrors:[],expressionVisited:0,expressionEvaluated:0,
layersVisited:0,limitations:[],truncated:false};
function limit(s){out.limitations.push(s);}
function inspectComp(c){
 var row={id:c.id,name:c.name,fps:c.frameRate,duration:c.duration,width:c.width,height:c.height,
  pixelAspect:c.pixelAspect,numLayers:c.numLayers,workAreaStart:c.workAreaStart,
  workAreaDuration:c.workAreaDuration,soloLayers:[]};
 out.comps.push(row);
 for(var l=1;l<=c.numLayers;l++){
  if(out.layersVisited>=cfg.maxProperties){out.truncated=true;break;}
  var layer=c.layer(l);out.layersVisited++;
  if(layer.solo)row.soloLayers.push(layer.id);
  var stack=[{p:layer,path:[]}];
  while(stack.length && out.expressionVisited<cfg.maxProperties){
   var n=stack.pop(),prop=n.p;out.expressionVisited++;
   try{
    if(prop.canSetExpression && prop.expression && prop.expressionEnabled){
     out.expressionEvaluated++;var failure='';
     try{prop.valueAtTime(c.time,false);}catch(e){failure=String(e);}
     if(prop.expressionError)failure=String(prop.expressionError);
     if(failure)out.expressionErrors.push({compId:c.id,layerId:layer.id,path:n.path,error:failure,time:c.time});
    }
    for(var k=prop.numProperties||0;k>=1;k--){
     if(stack.length+out.expressionVisited>=cfg.maxProperties){out.truncated=true;break;}
     var child=prop.property(k),step=prop.propertyType===PropertyType.INDEXED_GROUP?k-1:child.matchName;
     stack.push({p:child,path:n.path.concat([step])});
    }
   }catch(e){limit('expression property '+layer.id+': '+String(e));}
  }
  if(stack.length)out.truncated=true;
 }
}
for(var i=1;i<=Math.min(p.numItems,cfg.maxItems);i++){
 var x=p.item(i);
 try{
  if(x instanceof CompItem)inspectComp(x);
  else if(x instanceof FootageItem){
   var row={id:x.id,name:x.name,path:x.file?x.file.fsName:null,missing:x.footageMissing,
     unused:x.usedIn.length===0};
   if(x.proxySource)row.proxy={missing:x.proxySource.missingFootage,
     path:x.proxySource.file?x.proxySource.file.fsName:null,enabled:x.useProxy};
   out.footage.push(row);
  }
 }catch(e){limit('item '+x.id+': '+String(e));}
}
if(p.numItems>cfg.maxItems){out.truncated=true;limit('project item limit');}
if(out.truncated)limit('Some project/layer/property checks exceeded their traversal limits');
try{
 var fonts=p.usedFonts;
 if(fonts===undefined)limit('usedFonts API unavailable');
 else {for(var f=0;f<Math.min(fonts.length,cfg.maxItems);f++){
  var font=fonts[f].font;
  out.fonts.push({name:font.postScriptName,missing:font.isSubstitute});
 }if(fonts.length>cfg.maxItems){out.truncated=true;limit('font limit');}}
}catch(e){limit('fonts: '+String(e));}
var n=0;
try{outputScan:for(var r=1;r<=p.renderQueue.numItems;r++){
 var item=p.renderQueue.item(r);
 for(var m=1;m<=item.numOutputModules;m++){
  if(n++>=cfg.maxItems){out.truncated=true;limit('output module limit');break outputScan;}
  var om=item.outputModule(m),file=om.file;
  out.outputs.push({renderItem:r,module:m,compId:item.comp.id,queued:item.render,
   path:file?file.fsName:null,parentExists:file?file.parent.exists:false});
 }
}}catch(e){limit('render queue: '+String(e));}
return JSON.stringify(out);
})();'''


QC_TARGETS_JSX = r'''(function(){
var cfg=SETTINGS,p=app.project,c=p.activeItem;
if(cfg.compId){c=null;for(var i=1;i<=p.numItems;i++)if(p.item(i).id===cfg.compId){c=p.item(i);break;}}
if(!(c instanceof CompItem))return JSON.stringify({ok:false,error:'no_target_comp'});
var out={ok:true,compId:c.id,fps:c.frameRate,targets:[],visited:0,truncated:false,limitations:[]},stack=[];
for(var l=1;l<=Math.min(c.numLayers,cfg.maxNodes);l++)stack.push({p:c.layer(l),layerId:c.layer(l).id,path:[]});
if(c.numLayers>cfg.maxNodes)out.truncated=true;
while(stack.length && out.visited<cfg.maxNodes && out.targets.length<cfg.maxProperties){
 var n=stack.pop(),x=n.p;out.visited++;
 try{
  if(x.numKeys>0)out.targets.push({layerId:n.layerId,path:n.path,name:x.name,total:x.numKeys});
  for(var j=Math.min(x.numProperties||0,cfg.maxNodes);j>=1;j--){
   if(stack.length+out.visited>=cfg.maxNodes){out.truncated=true;break;}
   var child=x.property(j),step=x.propertyType===PropertyType.INDEXED_GROUP?j-1:child.matchName;
   stack.push({p:child,layerId:n.layerId,path:n.path.concat([step])});
  }
 }catch(e){out.limitations.push('property '+n.layerId+': '+String(e));}
}
if(stack.length)out.truncated=true;
return JSON.stringify(out);
})();'''


def _integer(value: Any, name: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer in 1..{maximum}")
    return value


def preflight_snapshot(ae: Any, max_items: int = 2000, max_properties: int = 5000) -> dict:
    settings = {"maxItems": _integer(max_items, "max_items", 20000),
                "maxProperties": _integer(max_properties, "max_properties", 20000)}
    return json.loads(ae.run_jsx(PREFLIGHT_JSX.replace("SETTINGS", json.dumps(settings)), timeout=60000))


def qc_targets(ae: Any, comp_id: int = 0, max_properties: int = 128, max_nodes: int = 5000) -> dict:
    if type(comp_id) is not int or comp_id < 0:
        raise ValueError("comp_id must be a nonnegative integer")
    settings = {"compId": comp_id, "maxProperties": _integer(max_properties, "max_properties", 256),
                "maxNodes": _integer(max_nodes, "max_nodes", 20000)}
    return json.loads(ae.run_jsx(QC_TARGETS_JSX.replace("SETTINGS", json.dumps(settings)), timeout=60000))


def _options(options: dict, fields: set[str]) -> None:
    if not isinstance(options, dict) or set(options) - fields:
        raise ValueError(f"Options must be an object with fields {sorted(fields)}")


def _finding(code: str, message: str, severity: str = "warning", **target: Any) -> dict:
    return {"code": code, "severity": severity, "message": message, **target}


def _finish(findings: list, limitations: list, coverage: dict) -> dict:
    return {"readOnly": True, "status": "incomplete" if limitations else
            "issues" if findings else "pass", "findings": findings,
            "limitations": limitations, "coverage": coverage,
            "counts": {s: sum(f["severity"] == s for f in findings)
                       for s in ("error", "warning", "info")}}


def run_preflight(call: Callable, options: dict) -> dict:
    _options(options, {"max_items", "max_expression_properties", "allowed_fps", "expected_working_space"})
    fps = options.get("allowed_fps", [23.976, 24, 25, 29.97, 30, 50, 59.94, 60])
    if not isinstance(fps, list) or not fps or any(type(x) not in (int, float) or
            not math.isfinite(x) or x <= 0 for x in fps):
        raise ValueError("allowed_fps must contain positive finite frame rates")
    expected = options.get("expected_working_space")
    if expected is not None and not isinstance(expected, str):
        raise ValueError("expected_working_space must be a string")
    max_items = _integer(options.get("max_items", 2000), "max_items", 20000)
    max_expr = _integer(options.get("max_expression_properties", 5000), "max_expression_properties", 20000)
    findings, limitations, coverage = [], [], {"expressions": "all scanned compositions at their current time only",
        "color": "project working space only; footage interpretation/output profiles require manual review"}
    try:
        data = call("get_preflight_snapshot", max_items=max_items, max_properties=max_expr)
        limitations.extend(data.get("limitations", []))
        if data.get("truncated"):
            limitations.append("Project scan truncated")
        coverage.update({key: len(data.get(key, [])) for key in ("comps", "footage", "fonts", "outputs")})
        for f in data.get("footage", []):
            if f.get("missing"):
                findings.append(_finding("missing-footage", "Source footage is missing", "error", item=f))
            if f.get("proxy", {}).get("missing"):
                findings.append(_finding("missing-proxy", "Proxy source is missing", "error", item=f))
            if f.get("unused"):
                findings.append(_finding("unused-footage", "No composition references this footage", "info", item=f))
        for font in data.get("fonts", []):
            if font.get("missing"):
                findings.append(_finding("missing-font", "AE is substituting a missing font", "error", font=font))
            elif font.get("missing") is None:
                limitations.append("Font substitution state unavailable: " + str(font.get("name")))
        names = {}
        for c in data.get("comps", []):
            names.setdefault(c.get("name"), []).append(c.get("id"))
            if not any(abs(c["fps"] - x) < 0.01 for x in fps):
                findings.append(_finding("frame-rate", "Frame rate is outside the configured delivery rates", comp=c))
            if not c.get("name", "").strip() or re_default_name(c["name"]):
                findings.append(_finding("comp-name", "Composition uses an empty/default name", comp=c))
            if abs(c.get("workAreaStart", 0)) > 1e-6 or abs(c.get("workAreaDuration", c["duration"]) - c["duration"]) > 1e-6:
                findings.append(_finding("partial-work-area", "Work area does not cover the full composition", comp=c))
            if c.get("numLayers") == 0:
                findings.append(_finding("empty-comp", "Composition has no layers", comp=c))
            if c.get("soloLayers"):
                findings.append(_finding("solo-layers", "Solo layers can suppress other layers; review intended output", comp=c))
        if len({round(c["fps"], 2) for c in data.get("comps", [])}) > 1:
            findings.append(_finding("mixed-comp-frame-rates", "Project contains different composition frame rates; review nested timing", "info"))
        for name, ids in names.items():
            if len(ids) > 1:
                findings.append(_finding("duplicate-comp-name", "Compositions share a name", name=name, compIds=ids))
        if not data.get("project", {}).get("file"):
            findings.append(_finding("unsaved-project", "Project has no saved path"))
        working = data.get("project", {}).get("workingSpace")
        if expected is not None and working != expected:
            findings.append(_finding("working-space", "Project working space differs from delivery requirement",
                                     actual=working, expected=expected))
        elif not working or str(working).casefold() == "none":
            findings.append(_finding("working-space-unset", "Project has no assigned color working space", "info"))
        coverage["workingSpace"] = working
        if not data.get("outputs"):
            findings.append(_finding("no-output", "No Render Queue output modules configured", "info"))
        for output in data.get("outputs", []):
            if not output.get("path") or not output.get("parentExists"):
                findings.append(_finding("output-path", "Output path is empty or its parent directory is missing", output=output))
        coverage["expressionPropertiesVisited"] = data.get("expressionVisited", 0)
        coverage["expressionsEvaluated"] = data.get("expressionEvaluated", 0)
        coverage["layersVisited"] = data.get("layersVisited", 0)
        findings.extend(_finding("expression-error", e["error"], "error", target=e)
                        for e in data.get("expressionErrors", []))
    except Exception as exc:
        limitations.append("Project preflight unavailable: " + str(exc))
    return _finish(findings, limitations, coverage)


def re_default_name(name: str) -> bool:
    import re
    return bool(re.fullmatch(r"(?:Comp|Composition|合成)\s*\d+", name, re.IGNORECASE))


def review_keyframes(keys: list[dict], fps: float, target: dict) -> list[dict]:
    """Native enum: 1=linear, 2=Bezier, 3=hold. Ease influence is a fraction."""
    findings = []
    def add(code: str, message: str, key: dict, severity: str = "warning") -> None:
        findings.append(_finding(code, message, severity, target=target, keyIndex=key.get("index")))
    previous = None
    for key in keys:
        incoming, outgoing = key.get("inInterpolation"), key.get("outInterpolation")
        if incoming not in (1, 2, 3) or outgoing not in (1, 2, 3):
            add("interpolation-unavailable", "Unrecognized interpolation enum", key, "info")
        elif incoming != outgoing:
            add("mixed-interpolation", "Incoming/outgoing interpolation differ; review intended timing", key)
        if previous:
            dt = key["time"] - previous["time"]
            if dt <= 0:
                add("key-time-order", "Duplicate or nonincreasing key times", key, "error")
            elif dt < 1.01 / fps:
                add("dense-keys", "Keys are one frame or less apart; may be intentional baked animation", key, "info")
            if {previous.get("outInterpolation"), incoming} == {1, 2}:
                add("segment-ease-mismatch", "Segment mixes linear and Bezier endpoints", key)
        for ease in key.get("temporalEase", []):
            if len(ease) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in ease):
                add("invalid-ease", "Temporal ease contains invalid data", key, "error")
                continue
            if (incoming == 2 and not 0.001 <= ease[1] <= 1) or (outgoing == 2 and not 0.001 <= ease[3] <= 1):
                add("ease-influence", "Temporal ease influence is outside native fraction range 0.001..1", key, "error")
            if incoming == outgoing == 2 and (abs(ease[0] - ease[2]) > 1e-5 or abs(ease[1] - ease[3]) > 0.25):
                add("asymmetric-ease", "Bezier speed/influence is asymmetric; review intentional acceleration", key, "info")
        tangents = key.get("spatialTangents", [])
        if tangents:
            if len(tangents) != 2 or any(not isinstance(v, list) or any(
                    type(x) not in (int, float) or not math.isfinite(x) for x in v) for v in tangents):
                add("invalid-tangents", "Spatial tangents contain invalid data", key, "error")
            elif len(tangents[0]) == len(tangents[1]):
                a, b = tangents
                na, nb = math.sqrt(sum(x*x for x in a)), math.sqrt(sum(x*x for x in b))
                if na > 1e-6 and nb > 1e-6 and sum(x*y for x, y in zip(a, b)) / (na*nb) > -0.5:
                    add("spatial-corner", "Spatial tangents form a corner; may be intentional", key, "info")
        previous = key
    return findings


def run_motion_review(call: Callable, options: dict) -> dict:
    _options(options, {"comp_id", "max_properties", "max_nodes", "max_keys"})
    max_keys = _integer(options.get("max_keys", 1000), "max_keys", 4096)
    findings, limitations, coverage = [], [], {"scope": "one composition; numeric native streams",
        "heuristics": "density, asymmetry and corners are review hints, not animation defects"}
    try:
        data = call("get_keyframe_qc_targets", comp_id=options.get("comp_id", 0),
                    max_properties=_integer(options.get("max_properties", 128), "max_properties", 256),
                    max_nodes=_integer(options.get("max_nodes", 5000), "max_nodes", 20000))
        limitations.extend(data.get("limitations", []))
        if data.get("truncated"):
            limitations.append("Animated property discovery truncated")
        coverage.update({"compId": data["compId"], "fps": data["fps"],
                         "propertiesDiscovered": len(data["targets"]), "propertiesReviewed": 0, "keysReviewed": 0})
        for target in data["targets"]:
            try:
                result = call("get_native_keyframes", layer_id=target["layerId"], path=target["path"],
                              comp_id=data["compId"], max_keys=max_keys)
                if result.get("truncated"):
                    limitations.append("Keyframe read truncated: " + str(target))
                keys = result["keyframes"]
                findings.extend(review_keyframes(keys, data["fps"], target))
                coverage["propertiesReviewed"] += 1
                coverage["keysReviewed"] += len(keys)
            except Exception as exc:
                limitations.append("Keyframe stream unavailable: " + str(target) + ": " + str(exc))
    except Exception as exc:
        limitations.append("Motion review unavailable: " + str(exc))
    return _finish(findings, limitations, coverage)
