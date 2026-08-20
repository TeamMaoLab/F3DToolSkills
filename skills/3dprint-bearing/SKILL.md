---
name: 3dprint-bearing
description: >-
  F3DToolSkills 应用：为 3D 打印而生的孔内成型球轴承——在 Fusion 360 任意位置/姿态的
  圆柱孔内一键生成**可直接打印**的完整球轴承（内盘+中环+外环+球+N 阵列+圆角，
  外环融入宿主一体打印）。配方按 FDM/光固化打印缩尺实测调校（clr 间隙、窝径缩尺、
  孔深下限、球用标准钢球）、球数公式、强制几何验收、no3dprint 一键隐藏球导出打印。
  当用户提到 3D 打印轴承、打印一体轴承、掏轴承、孔内成型、自定义球轴承、支撑球、
  bearing in a hole、gen_bearing_full、轴承设计器，要在 Fusion 孔里做参数化轴承、
  批量多孔轴承，或要求排雷/审计/修改轴承生成代码时使用。
  即使用户只说"给这个孔做个轴承"也要触发。依赖底座 f3dtoolskills 的 exec 端点（:9099）。
---

# 3D 打印轴承 · 孔内成型（F3DToolSkills 应用）

**这是给 3D 打印设计的轴承，不是建模玩具**：整个轴承在宿主孔内直接成型，外环融入
宿主，**打印出来就是一台能转的轴承**——你只需要准备一包标准钢球（⌀2.381/3/32″ 或
⌀2.5）从装球口滑入。设计自由度全部围绕打印工艺调校：

- **打印间隙 clr**：FDM 默认 0.2、光固化 0.05——窝径、球道、装球口全部由 clr 派生。
  实测 FDM 窝径印后缩尺约 −0.08mm，clr=0.2 印后径向间隙 0.16/边偏松，中靶档 clr=0.10
  （印后 0.06/边）；打印试验协议见 `reference/bearing_ball_sizes.md`
- **孔深=零件厚=轴承总厚**：D_h=4 通孔契约，窝上缘保 ≥0.55mm 打印线（孔深下限公式
  = 球径+2·clr+1.1）
- **打印友好结构**：圆角只倒外口两边、装球口 V 形引导、支撑球/球窝自身维持层间稳定
- **导出即打印**：脚本自动建 `no3dprint` 选择集（全部球一键隐藏——钢球不打印），
  配合 stl-export 应用导出后直接进切片机

在任意位置/姿态的圆柱孔里，按预设配方生成完整球轴承（内盘+中环+外环+球+N 阵列+圆角），
并把外环融合进宿主。全链路经底座 `/exec` 注入运行——应用即脚本，不新增端点。

## 资产（都在本 skill 目录）

| 资产 | 路径 | 用途 |
|---|---|---|
| 生成脚本 | `scripts/gen_bearing_full.py` | 一键全流程 + 强制验收，幂等 |
| 演示生成器 | `scripts/gen_demo_bearing.py` | **无孔宿主/看效果用**：参数化演示轴承（改头部外参区即可），体积逐步对账+幂等，实测两轮 PASS |
| 权威文档 | `reference/bearing_in_hole_workflow.md` | 配方表/球数公式/API 坑位全表——**改代码前必读第五、六点五节** |
| 球径推演 | `reference/bearing_ball_sizes.md` | ⌀3→2.5→2.381 缩放规则、孔深/N 杠杆 |
| 网页设计器 | `designer/bearing_designer.html` | 参数探索 + 3D 预览 + JSON 导出（浏览器直接打开） |
| 配方草图页 | `designer/bearing_sketch.html` | 三视图纯线稿 + 尺寸标注 |
| 宿主示例 | `scripts/prep_host_demo.py` | 无宿主时造 ⌀24×4+⌀16 通孔宿主并把孔面入选择集（实测 PASS） |
| 只读探针 | `scripts/inspect_selection.py`、`scripts/dump_features.py` | 看选集/时间线/面几何 |

## 前置检查（每次运行前）

> ⚠ 写/改任何注入代码前，先查底座 `../f3dtoolskills/reference/api_pitfalls.md`
> （ValueInput/createSphere/ObjectCollection 等坑都有正确写法，别靠报错试）。
> 用户只是想"看个轴承效果"（无孔宿主）→ 注入 `scripts/gen_demo_bearing.py`，
> 只改头部【外参】区（孔径/环径/宽/球径），不要现写脚本；
> 本 skill 只在满足输入契约（孔面在设计选择集）时运行。

1. `curl -s --max-time 5 http://127.0.0.1:9099/ping` —— 不通则按底座 f3dtoolskills 的「安装规范」装/启动 add-in
2. Fusion 打开目标文档——**必须允许嵌套零部件**（零件设计文档会报"只能包含一个零部件"）。两种修法：
   - 原地切换（推荐，不换文档）：`des=doc.design; des.designIntent=adsk.fusion.DesignIntentTypes.HybridDesignIntentType`
     （枚举 Part=0/Assembly=1/Hybrid=2；实测切换后立即可建组件）
   - 或开新档：`app.documents.add(c.DocumentTypes.FusionDesignDocumentType)`（新建默认 Hybrid）
3. **孔面在设计选择集**里（无宿主先跑 `scripts/prep_host_demo.py`）（不是 UI 选中——`/exec` 每次都会清掉 UI 选中）。契约：圆柱孔；
   孔深下限 = 球径+2·clr+1.1（窝上缘≥0.55 打印线，球 2.381/clr0.2 → ≥3.88，推荐 4）；
   孔半径 > ~5.2

## 运行（注入现成脚本，禁止自己写实现）

```bash
curl -s --max-time 300 -G http://127.0.0.1:9099/exec \
  --data-urlencode "code@<本skill目录>/scripts/gen_bearing_full.py"
```

**本 skill 的所有能力都已脚本化**（见资产表 5 个脚本）——改参数改脚本头部常量
（DBALL/CLR/N_BALLS），改流程先提 issue 而不是现写变体。自己现写 py = 绕开
幂等/验收/命名体系 = 前功尽弃。

**修改的正确姿势 = 设文档属性 → 重新注入（两步，不动脚本文件、agent 不许手动删东西）**：

```bash
# 1. 设参数（存进文档属性，随文档持久保存；可覆盖 N_BALLS/DBALL/CLR/RFILLET）
curl -G http://127.0.0.1:9099/exec --data-urlencode \
  "code=import adsk.core as c;d=c.Application.get().activeDocument.design;d.attributes.add('F3DToolSkills','N_BALLS','8')"
# 2. 重新注入（脚本自动读属性覆盖常量）
curl -G http://127.0.0.1:9099/exec --data-urlencode "code@<skill>/scripts/gen_bearing_full.py"
```

- 清除覆盖（回到公式自动）：把同名属性 deleteMe 或值设 'None'
- 脚本幂等：**自愈会自动删融合特征+旧组件、恢复孔面入选择集、重建、重新验收**
  （实测：N=7 建成后设 N_BALLS=8 重注入 → 自愈重建 PASS ✓）
- **agent 不要自己动手删组件/删实体**——手删会破坏融合状态和选择集，脚本的自愈路径
  才是唯一正确清理方式。重建是设计机制不是浪费：N 变更级联球窝×N/阵列×N/圆角边数/重命名，
  原地改特征链极易留脏状态。

- `DBALL`/`CLR`/`N_BALLS = None` → 球数公式自动；填数字 → 手动覆盖
- 输出看四块：`steps`（每步状态）、`n_formula`（球数依据）、`verify`（几何验收）、
  **`report_html`（给用户的报告链接，file:/// URL**：参数表+按实际参数绘制的剖面 SVG+
  步骤/验收表+下一步指引，**写到用户桌面** `bearing_report.html`）——agent 跑完把
  `report_html` 的值原样发给用户（形如 `file:///C:/Users/xx/Desktop/bearing_report.html`，
  客户端可直接点击；不要发裸盘符路径，多数客户端不认）
- **只有 `verify.总结论 == "PASS ✓"` 才算成功**。steps 全 ok 但几何错的历史案例太多（见下）

## 验收纪律（不可妥协）

- **特征创建成功 ≠ 几何正确**。历史四连坑：建到世界原点、窝是折线、圆角选错边、凸雕凸起——
  特征 API 全部返回成功。任何生成/修改后必须读几何证据：世界位置（实体顶点）、面型
  （Torus=真弧）、面积（圆角 1.192×2/位）、凹凸方向（质心径向 < R3）
- bbox 对角虚报径向（圆柱包围盒角 = √2·R），径向检查用**实体顶点采样**
- 凸雕面被劈成多片，单片质心天然偏心——方位验收用**联合包围盒质心**
- 改完代码：连续重跑两轮（幂等验证）+ PASS，才算完成

## 球数公式（不要拍脑袋定 N）

```
N = ⌊360° / max(θ口, θ窝, θ球)⌋，下限 3
θ口 = 2·atan((slotW/2 + 0.5)/R3)        V口顶宽在环外壁占角（g=0.5 余隙）
θ窝 = 2·asin(√(rg²−(δ−t_ring/2)²)/R2)   球窝在内壁开口占角
θ球 = 2·asin((dBall+0.3)/(2·R_track))   相邻球心弦长留隙
```
实测锚点：R3=7.7→N=8；R3=5.2→N=6（N=8 会叠口）；R3=10.5→N=11。

## 常见故障速查（详表在 reference/bearing_in_hole_workflow.md 第五节，改 API 调用前先查）

| 症状 | 原因 → 对策 |
|---|---|
| 报"选择集里没有圆柱孔面" | 融合吃掉了孔壁面（引用失效）→ 自愈路径走旧组件反推；多组件并存时报错要求显式指定，**不要猜** |
| 特征"成功"但几何没变 | 4 参 createInput 静默失败 → 3.14 版一律 3 参 + 属性（operation/quantity/totalAngle） |
| 切割/引用对象失效 | 特征操作后引用过期 → 按名重取（自己建的实体先命名） |
| profile 数不对 | 直接建模里构造线会切面域（隔离到独立草图）；闭环竖缘重复段自交（边界顺序：下段→弧→上段） |
| fillet 阵列报 FILLET_NO_EDGE_FOUND | 阵列复制不了圆角 → 先阵列后圆角（16 边一个特征全倒） |
| combine 切完没效果 | combine 特征不可阵列 → 球刀体先阵列 ×N 再一次性 Cut |
| 凸雕把口雕到别的方位 | 切点必须真在目标面上（球窝洞口区域没有面）→ z=0.5 连续区 + 平面法向验收 |
| 圆角面积不对 | 圆角边 = **凹陷面∩球窝面交界**（每球位 2 条、面片 1.192×2），不是 V口侧棱、不是球窝口沿整圈 |
| 整套轴承翻到孔另一侧/镜像 | 手写「世界→草图」矩阵逆映射有符号错 → 一律用官方 `sketch.modelToSketchSpace()`（±Z 轴孔必现） |
| 装球口草图报「曲面缺失已用缓存」 | 切平面 `setByTangentAtPoint` 挂在实体面上，后续圆角改面断链 → 改三点式挂草图参考点 |

## 命名与分组规范（脚本自动执行）

- **组件签名含宿主**：`轴承-全-{宿主实体名}-⌀XX`（融合特征同名签名挂 root）。
  **签名只含孔径会在同径多孔时互相清杀**（实测踩坑），必须带宿主名
- **球组子组件**：球统一放轴承组件名下的子组件 `球组-…`（`comp.occurrences.addNewComponent`，
  不是 root——否则平级）。球的圆周阵列在球组内做，与装球口阵列解耦。
  ⚠ **gen_bearing_full.py 本体尚未切换此结构（球仍平铺在轴承组件下）**——这是待办不是 bug；
  agent 不要自行改造脚本去补，平铺结构下 no3dprint 选择集正常工作
- **嵌套体入选择集的坑（实测三路径）**：组件链上拿的 occ（`comp.occurrences.item(n).bRepBodies`）
  喂 selectionSets.add 必报 `InternalValidationError: owningCompOfEntity == owningCompOfGroups`。
  正确做法二选一：① `root.allOccurrences` 里按组件名找到该 occ，再 `.bRepBodies`（root 视图）；
  ② `nativeBody.createForAssemblyContext(root视图occ)` 造代理
- **选择集只留 `no3dprint`**（全部球一键隐藏，导出打印用）。坑：枚举 selectionSets 过程中
  deleteMe 会使迭代器失效 → 惰性枚举跳过失效引用、多趟清完
- **实体**：`内盘` / `中环` / `球01…球NN`（自然序重命名；外环已并入宿主不单独存在）
- **脚手架**：全部草图收起、构造面灭灯——浏览器树只留成品
- 用户在 Fusion 里手动合并/撤销会破坏这套状态（选择集引用失效、组件消失），重跑前先快照检查

## 实体识别方法论（扩展功能时遵循）

顺序：**创建时留引用 > 命名重取 > 几何签名搜索（类型+尺寸+位置+方位，作用域收窄到自建 body）
> 拓扑邻接**。能引用不搜索，能命名不签名。每次筛选后配一条几何断言。

## 批量多孔

组件按「宿主+孔径」签名命名（同径并存互不清杀），融合特征同名签名；目标孔面逐孔放入
选择集再跑。多组件且无有效选择集 → 报错要求显式输入，拒绝启发式猜测。

## 网页设计器联动

浏览器直接打开 `designer/bearing_designer.html`：R_h → R_track → 球径预设 → N（自动公式）
四个自由参数，配方锁死；「复制参数 JSON」产出 `anchor/ball_center/preset/assembly/n_formula`
结构，是脚本参数化的目标契约（脚本直读 JSON 尚未实现，改参数要动脚本头部常量）。
