# Fusion 360 Python 3.14 API 坑位表（全部实战踩出，每条附正确写法）

写代码前先过一遍这张表。条目按主题分组。

## tempBrep（临时实体）
- `bRepBodies.add(body, bf)` 必须显式传 BaseFeature（tempBrep 入档）。
- tempBrep **无 createCylinder**（球/圆环有，圆柱没有）——用草图圆拉伸替代。
- `Sphere`/`Torus` 几何**无 `.center`**，用 `.origin` 或 bbox 中心。

## 特征/草图
- 多 profile 拉伸必须 ObjectCollection；`Profile` **无 `.area`**（3.14 移除），用 bbox 筛选/对账。
- revolve = **3 参 `createInput` + `.operation` 属性**；`setTwoSidesExtent` 签名已变——
  单侧用 `setDistanceExtent` 从 XY 面切。
- `addByThreePoints` 的"中点"必须**真在圆上**，离圆点直接"参数无效"拒画。
- 枚举名：拉伸出实体用 `NewBodyFeatureOperation`（不是 Combine 类）。
- 世界→草图落笔**必须用官方 `sketch.modelToSketchSpace()`**——手写 transform 逆映射
  矩阵展开放有符号错，孔轴手性一变整套翻面。
- 凸雕 `createInput` 不吃 3D 落笔曲线（轮廓必须真在平面上）；`createInput(list, list, VI)` 重载。
- 圆角 `addConstantRadiusEdgeSet(OC, VI, bool)`。
- 定向平面 `setByTangentAtPoint(face, 点)`——但**面被后续特征（如圆角）改动会断链**
  （"曲面缺失，已使用缓存"）。稳妥做法：切平面改**三点式挂草图参考点**（点不死）。
- 齿形等 300 点样条在 rot=15° 采样相位下切量会 +2%（样条鼓包），rot=0/7.5° 正常；
  **千万别一次上千点（卡死 Fusion）**。

## 选择集 / ObjectCollection
- `SelectionSets.add(entities, name)` —— **实体列表在前、名字在后**（Python list 可，
  ObjectCollection 必拒）；名字在前的旧签名已废。
- `MoveFeatures.createInput` 相反：要 **ObjectCollection**。
- 融合后孔面集会成 0 实体死集，脚本要自动清。
- `occ.bRepBodies` 喂的是 occurrence 视图（root 上下文），组件裸 body 被拒。

## 变换 / 坐标
- `Matrix3D` 3.14 **无 createTranslation** → `Matrix3D.create()` 后赋 `.translation`。
- `transform2` 的 translation 单位是 **cm**，×10 转 mm；旋转部分无量纲。
- Fusion 圆柱面：`face.geometry` 为 `Cylinder` 时 `.radius` / `.axis`（**直接是 Vector3D**，
  不是 `.axis.vector`）/ `.origin`；轴向要世界系时用 `transformBy(occ.transform2)`。
- 关节 API：`Joint.geometryOrOriginOrImplicitPoint` 没了，用 `joint.geometryOrOriginOne/Two`
  （JointGeometry，含 `origin` Point3D + `primaryAxisVector`）。

## 组件 / 装配
- `comp.occurrences.addNewComponent` 建子组件（在 root 直接建会平级）。
- 跨组件合并刚体：`createForAssemblyContext` 代理 JOIN。
- **幂等清理**：先删特征再删 body（合并目标 body 先删 → TARGET_BODY_REFERENCE_LOST），
  倒序 + 多趟重试（悬空特征挡依赖删除）。
- 草图**不是 feature**——健康检查扫 features 查不出草图孤儿化，要另测 `sk.transform` 可读性。

## 导出
- `createSTLExportOptions(o,...).execute` 对不可见 occurrence **返回 True 但不写文件**（假阳性）：
  先打通祖先链 `isLightBulbOn=True` + `body.isVisible=True`，finally 恢复，导完
  `os.path.exists` 校验。`occurrence.isVisible` 只读，`isLightBulbOn` 可写。

## add-in / 进程
- Fusion API 非线程安全：HTTP 请求 → CustomEvent → 主线程队列执行。
- **/exec 持久命名空间**：笔误裸变量名（漏下划线）不报 NameError，静默命中旧值——
  注入脚本自包含、循环解包变量带专属后缀。
- 模块缓存进程级隔离：热重载要倒序删 + 清 `__dict__` + `invalidate_caches`。
- BaseFeature 必须 `startEdit/finishEdit`（失败不关会话会毒化所有特征 API）。
- 文字 API（SketchTexts.add）在 /exec 调不通（InternalValidationError），编号改点孔。

## 通用防御
- `str.replace` 前 `assert 旧串非空 and content.count(锚点)==1`
  （空串锚点会把替换块插进每个字符之间，文件爆炸）。
- 失败半步留重名草图 → 每步前清理同重名。

## STL 导出（示例 examples/export_stl.py 实测）
- `STLExportOptions` **无 `.execute()`**——执行在 `exportManager.execute(options)` 上。
- `Occurrence` **无 `parentOccurrence`**——祖先链靠自顶向下递归时随身携带
  （rootComponent.occurrences → occ.childOccurrences）。
- 选项里有 `isIncludingInvisibleComponents/Bodies` 可绕开 lightbulb 链（未验证导出质量）。

## 值/输入对象（WorkBuddy 实战补充 2026-08-20）
- `ValueInput` **无 createByInteger** → 用 `createByReal`（或 createByString）。
- `TemporaryBRepManager.createSphere(center, radius)` 的 radius 是**原始 double（cm）**，
  不吃 ValueInput。
- `CircularPatternFeatures.createInput` 入参要 **ObjectCollection**，Python list 必拒
  （与 MoveFeatures 同源；SelectionSets.add 则相反只要 list——三个 API 三种口味，别背错）。
- `setDistanceExtent(isSymmetric, distance)` 的 distance 是 **ValueInput**（`createByReal`），
  不是裸 float（3.14 实测）。
- 两同心圆草图产生**两个 profile（内盘+圆环）**，`profiles.item(0)` 不保证是环——
  按 bbox 半径==外径筛选（同前条：Profile 无 .area 用 bbox）。
- 组件基准面是 `xYConstructionPlane`（不是 `xYPlane`）。

## 文档类型（零件设计 vs 装配）
- 「零件设计文档只能包含一个零部件」报错 = `design.designIntent == PartDesignIntentType(0)`。
  **可运行时切换**：`des.designIntent = DesignIntentTypes.HybridDesignIntentType`（2），
  切完立即可 addNewComponent（实测）；`documents.add(FusionDesignDocumentType)` 新建的档默认 Hybrid。
  注意 `app.activeDocument` 只读（无 setter），跨文档操作直接用 doc 对象。
- selectionSets.add 喂嵌套组件的体，occ 必须**root 视图**：组件链 occ.bRepBodies →
  InternalValidationError(owningCompOfEntity==owningCompOfGroups)；root.allOccurrences
  拿的 occ 或 createForAssemblyContext(rootocc) 均实测 OK（2026-08-20 三路径对照）。
- `attributes.itemsByGroup()` 返回 **AttributeVector，无 .count**——用 `list(g)` 后 len/迭代。
- 文档属性存参数是好模式：参数随文档持久、跨会话、不改脚本（见 3dprint-bearing 修改姿势）。

## 圆周阵列（合一阵列实验 2026-08-20，实测）
- **切割(combine)特征可以进 ObjectCollection 阵列**（推翻"combine 不可阵列"旧结论）——
  但**不要这么做**：阵列副本重算会摧毁目标体（中环被算到 0.1mm³，API 却全程返回成功）。
  稳定路线仍是：刀体先阵列 ×N → 一次性 Cut。
- **圆角特征不可进阵列**：FILLET_NO_EDGE_FOUND（副本里引用边找不到对应）。圆角永远阵列后做。
- 阵列副本的面拓扑类型会变（母窝 Sphere → 副本 Nurbs）——按面型选边/选面的逻辑在
  阵列副本上不可靠，用几何判据（顶点到刀圆距离等）。

## 时间线特征归组（TimelineGroups，实测 2026-08-20）
- 入口 `design.timeline.timelineGroups.add(startIndex, endIndex)`（时间线索引，非特征对象）。
- **建组会吸收条目使后续索引位移**：多组要从后往前建（或建一组平移一次后续区间）。
- 组内条目再访问 `timeline.item(i).entity` 会抛 "Associated feature is invalid"——扫描时间线要逐条 try。
- combine/切割类特征进组可能报 InternalValidationError(dcFeature)——归组做 best-effort，失败跳过。
- 组名可赋值（`g.name=...`）。
