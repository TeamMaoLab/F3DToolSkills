# 演示轴承生成器（参数化·幂等·逐步对账·收尾）——3dprint-bearing 的姊妹脚本
# 用途：没有孔宿主、只想看轴承效果/做装配参考件时用本脚本；
#      真要打印请走 gen_bearing_full.py（孔内成型）。
# 改参数：只改下面【外参】区。其余勿动。
# 注入：curl -G http://127.0.0.1:9099/exec --data-urlencode "code@本文件"

import math
import adsk.core
import adsk.fusion

# ===== 外参（mm，API 内部换算 cm）=====
DB_BORE = 8.0      # 内环孔径
D_IN_OD = 12.0     # 内环外径
D_OUT_ID = 16.0    # 外环内径
D_OUT_OD = 20.0    # 外环外径
W_BRG = 6.0        # 宽度
D_BALL = 3.5       # 球径
CLR_BALL = 0.5     # 相邻球间隙

# ===== 派生（公式，勿手改）=====
R_TRACK = (D_IN_OD + D_OUT_ID) / 4.0            # 球心圆半径
N_BALLS = max(3, int(2 * math.pi * R_TRACK / (D_BALL + CLR_BALL)))

# ===== 对账基准 =====
V_INNER = math.pi * ((D_IN_OD / 2) ** 2 - (DB_BORE / 2) ** 2) * W_BRG   # mm³
V_OUTER = math.pi * ((D_OUT_OD / 2) ** 2 - (D_OUT_ID / 2) ** 2) * W_BRG

_app_db = adsk.core.Application.get()
_comp_db = _app_db.activeDocument.design.rootComponent
_steps_db = []


def _log_db(step, ok, detail):
    _steps_db.append({'step': step, 'ok': ok, 'detail': detail})
    if not ok:
        raise RuntimeError(f'对账失败@{step}: {detail}')


# ---- 幂等清理：按命名体系删旧件 ----
_killed_db = 0
for _b_db in list(_comp_db.bRepBodies):
    if _b_db.name in ('内环', '外环') or _b_db.name.startswith('球'):
        _b_db.deleteMe()
        _killed_db += 1
for _s_db in list(_comp_db.sketches):
    if _s_db.name.startswith(('内环草图', '外环草图')):
        _s_db.deleteMe()
        _killed_db += 1


def _ring_db(r_in_mm, r_out_mm, name):
    _sk = _comp_db.sketches.add(_comp_db.xYConstructionPlane)
    _sk.name = name + '草图'
    _sc = _sk.sketchCurves.sketchCircles
    _sc.addByCenterRadius(adsk.core.Point3D.create(0, 0, 0), r_in_mm / 10.0)
    _sc.addByCenterRadius(adsk.core.Point3D.create(0, 0, 0), r_out_mm / 10.0)
    # 两同心圆→两个profile(盘+环)：按 bbox 半径=外径筛选出环（Profile 无 .area，用 bbox）
    _prof = None
    for _p in _sk.profiles:
        if abs(_p.boundingBox.maxPoint.x * 10.0 - r_out_mm) < 1e-6:
            _prof = _p
            break
    if _prof is None:
        raise RuntimeError(f'{name}: 未找到外径 {r_out_mm} 的环形 profile')
    _inp = _comp_db.features.extrudeFeatures.createInput(
        _prof, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    _inp.setDistanceExtent(False, adsk.core.ValueInput.createByReal(W_BRG / 10.0))
    _feat = _comp_db.features.extrudeFeatures.add(_inp)
    _feat.name = name + '拉伸'
    _body = _feat.bodies.item(0)
    _body.name = name
    return _sk, _body


# ---- 内环 ----
_sk_in, _body_in = _ring_db(DB_BORE / 2.0, D_IN_OD / 2.0, '内环')
_log_db('内环', abs(_body_in.volume * 1000 - V_INNER) < V_INNER * 0.01,
        {'vol_mm3': round(_body_in.volume * 1000, 2), 'expect': round(V_INNER, 2)})

# ---- 外环 ----
_sk_out, _body_out = _ring_db(D_OUT_ID / 2.0, D_OUT_OD / 2.0, '外环')
_log_db('外环', abs(_body_out.volume * 1000 - V_OUTER) < V_OUTER * 0.01,
        {'vol_mm3': round(_body_out.volume * 1000, 2), 'expect': round(V_OUTER, 2)})

# ---- 球阵（tempBrep，显式 BaseFeature）----
_tbr = adsk.fusion.TemporaryBRepManager.get()
_bf = _comp_db.features.baseFeatures.add()
_bf.startEdit()
try:
    for _i in range(N_BALLS):
        _a = 2 * math.pi * _i / N_BALLS
        _sph = _tbr.createSphere(adsk.core.Point3D.create(
            R_TRACK / 10.0 * math.cos(_a), R_TRACK / 10.0 * math.sin(_a),
            W_BRG / 20.0), D_BALL / 20.0)   # 半径=球径/2，cm
        _comp_db.bRepBodies.add(_sph, _bf)
finally:
    _bf.finishEdit()
_bf.name = '球阵'
for _i, _b in enumerate([b for b in _comp_db.bRepBodies if b.name.startswith('BRep') or b.name.isdigit()], 1):
    pass  # 命名在下方统一做

# 球命名（baseFeature 产生的 body 自然序）
_n = 0
for _b in _bf.bodies if hasattr(_bf, 'bodies') else []:
    _n += 1
    _b.name = f'球{_n:02d}'

_balls_db = [b for b in _comp_db.bRepBodies if b.name.startswith('球')]
_log_db('球阵', len(_balls_db) == N_BALLS,
        {'n': len(_balls_db), 'expect': N_BALLS})

# ---- 收尾：草图收起，浏览器树只留成品 ----
for _s in _comp_db.sketches:
    if _s.name in ('内环草图', '外环草图'):
        _s.isVisible = False

_result = {
    'ok': True,
    'params': {'bore': DB_BORE, 'track_R': R_TRACK, 'balls': N_BALLS, 'ball_D': D_BALL},
    'idempotent_killed': _killed_db,
    'steps': _steps_db,
    'bodies_total': _comp_db.bRepBodies.count,
}
