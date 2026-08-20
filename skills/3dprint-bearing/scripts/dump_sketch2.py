# 从当前打开的轴承文档 dump 全部草图几何（含可见性），供网页逐线对照
import json as _j
import adsk.core
import adsk.fusion

_app = adsk.core.Application.get()
_d = [x for x in _app.documents if x.design.rootComponent.occurrences.count == 1][0]
_d.activate()
_comp = _d.design.rootComponent.occurrences.item(0).component
_out = {}
for _s in _comp.sketches:
    _cs = []
    for _ln in _s.sketchCurves.sketchLines:
        _cs.append(('L',
                    (round(_ln.startSketchPoint.geometry.x * 10, 2), round(_ln.startSketchPoint.geometry.y * 10, 2)),
                    (round(_ln.endSketchPoint.geometry.x * 10, 2), round(_ln.endSketchPoint.geometry.y * 10, 2))))
    for _ar in _s.sketchCurves.sketchArcs:
        _cc = _ar.centerSketchPoint.geometry
        _cs.append(('A',
                    (round(_cc.x * 10, 2), round(_cc.y * 10, 2)),
                    (round(_ar.startSketchPoint.geometry.x * 10, 2), round(_ar.startSketchPoint.geometry.y * 10, 2)),
                    (round(_ar.endSketchPoint.geometry.x * 10, 2), round(_ar.endSketchPoint.geometry.y * 10, 2)),
                    round(_ar.radius * 10, 2)))
    for _ci in _s.sketchCurves.sketchCircles:
        _cc = _ci.centerSketchPoint.geometry
        _cs.append(('C', (round(_cc.x * 10, 2), round(_cc.y * 10, 2)), round(_ci.radius * 10, 2)))
    _out[_s.name] = {'curves': _cs, 'visible': _s.isVisible}

with open('D:/robot/F3DToolSkills/skills/3dprint-bearing/sketch2.json', 'w', encoding='utf-8') as _f:
    _j.dump({'unit': 'mm', 'component': _comp.name, 'sketches': _out}, _f, ensure_ascii=False)
_result = {'ok': True, 'sketches': {k: len(v['curves']) for k, v in _out.items()}}
