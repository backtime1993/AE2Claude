"""C++ Native API Full Test — PyShiftCore via POST /"""
import json, urllib.request

BASE = "http://127.0.0.1:8089"

def run(code):
    data = code.encode('utf-8')
    req = urllib.request.Request(f"{BASE}/", data=data,
        headers={'Content-Type': 'text/plain; charset=utf-8'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

code = '''
import PyShiftCore as psc
P, F, FAILS = 0, 0, []

def t(name, fn):
    global P, F, FAILS
    try:
        r = fn()
        P += 1
    except Exception as e:
        print(f"  FAIL  {name}: {e}")
        F += 1; FAILS.append(name)

comp = psc.app.project.activeItem

# 1. App/Project (6)
t("app",                lambda: psc.app is not None)
t("project",            lambda: psc.app.project is not None)
t("comp_name",          lambda: comp.name)
t("comp_size",          lambda: f"{comp.width}x{comp.height}")
t("numLayers",          lambda: comp.numLayers)
t("frameRate",          lambda: comp.frameRate)

# 2. CompItem expanded (5)
t("bgColor",            lambda: comp.bgColor)
t("workAreaStart",      lambda: comp.workAreaStart)
t("workAreaDuration",   lambda: comp.workAreaDuration)
t("displayStartTime",   lambda: comp.displayStartTime)
t("bgColor_set",        lambda: (setattr(comp, "bgColor", [0.1, 0.1, 0.1]), "ok")[1])

# 3. Layer basics (6)
layer = comp.layers[0]
t("layer_name",         lambda: layer.name)
t("label_get",          lambda: layer.label)
t("label_set",          lambda: (setattr(layer, "label", 7), layer.label)[1])
t("is3D",               lambda: layer.is3D)
t("layerID",            lambda: layer.layerID)
t("index",              lambda: layer.index)

# 4. Layer expanded (4)
t("transferMode",       lambda: layer.transferMode)
t("stretch",            lambda: layer.stretch)
t("objectType",         lambda: layer.objectType)
t("samplingQuality",    lambda: layer.samplingQuality)

# 5. UI refresh (1)
t("refresh_ui",         lambda: psc.refresh_ui())

# Find Text1 layer
text_layer = None
for i in range(comp.numLayers):
    if comp.layers[i].name == "Text1":
        text_layer = comp.layers[i]; break

if text_layer:
    path = ["ADBE Transform Group", "ADBE Opacity"]
    pos_path = ["ADBE Transform Group", "ADBE Position"]

    # 6. Stream value (2)
    t("get_stream_val",     lambda: psc.get_stream_value(text_layer, pos_path, 0.0))
    t("get_stream_opa",     lambda: psc.get_stream_value(text_layer, path, 0.5))

    # 7. Property tree (2)
    t("list_streams",       lambda: len(psc.list_streams(text_layer, [])))
    t("list_transform",     lambda: len(psc.list_streams(text_layer, ["ADBE Transform Group"])))

    # 8. Keyframe CRUD (7)
    t("kf_count",           lambda: psc.get_stream_keyframe_count(text_layer, path))
    t("kf_time",            lambda: psc.get_keyframe_time(text_layer, path, 0))
    t("kf_value",           lambda: psc.get_keyframe_value(text_layer, path, 0))
    t("kf_insert",          lambda: psc.insert_keyframe(text_layer, path, 0.5))
    t("kf_count2",          lambda: psc.get_stream_keyframe_count(text_layer, path))
    t("kf_delete",          lambda: psc.delete_keyframe(text_layer, path, 1))
    t("kf_ease",            lambda: psc.set_keyframe_ease(text_layer, path, 0, 0, 80, 0, 80, 1))

    # 9. Interpolation (1)
    t("kf_interp",          lambda: psc.set_keyframe_interpolation(text_layer, path, 0, 6, 6))

    # 10. Expression (3)
    t("set_expr",           lambda: psc.set_expression(text_layer, pos_path, "wiggle(2,50)"))
    t("get_expr",           lambda: psc.get_expression(text_layer, pos_path))
    t("clear_expr",         lambda: psc.set_expression(text_layer, pos_path, ""))

    # 11. Layer Styles AEGP (3)
    t("enable_style",       lambda: psc.enable_layer_style(text_layer, "innerGlow/enabled", True))
    t("set_flag",           lambda: psc.set_stream_flag(text_layer, ["ADBE Layer Styles", "bevelEmboss/enabled"], 1, True))
    t("unhide",             lambda: psc.unhide_stream_children(text_layer, ["ADBE Layer Styles"]))

    # 12. Effect native (5)
    t("num_effects",        lambda: psc.get_layer_num_effects(text_layer))
    t("apply_fx",           lambda: psc.apply_effect(text_layer, "ADBE Gaussian Blur 2"))
    t("fx_matchname",       lambda: psc.get_effect_matchname(text_layer, 0))
    t("fx_enabled",         lambda: psc.set_effect_enabled(text_layer, 0, False))
    t("fx_delete",          lambda: psc.delete_effect(text_layer, 0))

# 13. Item ops (4)
t("item_type",          lambda: psc.get_item_type(comp.layers[0].source))
t("item_id",            lambda: psc.get_item_id(comp.layers[0].source))
t("item_label",         lambda: psc.get_item_label(comp.layers[0].source))
t("item_comment_set",   lambda: psc.set_item_comment(comp.layers[0].source, "test comment"))

# 14. Project ops (3)
t("is_dirty",           lambda: psc.is_project_dirty())
t("bit_depth",          lambda: psc.get_project_bit_depth())
t("execute_cmd",        lambda: psc.execute_command(2004))  # Select All

print(f"\\nC++ TOTAL: {P}/{P+F} passed")
if FAILS: print(f"Failed: {FAILS}")
'''

r = run(code)
if r.get('output'):
    print(r['output'])
if r.get('error'):
    print(f"ERROR: {r['error']}")
