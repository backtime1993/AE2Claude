"""`ae2claude pin` subcommand: Puppet Pin one-liner workflow.

Registered by ae2claude's main() dispatcher. Reuses pin_placer.PinPlacer
(from the AE2ClaudePinClicker project) as the underlying engine.
"""
import argparse
import ctypes
import json
import os
import sys
import time
from pathlib import Path

_PIN_MODULE = Path(r"F:\claude\longterm\AE2ClaudePinClicker\python")
if str(_PIN_MODULE) not in sys.path:
    sys.path.insert(0, str(_PIN_MODULE))
from pin_placer import PinPlacer, CEPError  # noqa: E402


CEP = "http://127.0.0.1:8891"


def _resolve_layer(pl, layer_name):
    code = (
        'var ai=app.project.activeItem; '
        'if(!ai || !(ai instanceof CompItem)) return {err:"no_active_comp"};'
        f'var n="{layer_name}"; var found=null;'
        'for(var k=1;k<=ai.numLayers;k++){if(ai.layer(k).name===n){found=k;break;}}'
        'if(!found) return {err:"layer_not_found",name:n,comp:ai.name};'
        'return {comp_id:ai.id,comp_name:ai.name,layer_index:found,layer_name:n};'
    )
    r = pl.jsx(code)
    if r.get("err"):
        raise SystemExit(f"ERROR: {r['err']} (layer '{layer_name}' in {r.get('comp', '?')})")
    return int(r["comp_id"]), int(r["layer_index"])


def _fmt(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def cmd_adapt(args):
    t0 = time.time()
    with PinPlacer(cep_url=CEP) as pl:
        cid, lidx = _resolve_layer(pl, args.layer)
        pl.ensure_target(cid, lidx)
        r = pl.adaptive_pin(
            coverage=args.coverage,
            count=args.pins,
            root=args.root,
            center_first=not args.no_center,
            ensure_tool=not args.no_tool,
            starch_type=(None if args.starch_type == 0 else args.starch_type),
            solo=not args.no_solo,
            use_medial=not args.no_medial,
            skeleton_slice_step=args.slice_step,
        )
    elapsed = time.time() - t0
    print(_fmt({
        "ok": True, "elapsed_s": round(elapsed, 2), "layer": args.layer,
        "chain_source": r.get("chain_source"),
        "pins_placed": len([p for p in r["pins"] if "actual_src" in p]),
        "pins_total": len(r["pins"]),
        "chain": r["chain"],
        "final_zoom": (r.get("center") or {}).get("final_zoom"),
        "residual": (r.get("center") or {}).get("residual"),
        "root_coerce": r.get("root_type_coerce"),
    }))


def cmd_center(args):
    with PinPlacer(cep_url=CEP) as pl:
        cid, lidx = _resolve_layer(pl, args.layer)
        pl.ensure_target(cid, lidx)
        pl.load_layer_meta()
        r = pl.center_layer_fast_v2(coverage=args.coverage)
    print(_fmt({"ok": True, "final_zoom": r["final_zoom"], "residual": r["residual"],
                "phases": r["phases"]}))


def cmd_place(args):
    with PinPlacer(cep_url=CEP) as pl:
        cid, lidx = _resolve_layer(pl, args.layer)
        pl.ensure_target(cid, lidx)
        pl.load_layer_meta()
        if pl.tx is None:
            try:
                pl.set_affine_from_centered_layer()
            except CEPError:
                d = pl.find_layer_on_screen_via_diff(alpha_thresh=25)
                pl.preferred_seed_point = d["center"]
                pl.read_zoom()
                pl.calibrate()
        if args.comp:
            r = pl.place_at_comp_true(args.x, args.y)
        else:
            r = pl.place_at_layer_src(args.x, args.y)
    print(_fmt(r))


def cmd_skeleton(args):
    with PinPlacer(cep_url=CEP) as pl:
        cid, lidx = _resolve_layer(pl, args.layer)
        pl.ensure_target(cid, lidx)
        pl.load_layer_meta()
        if args.medial:
            try:
                pl.set_affine_from_centered_layer()
            except CEPError:
                raise SystemExit("medial needs centered layer — run `ae2claude pin center` first "
                                 "or run `ae2claude pin adapt` which does it all")
            chain = pl.skeleton_chain_medial(count=args.count, root=args.root,
                                               slice_step=args.slice_step)
        else:
            chain = pl.skeleton_chain(count=args.count, root=args.root, edge_inset=args.edge)
    print(_fmt({"layer": args.layer, "meta": pl.layer_meta, "chain": chain}))


def cmd_tool(args):
    with PinPlacer(cep_url=CEP) as pl:
        code = (
            'var ai=app.project.activeItem; if(!ai||!(ai instanceof CompItem)) return {err:"no_comp"};'
            'var L=null; for(var k=1;k<=ai.numLayers;k++){if(ai.layer(k).selected){L=ai.layer(k);break;}}'
            'if(!L && ai.numLayers>0) L=ai.layer(1);'
            'return {comp_id:ai.id,layer_index:L?L.index:0};'
        )
        r = pl.jsx(code)
        if r.get("err"):
            raise SystemExit(f"ERROR: {r['err']}")
        pl.comp_id = r["comp_id"]
        pl.layer_index = r["layer_index"]
        res = pl.ensure_puppet_position_tool_fast()
    print(_fmt(res))


def cmd_clean(args):
    with PinPlacer(cep_url=CEP) as pl:
        cid, lidx = _resolve_layer(pl, args.layer)
        code = (
            f'var c=null;for(var i=1;i<=app.project.numItems;i++){{var it=app.project.item(i); if(it.id=={cid}){{c=it;break;}}}}'
            f'var L=c.layer({lidx}); var ep=L.property("ADBE Effect Parade");'
            'var removed=0;'
            'for(var k=ep.numProperties;k>=1;k--){var e=ep.property(k); if(e.matchName=="ADBE FreePin3"){e.remove(); removed++;}}'
            'return {removed:removed};'
        )
        r = pl.jsx(code)
    print(_fmt(r))


def cmd_pins(args):
    with PinPlacer(cep_url=CEP) as pl:
        cid, lidx = _resolve_layer(pl, args.layer)
        pl.ensure_target(cid, lidx)
        pins = pl.list_pins()
    print(_fmt(pins))


def cmd_meta(args):
    with PinPlacer(cep_url=CEP) as pl:
        cid, lidx = _resolve_layer(pl, args.layer)
        pl.ensure_target(cid, lidx)
        m = pl.load_layer_meta()
    print(_fmt(m))


def cmd_snap(args):
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    from PIL import ImageGrab
    out = args.out or ("viewer.png" if args.viewer else "screen.png")
    if args.viewer:
        with PinPlacer(cep_url=CEP) as pl:
            pl._post("/focus-ae")
            time.sleep(0.35)
            ae = pl.ae_window_rect()
            vr = pl.find_viewer_rect((ae["center_x"], ae["center_y"]))
        if not vr:
            raise SystemExit("cannot locate composition viewer")
        u = ctypes.windll.user32
        vx0, vy0 = u.GetSystemMetrics(76), u.GetSystemMetrics(77)
        ImageGrab.grab(all_screens=True).crop(
            (vr["left"]-vx0, vr["top"]-vy0, vr["right"]-vx0, vr["bottom"]-vy0)
        ).save(out)
        print(_fmt({"saved": os.path.abspath(out), "viewer_rect": vr}))
    else:
        ImageGrab.grab(all_screens=True).save(out)
        print(_fmt({"saved": os.path.abspath(out)}))


def _build_parser():
    ap = argparse.ArgumentParser(
        prog="ae2claude pin",
        description="AE Puppet Pin 一行命令 (skeleton+starch+fast view).",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("adapt", help="一键自适应打点 (solo+center+tool+skeleton chain)")
    a.add_argument("layer")
    a.add_argument("--pins", type=int, default=4)
    a.add_argument("--root", default="top", choices=["top", "bottom", "left", "right"])
    a.add_argument("--coverage", type=float, default=0.55)
    a.add_argument("--no-center", action="store_true")
    a.add_argument("--no-solo", action="store_true")
    a.add_argument("--no-tool", action="store_true")
    a.add_argument("--no-medial", action="store_true",
                   help="use straight-centerline instead of alpha medial line")
    a.add_argument("--slice-step", type=int, default=4, help="medial sampling step (px)")
    a.add_argument("--starch-type", type=int, default=3,
                   help="PosPin Type for root pin (0=skip, 1=pos, 3=advanced/starch)")
    a.set_defaults(func=cmd_adapt)

    c = sub.add_parser("center", help="视口居中+缩放 (2-3 步)")
    c.add_argument("layer")
    c.add_argument("--coverage", type=float, default=0.55)
    c.set_defaults(func=cmd_center)

    p = sub.add_parser("place", help="单点打点")
    p.add_argument("layer")
    p.add_argument("x", type=float)
    p.add_argument("y", type=float)
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--src", action="store_true", help="layer source coords (default)")
    grp.add_argument("--comp", action="store_true", help="comp coords")
    p.set_defaults(func=cmd_place)

    s = sub.add_parser("skeleton", help="预览骨架链点 (不打点)")
    s.add_argument("layer")
    s.add_argument("--count", type=int, default=4)
    s.add_argument("--root", default="top", choices=["top", "bottom", "left", "right"])
    s.add_argument("--edge", type=float, default=0.08)
    s.add_argument("--medial", action="store_true", help="alpha-medial instead of straight")
    s.add_argument("--slice-step", type=int, default=4)
    s.set_defaults(func=cmd_skeleton)

    t = sub.add_parser("tool", help="确保 Puppet Position Pin 工具")
    t.set_defaults(func=cmd_tool)

    cl = sub.add_parser("clean", help="移除图层 Puppet 效果")
    cl.add_argument("layer")
    cl.set_defaults(func=cmd_clean)

    pn = sub.add_parser("pins", help="列出现有 pin")
    pn.add_argument("layer")
    pn.set_defaults(func=cmd_pins)

    me = sub.add_parser("meta", help="层 meta (pos/anchor/scale/w/h)")
    me.add_argument("layer")
    me.set_defaults(func=cmd_meta)

    sn = sub.add_parser("snap", help="截图 (默认全屏, --viewer 只截 AE viewer)")
    sn.add_argument("out", nargs="?")
    sn.add_argument("--viewer", action="store_true")
    sn.set_defaults(func=cmd_snap)

    return ap


def main(argv):
    ap = _build_parser()
    args = ap.parse_args(argv)
    try:
        args.func(args)
    except CEPError as e:
        raise SystemExit(f"CEPError: {e}")


if __name__ == "__main__":
    main(sys.argv[1:])
