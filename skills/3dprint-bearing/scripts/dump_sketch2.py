# 导出轴承 S2 关键截面草图的真实几何（Fusion 本尊数据）→ sketch2.json
# 曲线类型：line / circle / arc，坐标为草图空间 cm → 统一转 mm
import json as _json_x
import math as _math_x
import adsk.core
import adsk.fusion

_app_dx = adsk.core.Application.get()
_des_dx = _app_dx.activeDocument.design
_root_dx = _des_dx.rootComponent

# 找轴承组件里的草图（优先名含"截面/闭环"，否则取组件内全部草图）
_target_dx = None
for _o_dx in _root_dx.occurrences:
    if '轴承-全' in _o_dx.component.name:
        _target_dx = _o_dx.component
        break
if _target_dx is None:
    _target_dx = _root_dx

_curves_dx = []
for _sk_dx in _target_dx.sketches:
    _meta_dx = {'sketch': _sk_dx.name, 'curves': []}
    _sc_dx = _sk_dx.sketchCurves
    for _ln_dx in _sc_dx.sketchLines:
        _meta_dx['curves'].append({
            't': 'line',
            'a': [_ln_dx.startSketchPoint.geometry.x * 10, _ln_dx.startSketchPoint.geometry.y * 10],
            'b': [_ln_dx.endSketchPoint.geometry.x * 10, _ln_dx.endSketchPoint.geometry.y * 10]})
    for _ci_dx in _sc_dx.sketchCircles:
        _meta_dx['curves'].append({
            't': 'circle',
            'c': [_ci_dx.centerSketchPoint.geometry.x * 10, _ci_dx.centerSketchPoint.geometry.y * 10],
            'r': _ci_dx.radius * 10})
    for _ar_dx in _sc_dx.sketchArcs:
        _c_dx = _ar_dx.centerSketchPoint.geometry
        _meta_dx['curves'].append({
            't': 'arc',
            'c': [_c_dx.x * 10, _c_dx.y * 10],
            'r': _ar_dx.radius * 10,
            'a': [_ar_dx.startSketchPoint.geometry.x * 10, _ar_dx.startSketchPoint.geometry.y * 10],
            'b': [_ar_dx.endSketchPoint.geometry.x * 10, _ar_dx.endSketchPoint.geometry.y * 10]})
    for _sp_dx in _sc_dx.sketchFittedSplines:
        _pts_dx = [[_p_dx.x * 10, _p_dx.y * 10] for _p_dx in _sp_dx.getSketchPoints()]
        if len(_pts_dx) > 1:
            _meta_dx['curves'].append({'t': 'spline', 'pts': _pts_dx})
    _curves_dx.append(_meta_dx)

_out_dx = {
    'unit': 'mm',
    'source': 'Fusion 360',
    'component': _target_dx.name,
    'sketches': _curves_dx,
}
_path_dx = 'D:/robot/F3DToolSkills/skills/3dprint-bearing/sketch2.json'
with open(_path_dx, 'w', encoding='utf-8') as _f_dx:
    _json_x.dump(_out_dx, _f_dx, ensure_ascii=False)
_result = {
    'ok': True,
    'out': _path_dx,
    'sketches': [(m['sketch'], len(m['curves'])) for m in _curves_dx],
    'total_curves': sum(len(m['curves']) for m in _curves_dx),
}
