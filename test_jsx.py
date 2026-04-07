"""JSX Full Test — ae_bridge.py all methods"""
import sys; sys.path.insert(0, '.')
from ae_bridge import AEBridge
ae = AEBridge()
P, F, FAILS = 0, 0, []

def t(name, fn):
    global P, F
    try:
        r = fn()
        P += 1
    except Exception as e:
        print(f'  FAIL  {name}: {e}')
        F += 1; FAILS.append(name)

# 1. Query (6)
t('comp_info',          lambda: ae.comp_info()['name'])
t('project_info',       lambda: ae.project_info())
t('list_layers',        lambda: ae.list_layers())
t('layer_exists',       lambda: ae.layer_exists('Text1'))
t('get_layer_info',     lambda: ae.get_layer_info('Text1'))
t('list_comps',         lambda: ae.list_comps())

# 2. Property Read (6)
t('get_position',       lambda: ae.get_transform_value('Text1', 'position'))
t('get_opacity',        lambda: ae.get_transform_value('Text1', 'opacity'))
t('get_pos_at_t',       lambda: ae.get_transform_value('Text1', 'position', at_time=0.5))
t('get_keyframes',      lambda: ae.get_keyframes('Text1', 'opacity'))
t('get_prop_val',       lambda: ae.get_property_value('Text1', 'property("ADBE Transform Group").property("ADBE Opacity")'))
t('get_prop_kfs',       lambda: ae.get_property_keyframes('Text1', 'property("ADBE Transform Group").property("ADBE Position")'))

# 3. Shape (5)
ae.begin_undo('T')
t('add_shape',          lambda: ae.add_shape_layer('Shape1'))
t('shape_rect',         lambda: ae.add_shape_rect('Shape1', size=[200,100], roundness=10))
t('shape_ellipse',      lambda: ae.add_shape_ellipse('Shape1', size=[80,80]))
t('shape_fill',         lambda: ae.add_shape_fill('Shape1', color=[0,1,0]))
t('shape_stroke',       lambda: ae.add_shape_stroke('Shape1', color=[1,1,1], width=2))
ae.end_undo()

# 4. Mask (5)
ae.begin_undo('T')
t('add_mask',           lambda: ae.add_mask_rect('Solid1', 50, 50, 400, 300, feather=5))
t('list_masks',         lambda: ae.list_masks('Solid1'))
t('mask_feather',       lambda: ae.set_mask_feather('Solid1', 1, 15))
t('mask_opacity',       lambda: ae.set_mask_opacity('Solid1', 1, 80))
t('mask_expansion',     lambda: ae.set_mask_expansion('Solid1', 1, 5))
ae.end_undo()

# 5. Marker (5)
ae.begin_undo('T')
t('comp_marker',        lambda: ae.add_comp_marker(1.0, comment='B1', label=2))
t('comp_marker2',       lambda: ae.add_comp_marker(3.0, comment='B2', duration=0.5))
t('list_comp_mk',       lambda: ae.list_comp_markers())
t('layer_marker',       lambda: ae.add_layer_marker('Text1', 0.5, comment='LM'))
t('list_layer_mk',      lambda: ae.list_layer_markers('Text1'))
ae.end_undo()

# 6. Parent (4)
ae.begin_undo('T')
t('create_null',        lambda: ae.create_null_control('Ctrl', parent_to=['Text1']))
t('get_parent',         lambda: ae.get_parent('Text1'))
t('remove_parent',      lambda: ae.remove_parent('Text1'))
t('parent_none',        lambda: ae.get_parent('Text1'))
ae.end_undo()

# 7. Blend (3)
t('blend_set',          lambda: ae.set_blending_mode('Solid1', 'multiply'))
t('blend_get',          lambda: ae.get_blending_mode('Solid1'))
t('blend_back',         lambda: ae.set_blending_mode('Solid1', 'normal'))

# 8. Text Animator (2)
ae.begin_undo('T')
t('text_anim',          lambda: ae.add_text_animator('Text1', {'opacity': 0, 'position': [0,-20]}))
t('anim_selector',      lambda: ae.animate_text_selector('Text1', keyframes={'offset': [(0,0),(1,100)]}))
ae.end_undo()

# 9. Layer Styles (4)
t('style_ds',           lambda: ae.add_layer_style('Text1', 'drop_shadow'))
t('style_stroke',       lambda: ae.add_layer_style('Solid1', 'stroke'))
t('style_off',          lambda: ae.enable_layer_style('Text1', 'drop_shadow', False))
t('style_on',           lambda: ae.enable_layer_style('Text1', 'drop_shadow', True))

# 10. 3D/Camera/Light (5)
ae.begin_undo('T')
t('set_3d',             lambda: ae.set_3d_layer('Text1'))
t('camera',             lambda: ae.create_camera('Cam1', zoom=1200))
t('light',              lambda: ae.create_light('Light1', intensity=80))
t('cam_prop',           lambda: ae.set_camera_property('Cam1', 'zoom', 1500))
t('light_prop',         lambda: ae.set_light_property('Light1', 'intensity', 60))
ae.end_undo()

# 11. Keyframes (5)
ae.begin_undo('T')
t('pos_kf',             lambda: ae.set_position_keyframes('Solid1', [(0,[100,100]),(1,[500,500])]))
t('opa_kf',             lambda: ae.set_opacity_keyframes('Solid1', [(0,0),(0.5,100),(1,0)]))
t('scale_kf',           lambda: ae.set_scale_keyframes('Solid1', [(0,[50,50,100]),(1,[100,100,100])]))
t('rot_kf',             lambda: ae.set_rotation_keyframes('Solid1', [(0,0),(1,360)]))
t('easing',             lambda: ae.apply_easing('Solid1', ['opacity','position','scale']))
ae.end_undo()

# 12. Effects (4)
ae.begin_undo('T')
t('add_blur',           lambda: ae.add_effect('Solid1', 'gaussian_blur', props={'blurriness': 20}))
t('add_shadow',         lambda: ae.add_effect('Solid1', 'drop_shadow', props={'opacity': 150}))
t('enum_fx',            lambda: ae.enumerate_effects('Solid1'))
t('fx_ease',            lambda: ae.apply_effect_easing('Solid1', 'gaussian_blur', 'blurriness'))
ae.end_undo()

# 13. Expression (2)
t('set_expr',           lambda: ae.set_expression('Text1', 'property("ADBE Transform Group").property("ADBE Position")', 'wiggle(2,50)'))
t('clear_expr',         lambda: ae.clear_expression('Text1', 'property("ADBE Transform Group").property("ADBE Position")'))

# 14. Comp Mgmt (4)
t('create_comp',        lambda: ae.create_comp('Sub', 1920, 1080, 24, 5))
t('set_active',         lambda: ae.set_active_comp('FullTest2'))
t('precomps',           lambda: ae.list_precomps())
t('nest_comp',          lambda: ae.add_comp_to_comp('Sub'))

# 15. Import (1)
t('import',             lambda: ae.import_file(r'C:/Users/kensei/Downloads/新奥利 c1-c3_04.06.mov'))

# 16. Layer Mgmt (7)
t('add_text2',          lambda: ae.add_text_layer('Extra', name='XText'))
t('rename',             lambda: ae.rename_layer('XText', 'RText'))
t('set_label',          lambda: ae.set_layer_label('RText', 5))
t('set_timing',         lambda: ae.set_layer_timing('RText', start=1.0, end=5.0))
t('center_anchor',      lambda: ae.center_anchor('RText'))
t('dup_layer',          lambda: ae.duplicate_layer('Solid1'))
t('reorder',            lambda: ae.reorder_layer('RText', 1))

# 17. Selection (3)
t('select',             lambda: ae.select_layers(['Text1', 'Solid1']))
t('get_selected',       lambda: ae.get_selected_layers())
t('deselect',           lambda: ae.deselect_all())

# 18. Batch (1)
t('batch',              lambda: ae.batch_jsx(['"a"', '1+2', '"b"']))

# 19. Render Queue (1)
t('rq_info',            lambda: ae.render_queue_info())

# 20. Remove (3)
t('rm_layer',           lambda: ae.remove_layer('RText'))
t('rm_mask',            lambda: ae.remove_mask('Solid1', 1))
t('rm_marker',          lambda: ae.remove_comp_marker(1))

# 21. Precompose (1)
ae.begin_undo('T')
t('precompose',         lambda: ae.precompose(['Solid1'], comp_name='PreSolid'))
ae.end_undo()

# 22. Stable ID (1)
t('comp_by_id',         lambda: ae.set_active_comp_by_id(ae.list_comps()[0]['id']))

print(f'\n=== JSX TOTAL: {P}/{P+F} passed ===')
if FAILS: print(f'Failed: {FAILS}')
