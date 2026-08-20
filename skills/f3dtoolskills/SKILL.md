---
name: f3dtoolskills
description: >-
  Fusion 360 AI 底座（TeamMaoLab）：在 Fusion 的 Python 环境里开一个可注入脚本的
  /exec 端点（:9099），让 agent 自由探索 Fusion 全部能力；自带 add-in 源码与
  agent 可直接执行的安装规范（定位 AddIns 目录→复制→探活→引导启动，零外部依赖）、
  Python 3.14 API 坑位表、
  幂等构建与实体读回验收纪律、STL 导出坑（lightbulb 假阳性）。
  当用户说"帮我安装 TeamMaoLab/F3DToolSkills / Fusion AI 插件"，或提到 Fusion 远程控制、
  /exec、F3DToolSkillsEndpoint、9099 端口、Fusion 脚本报错、tempBrep、导出 STL、
  Fusion API 坑、幂等、实体验收，或要在 Fusion 里做任何建模/导出/探查任务时使用。
---

# f3dtoolskills

**底座**：在 Fusion 360 的 Python 环境里开一个可注入脚本的 `/exec` 端点（:9099），
让 agent 能自由探索 Fusion 的全部 Python 能力，并在其上可靠地建实体、验收、导出。
摆线减速器、孔内轴承等领域 skill 都是本底座之上的**应用**——它们共享这里的
远程链路、API 坑位表和验收纪律，但底座本身零业务逻辑。

**典型入口**：用户一句「帮我装 GitHub 上的 TeamMaoLab/F3DToolSkills」→ 本 skill 被触发 →
agent 按下面「安装规范」亲手装好 exec 端点 → 之后一切 Fusion 任务都从这里出发。

## 探索/发现工作流（底座的第一卖点）

面对没做过的任务，**不要凭记忆猜 API**——用 /exec 当场的实时探查，先发现再写：

```bash
# 1. 环境与当前文档
curl -G http://127.0.0.1:9099/exec --data-urlencode \
  "code=import adsk.core as c;a=c.Application.get();d=a.activeDocument;_result=(a.versionText, d.name, d.design.designType)"

# 2. 选中对象是什么（用户选中一个东西让你分析时）
curl -G http://127.0.0.1:9099/exec --data-urlencode \
  "code=import adsk.core as c;s=c.Application.get().userInterface.activeSelections;_result=[(o.entity.objectType, getattr(o.entity,'name','')) for o in s]"

# 3. 对象有哪些属性/方法（API 签名当场发现）
curl -G http://127.0.0.1:9099/exec --data-urlencode \
  "code=import adsk.core as c;b=c.Application.get().activeDocument.design.rootComponent.bRepBodies.item(0);_result=[m for m in dir(b) if not m.startswith('_')]"
```

发现循环：**探查现状 → 小步试验（一个特征/一个读回）→ 读回验证 → 下一步**。
每个试验都是一次独立注入；确认有效的写法沉淀进 `reference/api_pitfalls.md`。
探索修改了文档也没关系——`inspect_*`/`dump_*` 只读探查先行，改动脚本保持幂等可重放。

## 安装规范（agent 执行，不依赖用户本机 Python）

用户说「帮我装 F3DToolSkills / Fusion AI 插件」时，**由你（agent）亲自完成安装**，
不需要任何 bootstrap 脚本——你自己的 shell/文件能力就是安装器。按序执行：

**第 0 步：先探活**（可能已经装好且在跑）

```bash
curl -s --max-time 3 http://127.0.0.1:9099/ping
```

返回 JSON（含 `python: 3.14.x`）→ 直接报告已就绪，结束。

**第 1 步：定位 Fusion 的用户级 AddIns 目录**

| 环境 | 目录 |
|---|---|
| Windows | `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns`（即 `C:\Users\<用户>\AppData\Roaming\...`） |
| macOS | `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns` |
| WSL（Fusion 在 Windows 侧） | `/mnt/c/Users/<用户>/AppData/Roaming/Autodesk/Autodesk Fusion 360/API/AddIns` |

目录不存在说明 Fusion 未装或装在非默认位置：列出探测过程，让用户确认路径。
顺带可报告 Fusion 自带 Python 位置（Win `%LOCALAPPDATA%\Autodesk\webdeploy\production\<hash>\Python`，
当前 3.14）——Fusion 内脚本跑在它里面。

**第 2 步：复制 add-in**（源在本 plugin 的 `../../addin/F3DToolSkillsEndpoint/`）

```bash
cp -r <plugin根>/addin/F3DToolSkillsEndpoint <AddIns目录>/   # 目录已存在则先 rm 再 cp（升级覆盖）
```

复制后抽验：`<AddIns>/F3DToolSkillsEndpoint/F3DToolSkillsEndpoint.py` 和 `.manifest` 两个文件都在。

**第 3 步：引导用户手动启动（唯一需要人手的一步）**

Fusion 不允许外部进程启动 add-in。两条路任选：
- **免复制直跑（推荐试用）**：ADD-INS 面板点绿色 `+`，直接选 `<plugin根>/addin/F3DToolSkillsEndpoint`
  文件夹加载——不往系统目录拷任何东西，插件升级即自动生效；
- **标准安装**：Fusion → 实用程序 Utilities → ADD-INS → 列表选中 `F3DToolSkillsEndpoint` → **Run**
  （建议勾 "Run on Startup"，以后自启）。

用户操作完回到第 0 步探活确认，PASS 才算装完。

## 远程调用速查（端点 :9099）

```bash
curl http://127.0.0.1:9099/ping                                              # 连通性
# 长脚本用 POST（无 URL 长度限制，body=纯文本/JSON/表单均可）：
curl -s --max-time 300 http://127.0.0.1:9099/exec --data-urlencode "code@scripts/xxx.py"
curl http://127.0.0.1:9099/reload                                            # 热重载（仅 inf3d/common）
curl -G http://127.0.0.1:9099/exec --data-urlencode "code@scripts/xxx.py"    # 一行式短代码（GET）
curl -G http://127.0.0.1:9099/exec --data-urlencode \
  "code=import adsk.core as c;_result=c.Application.get().activeDocument.name"   # 一行式：结果放 _result
```

关键事实：
- **返回值契约：`_result`**——/exec 只把注入代码里的 `_result` 变量以 JSON 回传，
  `print()` 输出去 Fusion 控制台不回传。脚本结尾必须 `_result = ...`。
- **/exec 在 Fusion 主线程执行**（CustomEvent 调度，API 非线程安全），长任务会阻塞 HTTP 响应，超时调大。
- **/exec 是持久命名空间**：裸变量残留跨请求存活，笔误不报 NameError 会静默命中旧值——
  注入脚本必须自包含（全部常量自带、循环变量带专属后缀）。
- 端点只有 `/ping /exec /reload` 和三个**内容无关**的伺服路由：`/`（主页）、
  `/report`（最新构建报告）、`/s/<skill>/<文件>`（应用静态页，从 webroot.txt 指向的
  skills 目录读取——**页面归属各自 skill**，底座只做通用伺服）。业务能力仍全部走注入脚本。
- WSL → Windows Fusion：`127.0.0.1:9099` 直通；Fusion 读 WSL 文件走 UNC `\\wsl.localhost\<distro>\...`。
- **安全**：/exec 即任意代码执行，add-in 只绑本地回环，绝不端口转发到公网。

## 建模通用规范（任何建模任务先读 `reference/modeling_standards.md`）

命名体系 / 构造线草图纪律 / 参数三层 / 分步特征+体积对账 / 验收门槛 / 脚手架收尾。
**"只是画个演示"也不例外**——没有这套规范的模型就是一次性垃圾。

## 注入优先原则（token 经济学，硬规则）

**agent 的活是"选脚本+改参数+读 JSON"，不是写代码。** 执行顺序：

1. **先找现成脚本**：`ls <各skill>/scripts/` —— 覆盖了就直接注入（curl code@路径），
   改行为只改脚本头部【外参】常量区。**禁止把 skill 已有的能力重新写一遍**。
2. **探索性小动作**才允许一行式 /exec（dir() 探查、读选中物、读回验证）。
3. **skill 没覆盖的正事**：写成完整脚本（守 modeling_standards），存进对应 skill 的
   `scripts/`（沉淀），再注入执行。**不要在对话里内联长代码**——一次性的内联代码
   无法复用、无法验收、无法沉淀。
4. 解读返回的 `_result` JSON，按其中的验收字段报结论，不重算。

## 工程纪律（本 skill 的灵魂，违反必踩坑）

1. **幂等构建**：每步前清理同重名特征/草图；删组件必须**先删特征再删 body**（合并特征悬空会
   TARGET_BODY_REFERENCE_LOST），且**倒序+多趟重试**。构造平面按零件命名，只删自己的，别全清
   （全清会孤儿化其他零件的草图参考平面）。
2. **验收三关**：几何读回 PASS 判定 + 幂等重跑 + 篡改拦截。**特征成功≠几何正确**——必须读回
   实体（bbox/体积/Torus 圆心等）附几何证据才算交付。
3. **程序化≠不可回溯**：草图全用构造线，每个尺寸可回溯到公式。
4. **防御性脚本**：`str.replace` 前 `assert 锚点非空 and count==1`；失败半步留重名 → 下步前清理。
5. **别一次性上千点样条**（Fusion 直接卡死，未保存文档全丢），加密采样小步试。
6. **Fusion Python 3.14 API 坑先查 `reference/api_pitfalls.md` 再写代码**——tempBrep/Profile/
   Matrix3D/SelectionSets/addByThreePoints 等全部实测过，每条都有正确写法。

## STL 导出（lightbulb 假阳性）

`createSTLExportOptions(...).execute` 对不可见 occurrence **返回 True 但不写文件**。
导出前必须临时打通整条祖先链 `occurrence.isLightBulbOn=True` + `body.isVisible=True`
（`occurrence.isVisible` 只读，lightbulb 可写），finally 恢复；导完用 `os.path.exists(fpath)`
校验，不能信返回值。

## 沉淀用户自己的流程（agent 行为规范）

用户说「把这个流程沉淀下来 / 做成 skill / 以后一句话就能跑」时，你替他把流程写成
一个应用 skill。**没有模板文件——你就是生成器**，参照插件内两个范例照办：

1. **先问清楚三件事**（用户没说清就问，不要猜）：触发词（用户以后会怎么一句话叫起它）、
   输入契约（要用户在 Fusion 里准备什么，如选择集/孔面/参数）、产出是什么（实体/导出/报告）。
2. **把流程固化为注入脚本**放 `scripts/`，写法遵守本 skill 的全部纪律：
   自包含（不依赖 /exec 残留变量）、幂等（重跑=覆盖）、结尾 `_result = ...`、
   附几何/文件读回验收（参照 `../stl-export/scripts/export_stl.py` 的结构）。
   复杂多步流程可用特征名自进度（重跑跳过已完成步骤，参照 `../3dprint-bearing/`）。
3. **写 SKILL.md**：frontmatter 的 description 写触发词（越口语越好，含"即使只说 X 也要触发"
   式兜底）；正文写输入契约、运行命令（`code@<skill目录>/scripts/xxx.py`）、验收判据、
   常见故障。格式参照 `../stl-export/SKILL.md`（简）或 `../3dprint-bearing/SKILL.md`（全）。
4. **放置**：用户的个人流程放他自己的 `~/.agents/skills/<应用名>/`（跨工具可见、不受插件
   升级影响）；要贡献回 F3DToolSkills 就放插件 `skills/` 下提 PR。
   **不要把脚本写进 `~/.agents/skills/f3dtoolskills/`（底座目录）**——那是插件的内容，
   重装/升级即被覆盖。
5. **沉淀完当场验收**：按 SKILL.md 自己写的触发词、输入契约、运行命令走一遍全链路，
   PASS 才交付——你写的说明书自己要先照着跑通。
6. 参数多的流程可加自包含设计器 `designer/*.html`（浏览器直接打开，参照
   `../3dprint-bearing/designer/`），「复制参数 JSON」即脚本的目标契约。

脚本命名：`gen_*` 生成 / `_build_*` 分步构建 / `inspect_*` 只读逆向 /
`verify_*` 验收 / `dump_*` 调试导出。

## reference（相对本 skill 目录；add-in/安装器在 plugin 根，即 `../../`）

- `reference/api_pitfalls.md` —— Python 3.14 API 坑位表（写代码前必查）
- `reference/modeling_standards.md` —— 实体建模通用规范（动手建模前必读）
- `reference/workflow.md` —— 远程链路细节 / 坐标系三层结构 / 导出契约 / 调试手段
- `../../addin/F3DToolSkillsEndpoint/` —— 核心 add-in 源码（/ping /exec /reload）
- `../stl-export/` —— 应用 #1（最简范例）
- `../3dprint-bearing/` —— 应用 #2（3D 打印轴承·孔内成型，重量级范例）
