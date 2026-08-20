---
name: stl-export
description: >-
  F3DToolSkills 应用：导出当前 Fusion 文档全部可见 occurrence 的 STL（注入脚本形态，
  幂等、lightbulb 祖先链处理、exists() 双校验）。当用户要导出 STL、导出装配体、
  导出零件打印、批量导出可见组件时使用。依赖底座 f3dtoolskills 的 exec 端点。
---

# stl-export（F3DToolSkills 应用 #1）

应用即脚本：一条 /exec 注入完成导出，不新增端点、不装新 add-in。

```bash
curl -G http://127.0.0.1:9099/exec --data-urlencode "code@<本skill目录>/scripts/export_stl.py"
```

- 只导**用户可见**的 occurrence（尊重 lightbulb 隐藏），嵌套子组件递归导出；
- 输出到系统临时目录 `f3dtoolskills_exports/`，每个 occurrence 一个 STL
  （`fullPathName` 命名，去重 `:`/`/`）；
- 返回 `_result` JSON：`count / verified_files / exports[]`，
  每条含 `api_returned`（不可信）与 `file_ok`（`exists()+size>0` 双校验，以此为准）。

改参数：输出目录改脚本头部 `_out_ex`；要导隐藏件用
`isIncludingInvisibleComponents=True`（见底座 `api_pitfalls.md`，导出质量未验证）。

写你自己的应用时照抄这个模式：**自包含脚本 + `_result` 契约 + 幂等 + 读回验证**，
然后在 `skills/` 下建同名目录沉淀（SKILL.md + scripts/ + 可选 html 设计器）。
