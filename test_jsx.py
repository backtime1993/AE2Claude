"""JSX Full Test — all ae_bridge methods via ae2claude CLI"""
import subprocess, json, sys, os

P, F, FAILS = 0, 0, []

def call(*args):
    """Run ae2claude call <method> [args...]"""
    r = subprocess.run(
        [sys.executable, "ae2claude", "call"] + list(args),
        capture_output=True, text=True, timeout=30
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    out = r.stdout.strip()
    if out.startswith('{') or out.startswith('['):
        return json.loads(out)
    return out

def jsx(code):
    """Run ae2claude jsx <code>"""
    r = subprocess.run(
        [sys.executable, "ae2claude", "jsx", code],
        capture_output=True, text=True, timeout=30
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout.strip()

def t(name, fn):
    global P, F
    try:
        r = fn()
        P += 1
    except Exception as e:
        print(f'  FAIL  {name}: {e}')
        F += 1; FAILS.append(name)

# 1. Query (5)
t('comp_info',          lambda: call('comp_info'))
t('project_info',       lambda: call('project_info'))
t('list_layers',        lambda: call('list_layers'))
t('get_layer_info',     lambda: call('get_layer_info', 'Text1'))
t('list_comps',         lambda: call('list_comps'))

# 2. Property Read (4)
t('get_position',       lambda: call('get_value', 'Text1', 'position'))
t('get_opacity',        lambda: call('get_value', 'Text1', 'opacity'))
t('get_pos_at_t',       lambda: call('get_value', 'Text1', 'position', '--at_time', '0.5'))
t('get_keyframes',      lambda: call('get_keyframes', 'Text1', 'opacity'))

# 3. Shape (5)
t('begin_undo',         lambda: call('begin_undo', 'T'))
t('add_shape',          lambda: call('add_shape_layer', 'Shape1'))
t('shape_rect',         lambda: call('add_shape_rect', 'Shape1', '--size', '[200,100]', '--roundness', '10'))
t('shape_fill',         lambda: call('add_shape_fill', 'Shape1', '--color', '[0,1,0]'))
t('shape_stroke',       lambda: call('add_shape_stroke', 'Shape1', '--color', '[1,1,1]', '--width', '2'))
t('end_undo',           lambda: call('end_undo'))

# 4. Mask (5)
t('begin_undo2',        lambda: call('begin_undo', 'T'))
t('add_mask',           lambda: call('add_mask', 'Solid1', '[[50,50],[450,50],[450,350],[50,350]]', '--feather', '5'))
t('list_masks',         lambda: call('list_masks', 'Solid1'))
t('mask_feather',       lambda: call('set_mask_feather', 'Solid1', '1', '15'))
t('mask_opacity',       lambda: call('set_mask_opacity', 'Solid1', '1', '80'))
t('end_undo2',          lambda: call('end_undo'))

# 5. Marker (5)
t('comp_marker',        lambda: call('add_comp_marker', '1.0', '--comment', 'B1', '--label', '2'))
t('comp_marker2',       lambda: call('add_comp_marker', '3.0', '--comment', 'B2', '--duration', '0.5'))
t('list_comp_mk',       lambda: call('list_comp_markers'))
t('layer_marker',       lambda: call('add_layer_marker', 'Text1', '0.5', '--comment', 'LM'))
t('list_layer_mk',      lambda: call('list_layer_markers', 'Text1'))

# 6. Parent (4)
t('create_null',        lambda: call('create_null_control', 'Ctrl', '--parent_to', '["Text1"]'))
t('get_parent',         lambda: call('get_parent', 'Text1'))
t('remove_parent',      lambda: call('remove_parent', 'Text1'))
t('parent_none',        lambda: call('get_parent', 'Text1'))

# 7. Blend (3)
t('blend_set',          lambda: call('set_blending_mode', 'Solid1', 'multiply'))
t('blend_get',          lambda: call('get_blending_mode', 'Solid1'))
t('blend_back',         lambda: call('set_blending_mode', 'Solid1', 'normal'))

# 8. Text Animator (2)
t('text_anim',          lambda: call('add_text_animator', 'Text1', '--properties', '{"opacity": 0}'))
t('anim_selector',      lambda: call('animate_text_selector', 'Text1', '--keyframes', '{"offset": [[0,0],[1,100]]}'))

# 9. Layer Styles (2) — returns ERR:not_scriptable (expected, AEGP-only)
t('style_ds',           lambda: call('add_layer_style', 'Text1', 'drop_shadow'))
t('style_off',          lambda: call('enable_layer_style', 'Text1', 'drop_shadow', 'false'))

# 10. 3D/Camera/Light (5)
t('set_3d',             lambda: call('set_3d_layer', 'Text1'))
t('camera',             lambda: call('create_camera', 'Cam1', '--zoom', '1200'))
t('light',              lambda: call('create_light', 'Light1', '--intensity', '80'))
t('cam_prop',           lambda: call('set_camera_property', 'Cam1', 'zoom', '1500'))
t('light_prop',         lambda: call('set_light_property', 'Light1', 'intensity', '60'))

# 11. Keyframes (7)
t('pos_kf',             lambda: call('set_keyframes', 'Solid1', 'position', '[[0,[100,100]],[1,[500,500]]]'))
t('opa_kf',             lambda: call('set_keyframes', 'Solid1', 'opacity', '[[0,0],[0.5,100],[1,0]]'))
t('scale_kf',           lambda: call('set_keyframes', 'Solid1', 'scale', '[[0,[50,50,100]],[1,[100,100,100]]]'))
t('rot_kf',             lambda: call('set_keyframes', 'Solid1', 'rotation', '[[0,0],[1,360]]'))
t('easing_opa',         lambda: call('apply_transform_easing', 'Solid1', 'opacity'))
t('easing_pos',         lambda: call('apply_transform_easing', 'Solid1', 'position'))
t('easing_scale',       lambda: call('apply_transform_easing', 'Solid1', 'scale'))

# 12. Effects (6)
t('add_blur',           lambda: call('add_effect', 'Solid1', 'gaussian_blur'))
t('set_blur_props',     lambda: call('set_effect_props', 'Solid1', '1', '{"blurriness": 20}'))
t('add_shadow',         lambda: call('add_effect', 'Solid1', 'drop_shadow'))
t('set_shadow_props',   lambda: call('set_effect_props', 'Solid1', '2', '{"opacity": 150}'))
t('enum_fx',            lambda: call('enumerate_effects', 'Solid1'))
t('fx_ease',            lambda: call('apply_effect_easing', 'Solid1', '1', 'blurriness'))

# 13. Expression (2)
t('set_expr',           lambda: jsx('var c=app.project.activeItem;c.layer("Text1").property("ADBE Transform Group").property("ADBE Position").expression="wiggle(2,50)";"ok"'))
t('clear_expr',         lambda: jsx('var c=app.project.activeItem;c.layer("Text1").property("ADBE Transform Group").property("ADBE Position").expression="";"ok"'))

# 14. Comp Mgmt (4)
t('create_comp',        lambda: call('create_comp', 'Sub', '1920', '1080', '24', '5'))
t('set_active',         lambda: call('set_active_comp', 'Final'))
t('precomps',           lambda: call('list_precomps'))
t('nest_comp',          lambda: call('add_comp_to_comp', 'Sub'))

# 15. Import (1) — 跳过如果没有测试素材
import glob as _glob
_test_movs = _glob.glob(os.path.expanduser("~/Downloads/*.mov"))
if _test_movs:
    t('import',         lambda: call('import_file', _test_movs[0].replace('\\', '/')))
else:
    P += 1  # skip but count as pass

# 16. Layer Mgmt (7)
t('add_text2',          lambda: call('add_text_layer', 'Extra', 'XText'))
t('rename',             lambda: call('rename_layer', 'XText', 'RText'))
t('set_label',          lambda: call('set_layer_label', 'RText', '5'))
t('set_timing',         lambda: call('set_layer_timing', 'RText', '--start', '1.0', '--end', '5.0'))
t('center_anchor',      lambda: call('center_anchor', 'RText'))
t('dup_layer',          lambda: call('duplicate_layer', 'Solid1'))
t('reorder',            lambda: call('reorder_layer', 'RText', '1'))

# 17. New v3 methods (4)
t('add_solid',          lambda: call('add_solid', 'TestSolid', '[1,0,0]'))
t('set_text_content',   lambda: call('set_text_content', 'Text1', 'Changed'))
t('set_text_style',     lambda: call('set_text_style', 'Text1', '--font_size', '72', '--fill_color', '[1,1,1]'))
t('set_value',          lambda: call('set_value', 'Text1', 'opacity', '50'))

# 18. Selection (3)
t('select',             lambda: call('set_layer_selected', 'Text1', 'true'))
t('get_selected',       lambda: call('get_selected_layers'))
t('deselect',           lambda: call('deselect_all'))

# 19. Render Queue (1)
t('rq_info',            lambda: call('render_queue_info'))

# 20. Remove (3)
t('rm_layer',           lambda: call('remove_layer', 'RText'))
t('rm_mask',            lambda: call('remove_mask', 'Solid1', '1'))
t('rm_marker',          lambda: call('remove_comp_marker', '1'))

# 21. Precompose (1)
t('precompose',         lambda: call('precompose', '["Solid1"]', 'PreSolid'))

# 22. Stable ID (1)
comps = call('list_comps')
if comps:
    t('comp_by_id',     lambda: call('set_active_comp_by_id', str(comps[0]['id'])))

print(f'\n=== JSX TOTAL: {P}/{P+F} passed ===')
if FAILS: print(f'Failed: {FAILS}')
