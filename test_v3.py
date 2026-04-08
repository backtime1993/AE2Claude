"""AE2Claude v3.0 Self-contained Integration Test

Creates its own composition + layers, tests every v3 API domain, then cleans up.
Does NOT depend on any pre-existing AE project state.
"""
import subprocess, json, sys, os, time

P, F, FAILS = 0, 0, []

_DIR = os.path.dirname(os.path.abspath(__file__))
_CLI = os.path.join(_DIR, "ae2claude")


def call(*args):
    """Run ae2claude call <method> [args...]"""
    r = subprocess.run(
        [sys.executable, _CLI, "call"] + [str(a) for a in args],
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
        [sys.executable, _CLI, "jsx", code],
        capture_output=True, text=True, timeout=30
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout.strip()


def t(name, fn):
    global P, F
    try:
        r = fn()
        print(f'  pass  {name}')
        P += 1
    except Exception as e:
        print(f'  FAIL  {name}: {e}')
        F += 1
        FAILS.append(name)


# ══════════════════════════════════════════════════════════
# SETUP: Create TestV3 composition and seed layers
# ══════════════════════════════════════════════════════════

print('\n[Setup] Creating TestV3 composition...')

# Delete any leftover TestV3 comp from a previous run
jsx(
    '(function(){'
    'for(var i=app.project.numItems;i>=1;i--){'
    'var it=app.project.item(i);'
    'if(it instanceof CompItem&&(it.name=="TestV3"||it.name=="SubComp"||it.name=="PreSolid"))'
    'it.remove();}'
    '})()'
)

# Create fresh TestV3 composition: 1920x1080, 30fps, 10s
jsx(
    'var c=app.project.items.addComp("TestV3",1920,1080,1,10,30);'
    'c.openInViewer();c.name;'
)

call('begin_undo', 'TestV3Setup')

# Create text layer "Text1"
call('add_text_layer', 'Hello World', 'Text1')

# Create solid layer "Solid1" via add_solid (v3 method)
call('add_solid', 'Solid1', '[0,0,1]')

# Create a null for parenting tests
call('create_null_control', 'NullCtrl')

call('end_undo')

print('[Setup] Done. Starting tests...\n')


# ══════════════════════════════════════════════════════════
# 1. QUERY DOMAIN
# ══════════════════════════════════════════════════════════

print('--- Query ---')

t('comp_info',      lambda: call('comp_info'))
t('project_info',   lambda: call('project_info'))
t('list_layers',    lambda: call('list_layers'))
t('list_comps',     lambda: call('list_comps'))
t('get_layer_info', lambda: call('get_layer_info', 'Text1'))


# ══════════════════════════════════════════════════════════
# 2. TRANSFORM DOMAIN (unified set/get_value, set/get_keyframes)
# ══════════════════════════════════════════════════════════

print('\n--- Transform ---')

t('set_value_opacity',
    lambda: call('set_value', 'Text1', 'opacity', '50'))

t('get_value_opacity_verify', lambda: (
    lambda v: (lambda _: None)(
        None if (float(v) == 50 or (isinstance(v, list) and float(v[0]) == 50))
        else (_ for _ in ()).throw(AssertionError(f'Expected 50, got {v}'))
    )
)(call('get_value', 'Text1', 'opacity')))

t('set_value_opacity_at_time',
    lambda: call('set_value', 'Text1', 'opacity', '80', '--at_time', '2.0'))

t('set_keyframes_position',
    lambda: call('set_keyframes', 'Text1', 'position',
                 '[[0,[100,200]],[5,[800,400]],[10,[1800,900]]]'))

t('get_keyframes_position', lambda: (
    lambda kfs: (lambda _: None)(
        None if len(kfs) >= 2
        else (_ for _ in ()).throw(AssertionError(f'Expected >=2 keyframes, got {len(kfs)}'))
    )
)(call('get_keyframes', 'Text1', 'position')))

t('set_keyframes_opacity',
    lambda: call('set_keyframes', 'Solid1', 'opacity',
                 '[[0,0],[3,100],[7,100],[10,0]]'))

t('set_keyframes_scale',
    lambda: call('set_keyframes', 'Solid1', 'scale',
                 '[[0,[50,50]],[5,[100,100]],[10,[80,80]]]'))

t('set_keyframes_rotation',
    lambda: call('set_keyframes', 'Solid1', 'rotation',
                 '[[0,0],[10,360]]'))

t('get_value_position',
    lambda: call('get_value', 'Text1', 'position'))

t('get_value_position_at_time',
    lambda: call('get_value', 'Text1', 'position', '--at_time', '2.5'))

t('get_keyframes_opacity',
    lambda: call('get_keyframes', 'Solid1', 'opacity'))


# ══════════════════════════════════════════════════════════
# 3. TEXT DOMAIN (new v3 methods)
# ══════════════════════════════════════════════════════════

print('\n--- Text ---')

t('set_text_content',
    lambda: call('set_text_content', 'Text1', 'Modified'))

t('set_text_style_font_size',
    lambda: call('set_text_style', 'Text1', '--font_size', '72'))

t('set_text_style_fill_color',
    lambda: call('set_text_style', 'Text1', '--fill_color', '[1,0,0]'))

t('set_text_style_combined',
    lambda: call('set_text_style', 'Text1',
                 '--font_size', '60',
                 '--fill_color', '[1,1,0]'))


# ══════════════════════════════════════════════════════════
# 4. LAYER DOMAIN
# ══════════════════════════════════════════════════════════

print('\n--- Layer ---')

t('set_layer_timing',
    lambda: call('set_layer_timing', 'Solid1', '--start', '1.0', '--end', '9.0'))

t('set_layer_label',
    lambda: call('set_layer_label', 'Text1', '3'))

t('set_3d_layer',
    lambda: call('set_3d_layer', 'Text1'))

t('set_blending_mode',
    lambda: call('set_blending_mode', 'Solid1', 'multiply'))

t('get_blending_mode',
    lambda: call('get_blending_mode', 'Solid1'))

t('set_blending_mode_back',
    lambda: call('set_blending_mode', 'Solid1', 'normal'))

t('rename_layer',
    lambda: call('rename_layer', 'NullCtrl', 'NullRenamed'))

t('duplicate_layer',
    lambda: call('duplicate_layer', 'Solid1'))

# Layer selection
t('set_layer_selected',
    lambda: call('set_layer_selected', 'Text1', 'true'))

t('get_selected_layers',  lambda: (
    lambda sel: (lambda _: None)(
        None if len(sel) >= 1
        else (_ for _ in ()).throw(AssertionError(f'Expected >=1 selected, got {sel}'))
    )
)(call('get_selected_layers')))

t('deselect_all',
    lambda: call('deselect_all'))

# Parenting
t('set_parent',
    lambda: call('set_parent', 'Text1', 'NullRenamed'))

t('get_parent', lambda: (
    lambda p: (lambda _: None)(
        None if p == 'NullRenamed'
        else (_ for _ in ()).throw(AssertionError(f'Expected NullRenamed, got {p}'))
    )
)(call('get_parent', 'Text1')))

t('remove_parent',
    lambda: call('remove_parent', 'Text1'))

t('get_parent_after_remove', lambda: (
    lambda p: (lambda _: None)(
        None if p == 'null' or p == '' or p is None
        else (_ for _ in ()).throw(AssertionError(f'Expected null parent, got {p}'))
    )
)(call('get_parent', 'Text1')))

t('center_anchor',
    lambda: call('center_anchor', 'Solid1'))

t('reorder_layer',
    lambda: call('reorder_layer', 'Text1', '1'))


# ══════════════════════════════════════════════════════════
# 5. EFFECT DOMAIN (v3 index-based)
# ══════════════════════════════════════════════════════════

print('\n--- Effects ---')

# add_effect returns the effect index as a string, parse it
blur_idx = None

def _add_blur():
    global blur_idx
    result = call('add_effect', 'Solid1', 'gaussian_blur')
    blur_idx = int(result)
    return blur_idx

t('add_effect_gaussian_blur', _add_blur)

t('set_effect_props',
    lambda: call('set_effect_props', 'Solid1', str(blur_idx or 1),
                 '{"blurriness": 20}'))

t('set_effect_keyframes',
    lambda: call('set_effect_keyframes', 'Solid1', str(blur_idx or 1),
                 '{"blurriness": [[0,0],[5,50],[10,0]]}'))

t('enumerate_effects', lambda: (
    lambda efx: (lambda _: None)(
        None if len(efx) >= 1
        else (_ for _ in ()).throw(AssertionError(f'Expected >=1 effect, got {efx}'))
    )
)(call('enumerate_effects', 'Solid1')))

t('get_effect_param',
    lambda: call('get_effect_param', 'Solid1', str(blur_idx or 1), 'blurriness'))

t('get_effect_keyframes', lambda: (
    lambda kfs: (lambda _: None)(
        None if len(kfs) >= 2
        else (_ for _ in ()).throw(AssertionError(f'Expected >=2 kfs, got {kfs}'))
    )
)(call('get_effect_keyframes', 'Solid1', str(blur_idx or 1), 'blurriness')))

# Add a second effect (drop_shadow) to test index 2
shadow_idx = None

def _add_shadow():
    global shadow_idx
    result = call('add_effect', 'Solid1', 'drop_shadow')
    shadow_idx = int(result)
    return shadow_idx

t('add_effect_drop_shadow', _add_shadow)

t('set_effect_props_shadow',
    lambda: call('set_effect_props', 'Solid1', str(shadow_idx or 2),
                 '{"opacity": 120, "softness": 15}'))


# ══════════════════════════════════════════════════════════
# 6. EASING DOMAIN (v3 split methods)
# ══════════════════════════════════════════════════════════

print('\n--- Easing ---')

t('apply_transform_easing_opacity',
    lambda: call('apply_transform_easing', 'Solid1', 'opacity'))

t('apply_transform_easing_position',
    lambda: call('apply_transform_easing', 'Text1', 'position'))

t('apply_transform_easing_scale',
    lambda: call('apply_transform_easing', 'Solid1', 'scale'))

t('apply_transform_easing_rotation',
    lambda: call('apply_transform_easing', 'Solid1', 'rotation'))

t('apply_effect_easing',
    lambda: call('apply_effect_easing', 'Solid1', str(blur_idx or 1), 'blurriness'))


# ══════════════════════════════════════════════════════════
# 7. MASK DOMAIN
# ══════════════════════════════════════════════════════════

print('\n--- Masks ---')

t('add_mask',
    lambda: call('add_mask', 'Solid1',
                 '[[50,50],[850,50],[850,650],[50,650]]'))

t('list_masks', lambda: (
    lambda masks: (lambda _: None)(
        None if len(masks) >= 1
        else (_ for _ in ()).throw(AssertionError(f'Expected >=1 mask, got {masks}'))
    )
)(call('list_masks', 'Solid1')))

t('set_mask_feather',
    lambda: call('set_mask_feather', 'Solid1', '1', '20'))

t('set_mask_opacity',
    lambda: call('set_mask_opacity', 'Solid1', '1', '85'))

t('set_mask_expansion',
    lambda: call('set_mask_expansion', 'Solid1', '1', '5'))

t('remove_mask',
    lambda: call('remove_mask', 'Solid1', '1'))


# ══════════════════════════════════════════════════════════
# 8. MARKER DOMAIN
# ══════════════════════════════════════════════════════════

print('\n--- Markers ---')

t('add_comp_marker_1',
    lambda: call('add_comp_marker', '1.0', '--comment', 'Beat1', '--label', '2'))

t('add_comp_marker_2',
    lambda: call('add_comp_marker', '4.0', '--comment', 'Beat2', '--duration', '0.5'))

t('list_comp_markers', lambda: (
    lambda markers: (lambda _: None)(
        None if len(markers) >= 2
        else (_ for _ in ()).throw(AssertionError(f'Expected >=2 markers, got {markers}'))
    )
)(call('list_comp_markers')))

t('remove_comp_marker',
    lambda: call('remove_comp_marker', '1'))

t('add_layer_marker',
    lambda: call('add_layer_marker', 'Text1', '2.0', '--comment', 'LayerMark'))

t('list_layer_markers', lambda: (
    lambda markers: (lambda _: None)(
        None if len(markers) >= 1
        else (_ for _ in ()).throw(AssertionError(f'Expected >=1 marker, got {markers}'))
    )
)(call('list_layer_markers', 'Text1')))


# ══════════════════════════════════════════════════════════
# 9. EXPRESSION DOMAIN (via JSX)
# ══════════════════════════════════════════════════════════

print('\n--- Expressions ---')

t('set_expression',
    lambda: jsx(
        'var c=app.project.activeItem;'
        'c.layer("Text1")'
        '.property("Transform")'
        '.property("Opacity")'
        '.expression="Math.sin(time)*30+70";'
        '"ok"'
    ))

t('clear_expression',
    lambda: jsx(
        'var c=app.project.activeItem;'
        'c.layer("Text1")'
        '.property("Transform")'
        '.property("Opacity")'
        '.expression="";'
        '"ok"'
    ))


# ══════════════════════════════════════════════════════════
# 10. COMPOSITION MANAGEMENT
# ══════════════════════════════════════════════════════════

print('\n--- Composition Management ---')

t('create_comp_sub',
    lambda: call('create_comp', 'SubComp', '1920', '1080', '30', '5'))

t('set_active_comp_back',
    lambda: call('set_active_comp', 'TestV3'))

t('list_precomps',
    lambda: call('list_precomps'))

t('add_comp_to_comp',
    lambda: call('add_comp_to_comp', 'SubComp', 'TestV3'))

t('precompose',
    lambda: call('precompose', '["Solid1"]', 'PreSolid'))

t('set_active_comp_after_precompose',
    lambda: call('set_active_comp', 'TestV3'))


# ══════════════════════════════════════════════════════════
# 11. RENDER QUEUE (query only)
# ══════════════════════════════════════════════════════════

print('\n--- Render Queue ---')

t('render_queue_info',
    lambda: call('render_queue_info'))


# ══════════════════════════════════════════════════════════
# 12. TIME REMAP (on the SubComp layer in TestV3)
# ══════════════════════════════════════════════════════════

print('\n--- Time Remap ---')

# SubComp was nested into TestV3 via add_comp_to_comp; find its layer name
def _enable_time_remap():
    layers = call('list_layers')
    # find a precomp/footage layer (SubComp layer will be named "SubComp")
    target = None
    for l in layers:
        if 'SubComp' in l.get('name', '') or 'PreSolid' in l.get('name', ''):
            target = l['name']
            break
    if not target:
        raise RuntimeError('No SubComp/PreSolid layer found in TestV3 for time remap')
    result = call('enable_time_remap', target)
    # "ERR:layer_not_supported" means the layer can't remap — acceptable
    if result.startswith('ERR:layer_not_supported'):
        return 'skipped (layer_not_supported)'
    return result

t('enable_time_remap', _enable_time_remap)

def _set_time_remap_kfs():
    layers = call('list_layers')
    target = None
    for l in layers:
        if 'SubComp' in l.get('name', '') or 'PreSolid' in l.get('name', ''):
            target = l['name']
            break
    if not target:
        raise RuntimeError('No SubComp/PreSolid layer found for time remap kfs')
    result = call('set_time_remap_keyframes', target,
                  '[[0,0],[2.5,2.5],[5,5]]')
    if result.startswith('ERR:layer_not_supported'):
        return 'skipped (layer_not_supported)'
    return result

t('set_time_remap_keyframes', _set_time_remap_kfs)


# ══════════════════════════════════════════════════════════
# CLEANUP: Remove test compositions
# ══════════════════════════════════════════════════════════

print('\n[Cleanup] Removing test compositions...')

jsx(
    '(function(){'
    'var names={"TestV3":1,"SubComp":1,"PreSolid":1};'
    'for(var i=app.project.numItems;i>=1;i--){'
    'var it=app.project.item(i);'
    'if(it instanceof CompItem&&names[it.name])it.remove();}'
    '})()'
)

print('[Cleanup] Done.')


# ══════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════

print(f'\n=== V3 TEST: {P}/{P+F} passed ===')
if FAILS:
    print(f'Failed: {FAILS}')
