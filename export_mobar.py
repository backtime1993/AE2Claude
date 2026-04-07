"""Export MoBar scriptlets to individual .jsx files + registry.json"""
import json, re, os

SETTINGS = os.path.expanduser(r"~\AppData\Roaming\MoBar\settings-v2.json")
OUT_DIR = os.path.join(os.path.dirname(__file__), "scripts")
os.makedirs(OUT_DIR, exist_ok=True)

with open(SETTINGS, "r", encoding="utf-8") as f:
    d = json.load(f)

panels = d.get("userPanels", [])
registry = []

for p in panels:
    for it in p.get("items", []):
        if it.get("type") != "scriptlet":
            continue
        name = it.get("name", "unnamed")
        cmd = it.get("command", "")
        try:
            code = json.loads(cmd) if cmd.startswith('"') else cmd
        except:
            code = cmd

        # slug: keep Chinese, replace special chars
        slug = name
        for ch in " /\\()（）≥":
            slug = slug.replace(ch, "-")
        slug = re.sub(r"-+", "-", slug).strip("-")

        fname = slug + ".jsx"
        fpath = os.path.join(OUT_DIR, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(code)

        registry.append({"slug": slug, "name": name, "file": fname})
        print(f"  {fname}")

with open(os.path.join(OUT_DIR, "registry.json"), "w", encoding="utf-8") as f:
    json.dump(registry, f, indent=2, ensure_ascii=False)

print(f"\n共 {len(registry)} 个脚本导出到 {OUT_DIR}")
