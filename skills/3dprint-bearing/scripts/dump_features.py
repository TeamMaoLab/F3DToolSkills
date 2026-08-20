# -*- coding: utf-8 -*-
"""dump_features.py — 逆向特征参数（只读）：时间线每个特征的类型/操作/范围/参考草图。

用法：
  curl -G http://127.0.0.1:9099/exec --data-urlencode "code@scripts/dump_features.py"
"""
import traceback

import adsk.core
import adsk.fusion


def mm(v):
    return round(v * 10.0, 4)


def tname(o):
    try:
        return o.objectType.split('::')[-1].replace('Ptr', '')
    except Exception:
        return '?'


def extent_info(ext):
    if ext is None:
        return None
    d = {"kind": tname(ext)}
    dist = getattr(ext, "distance", None)
    if dist is not None:
        try:
            d["dist_mm"] = mm(dist.value)
            d["expr"] = dist.expression
        except Exception:
            pass
    return d


def feature_info(f):
    tn = tname(f)
    d = {"type": tn, "name": f.name}
    try:
        d["op"] = str(f.operation).split('.')[-1]
    except Exception:
        pass
    try:
        d["is_solid"] = f.isSolid
    except Exception:
        pass
    for k in ("startExtent", "endExtent"):
        try:
            d[k] = extent_info(getattr(f, k, None))
        except Exception:
            pass
    try:
        d["angle"] = mm(getattr(f, "angle", None).value)
    except Exception:
        pass
    # 参考草图（profile / profiles）
    try:
        ps = getattr(f, "profile", None) or []
        if not isinstance(ps, (list, tuple)):
            ps = [ps]
        names = []
        for p in ps:
            names.append(p.parentSketch.name)
        if names:
            d["sketch"] = names[0] if len(set(names)) == 1 else names
    except Exception:
        pass
    try:
        pb = [b.name for b in f.participantBodies]
        if pb:
            d["participants"] = pb
    except Exception:
        pass
    return d


def main():
    app = adsk.core.Application.get()
    des = adsk.fusion.Design.cast(app.activeProduct)
    if not des:
        return {"error": "无活动 Design"}

    feats = []
    try:
        for t in des.timeline:
            e = t.entity
            tn = tname(e)
            if tn in ("Occurrence", "Sketch", "ConstructionPlane", "ConstructionAxis"):
                feats.append({"i": t.index, "type": tn, "name": e.name})
            elif "Feature" in tn or tn.endswith("Features"):
                feats.append(dict({"i": t.index}, **feature_info(e)))
            else:
                feats.append({"i": t.index, "type": tn, "name": getattr(e, "name", "?")})
    except Exception as e:
        feats = [{"error": str(e), "tb": traceback.format_exc()[-300:]}]

    bodies = []
    root = des.rootComponent

    def walk(c, path, depth):
        for b in c.bRepBodies:
            bodies.append({"path": path, "name": b.name,
                           "n_faces": b.faces.count, "visible": b.isVisible})
        if depth < 5:
            for o in c.occurrences:
                walk(o.component, path + "/" + o.name, depth + 1)
    walk(root, "root", 0)

    return {"document": app.activeDocument.name,
            "timeline": feats, "bodies": bodies}


try:
    _result = main()
except Exception as e:
    _result = {"error": str(e), "tb": traceback.format_exc()}
