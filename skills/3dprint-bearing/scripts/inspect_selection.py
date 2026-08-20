# -*- coding: utf-8 -*-
"""inspect_selection.py — dump 当前选中的实体 + 文档特征/实体现状（只读）。

用法：
  curl -G http://127.0.0.1:9099/exec --data-urlencode "code@scripts/inspect_selection.py"
"""
import traceback

import adsk.core
import adsk.fusion


def mm(v):
    return round(v * 10.0, 4)


def vec(v):
    return [mm(v.x), mm(v.y), mm(v.z)]


def unit(v):
    return [round(v.x, 4), round(v.y, 4), round(v.z, 4)]


def describe(ent):
    d = {"type": ent.objectType.split('::')[-1].replace('Ptr', '')}
    try:
        d["name"] = ent.name
    except Exception:
        pass
    try:
        d["area_mm2"] = round(ent.area * 100.0, 3)      # face
    except Exception:
        pass
    try:
        d["n_faces"] = ent.faces.count                  # body
    except Exception:
        pass
    g = getattr(ent, "geometry", None)
    if g is not None:
        try:
            d["surface"] = g.objectType.split('::')[-1].replace('Ptr', '')
            for attr in ("axis", "origin", "center", "normal", "rootPoint",
                         "radius", "majorRadius", "minorRadius", "halfAngle"):
                v = getattr(g, attr, None)
                if v is None:
                    continue
                if hasattr(v, "x"):
                    d[attr] = unit(v) if attr in ("axis", "normal") else vec(v)
                else:
                    try:
                        d[attr] = mm(v)
                    except Exception:
                        d[attr] = str(v)
        except Exception as e:
            d["geom_err"] = str(e)
    return d


def main():
    app = adsk.core.Application.get()
    des = adsk.fusion.Design.cast(app.activeProduct)
    if not des:
        return {"error": "无活动 Design"}

    sels = []
    try:
        for s in app.userInterface.activeSelections:
            sels.append(describe(s.entity))
    except Exception as e:
        sels = [{"error": str(e)}]

    feats = []
    try:
        for t in des.timeline:
            f = t.entity
            feats.append({"type": f.objectType.split('::')[-1].replace('Ptr', ''),
                          "name": f.name})
    except Exception as e:
        feats = [{"error": str(e)}]

    bodies = []
    try:
        for b in des.rootComponent.bRepBodies:
            bodies.append({"name": b.name, "n_faces": b.faces.count})
    except Exception as e:
        bodies = [{"error": str(e)}]

    return {"document": app.activeDocument.name,
            "design_type": str(des.designType),
            "selection": sels,
            "timeline": feats,
            "bodies": bodies}


try:
    _result = main()
except Exception as e:
    _result = {"error": str(e), "tb": traceback.format_exc()}
