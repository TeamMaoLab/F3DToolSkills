# -*- coding: utf-8 -*-
"""gen_bearing_full.py — 孔内成型球轴承 完整流程 v2（幂等，任意孔位/姿态）。

v2 修复（2026-08-18 审计后）：
  ① 全部草图改「世界→草图局部逆映射」落笔（v1 平面局部 2D 假设锚点在孔底，实际
     Fusion 自选参数化 → 整个轴承建到了世界原点）
  ② 窝弧恢复真圆弧 addByThreePoints（v1 是 16 段折线 → Cone×18 棱面；验收=出现 Torus）
  ③ 圆角 r1 只选外口 2 条边、关相切链（v1 选 4 边+相切链导致 r1 失败后擅自降 0.2）
  ④ 凸雕删 +1mm 兜底（凸起也变面数，检测不住）；改为读 nurbs 面质心径向位置判凹凸
  ⑤ 交付强制几何验收：所有实体 bbox 必须落在孔系内（径向≤R_h+1，轴向∈孔深±1），
     球心径向=R_track、内/外环含 Torus —— 不满足直接整体报 FAIL

输入：设计选择集里的圆柱孔面。
方案：球径预设（DBALL，默认⌀3，可换 2.5 / 2.381=3/32″）+ 同心 + R_track = R_h − δ − t_wall。
球径缩放律（docs/bearing_ball_sizes.md）：配方中唯一随球变的是窝 rg=DBALL/2+0.05；
δ/中环厚/壁厚/装球口宽全是打印绝对值或孔驱动，不随球缩放。
用法：
  curl -G http://127.0.0.1:9099/exec --data-urlencode "code@scripts/gen_bearing_full.py"
"""
import math
import traceback

import adsk.core
import adsk.fusion

COMP_PREFIX = "轴承-全"   # 实际名 = 前缀-⌀XX（按孔签名，多孔并存互不误删）
DELTA, TRING, TWALL = 0.8, 1.0, 2.0
DBALL = 2.38125      # 全局统一球规格（用户定则）：2.38125(3/32″) 或 2.5 二选一，轴承与支撑球共用同一规格（默认 2.381）
CLR = 0.2            # 窝间隙（打印精度驱动，可选）：光固化 0.05 / FDM 0.2（默认，0.1 对打印偏挤）
RG = DBALL / 2 + CLR    # 窝半径 = 球半径 + 间隙（实验室原版 ⌀3+clr0.05 时 =1.55）
N_BALLS = None    # None=球数公式自动（⌀16→7 等，见 SKILL 锚点）；数字=手动覆盖
RFILLET = 1.0     # 用户口述：外口两条边、r1（不擅自改）

# ---- 文档属性参数覆盖（改参数不动脚本：属性组 F3DToolSkills，键=常量名，值=数字或null）----
# 设置示例（一行）：design.attributes.add('F3DToolSkills', 'N_BALLS', '8')
# 清除示例：attributes 按组遍历 deleteMe 同名项（null 值跳过）
try:
    _app_ov = adsk.core.Application.get()
    _des_ov = _app_ov.activeDocument.design
    _grp = list(_des_ov.attributes.itemsByGroup('F3DToolSkills'))
    if _grp:
        for _a_ov in _grp:
            if _a_ov.name in ('DBALL', 'CLR', 'N_BALLS', 'RFILLET') and _a_ov.value not in ('', 'null', None):
                try:
                    _v_ov = None if _a_ov.value == 'None' else float(_a_ov.value)
                    if _a_ov.name == 'N_BALLS' and _v_ov is not None:
                        _v_ov = int(_v_ov)
                except ValueError:
                    continue
                globals()[_a_ov.name] = _v_ov
    del _app_ov, _des_ov, _grp
except Exception:
    pass  # 无活动文档等情况：静默用默认值


def n_balls_auto(R_track, R2, R3, slotW, rg, dBall, gap_seat, g=0.5, c=0.3):
    """球数公式：N = floor(2π / max(θ口, θ窝, θ球))，下限3。
    θ口 = 2·atan((slotW/2+g)/R3)         V口顶宽在环外壁占角（g=口间余隙）
    θ窝 = 2·asin(w/R2), w=√(rg²−gap²)    球窝在内壁开口占角（gap=球心到壁距）
    θ球 = 2·asin((dBall+c)/2R_track)     相邻球心弦长留隙 c
    实测：R3=7.7→8（与已建一致）✓；R3=5.2→6（N=8 会叠口）✓；实验室 R3=10.5→11（手选8保守）"""
    th_slot = 2 * math.atan((slotW / 2 + g) / R3)
    w_seat = math.sqrt(max(rg * rg - gap_seat * gap_seat, 1e-9))
    th_seat = 2 * math.asin(min(1.0, w_seat / R2))
    th_ball = 2 * math.asin(min(1.0, (dBall + c) / (2 * R_track)))
    th = max(th_slot, th_seat, th_ball)
    n = max(3, int(math.floor(2 * math.pi / th + 1e-9)))
    return n, th_slot, th_seat, th_ball


def tname(o):
    try:
        return o.objectType.split('::')[-1].replace('Ptr', '')
    except Exception:
        return '?'


def norm(v):
    L = math.sqrt(sum(a * a for a in v))
    return tuple(a / L for a in v)


def cross(u, v):
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def sub3(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def main():
    steps = {}
    verify = {}
    app = adsk.core.Application.get()
    des = adsk.fusion.Design.cast(app.activeProduct)
    if not des:
        return {"error": "无活动 Design"}
    root = des.rootComponent

    def cm(v):
        return v / 10.0

    # ---- 孔：从选择集 ----
    face = None
    used_set = None
    try:
        for ss in des.selectionSets:
            for e in ss.entities:
                if tname(e) == "BRepFace" and tname(getattr(e, "geometry", None)) == "Cylinder":
                    face, used_set = e, ss.name
                    break
            if face:
                break
    except Exception as ex:
        return {"error": "读取选择集失败: " + str(ex)[:100]}
    if face is None:
        # 自愈：融合会吃掉孔壁面（选择集引用失效）。从旧组件反推孔签名还原。
        # 多个轴承组件并存时拒绝猜测（要求显式把目标孔面存入选择集）。
        old_occ = None
        cands = [o_ for o_ in root.occurrences
                 if o_.component.name == COMP_PREFIX or o_.component.name.startswith(COMP_PREFIX + "-")]
        heal_err = ""
        if len(cands) > 1:
            return {"error": "存在 {} 个轴承组件（{}），请把目标孔面重新存入选择集再跑".format(
                len(cands), [o_.component.name for o_ in cands])}
        if len(cands) == 1:
            old_occ = cands[0]
            try:
                inner_b = None
                for b in old_occ.component.bRepBodies:
                    if b.name == "内盘":
                        inner_b = b
                        break
                ax2 = o2 = None
                R1_old = 0
                if inner_b:
                    for f_ in inner_b.faces:
                        gg = f_.geometry
                        if tname(gg) == "Cylinder":
                            ax2 = (gg.axis.x, gg.axis.y, gg.axis.z)
                            o2 = (gg.origin.x * 10, gg.origin.y * 10, gg.origin.z * 10)
                            R1_old = gg.radius * 10
                            break
                if ax2 is not None:
                    # 该组件自己的融合特征（带签名或旧名）
                    for f in list(root.features.combineFeatures):
                        if f.name.startswith("轴承-宿主融合"):
                            f.deleteMe()
                    old_occ.deleteMe()
                    u2 = norm(ax2)
                    R_h_guess = R1_old + 2 * DELTA + TWALL
                    for b in root.bRepBodies:
                        for f_ in b.faces:
                            gg = f_.geometry
                            if tname(gg) == "Cylinder" and abs(gg.radius * 10 - R_h_guess) < 0.15:
                                a3 = norm((gg.axis.x, gg.axis.y, gg.axis.z))
                                if abs(abs(sum(a3[i] * u2[i] for i in range(3))) - 1) < 1e-3:
                                    c3 = (gg.origin.x * 10, gg.origin.y * 10, gg.origin.z * 10)
                                    d = sub3(c3, o2)
                                    dperp = tuple(d[i] - u2[i] * sum(d[j] * u2[j] for j in range(3)) for i in range(3))
                                    if math.sqrt(sum(x * x for x in dperp)) < 0.2:
                                        face = f_
                                        used_set = "自愈(旧组件反推)"
                                        break
                            if face:
                                break
                    if face is not None:
                        setname = "孔面-⌀{:.0f}".format(R_h_guess * 2)
                        set_err = None
                        # 3.14 实测：add(entities, name) —— 列表在前、名字在后；ObjectCollection 会被拒
                        # 旧集引用已随融合失效（0 实体），同名存在时 Fusion 会自动改名 "(2)" → 先清再建
                        for ss_ in list(des.selectionSets):
                            if ss_.name == setname or ss_.name.startswith(setname + " ("):
                                try:
                                    ss_.deleteMe()
                                except Exception:
                                    pass
                        try:
                            des.selectionSets.add([face], setname)
                        except Exception as ex:
                            set_err = str(ex)[:120]
                        if set_err:
                            heal_err = "选择集补回失败: " + set_err
                    else:
                        heal_err = "旧组件已清但未找到 ⌀{:.0f} 孔面（宿主可能被改动）".format(R_h_guess * 2)
            except Exception as ex:
                heal_err = str(ex)[:100]
    if face is None:
        return {"error": "选择集里没有圆柱孔面（自愈也失败：{}）".format(
            heal_err if heal_err else "无旧组件可反推")}
    g = face.geometry
    R_h = g.radius * 10.0
    ax = (g.axis.x, g.axis.y, g.axis.z)
    o = (g.origin.x * 10, g.origin.y * 10, g.origin.z * 10)
    u = norm(ax)
    rims = []
    for e in face.edges:
        eg = e.geometry
        if "Circle" in tname(eg):
            c = eg.center
            rims.append((c.x * 10, c.y * 10, c.z * 10))
    if len(rims) >= 2:
        def proj(p):
            return sum((p[i] - o[i]) * u[i] for i in range(3))
        lo = min(rims, key=proj)
        hi = max(rims, key=proj)
        A0 = lo
        D_h = proj(hi) - proj(lo)
    else:
        return {"error": "孔口两端不是正圆（孔轴需垂直于孔口面，斜面孔请先重做）"}
    zB = D_h / 2.0
    # 输入校验：配方锁 D_h=5；窝不穿透内盘 → R_h 下限
    dh_min = DBALL + 2 * CLR + 1.1   # 窝上缘≥0.55 打印线（硬线=窝不穿端面 D_h>d+2clr；随 CLR 自动放大）
    if D_h < dh_min - 0.05:
        return {"error": "孔深 {0:.2f} < 球⌀{1:.3f}+clr{2} 配方下限 {3:.2f}".format(D_h, DBALL, CLR, dh_min) +
                         "（窝上缘≥0.55 打印线 = d+2clr+1.1；几何硬线=窝不穿端面 D_h>d+2clr={:.2f}）".format(DBALL + 2 * CLR)}
    if R_h - DELTA - TWALL - DELTA <= RG + 0.1:
        return {"error": "孔半径 {:.2f} 太小（需 > {:.2f}，否则窝穿透内盘）".format(
            R_h, RG + 0.1 + 2 * DELTA + TWALL)}
    er0_raw = (1, 0, 0) if abs(u[0]) < 0.9 else (0, 1, 0)
    er0_raw = tuple(er0_raw[i] - u[i] * sum(er0_raw[j] * u[j] for j in range(3)) for i in range(3))
    er0 = norm(er0_raw)
    et = norm(cross(u, er0))

    R_track = R_h - DELTA - TWALL
    R1, R2, R3, R4, R5 = (R_track - DELTA, R_track - TRING / 2, R_track + TRING / 2,
                          R_track + DELTA, R_h)
    h = math.radians(45)
    Er_in = R_track - RG * math.sin(h)
    t_in = abs(Er_in - R1) / math.cos(h)
    Er_out = R_track + RG * math.sin(h)
    t_out = abs(Er_out - R4) / math.cos(h)
    face_in_hi = zB + RG * math.cos(h) + t_in * math.sin(h)
    face_in_lo = zB - RG * math.cos(h) - t_in * math.sin(h)
    face_out_hi = zB + RG * math.cos(h) + t_out * math.sin(h)
    face_out_lo = zB - RG * math.cos(h) - t_out * math.sin(h)

    slotW = 2 * (D_h - zB) / math.tan(math.radians(45))   # V角90°顶宽
    if N_BALLS is None:
        N_eff, th_s, th_e, th_b = n_balls_auto(R_track, R2, R3, slotW, RG, DBALL,
                                               gap_seat=DELTA - TRING / 2)
    else:
        N_eff = N_BALLS
        th_s = th_e = th_b = 0.0

    steps["S0输入配方"] = "ok 孔⌀{:.0f}×{:.1f} 球⌀{:.3f} N={}".format(
        R_h * 2, D_h, DBALL, N_eff)

    def W(r, z):
        """孔系 (r 径向, z 轴向 0=孔底) → 世界 mm。"""
        return (A0[0] + er0[0] * r + u[0] * z,
                A0[1] + er0[1] * r + u[1] * z,
                A0[2] + er0[2] * r + u[2] * z)

    def radial_of(p):
        """点到孔轴的径向距离（mm）。"""
        d = sub3(p, A0)
        ax_comp = sum(d[i] * u[i] for i in range(3))
        dr = tuple(d[i] - u[i] * ax_comp for i in range(3))
        return math.sqrt(sum(a * a for a in dr))

    # ---- 孔签名命名（多孔并存：签名含宿主实体名，防同径多孔互相清）----
    HOST_TAG = face.body.name
    COMP_NAME = "{}-{}-⌀{:.0f}".format(COMP_PREFIX, HOST_TAG, R_h * 2)
    FUSION_NAME = "轴承-宿主融合-{}-⌀{:.0f}".format(HOST_TAG, R_h * 2)

    # ---- purge（只清自己签名的融合+组件）----
    purged = []
    for f in list(root.features.combineFeatures):
        if f.name == FUSION_NAME:
            try:
                f.deleteMe()
                purged.append("特征:轴承-宿主融合")
            except Exception:
                pass
    for occ_ in list(root.occurrences):
        if occ_.component.name == COMP_NAME:
            purged.append(occ_.name)
            occ_.deleteMe()
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    comp.name = COMP_NAME
    NewBody = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    Cut = adsk.fusion.FeatureOperations.CutFeatureOperation
    planes = comp.constructionPlanes

    # ============ ① 过轴构造平面（实体引用三点）============
    skp = comp.sketches.add(comp.xYConstructionPlane)
    skp.name = "参考点"
    pA = skp.sketchPoints.add(adsk.core.Point3D.create(cm(A0[0]), cm(A0[1]), cm(A0[2])))
    pB = skp.sketchPoints.add(adsk.core.Point3D.create(cm(A0[0] + u[0]), cm(A0[1] + u[1]), cm(A0[2] + u[2])))
    pC = skp.sketchPoints.add(adsk.core.Point3D.create(cm(A0[0] + er0[0] * R5), cm(A0[1] + er0[1] * R5), cm(A0[2] + er0[2] * R5)))
    plane = None
    for _try in range(2):
        try:
            pin = planes.createInput()
            pin.setByThreePoints(pA, pB, pC)
            plane = planes.add(pin)
            break
        except Exception:
            continue
    if plane is None:
        return {"error": "过轴平面失败"}
    plane.name = "轴承截面平面"
    steps["S1过轴平面"] = "ok"

    # ============ 草图落笔器：官方 API（手写矩阵逆映射在 ±Z 轴孔上有符号翻面 bug，已废弃）============
    def mapper(sk):
        def TL(p_w):
            return sk.modelToSketchSpace(
                adsk.core.Point3D.create(cm(p_w[0]), cm(p_w[1]), cm(p_w[2])))
        return TL

    # ============ ② 三闭环草图（真圆弧窝，逆映射落笔）============
    def make_loop_sketch(name, segs, seg_arc):
        """segs: 直线段 [(p1,p2),...]（世界mm对）；seg_arc: (起,中,末) 真弧。
        返回 (sk, 最后一条线) —— 内盘最后一条线 = r=0 轴。"""
        sk = comp.sketches.add(plane)
        sk.name = name
        TL = mapper(sk)
        last = None
        for a_, b_ in segs:
            last = sk.sketchCurves.sketchLines.addByTwoPoints(TL(W(*a_)), TL(W(*b_)))
        if seg_arc:
            p0, pm, p1 = seg_arc
            sk.sketchCurves.sketchArcs.addByThreePoints(TL(W(*p0)), TL(W(*pm)), TL(W(*p1)))
        return sk, last

    # 内盘：直线下缘→竖缘下段→切线→[真弧 225°→135° 过左端]→切线→竖缘上段→顶缘→r=0 轴
    in_segs = [
        ((0, 0), (R1, 0)),
        ((R1, 0), (R1, face_in_lo)),
        ((R1, face_in_lo), (Er_in, zB - RG * math.cos(h))),
        # 弧占位（下面传 seg_arc）
        ((Er_in, zB + RG * math.cos(h)), (R1, face_in_hi)),
        ((R1, face_in_hi), (R1, D_h)),
        ((R1, D_h), (0, D_h)),
        ((0, D_h), (0, 0)),          # r=0 轴（旋转轴，最后一条线）
    ]
    in_arc = ((Er_in, zB - RG * math.cos(h)),
              (R_track - RG, zB),                       # 180° 左端
              (Er_in, zB + RG * math.cos(h)))
    ring_segs = [((R2, 0), (R3, 0)), ((R3, 0), (R3, D_h)),
                 ((R3, D_h), (R2, D_h)), ((R2, D_h), (R2, 0))]
    out_segs = [
        ((R4, 0), (R4, face_out_lo)),
        ((R4, face_out_lo), (Er_out, zB - RG * math.cos(h))),
        ((Er_out, zB + RG * math.cos(h)), (R4, face_out_hi)),
        ((R4, face_out_hi), (R4, D_h)),
        ((R4, D_h), (R5, D_h)),
        ((R5, D_h), (R5, 0)),
        ((R5, 0), (R4, 0)),
    ]
    out_arc = ((Er_out, zB - RG * math.cos(h)),
               (R_track + RG, zB),                      # 0° 右端
               (Er_out, zB + RG * math.cos(h)))
    sk_in, axis_line = make_loop_sketch("内盘闭环", in_segs, in_arc)
    sk_ring, _ = make_loop_sketch("中环闭环", ring_segs, None)
    sk_out, _ = make_loop_sketch("外环闭环", out_segs, out_arc)
    steps["S2闭环草图"] = "in={} ring={} out={}".format(
        sk_in.profiles.count, sk_ring.profiles.count, sk_out.profiles.count)
    if not (sk_in.profiles.count == sk_ring.profiles.count == sk_out.profiles.count == 1):
        return {"error": "闭环草图面域数异常（in={} ring={} out={}，应各=1；闭环未咬合）".format(
            sk_in.profiles.count, sk_ring.profiles.count, sk_out.profiles.count)}

    # ============ ③ 三体旋转 ============
    def revolve_sk(sk, name):
        revs = comp.features.revolveFeatures
        oc = adsk.core.ObjectCollection.create()
        for i in range(sk.profiles.count):
            oc.add(sk.profiles.item(i))
        inp = None
        for mk in (lambda: revs.createInput(oc, axis_line, True),
                   lambda: revs.createInput(oc, axis_line)):
            try:
                inp = mk()
                break
            except Exception:
                continue
        if inp is None:
            raise RuntimeError("revolve createInput 失败")
        inp.operation = NewBody
        inp.setAngleExtent(False, adsk.core.ValueInput.createByString("360 deg"))
        f = revs.add(inp)
        f.name = name
        return f

    bodies = []
    try:
        bodies.append(revolve_sk(sk_in, "内盘旋转").bodies.item(0))
        bodies.append(revolve_sk(sk_ring, "中环旋转").bodies.item(0))
        bodies.append(revolve_sk(sk_out, "外环旋转").bodies.item(0))
        steps["S3旋转三体"] = "ok bodies={}".format(len(bodies))
    except Exception as e:
        steps["S3旋转三体"] = "FAIL " + str(e)[:120]

    # ④ 分类
    inner = ring = outer = None
    try:
        for bd in bodies:
            radii = sorted(round(f_.geometry.radius * 10, 2) for f_ in bd.faces
                           if tname(f_.geometry) == "Cylinder")
            rmax = radii[-1] if radii else 0
            if rmax > R3 + 0.5:
                outer = bd
            elif rmax > R1 + 0.5:
                ring = bd
            else:
                inner = bd
        for bd, nm in ((inner, "内盘"), (ring, "中环"), (outer, "外环")):
            if bd:
                bd.name = nm
        steps["S3·分类"] = "ok"
    except Exception as e:
        steps["S3·分类"] = "FAIL " + str(e)[:100]

    # ============ ⑤ 球窝切割（球刀体阵列 ×N → 一次性 Cut）============
    def make_sphere_body(rc, zc, rr, name, comp_t=None, plane_t=None):
        """球体：截面平面（过轴）上画半圆（逆映射落笔）→ 绕直径旋转。
        默认建在 comp；球组版传 grp + 组内自建平面。返回 (body, feat, 轴线)。"""
        comp_t = comp_t or comp
        plane_t = plane_t or plane
        skb = comp_t.sketches.add(plane_t)
        skb.name = name + "-草图"
        TL = mapper(skb)
        C = W(rc, zc)
        D1 = W(rc - rr, zc)
        D2 = W(rc + rr, zc)
        Apex = (C[0] + u[0] * rr, C[1] + u[1] * rr, C[2] + u[2] * rr)
        ax_b = skb.sketchCurves.sketchLines.addByTwoPoints(TL(D1), TL(D2))
        skb.sketchCurves.sketchArcs.addByThreePoints(TL(D1), TL(Apex), TL(D2))
        ocb = adsk.core.ObjectCollection.create()
        for i in range(skb.profiles.count):
            ocb.add(skb.profiles.item(i))
        inpb = None
        for mk in (lambda: comp_t.features.revolveFeatures.createInput(ocb, ax_b, True),
                   lambda: comp_t.features.revolveFeatures.createInput(ocb, ax_b)):
            try:
                inpb = mk()
                break
            except Exception:
                continue
        inpb.operation = NewBody
        inpb.setAngleExtent(False, adsk.core.ValueInput.createByString("360 deg"))
        fb = comp_t.features.revolveFeatures.add(inpb)
        fb.name = name
        bd = fb.bodies.item(0)
        bd.name = name
        return bd, fb, ax_b

    try:
        if ring is None:
            raise RuntimeError("中环未识别")
        ring_now = None
        for b in comp.bRepBodies:
            if b.name == "中环":
                ring_now = b
        tool, _tf, _ta = make_sphere_body(R_track, zB, RG, "球窝刀")
        cps = comp.features.circularPatternFeatures
        oc1 = adsk.core.ObjectCollection.create()
        oc1.add(tool)
        pi = None
        for mk in (lambda: cps.createInput(oc1, axis_line),):
            try:
                pi = mk()
                break
            except Exception:
                continue
        pi.quantity = adsk.core.ValueInput.createByString("{}".format(N_eff))
        pi.totalAngle = adsk.core.ValueInput.createByString("360 deg")
        pf = cps.add(pi)
        pf.name = "球刀阵列"
        combs = comp.features.combineFeatures
        oc_t = adsk.core.ObjectCollection.create()
        for b in comp.bRepBodies:
            if b.name.startswith("球窝刀"):
                oc_t.add(b)
        ci = None
        for mk in (lambda: combs.createInput(ring_now, oc_t),
                   lambda: combs.createInput(ring_now, oc_t, Cut)):
            try:
                ci = mk()
                break
            except Exception:
                continue
        ci.operation = Cut
        f = combs.add(ci)
        f.name = "球窝切割×N"
        steps["S4球窝切割"] = "ok tools={}".format(oc_t.count)
    except Exception as e:
        steps["S4球窝切割"] = "FAIL " + str(e)[:150]

    # ============ ⑥ 凸雕 V口（−1mm 切入，凹凸验证）============
    slotW = 2 * (D_h - zB) / math.tan(math.radians(45))
    emb_feat = None
    try:
        if ring is None:
            raise RuntimeError("中环未识别")
        ring2 = None
        for b in comp.bRepBodies:
            if b.name == "中环":
                ring2 = b
        od_face = None
        for f_ in (ring2 or ring).faces:
            gg = f_.geometry
            if tname(gg) == "Cylinder" and abs(gg.radius * 10 - R3) < 0.1:
                od_face = f_
                break
        if od_face is None:
            raise RuntimeError("没找到中环外圆柱面")
        T0 = W(R3, 0.5)                    # 切点取 α0 方位、z=0.5（球窝洞口 z≈1.0~4.0 之外，点真在 od_face 上）
        skp2 = comp.sketches.add(comp.xYConstructionPlane)
        skp2.name = "参考点2"
        sp0 = skp2.sketchPoints.add(adsk.core.Point3D.create(cm(T0[0]), cm(T0[1]), cm(T0[2])))
        pl2 = None
        for _try in range(3):
            try:
                pin = planes.createInput()
                pin.setByTangentAtPoint(od_face, sp0)
                pl2 = planes.add(pin)
                break
            except Exception:
                continue
        if pl2 is None:
            raise RuntimeError("切平面失败")
        # 平面方位验收：法向必须 ≈ er0（切点吸附容错可能把平面建到别的方位）
        nrm = pl2.geometry.normal
        dot_e = nrm.x * er0[0] + nrm.y * er0[1] + nrm.z * er0[2]
        if abs(dot_e) < 0.99:
            raise RuntimeError("切平面法向偏离装球口方位（dot={:.3f}），拒绝继续".format(dot_e))
        pl2.name = "装球口平面"
        sk2 = comp.sketches.add(pl2)
        sk2.name = "装球口楔"
        TL2 = mapper(sk2)

        def Ww(x_t, z):
            """楔坐标（x_t 切向, z 轴向）→ 世界 mm。"""
            base = W(R3, z)
            return (base[0] + et[0] * x_t, base[1] + et[1] * x_t, base[2] + et[2] * x_t)
        w2 = slotW / 2
        A_ = Ww(-w2, D_h); B_ = Ww(w2, D_h); C_ = Ww(0, zB)
        sk2.sketchCurves.sketchLines.addByTwoPoints(TL2(A_), TL2(B_))
        sk2.sketchCurves.sketchLines.addByTwoPoints(TL2(B_), TL2(C_))
        sk2.sketchCurves.sketchLines.addByTwoPoints(TL2(C_), TL2(A_))
        profs = [p for p in sk2.profiles]
        if not profs:
            raise RuntimeError("楔草图没形成面域（三角未闭合）")
        embs = comp.features.embossFeatures
        inp = None
        for mk in (lambda: embs.createInput(profs, [od_face], adsk.core.ValueInput.createByString("-1 mm")),):
            try:
                inp = mk()
                break
            except Exception as e:
                raise RuntimeError("emboss createInput: " + str(e)[:100])
        f = embs.add(inp)
        f.name = "装球口"
        # 凹凸验证：nurbs 面质心径向位置（< R3 = 凹陷切入 ✓；> R3 = 凸起 ✗）
        r_dent = None
        for f_ in f.faces:
            if tname(f_.geometry) == "NurbsSurface":
                bb = f_.boundingBox
                cen = ((bb.minPoint.x + bb.maxPoint.x) / 2 * 10,
                       (bb.minPoint.y + bb.maxPoint.y) / 2 * 10,
                       (bb.minPoint.z + bb.maxPoint.z) / 2 * 10)
                r_dent = round(radial_of(cen), 3)
                break
        if r_dent is not None and r_dent > R3 + 0.05:
            try:
                f.deleteMe()
            except Exception:
                pass
            raise RuntimeError("凸雕方向错误（凸起 r={} > R3={}），已删除".format(r_dent, R3))
        # 方位验收：整个凸雕特征所有 Nurbs 面的联合包围盒质心必须 ≈ er0（单片质心天然偏心，不能用）
        if True:
            mn = [1e9, 1e9, 1e9]; mx = [-1e9, -1e9, -1e9]
            for f_ in f.faces:
                if tname(f_.geometry) == "NurbsSurface":
                    bb = f_.boundingBox
                    for k in range(3):
                        mn[k] = min(mn[k], bb.minPoint.getData()[k] if False else [bb.minPoint.x, bb.minPoint.y, bb.minPoint.z][k] * 10)
                        mx[k] = max(mx[k], [bb.maxPoint.x, bb.maxPoint.y, bb.maxPoint.z][k] * 10)
            cen = ((mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2)
            dr = sub3(cen, A0)
            dr = tuple(dr[i] - u[i] * sum(dr[j] * u[j] for j in range(3)) for i in range(3))
            dL = math.sqrt(sum(a * a for a in dr)) or 1e-12
            cos_a = sum(dr[i] * er0[i] for i in range(3)) / dL
            if cos_a < 0.98:
                try:
                    f.deleteMe()
                except Exception:
                    pass
                raise RuntimeError("凸雕方位错误（偏离 α0 {:.1f}°），已删除".format(
                    math.degrees(math.acos(max(-1, min(1, cos_a))))))
        emb_feat = f
        steps["S5装球口凸雕"] = "ok 凹陷r={}".format(r_dent)
    except Exception as e:
        steps["S5装球口凸雕"] = "FAIL " + str(e)[:150]

    # ⑥b 口棱圆角：移到 ⑨（阵列特征复制不了 fillet，改为阵列后统一倒）

    # ============ S6· 标准球（入球组子组件——2026-08-20 嵌套定则） ============
    grp = grp_name = None
    ball_axis = None
    try:
        grp_name = "球组-⌀{:.0f}".format(R_h * 2)
        grp_occ = comp.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        grp = grp_occ.component
        grp.name = grp_name
        # 组内自建过轴平面（三点式挂草图参考点——点不死，防圆角断链）
        skg = grp.sketches.add(grp.xYConstructionPlane)
        skg.name = "球组-参考点"
        qA = skg.sketchPoints.add(adsk.core.Point3D.create(cm(A0[0]), cm(A0[1]), cm(A0[2])))
        qB = skg.sketchPoints.add(adsk.core.Point3D.create(cm(A0[0] + u[0]), cm(A0[1] + u[1]), cm(A0[2] + u[2])))
        qC = skg.sketchPoints.add(adsk.core.Point3D.create(cm(A0[0] + er0[0] * R5), cm(A0[1] + er0[1] * R5), cm(A0[2] + er0[2] * R5)))
        plg = None
        for _try in range(2):
            try:
                pin = grp.constructionPlanes.createInput()
                pin.setByThreePoints(qA, qB, qC)
                plg = grp.constructionPlanes.add(pin)
                break
            except Exception:
                continue
        if plg is None:
            raise RuntimeError("球组过轴平面失败")
        plg.name = "球组截面平面"
        ball_body, ball_feat, ball_axis = make_sphere_body(
            R_track, zB, DBALL / 2, "球-⌀{:.2f}".format(DBALL), grp, plg)
        steps["S6·标准球"] = "ok(球组子组件)"
    except Exception as e:
        steps["S6·标准球"] = "FAIL " + str(e)[:120]
        ball_feat = None

    # ============ S6· 圆周阵列（凸雕+圆角+球）============
    try:
        # 凸雕留 comp（中环上）；球在球组内用组内轴阵列——与装球口阵列解耦（嵌套定则）
        if emb_feat:
            oc_e = adsk.core.ObjectCollection.create(); oc_e.add(emb_feat)
            inp_e = comp.features.circularPatternFeatures.createInput(oc_e, axis_line)
            inp_e.quantity = adsk.core.ValueInput.createByString("{}".format(N_eff))
            inp_e.totalAngle = adsk.core.ValueInput.createByString("360 deg")
            fe = comp.features.circularPatternFeatures.add(inp_e)
            fe.name = "装球口阵列"
        if ball_feat and ball_axis is not None and grp is not None:
            oc_b = adsk.core.ObjectCollection.create(); oc_b.add(ball_feat)
            inp_b = grp.features.circularPatternFeatures.createInput(oc_b, ball_axis)
            inp_b.quantity = adsk.core.ValueInput.createByString("{}".format(N_eff))
            inp_b.totalAngle = adsk.core.ValueInput.createByString("360 deg")
            fb8 = grp.features.circularPatternFeatures.add(inp_b)
            fb8.name = "球阵列"
        steps["S6·阵列"] = "ok x{}（球组内）".format(N_eff)
    except Exception as e:
        steps["S6·阵列"] = "FAIL " + str(e)[:150]

    # ============ S6· 口棱圆角（阵列后，凹陷∩球窝 边 ×16）============
    fillet_ok = False
    try:
        ring5 = None
        for b in comp.bRepBodies:
            if b.name == "中环":
                ring5 = b
        if ring5 is None:
            raise RuntimeError("中环未找到")
        cand = []
        for f_ in ring5.faces:
            if tname(f_.geometry) != "NurbsSurface":
                continue
            for e_ in f_.edges:
                adj = list(e_.faces)
                if len(adj) == 2 and sorted(tname(x.geometry) for x in adj) == ["NurbsSurface", "Sphere"]:
                    cand.append(e_)
        steps["S6·圆角候选边"] = len(cand)
        if not cand:
            raise RuntimeError("没找到凹陷∩球窝边")
        fils = comp.features.filletFeatures
        # 方案A：一个特征全倒
        try:
            oc_all = adsk.core.ObjectCollection.create()
            for e_ in cand:
                oc_all.add(e_)
            fi = fils.createInput()
            fi.addConstantRadiusEdgeSet(oc_all, adsk.core.ValueInput.createByString("{} mm".format(RFILLET)), False)
            fx = fils.add(fi)
            fx.name = "口棱圆角"
            fillet_ok = True
            steps["S6·口棱圆角"] = "ok(一次全倒) faces={}".format(fx.faces.count)
        except Exception:
            # 方案B：按方位角分组 ×8（每球位 2 条）
            def ang_of(e_):
                bb = e_.boundingBox
                m = ((bb.minPoint.x + bb.maxPoint.x) / 2 * 10,
                     (bb.minPoint.y + bb.maxPoint.y) / 2 * 10,
                     (bb.minPoint.z + bb.maxPoint.z) / 2 * 10)
                return math.atan2(m[1] - A0[1], m[0] - A0[0])
            cand.sort(key=ang_of)
            groups = []
            for e_ in cand:
                if not groups or abs(ang_of(e_) - ang_of(groups[-1][-1])) > math.radians(8):
                    groups.append([e_])
                else:
                    groups[-1].append(e_)
            n_ok = 0
            for gi, grp in enumerate(groups):
                oc_g = adsk.core.ObjectCollection.create()
                for e_ in grp:
                    oc_g.add(e_)
                fi = fils.createInput()
                fi.addConstantRadiusEdgeSet(oc_g, adsk.core.ValueInput.createByString("{} mm".format(RFILLET)), False)
                fx = fils.add(fi)
                fx.name = "口棱圆角{}".format(gi + 1)
                n_ok += fx.faces.count
            fillet_ok = n_ok > 0
            steps["S6·口棱圆角"] = "ok(分组×{}) faces={}".format(len(groups), n_ok)
    except Exception as e:
        steps["S6·口棱圆角"] = "FAIL " + str(e)[:150]

    # ============ S7 宿主融合（外环 JOIN 宿主，内盘/中环/球保持独立）============
    try:
        host_body = face.body                     # 孔面所属实体 = 宿主
        outer_proxy = None
        for b in comp.bRepBodies:
            if b.name == "外环":
                outer_proxy = b.createForAssemblyContext(occ)
        if outer_proxy is None:
            raise RuntimeError("外环未找到")
        Join = adsk.fusion.FeatureOperations.JoinFeatureOperation
        combs = root.features.combineFeatures
        oc_t = adsk.core.ObjectCollection.create()
        oc_t.add(outer_proxy)
        ci = None
        for mk in (lambda: combs.createInput(host_body, oc_t),
                   lambda: combs.createInput(host_body, oc_t, Join)):
            try:
                ci = mk()
                break
            except Exception:
                continue
        ci.operation = Join
        f = combs.add(ci)
        f.name = FUSION_NAME
        steps["S7宿主融合"] = "ok"
        # 验收：宿主应并入外环的 Torus 球道
        n_torus = sum(1 for ff in host_body.faces if tname(ff.geometry) == "Torus")
        verify["宿主融合"] = {"宿主Torus面": n_torus, "状态": "✓" if n_torus else "✗"}
    except Exception as e:
        steps["S7宿主融合"] = "FAIL " + str(e)[:150]
        verify["宿主融合"] = {"状态": "✗"}

    # ============ S8· 命名与分组整理 ============
    try:
        # 球自然序重命名：球-⌀XX / 球-⌀XX (k) → 球01…球NN
        import re as _re
        _scan = list(comp.bRepBodies) + (list(grp.bRepBodies) if grp is not None else [])
        balls = [b for b in _scan if b.name.startswith("球")]
        def _bn(b):
            m = _re.search(r"\((\d+)\)", b.name)
            return int(m.group(1)) if m else 0
        balls.sort(key=_bn)
        for i, b in enumerate(balls):
            b.name = "球{:02d}".format(i + 1)
        # 脚手架隐藏：草图全部收起，构造面灭灯（浏览器树只留成品）
        for _comp_x in [comp] + ([grp] if grp is not None else []):
            for sk_ in _comp_x.sketches:
                try:
                    sk_.isVisible = False
                except Exception:
                    pass
            for cp_ in _comp_x.constructionPlanes:
                try:
                    cp_.isLightBulbOn = False
                except Exception:
                    try:
                        cp_.isVisible = False
                    except Exception:
                        pass
        for cp_ in comp.constructionPlanes:
            try:
                cp_.isLightBulbOn = False
            except Exception:
                try:
                    cp_.isVisible = False
                except Exception:
                    pass
        steps["S8·整理"] = "ok 球×{}重命名+脚手架隐藏".format(len(balls))
    except Exception as e:
        steps["S8·整理"] = "FAIL " + str(e)[:120]

    # ============ S8· 选择集沉淀（球组 / 轴承全部：浏览器点击即选 → 一键隐藏 / 导出）============
    try:
        sig = "⌀{:.0f}".format(R_h * 2)
        set_balls, set_all = "球-" + sig, "轴承-全部-" + sig
        for nm in (set_balls, set_all):      # 幂等：同名旧集随重建已过期，先删
            try:
                des.selectionSets.itemByName(nm).deleteMe()
            except Exception:
                pass
        occ_ = None
        for o_ in root.occurrences:
            if o_.component.name == COMP_NAME:
                occ_ = o_
                break
        bodies_ = list(occ_.bRepBodies)      # occurrence 视图 = root 上下文实体（选择集只吃这个）
        if grp_name:
            grp_root = None
            for o_ in root.allOccurrences:   # 嵌套体入集必须 root 视图 occ（组件链 occ 必报 InternalValidationError）
                if o_.component.name == grp_name:
                    grp_root = o_
                    break
            if grp_root is not None:
                bodies_ = bodies_ + list(grp_root.bRepBodies)
        balls_ = [b_ for b_ in bodies_ if b_.name.startswith("球")]
        msg = []
        if balls_:
            des.selectionSets.add(balls_, set_balls)
            msg.append("{}×{}".format(set_balls, len(balls_)))
        if bodies_:
            des.selectionSets.add(bodies_, set_all)
            msg.append("{}×{}".format(set_all, len(bodies_)))
        # 孔面集是输入锚，⑩融合后引用必死（0 实体）→ 清掉，树上只留活集
        for ss_ in list(des.selectionSets):
            if ss_.name.startswith("孔面-") and len(list(ss_.entities)) == 0:
                try:
                    ss_.deleteMe()
                except Exception:
                    pass
        steps["S8·选择集"] = "ok " + " + ".join(msg) if msg else "ok(空)"
    except Exception as e:
        steps["S8·选择集"] = "FAIL " + str(e)[:120]

    # ============ ⑪ 交付强制几何验收 ============
    try:
        for b in list(comp.bRepBodies) + (list(grp.bRepBodies) if grp is not None else []):
            # 用实体顶点采样（bbox 对角会虚报径向，如圆柱盒角=√2·R）
            verts = []
            for f_ in b.faces:
                for v_ in f_.vertices:
                    g_ = v_.geometry
                    verts.append((g_.x * 10, g_.y * 10, g_.z * 10))
            if not verts:
                bb = b.boundingBox
                verts = [((bb.minPoint.x + bb.maxPoint.x) / 2 * 10,
                          (bb.minPoint.y + bb.maxPoint.y) / 2 * 10,
                          (bb.minPoint.z + bb.maxPoint.z) / 2 * 10)]
            r_max = max(radial_of(p) for p in verts)
            # 轴向范围（相对孔底 A0）
            zs = [sum((p[i] - A0[i]) * u[i] for i in range(3)) for p in verts]
            ok_pos = r_max <= R_h + 1.0 and min(zs) >= -1.0 and max(zs) <= D_h + 1.0
            surf = {}
            for f_ in b.faces:
                t = tname(f_.geometry)
                surf[t] = surf.get(t, 0) + 1
            if b.name.startswith("球"):
                cen = ((bb.minPoint.x + bb.maxPoint.x) / 2 * 10,
                       (bb.minPoint.y + bb.maxPoint.y) / 2 * 10,
                       (bb.minPoint.z + bb.maxPoint.z) / 2 * 10)
                verify[b.name] = {"径向": round(radial_of(cen), 3), "期望": round(R_track, 3),
                                  "位置": "✓" if ok_pos and abs(radial_of(cen) - R_track) < 0.2 else "✗"}
            else:
                verify[b.name] = {"r_max": round(r_max, 3), "z范围": [round(min(zs), 2), round(max(zs), 2)],
                                  "面型": surf, "位置": "✓" if ok_pos else "✗"}
        # 真弧验收：内盘/外环应含 Torus
        for nm in ("内盘", "外环"):
            for b in comp.bRepBodies:
                if b.name == nm:
                    n_torus = sum(1 for f_ in b.faces if tname(f_.geometry) == "Torus")
                    verify[nm + "-真弧"] = "✓ Torus×{}".format(n_torus) if n_torus else "✗ 仍是折线"
        steps_ok = all("FAIL" not in str(v) for v in steps.values())
        pos_ok = all(v.get("位置") != "✗" for v in verify.values() if isinstance(v, dict))
        n_ball_ok = sum(1 for b in list(comp.bRepBodies) + (list(grp.bRepBodies) if grp is not None else []) if b.name.startswith("球")) == N_eff
        verify["总结论"] = ("PASS ✓" if (steps_ok and pos_ok and n_ball_ok)
                            else "FAIL ✗ steps_ok={} pos_ok={} balls8={}".format(steps_ok, pos_ok, n_ball_ok))
    except Exception as e:
        verify["error"] = str(e)[:150]

    final = [{"name": b.name, "faces": b.faces.count}
             for b in list(comp.bRepBodies) + (list(grp.bRepBodies) if grp is not None else [])]

    # no3dprint：全部球一键隐藏（导出打印用，用户定则）
    try:
        des.selectionSets.itemByName("no3dprint").deleteMe()
    except Exception:
        pass
    _n3d = [b for b in root.bRepBodies if b.name.startswith("球")]
    for o_ in root.allOccurrences:
        _n3d += [b_ for b_ in o_.bRepBodies if b_.name.startswith("球")]
    if _n3d:
        des.selectionSets.add(_n3d, "no3dprint")

    return {
        "document": app.activeDocument.name, "component": COMP_NAME, "purged": purged,
        "hole": {"R_h": round(R_h, 3), "u": [round(v, 4) for v in u],
                 "A0": [round(v, 3) for v in A0], "D_h": round(D_h, 3),
                 "from_selection_set": used_set},
        "bearing": {"dBall": DBALL, "rg": round(RG, 4),
                    "R_track": round(R_track, 3), "R1": round(R1, 3), "R2": round(R2, 3),
                    "R3": round(R3, 3), "R4": round(R4, 3), "R5": round(R5, 3), "zB": round(zB, 3)},
        "n_formula": {"N": N_eff,
                      "约束角deg": {"口": round(math.degrees(th_s), 1),
                                    "窝": round(math.degrees(th_e), 1),
                                    "球": round(math.degrees(th_b), 1)},
                      "模式": "自动" if N_BALLS is None else "手动"},
        "steps": steps, "verify": verify, "final_bodies": final,
    }


try:
    _result = main()
except Exception as e:
    _result = {"error": str(e), "tb": traceback.format_exc()}
