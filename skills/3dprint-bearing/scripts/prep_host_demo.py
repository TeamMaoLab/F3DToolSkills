# 宿主准备：⌀24×4 圆板 + ⌀16 通孔，孔面入设计选择集「孔面-⌀16」
import adsk.core
import adsk.fusion

_app_h = adsk.core.Application.get()
_comp_h = _app_h.activeDocument.design.rootComponent

# 幂等清理
for _b in list(_comp_h.bRepBodies):
    if _b.name == '宿主':
        _b.deleteMe()
for _s in list(_app_h.activeDocument.selectionSets) if hasattr(_app_h.activeDocument, 'selectionSets') else []:
    if _s.name.startswith('孔面-'):
        _s.deleteMe()
des_h = _app_h.activeDocument.design
for _ss in list(des_h.selectionSets):
    if _ss.name.startswith('孔面-'):
        _ss.deleteMe()

# 一草图两圆 → 圆环 profile → 拉伸 4mm
_sk = _comp_h.sketches.add(_comp_h.xYConstructionPlane)
_sk.name = '宿主草图'
_sc = _sk.sketchCurves.sketchCircles
_sc.addByCenterRadius(adsk.core.Point3D.create(0, 0, 0), 0.8)   # ⌀16 孔
_sc.addByCenterRadius(adsk.core.Point3D.create(0, 0, 0), 1.2)   # ⌀24 外
_prof = None
for _p in _sk.profiles:
    if abs(_p.boundingBox.maxPoint.x * 10 - 12.0) < 1e-6:
        _prof = _p
        break
_inp = _comp_h.features.extrudeFeatures.createInput(
    _prof, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
_inp.setDistanceExtent(False, adsk.core.ValueInput.createByReal(0.4))
_feat = _comp_h.features.extrudeFeatures.add(_inp)
_feat.name = '宿主拉伸'
_body = _feat.bodies.item(0)
_body.name = '宿主'
_sk.isVisible = False

# 找圆柱孔面（r=8mm）入选择集
_hole_face = None
for _f in _body.faces:
    if _f.geometry and _f.geometry.objectType == adsk.core.Cylinder.classType():
        if abs(_f.geometry.radius * 10 - 8.0) < 1e-4:
            _hole_face = _f
            break
if _hole_face is None:
    raise RuntimeError('未找到 ⌀16 圆柱孔面')

des_h.selectionSets.add([_hole_face], '孔面-⌀16')

_result = {
    'ok': True,
    'host': _body.name,
    'vol_mm3': round(_body.volume * 1000, 2),
    'expect_mm3': round(3.14159265 * (12.0**2 - 8.0**2) * 4, 2),
    'selection_set': '孔面-⌀16',
}
