"""C++ Stable API Test — via ae2claude py CLI"""
import subprocess, sys

P, F, FAILS = 0, 0, []

def py(code):
    r = subprocess.run(
        [sys.executable, "ae2claude", "py", code],
        capture_output=True, text=True, timeout=15
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return r.stdout.strip()

def t(name, fn):
    global P, F
    try:
        r = fn()
        print(f'  PASS  {name}: {r[:80] if r else "ok"}')
        P += 1
    except Exception as e:
        print(f'  FAIL  {name}: {e}')
        F += 1; FAILS.append(name)

t('comp_name',      lambda: py('import PyShiftCore as psc; print(psc.app.project.activeItem.name)'))
t('comp_fps',       lambda: py('import PyShiftCore as psc; print(psc.app.project.activeItem.frameRate)'))
t('comp_size',      lambda: py('import PyShiftCore as psc; c=psc.app.project.activeItem; print(c.width, c.height)'))
t('comp_bgColor',   lambda: py('import PyShiftCore as psc; print(psc.app.project.activeItem.bgColor)'))
t('comp_workArea',  lambda: py('import PyShiftCore as psc; c=psc.app.project.activeItem; print(c.workAreaStart, c.workAreaDuration)'))
t('layer_name',     lambda: py('import PyShiftCore as psc; print(psc.app.project.activeItem.layers[0].name)'))
t('layer_label',    lambda: py('import PyShiftCore as psc; print(psc.app.project.activeItem.layers[0].label)'))
t('layer_is3D',     lambda: py('import PyShiftCore as psc; print(psc.app.project.activeItem.layers[0].is3D)'))
t('layer_layerID',  lambda: py('import PyShiftCore as psc; print(psc.app.project.activeItem.layers[0].layerID)'))
t('layer_transfer', lambda: py('import PyShiftCore as psc; print(psc.app.project.activeItem.layers[0].transferMode)'))
t('layer_stretch',  lambda: py('import PyShiftCore as psc; print(psc.app.project.activeItem.layers[0].stretch)'))
t('layer_objType',  lambda: py('import PyShiftCore as psc; print(psc.app.project.activeItem.layers[0].objectType)'))
t('label_set',      lambda: py('import PyShiftCore as psc; l=psc.app.project.activeItem.layers[0]; l.label=3; print(l.label)'))
t('refresh_ui',     lambda: py('import PyShiftCore as psc; print(psc.refresh_ui())'))

print(f'\n=== C++ STABLE: {P}/{P+F} passed ===')
if FAILS: print(f'Failed: {FAILS}')
