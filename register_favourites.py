"""Register MoBar favourites as CLI scripts"""
import json, os

scripts_dir = 'scripts'
reg_path = os.path.join(scripts_dir, 'registry.json')
with open(reg_path, 'r', encoding='utf-8') as f:
    reg = json.load(f)

settings_path = os.path.expanduser(r"~\AppData\Roaming\MoBar\settings-v2.json")
with open(settings_path, 'r', encoding='utf-8') as f:
    d = json.load(f)

fav = d.get('workspaces', {}).get('1', {}).get('favourites', [])

for item in fav:
    t = item.get('type', '')
    name = item.get('name', '')
    cmd = item.get('command', '')

    slug = 'fx-' + name.lower().replace(' ', '-').replace('/', '-')
    for ch in "'()_":
        slug = slug.replace(ch, '')
    slug = slug.replace('--', '-').strip('-')

    if any(s['slug'] == slug for s in reg):
        continue

    if t == 'effect':
        code = (
            f'/* 效果: {name} (matchName: {cmd}) */\n'
            f'(function(){{\n'
            f'var comp = app.project.activeItem;\n'
            f'if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";\n'
            f'var sel = comp.selectedLayers;\n'
            f'if (sel.length === 0) return "ERR:no_selection";\n'
            f'app.beginUndoGroup("Add {name}");\n'
            f'for (var i = 0; i < sel.length; i++) {{\n'
            f'    try {{ sel[i].property("Effects").addProperty("{cmd}"); }} catch(e) {{}}\n'
            f'}}\n'
            f'app.endUndoGroup();\n'
            f'return "added:{name}:" + sel.length;\n'
            f'}})()\n'
        )
    elif t == 'preset':
        path = cmd.replace('\\', '/')
        code = (
            f'/* 预设: {name} */\n'
            f'(function(){{\n'
            f'var comp = app.project.activeItem;\n'
            f'if (!comp || !(comp instanceof CompItem)) return "ERR:no_comp";\n'
            f'var sel = comp.selectedLayers;\n'
            f'if (sel.length === 0) return "ERR:no_selection";\n'
            f'app.beginUndoGroup("Apply {name}");\n'
            f'var f = new File("{path}");\n'
            f'if (!f.exists) return "ERR:preset_not_found";\n'
            f'for (var i = 0; i < sel.length; i++) {{\n'
            f'    sel[i].applyPreset(f);\n'
            f'}}\n'
            f'app.endUndoGroup();\n'
            f'return "applied:{name}:" + sel.length;\n'
            f'}})()\n'
        )
    else:
        continue

    fname = slug + '.jsx'
    with open(os.path.join(scripts_dir, fname), 'w', encoding='utf-8') as f:
        f.write(code)
    reg.append({'slug': slug, 'name': name, 'file': fname, 'note': 'MoBar收藏插件'})
    print(f'  {slug}')

with open(reg_path, 'w', encoding='utf-8') as f:
    json.dump(reg, f, indent=2, ensure_ascii=False)
print(f'\n共 {len(reg)} scripts')
