"""Structured, capability-tested AE authoring through the existing JSX bridge.

Every mutation defaults to a host-side dry run. JSON is the only input surface;
no caller-supplied code is executed. Native Graph Editor APIs stay independent.
"""
from __future__ import annotations

import json
import math
from typing import Any

from .properties import normalize_layer_ref, normalize_path

READ_ACTIONS = {"essential_graphics", "essential_properties", "shape_contents"}
ACTIONS = READ_ACTIONS | {"expose_control", "rename_control", "essential_property", "export_mogrt",
    "shape_operator", "stroke_dashes", "text_range", "keyframe_interpolation",
    "create_folder", "project_items", "render_output", "template_settings"}


def integer(value: Any, field: str, minimum: int = 0, maximum: int = 2**31 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{field} must be an integer in {minimum}..{maximum}")
    return value


def stable_id(value: Any, field: str, minimum: int = 0) -> int:
    return integer(value, field, minimum, 2**32 - 1)


def string(value: Any, field: str, empty: bool = False) -> str:
    if not isinstance(value, str) or "\0" in value or (not empty and not value.strip()):
        raise ValueError(f"{field} must be a nonempty string without NUL")
    return value


def number(value: Any, field: str, minimum: float | None = None) -> float:
    if type(value) not in (float, int) or not math.isfinite(value) or (minimum is not None and value < minimum):
        raise ValueError(f"{field} must be a finite number")
    return value


def normalize(action: str, options: dict | None, dry_run: bool) -> dict:
    if not isinstance(action, str) or action not in ACTIONS:
        raise ValueError(f"Unknown production action: {action}")
    if type(dry_run) is not bool or (options is not None and not isinstance(options, dict)):
        raise ValueError("dry_run must be boolean; options must be an object")
    o = dict(options or {})
    fields = {
        "essential_graphics": set(), "essential_properties": {"layer", "max_nodes"},
        "shape_contents": {"layer", "max_nodes"},
        "expose_control": {"layer", "path", "name"}, "rename_control": {"index", "name"},
        "essential_property": {"layer", "path", "value", "alternate_source_id", "time"},
        "export_mogrt": {"output_dir", "overwrite"},
        "shape_operator": {"layer", "path", "operation", "match_name", "name", "enabled", "index"},
        "stroke_dashes": {"layer", "path", "dashes", "offset"},
        "text_range": {"layer", "start", "end", "text", "key_index"},
        "keyframe_interpolation": {"layer", "path", "key_indices", "in_type", "out_type",
                                   "temporal_auto_bezier", "temporal_continuous"},
        "create_folder": {"name", "parent_id"}, "project_items": {"changes", "fix_expressions"},
        "render_output": {"output_path", "render_template", "output_template", "overwrite"},
        "template_settings": {"name"},
    }[action] | {"comp_id"}
    if set(o) - fields:
        raise ValueError(f"Unsupported {action} options: {sorted(set(o) - fields)}")
    cfg = {"action": action, "compId": stable_id(o.pop("comp_id", 0), "comp_id"),
           "dryRun": dry_run, **o}
    if "layer" in fields:
        cfg["selector"] = normalize_layer_ref(cfg.pop("layer", None))
    if "path" in fields:
        path = cfg.get("path")
        if (path is None or path == []) and action in {"expose_control", "shape_operator"}:
            cfg["path"] = []
        else:
            cfg["path"] = normalize_path(path)
    for key in ("name", "match_name", "render_template", "output_template", "output_path", "output_dir"):
        if key in cfg and cfg[key] is not None:
            cfg[key] = string(cfg[key], key)
    if action in {"essential_properties", "shape_contents"}:
        cfg["max_nodes"] = integer(cfg.get("max_nodes", 512), "max_nodes", 1, 4096)
    if action == "expose_control" and "name" not in cfg:
        cfg["name"] = None
    if action == "rename_control":
        cfg["index"] = integer(cfg.get("index"), "index", 1)
        cfg["name"] = string(cfg.get("name"), "name")
    if action == "template_settings":
        cfg["name"] = string(cfg.get("name"), "name")
    if action == "essential_property":
        if ("value" in cfg) == (cfg.get("alternate_source_id") is not None):
            raise ValueError("Specify exactly one of value or alternate_source_id")
        if cfg.get("alternate_source_id") is not None:
            cfg["alternate_source_id"] = stable_id(cfg["alternate_source_id"], "alternate_source_id", 1)
        if cfg.get("time") is not None:
            cfg["time"] = number(cfg["time"], "time", 0)
    if action in {"export_mogrt", "render_output"}:
        cfg["overwrite"] = cfg.get("overwrite", False)
        if type(cfg["overwrite"]) is not bool:
            raise ValueError("overwrite must be boolean")
    if action == "shape_operator":
        if cfg.get("operation") not in {"add", "remove", "rename", "move", "enable"}:
            raise ValueError("Invalid shape operation")
        required = {"add": "match_name", "rename": "name", "move": "index", "enable": "enabled"}
        if required.get(cfg["operation"]) not in cfg and cfg["operation"] in required:
            raise ValueError("Missing shape operation argument")
        if cfg["operation"] in {"add", "rename"}:
            field = required[cfg["operation"]]
            cfg[field] = string(cfg.get(field), field)
        if cfg["operation"] == "move":
            cfg["index"] = integer(cfg["index"], "index")
        if cfg["operation"] == "enable" and type(cfg["enabled"]) is not bool:
            raise ValueError("enabled must be boolean")
        if cfg["operation"] != "add" and not cfg["path"]:
            raise ValueError("Shape target path is required")
    if action == "stroke_dashes":
        if not isinstance(cfg.get("dashes"), list) or len(cfg["dashes"]) > 6:
            raise ValueError("dashes must contain 0..6 alternating dash/gap lengths")
        cfg["dashes"] = [number(x, "dash/gap", 0) for x in cfg["dashes"]]
        cfg["offset"] = number(cfg.get("offset", 0), "offset")
    if action == "text_range":
        cfg["start"] = integer(cfg.get("start"), "start")
        cfg["end"] = integer(cfg.get("end"), "end", cfg["start"])
        # AE normalizes paragraph breaks to CR, including CharacterRange writes.
        cfg["text"] = string(cfg.get("text"), "text", True).replace("\r\n", "\r").replace("\n", "\r")
        if cfg.get("key_index") is not None:
            cfg["key_index"] = integer(cfg["key_index"], "key_index")
    if action == "keyframe_interpolation":
        keys = cfg.get("key_indices")
        if not isinstance(keys, list) or not 1 <= len(keys) <= 256:
            raise ValueError("key_indices must contain 1..256 zero-based indices")
        cfg["key_indices"] = list(dict.fromkeys(integer(x, "key_index") for x in keys))
        cfg["out_type"] = cfg.get("out_type") or cfg.get("in_type")
        if any(cfg.get(k) not in {"linear", "bezier", "hold"} for k in ("in_type", "out_type")):
            raise ValueError("Interpolation must be linear, bezier or hold")
        for flag in ("temporal_auto_bezier", "temporal_continuous"):
            if cfg.get(flag) is not None and type(cfg[flag]) is not bool:
                raise ValueError(f"{flag} must be boolean")
            if cfg.get(flag) is True and (cfg["in_type"] != "bezier" or cfg["out_type"] != "bezier"):
                raise ValueError("Bezier flags require Bezier interpolation at both ends")
    if action == "create_folder":
        cfg["name"] = string(cfg.get("name"), "name")
        cfg["parent_id"] = stable_id(cfg.get("parent_id", 0), "parent_id")
    if action == "project_items":
        changes = cfg.get("changes")
        if not isinstance(changes, list) or not 1 <= len(changes) <= 256:
            raise ValueError("changes must contain 1..256 item changes")
        seen = set()
        for row in changes:
            if not isinstance(row, dict) or set(row) - {"item_id", "name", "folder_id"} or len(row) < 2:
                raise ValueError("Each change requires item_id and name/folder_id")
            item_id = stable_id(row.get("item_id"), "item_id", 1)
            if item_id in seen:
                raise ValueError("Duplicate item_id in changes")
            seen.add(item_id)
            if "name" in row:
                string(row["name"], "name")
            if "folder_id" in row:
                stable_id(row["folder_id"], "folder_id")
        cfg["fix_expressions"] = cfg.get("fix_expressions", True)
        if type(cfg["fix_expressions"]) is not bool:
            raise ValueError("fix_expressions must be boolean")
    # Reject non-JSON values, including NaN in property values, before transport.
    json.dumps(cfg, allow_nan=False)
    return cfg


JSX = r'''(function(){
var cfg=SETTINGS,p=app.project,c=null,l=null,target=null,started=false,undo=false;
var result={ok:true,action:cfg.action,dryRun:cfg.dryRun,applied:false};
function need(value,message){if(!value)throw new Error(message);}
function item(id){if(id===0)return p.rootFolder;for(var i=1;i<=p.numItems;i++)if(p.item(i).id===id)return p.item(i);return null;}
function comp(){var x=cfg.compId?item(cfg.compId):p.activeItem;need(x instanceof CompItem,'no_target_comp');return x;}
function layer(){var s=cfg.selector,x=null;if(s.id!==undefined){for(var i=1;i<=c.numLayers;i++)if(c.layer(i).id===s.id){x=c.layer(i);break;}}
 else if(s.index!==undefined){if(s.index<=c.numLayers)x=c.layer(s.index);}else {for(var j=1;j<=c.numLayers;j++)if(c.layer(j).name===s.name){need(!x,'ambiguous_layer_name');x=c.layer(j);}}
 need(x,'layer_not_found');return x;}
function resolve(root,path){var x=root;for(var i=0;i<path.length;i++){x=typeof path[i]==='number'?x.property(path[i]+1):x.property(path[i]);need(x,'property_not_found');}return x;}
function begin(){app.beginUndoGroup('AE2Claude '+cfg.action);undo=true;started=true;}
function eg(){var rows=[];need(typeof c.getMotionGraphicsTemplateControllerName==='function','essential_graphics_unavailable');
 for(var i=1;i<=c.motionGraphicsTemplateControllerCount;i++)rows.push({index:i,name:c.getMotionGraphicsTemplateControllerName(i)});
 return {compId:c.id,name:c.motionGraphicsTemplateName,controllers:rows};}
function tree(root){var stack=[{p:root,path:[],next:0}],rows=[];while(stack.length&&rows.length<cfg.max_nodes){var n=stack[stack.length-1],x=n.p;
 if(n.next>0){if(n.next>(x.numProperties||0)){stack.pop();continue;}
 var i=n.next++,child=x.property(i),step=x.propertyType===PropertyType.INDEXED_GROUP?i-1:child.matchName;
 stack.push({p:child,path:n.path.concat([step]),next:0});continue;}
 var row={path:n.path,name:x.name,matchName:x.matchName,numKeys:x.numKeys||0,numChildren:x.numProperties||0};
 try{if(x.canSetEnabled)row.enabled=x.enabled;if(x.canSetAlternateSource!==undefined)row.canSetAlternateSource=x.canSetAlternateSource;
 if(x.essentialPropertySource)row.source={name:x.essentialPropertySource.name,matchName:x.essentialPropertySource.matchName||null};
 if(!x.numProperties){var v=x.value;if(typeof v==='number'||typeof v==='string'||v instanceof Array)row.value=v;}}
 catch(e){row.readError=String(e);}rows.push(row);n.next=1;}
 while(stack.length&&stack[stack.length-1].next>(stack[stack.length-1].p.numProperties||0))stack.pop();
 result.truncated=stack.length>0;return rows;}
function shapeRoot(){var root=l.property('ADBE Root Vectors Group');need(root,'not_shape_layer');return root;}
function safeName(name){return name.replace(/[<>:"\/\\|?*\x00-\x1f]/g,'_').replace(/[. ]+$/,'')||'composition';}
function outputKey(file){var s=file.fsName.replace(/\\/g,'/');return typeof $!=='undefined'&&/windows/i.test($.os)?s.toLowerCase():s;}
function sequencePattern(file){var s=outputKey(file),m=/\[(#+)\]/.exec(s);if(!m)return null;
 function esc(t){return t.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');}
 return new RegExp('^'+esc(s.slice(0,m.index))+'-?\\d{'+m[1].length+',}'+esc(s.slice(m.index+m[0].length))+'$');}
function outputExists(file){if(file.exists)return true;var pattern=sequencePattern(file);if(!pattern)return false;
 var files=file.parent.getFiles();for(var i=0;i<files.length;i++)if(pattern.test(outputKey(files[i])))return true;return false;}
function outputReserved(file,skip){var rq=p.renderQueue,key=outputKey(file),pattern=sequencePattern(file);
 for(var i=1;i<=rq.numItems;i++){var ri=rq.item(i);if(ri===skip||!ri.render)continue;
  for(var j=1;j<=ri.numOutputModules;j++){var other=ri.outputModule(j).file;if(!other)continue;
   var otherKey=outputKey(other),otherPattern=sequencePattern(other);
   if((key.replace(/\[#+\]/g,'[#]')===otherKey.replace(/\[#+\]/g,'[#]'))||(pattern&&pattern.test(otherKey))||(otherPattern&&otherPattern.test(key)))return true;}}
 return false;}
try{
 if(cfg.action!=='create_folder'&&cfg.action!=='project_items')c=comp();
 if(cfg.selector)l=layer();
 if(cfg.action==='essential_graphics'){result.result=eg();return JSON.stringify(result);}
 if(cfg.action==='essential_properties'){need(l.essentialProperty,'essential_properties_unavailable');result.result=tree(l.essentialProperty);return JSON.stringify(result);}
 if(cfg.action==='shape_contents'){result.result=tree(shapeRoot());return JSON.stringify(result);}
 if(cfg.action==='expose_control'){
  target=cfg.path.length?resolve(l,cfg.path):l;
  need(typeof target.canAddToMotionGraphicsTemplate==='function','egp_exposure_unavailable');
  need(target.canAddToMotionGraphicsTemplate(c),'control_not_eligible_or_already_exposed');
  need(typeof target.addToMotionGraphicsTemplateAs==='function','named_egp_exposure_unavailable');
  result.plan={compId:c.id,layerId:l.id,path:cfg.path,name:cfg.name||target.name};
  if(!cfg.dryRun){begin();need(target.addToMotionGraphicsTemplateAs(c,result.plan.name)===true,'egp_exposure_failed');result.result=eg();}
 }else if(cfg.action==='rename_control'){
  var prior=eg();need(cfg.index<=prior.controllers.length,'control_index_out_of_range');
  need(typeof c.setMotionGraphicsControllerName==='function','egp_rename_unavailable');result.plan={index:cfg.index,oldName:prior.controllers[cfg.index-1].name,name:cfg.name};
  if(!cfg.dryRun){begin();c.setMotionGraphicsControllerName(cfg.index,cfg.name);result.result=eg();need(result.result.controllers[cfg.index-1].name===cfg.name,'egp_rename_readback_failed');}
 }else if(cfg.action==='essential_property'){
  need(l.essentialProperty,'essential_properties_unavailable');target=resolve(l.essentialProperty,cfg.path);
  var replacement=cfg.alternate_source_id?item(cfg.alternate_source_id):null;
  if(cfg.alternate_source_id){need(replacement,'alternate_source_not_found');need(target.canSetAlternateSource&&typeof target.setAlternateSource==='function','not_media_replacement_property');need(replacement.isMediaReplacementCompatible===true,'incompatible_media_replacement');}
  else {need(target.propertyType===PropertyType.PROPERTY,'not_leaf_property');need(!target.expressionEnabled,'expression_driven_property');
   need(!target.numKeys||(cfg.time!==undefined&&cfg.time!==null),'animated_property_requires_time');}
  result.plan={compId:c.id,layerId:l.id,path:cfg.path,alternateSourceId:cfg.alternate_source_id||null,value:cfg.value};
  if(!cfg.dryRun){begin();if(replacement)target.setAlternateSource(replacement);
   else if(cfg.time!==undefined&&cfg.time!==null)target.setValueAtTime(cfg.time,cfg.value);else target.setValue(cfg.value);
   var atTime=cfg.time!==undefined&&cfg.time!==null;
   result.result={path:cfg.path,time:atTime?cfg.time:null,value:replacement?null:(atTime?target.valueAtTime(cfg.time,false):target.value),alternateSourceId:replacement?target.alternateSource.id:null};}
 }else if(cfg.action==='template_settings'){
  need(c.motionGraphicsTemplateName!==undefined,'mogrt_name_unavailable');result.plan={compId:c.id,oldName:c.motionGraphicsTemplateName,name:cfg.name};
  if(!cfg.dryRun){begin();c.motionGraphicsTemplateName=cfg.name;result.result=eg();need(result.result.name===cfg.name,'mogrt_name_readback_failed');}
 }else if(cfg.action==='export_mogrt'){
  need(typeof c.exportAsMotionGraphicsTemplate==='function','mogrt_export_unavailable');
  need(p.file&&!p.dirty,'save_project_before_mogrt_export');
  var folder=new Folder(cfg.output_dir||p.file.parent.fsName),name=c.motionGraphicsTemplateName;
  need(folder.exists,'mogrt_destination_missing');need(name&&safeName(name)===name,'invalid_mogrt_name');
  var destination=new File(folder.fsName+'/'+name+'.mogrt');need(cfg.overwrite||!destination.exists,'mogrt_destination_exists');
  result.plan={compId:c.id,path:destination.fsName,overwrite:cfg.overwrite};
  if(!cfg.dryRun){started=true;need(c.exportAsMotionGraphicsTemplate(cfg.overwrite,folder.fsName)===true,'mogrt_export_failed');
   destination=new File(destination.fsName);need(destination.exists&&destination.length>0,'mogrt_file_not_verified');result.result={path:destination.fsName,bytes:destination.length};}
 }else if(cfg.action==='shape_operator'){
  target=resolve(shapeRoot(),cfg.path);var op=cfg.operation;
  if(op==='add'){need(target.matchName==='ADBE Root Vectors Group'||target.matchName==='ADBE Vectors Group','not_shape_contents_group');
   need(/^ADBE Vector (Filter|Graphic|Shape|Group)/.test(cfg.match_name),'invalid_shape_match_name');need(target.canAddProperty(cfg.match_name),'shape_operator_not_supported');}
  else {need(target!==shapeRoot(),'cannot_edit_shape_root');if(op==='move')need(cfg.index<target.parentProperty.numProperties,'shape_index_out_of_range');
   if(op==='enable')need(target.canSetEnabled,'shape_enable_unavailable');}
  result.plan={layerId:l.id,path:cfg.path,operation:op,matchName:cfg.match_name,index:cfg.index};
  if(!cfg.dryRun){begin();if(op==='add'){var added=target.addProperty(cfg.match_name),addedIndex=added.propertyIndex;
    target=resolve(shapeRoot(),cfg.path).property(addedIndex);if(cfg.name)target.name=cfg.name;
    result.result={path:cfg.path.concat([addedIndex-1]),name:target.name,matchName:target.matchName};}
   else if(op==='remove'){target.remove();result.result={removed:true};}
   else if(op==='rename'){target.name=cfg.name;result.result={name:target.name};}
   else if(op==='enable'){target.enabled=cfg.enabled;result.result={enabled:target.enabled};}
   else {target.moveTo(cfg.index+1);result.result={index:cfg.index};}}
 }else if(cfg.action==='stroke_dashes'){
  target=resolve(shapeRoot(),cfg.path);need(target.matchName==='ADBE Vector Graphic - Stroke','not_shape_stroke');
  var dashes=target.property('ADBE Vector Stroke Dashes');need(dashes,'stroke_dashes_unavailable');
  for(var i=1;i<=dashes.numProperties;i++)need(!dashes.property(i).numKeys&&!dashes.property(i).expressionEnabled,'animated_dash_property');
  for(var v=0;v<cfg.dashes.length;v++){var candidate='ADBE Vector Stroke '+(v%2?'Gap ':'Dash ')+(Math.floor(v/2)+1);
   need(dashes.property(candidate)||dashes.canAddProperty(candidate),'dash_not_supported');}
  result.plan={layerId:l.id,path:cfg.path,dashes:cfg.dashes,offset:cfg.offset};
  if(!cfg.dryRun){begin();for(var j=dashes.numProperties;j>=1;j--)if(dashes.property(j).matchName!=='ADBE Vector Stroke Offset')dashes.property(j).remove();
   for(var k=0;k<cfg.dashes.length;k++){var match='ADBE Vector Stroke '+(k%2?'Gap ':'Dash ')+(Math.floor(k/2)+1);
    dashes=resolve(shapeRoot(),cfg.path).property('ADBE Vector Stroke Dashes');need(dashes.canAddProperty(match),'dash_not_supported');
    var added=dashes.addProperty(match);added.setValue(cfg.dashes[k]);}
   dashes=resolve(shapeRoot(),cfg.path).property('ADBE Vector Stroke Dashes');var offset=dashes.property('ADBE Vector Stroke Offset');
   offset=dashes.addProperty('ADBE Vector Stroke Offset');offset.setValue(cfg.offset);
   result.result={dashes:[],offset:cfg.offset};dashes=resolve(shapeRoot(),cfg.path).property('ADBE Vector Stroke Dashes');
   for(var n=1;n<=dashes.numProperties;n++)result.result.dashes.push({matchName:dashes.property(n).matchName,value:dashes.property(n).value});}
 }else if(cfg.action==='text_range'){
  target=l.property('ADBE Text Properties');need(target,'not_text_layer');target=target.property('ADBE Text Document');need(!target.expressionEnabled,'expression_driven_text');
  var keyed=cfg.key_index!==undefined&&cfg.key_index!==null;
  need(keyed||!target.numKeys,'animated_text_requires_key_index');if(keyed)need(cfg.key_index<target.numKeys,'text_key_index_out_of_range');
  var doc=keyed?target.keyValue(cfg.key_index+1):target.value;
  need(typeof doc.characterRange==='function','character_range_requires_ae_24_3');need(cfg.end<=doc.text.length,'text_range_out_of_bounds');
  function boundary(i){var code=doc.text.charCodeAt(i);return !(i>0&&code>=56320&&code<=57343);}
  need(boundary(cfg.start)&&boundary(cfg.end),'text_range_splits_surrogate_pair');
  var before=doc.text,expected=before.slice(0,cfg.start)+cfg.text+before.slice(cfg.end);
  result.plan={layerId:l.id,start:cfg.start,end:cfg.end,before:before,after:expected,keyIndex:keyed?cfg.key_index:null};
  if(!cfg.dryRun){doc.characterRange(cfg.start,cfg.end).text=cfg.text;begin();if(keyed)target.setValueAtKey(cfg.key_index+1,doc);else target.setValue(doc);
   result.result={text:(keyed?target.keyValue(cfg.key_index+1):target.value).text};need(result.result.text===expected,'text_readback_failed');}
 }else if(cfg.action==='keyframe_interpolation'){
  target=resolve(l,cfg.path);var types={linear:KeyframeInterpolationType.LINEAR,bezier:KeyframeInterpolationType.BEZIER,hold:KeyframeInterpolationType.HOLD};
  need(target.isInterpolationTypeValid(types[cfg.in_type])&&target.isInterpolationTypeValid(types[cfg.out_type]),'interpolation_not_supported');
  for(var i=0;i<cfg.key_indices.length;i++)need(cfg.key_indices[i]<target.numKeys,'key_index_out_of_range');
  result.plan={layerId:l.id,path:cfg.path,keyIndices:cfg.key_indices,inType:cfg.in_type,outType:cfg.out_type};
  if(!cfg.dryRun){begin();result.result=[];for(var j=0;j<cfg.key_indices.length;j++){var key=cfg.key_indices[j]+1;
   target.setInterpolationTypeAtKey(key,types[cfg.in_type],types[cfg.out_type]);
   if(cfg.temporal_auto_bezier!==undefined&&cfg.temporal_auto_bezier!==null)target.setTemporalAutoBezierAtKey(key,cfg.temporal_auto_bezier);
   if(cfg.temporal_continuous!==undefined&&cfg.temporal_continuous!==null)target.setTemporalContinuousAtKey(key,cfg.temporal_continuous);
   result.result.push({index:key-1,inType:target.keyInInterpolationType(key),outType:target.keyOutInterpolationType(key)});}}
 }else if(cfg.action==='create_folder'){
  var parent=item(cfg.parent_id);need(parent instanceof FolderItem,'parent_folder_not_found');
  var existing=null;for(var i=1;i<=p.numItems;i++){var x=p.item(i);if(x instanceof FolderItem&&x.parentFolder===parent&&x.name===cfg.name){need(!existing,'ambiguous_folder_name');existing=x;}}
  result.plan={name:cfg.name,parentId:cfg.parent_id,existingId:existing?existing.id:null};
  if(!cfg.dryRun){if(existing)result.result={id:existing.id,created:false};else {begin();var folder=p.items.addFolder(cfg.name);folder.parentFolder=parent;result.result={id:folder.id,created:true};}}
 }else if(cfg.action==='project_items'){
  var rows=[],plannedParents={},oldNames={},newNames={};
  for(var i=0;i<cfg.changes.length;i++){var change=cfg.changes[i],x=item(change.item_id);need(x&&x!==p.rootFolder,'project_item_not_found');
   var parent=change.folder_id!==undefined?item(change.folder_id):x.parentFolder;need(parent instanceof FolderItem,'destination_folder_not_found');
   if(cfg.fix_expressions&&change.name!==undefined&&change.name!==x.name){need(typeof p.autoFixExpressions==='function','expression_repair_unavailable');
    for(var n=1;n<=p.numItems;n++)if(p.item(n)!==x)need(p.item(n).name!==x.name,'ambiguous_expression_source_name');oldNames['$'+x.name]=true;
    need(!newNames['$'+change.name],'duplicate_destination_name');newNames['$'+change.name]=true;
    for(var q=1;q<=p.numItems;q++)if(p.item(q)!==x)need(p.item(q).name!==change.name,'ambiguous_expression_destination_name');}
   plannedParents[String(x.id)]=parent.id;rows.push({item:x,parent:parent,change:change,oldName:x.name});}
  for(var j=0;j<rows.length;j++){var row=rows[j],ancestor=row.parent,seen={};
   while(ancestor&&ancestor!==p.rootFolder){need(ancestor!==row.item&&!seen[String(ancestor.id)],'folder_cycle');seen[String(ancestor.id)]=true;
    ancestor=plannedParents[String(ancestor.id)]!==undefined?item(plannedParents[String(ancestor.id)]):ancestor.parentFolder;}
   if(cfg.fix_expressions&&row.change.name!==undefined&&row.change.name!==row.oldName)need(!oldNames['$'+row.change.name],'rename_chain_requires_separate_steps');}
  result.plan=cfg.changes;
  if(!cfg.dryRun){begin();result.result=[];
   for(var d=0;d<rows.length;d++)if(rows[d].item instanceof FolderItem&&rows[d].item.parentFolder!==rows[d].parent)rows[d].item.parentFolder=p.rootFolder;
   for(var k=0;k<rows.length;k++){var row=rows[k];row.item.parentFolder=row.parent;
   if(row.change.name!==undefined){row.item.name=row.change.name;if(cfg.fix_expressions&&row.oldName!==row.change.name)p.autoFixExpressions(row.oldName,row.change.name);}
   result.result.push({id:row.item.id,name:row.item.name,parentId:row.item.parentFolder===p.rootFolder?0:row.item.parentFolder.id});}}
 }else if(cfg.action==='render_output'){
  need(!p.renderQueue.rendering,'render_in_progress');var path=cfg.output_path,automatic=!path,suffix=0,stem=null;
  if(automatic){need(p.file,'save_project_before_default_render_path');stem=p.file.parent.fsName+'/'+safeName(c.name);
   path=stem+'.mov';while((outputExists(new File(path))||outputReserved(new File(path),null))&&suffix<1000){suffix++;path=stem+'_'+suffix+'.mov';}need(suffix<1000,'default_output_names_exhausted');}
  var file=new File(path);need(file.parent.exists,'output_directory_missing');need(cfg.overwrite||!outputExists(file),'render_destination_exists');need(!outputReserved(file,null),'render_output_reserved');
  result.plan={compId:c.id,path:file.fsName,exists:file.exists,renderTemplate:cfg.render_template||null,outputTemplate:cfg.output_template||null,
   templateValidation:'templates are validated during apply; new queue item is removed on failure'};
  if(!cfg.dryRun){begin();var ri=p.renderQueue.items.add(c);
   try{if(cfg.render_template)ri.applyTemplate(cfg.render_template);if(cfg.output_template)ri.outputModule(1).applyTemplate(cfg.output_template);
    var actual=null;while(true){ri.outputModule(1).setSettings({'Output File Info':{'Full Flat Path':file.fsName}});
     actual=ri.outputModule(1).file;need(actual,'output_path_readback_failed');
     var occupied=outputExists(actual),reserved=outputReserved(actual,ri);
     if(!reserved&&(!occupied||(cfg.overwrite&&!automatic)))break;
     if(!automatic){need(!reserved,'render_output_reserved');need(!occupied,'render_destination_exists');}
     suffix++;need(suffix<1000,'default_output_names_exhausted');file=new File(stem+'_'+suffix+'.mov');}
    result.result={index:p.renderQueue.numItems,path:actual.fsName,queued:ri.render};
   }catch(e){ri.remove();throw e;}}
 }
 result.applied=started;result.undoMode=undo?'single-group':'none';return JSON.stringify(result);
}catch(e){return JSON.stringify({ok:false,action:cfg.action,error:String(e),outcome:started?'unknown':'not_started',retrySafe:!started});}
finally{if(undo)app.endUndoGroup();}
})();'''


def invoke(ae: Any, action: str, options: dict | None = None, dry_run: bool = True) -> dict:
    cfg = normalize(action, options, dry_run)
    code = JSX.replace("SETTINGS", json.dumps(cfg, ensure_ascii=True, allow_nan=False))
    return json.loads(ae.run_jsx(code, timeout=120000 if action == "export_mogrt" else 60000))
