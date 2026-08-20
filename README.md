# F3DToolSkills

> TeamMaoLab 出品 · 作者 maoge

**在 Fusion 360 里开一个可注入脚本的 exec 端点，把整个 Fusion Python 环境交给 AI。**

## 哲学

一句话：**把 CAD 软件变成 AI 的解释器，而不是给 AI 写一堆 CAD 工具。**

1. **端点即插座，能力即脚本。** 底座只做一件事：开一个 `/exec` 注入端点，不预设任何
   业务端点。「注入」比「API」高一个自由度：API 是开发者替用户枚举可能性，注入是让
   agent 自己组合可能性。
2. **探索优先于文档。** 面对没做过的任务，agent 不背文档，当场问 Fusion 本人：
   `dir()` 探签名、读选中对象、小步试验。坑位表是探索的沉淀，不是探索的替代。
3. **应用以 skill 沉淀，不以代码膨胀。** 插件长大靠 `skills/` 下多一个目录
   （SKILL.md + 注入脚本 + 设计器），不靠 add-in 多一个端点。底座永远不增重。
4. **装我的前提是有 agent，所以 agent 就是安装器。** 没有 bootstrap 脚本、不要求本机
   Python——SKILL.md 里的安装规范就是给 agent 的行为指令。分发退化成一句话：
   「帮我装 TeamMaoLab/F3DToolSkills」。
5. **特征成功 ≠ 几何正确，必须留下证据。** 一切生成必须读回几何证据（实体顶点/面型/
   面积/幂等重跑）才算交付。AI 时代 CAD 最危险的不是不会建，是「以为建对了」。
6. **程序化 ≠ 不可回溯。** 机器建的模型也要人能读懂：草图全构造线、特征语义命名、
   每个尺寸回溯到公式。AI 生成的东西不能变成黑盒。

只保留一句对外的话：**「底座自由可探索，应用可拓展」——前半句是我们给的自由，
后半句是我们守的秩序。**

## 两个卖点

### 1. 底座自由可探索

F3DToolSkills 的最终能力只有一个：利用 Fusion 自带的 Python 环境，开启一个
**`/exec` 脚本注入端点**（本地 HTTP，端口 9099）。有了这个底座，AI agent 可以——

- **探索**：任意一行 Python 即可探测 Fusion 的实时状态（文档/时间线/选中体/API 能力），
  做不到先发现、再设计、再验证，而不是照着过时文档瞎猜；
- **自由**：不预设「能做什么」。建实体、掏轴承、摆线齿轮、导出 STL、逆向别人的建模
  操作——全是注入脚本的即时产物，底座本身零业务逻辑；
- **可信**：注入在 Fusion 主线程执行（CustomEvent 调度），附 Python 3.14 API 坑位表
  和「实体读回验收」纪律，让 AI 的每一步都有几何证据。

```bash
curl -G http://127.0.0.1:9099/exec \
  --data-urlencode "code=import adsk.core as c;a=c.Application.get();_result=(a.activeDocument.name, a.activeDocument.design.designType)"
```

### 2. 应用可拓展

摆线针轮减速器、孔内成型 3D 打印轴承、装配体一键导出——这些都**不是底座的一部分**，
而是跑在底座上的应用范例。每个应用 = 一组「设计器 → 方案 JSON → 注入脚本 → 实体验收」
的参数化链路，写成独立的领域 skill 即可挂进来，互不依赖：

```
┌─────────────────────────────────────────────┐
│  应用层（可拓展）：摆线减速器 / 孔内轴承 /    │
│  装配导出 / 你的下一个 idea ……               │
├─────────────────────────────────────────────┤
│  方法论层：API 坑位表 / 幂等构建 / 验收三关   │
├─────────────────────────────────────────────┤
│  底座：F3DToolSkillsEndpoint add-in               │
│  Fusion Python 环境 + /exec 注入端点 (:9099) │
└─────────────────────────────────────────────┘
```

本仓库自带的方法论 skill 展示了「在底座上干活应该守什么规矩」；
写应用时不写新 add-in，写**注入脚本**——底座 `/exec` 一打，能力即达。

## 分发形态：一句话安装

> **"帮我安装 GitHub 上的这个 Fusion AI 插件：TeamMaoLab/F3DToolSkills"**

就这一句，不需要任何命令。agent 收到后（ZCode/Claude 兼容 plugin，`.zcode-plugin/plugin.json`）：

1. 从 Plugin Management（或直接 `git clone`）装上插件——底座 skill（`skills/f3dtoolskills/`）
   随插件就位，从此 Fusion 相关任务自动触发它；
2. 底座 skill 里是一份 **agent 可直接执行的安装规范**（定位 AddIns 目录 → `cp` 复制
   add-in → curl 探活 → 引导用户在 ADD-INS 面板 Run）。不依赖用户本机 Python——
   有 agent 在，agent 自己就是安装器；
3. 结束。此后 `curl http://127.0.0.1:9099/ping` 通了，整个 Fusion 就是 agent 的游乐场。

## 应用沉淀（插件怎么长大）

好用的能力以**应用 skill** 形式沉淀进 `skills/`，每个应用一个目录：

```
skills/<应用名>/
├── SKILL.md      # 触发条件 + 用法
├── scripts/      # 注入脚本（自包含、幂等、_result 契约）
└── *.html        # 可选：参数化设计器/预览页
```

内置应用：
- `skills/stl-export/` —— STL 批量导出（最简应用范例）
- `skills/3dprint-bearing/` —— **3D 打印轴承**·孔内成型（重量级应用：打印后即可转动的
  一体轴承，clr 打印间隙配方/钢球标准件/no3dprint 导出打印全链路；840 行生成脚本 +
  强制几何验收 + 网页设计器 + 配方文档，实战踩坑全量沉淀）

**你自己的流程也能这样沉淀**：对 agent 说「把这个流程沉淀成 skill」，它会按底座 skill
里的沉淀规范替你办——问清触发词/输入契约/产出，把流程固化成守纪律的注入脚本
（自包含、幂等、`_result` 契约、读回验收），写好 SKILL.md，放进你自己的
`~/.agents/skills/`（个人，跨插件升级存活）或提 PR 回 `skills/`（贡献给社区）。
内置的两个应用就是活范例——**应用=注入脚本，永远不新增端点**。

## 组成

| 路径 | 层 | 内容 |
|---|---|---|
| `addin/F3DToolSkillsEndpoint/` | 底座 | 核心 add-in：`/ping` `/exec` `/reload`（零业务逻辑） |
| `skills/f3dtoolskills/SKILL.md` | 方法论 | 给 agent 的探索工作流 + 工程纪律 |
| `skills/f3dtoolskills/reference/api_pitfalls.md` | 方法论 | Fusion Python 3.14 API 坑位表（每条附正确写法） |
| `skills/f3dtoolskills/reference/workflow.md` | 方法论 | 远程链路架构、坐标系三层结构、导出契约、调试 |

## 快速开始

对 agent 说「帮我安装 TeamMaoLab/F3DToolSkills」，它会按底座 skill 的安装规范执行：
curl 探活 → 定位 AddIns 目录 → `cp` 复制 add-in → 引导你在 Fusion 的
ADD-INS 面板 Run 一次（Fusion 不允许外部进程启动 add-in，这是唯一需要人手的一步）。
**全程不依赖用户本机 Python。**

装好后验证与使用（任何能发 HTTP 的东西都行）：

```bash
curl http://127.0.0.1:9099/ping

# 远程执行任意 Fusion Python（结果放 _result 变量回传）
curl -G http://127.0.0.1:9099/exec \
  --data-urlencode "code=import adsk.core as c;_result=c.Application.get().activeDocument.name"

# 复杂能力（如装配体导出）不写新端点，注入整段脚本即可（见 skills/stl-export）
```

## 安全提示

`/exec` 等价于「任何能访问本机 9099 端口的进程都能在 Fusion 里执行任意 Python」。
add-in 只绑定本地回环，**不要**把它端口转发到公网。

## 已验证平台

- Windows 11 + WSL2（agent 在 WSL，Fusion 在 Windows：`127.0.0.1:9099` 直通，
  Fusion 读 WSL 文件走 `\\wsl.localhost\<distro>\...` UNC）
- Fusion 360 Python 3.14（manifest `supportedOS: windows|mac`，mac 路径已适配未实测）

## License

MIT — 见 [LICENSE](LICENSE)。
