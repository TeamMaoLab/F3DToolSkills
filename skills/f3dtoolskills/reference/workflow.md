# 远程链路细节 / 坐标系 / 导出契约 / 调试

## 架构

```
agent / shell（任意平台）
  │ curl http://127.0.0.1:9099/...        ← 端口 9099，add-in 内建 HTTPServer
  ▼
F3DToolSkillsEndpoint add-in（Fusion 主线程，Python 3.14）
  ├─ /ping           连通性 + Python 版本
  ├─ /reload         热重载 inf3d/common（改 add-in 主模块要 Stop→Run）
  ├─ /exec           注入任意代码，主线程执行（CustomEvent 队列）
  └─ （刻意只有这三个——一切业务能力走 /exec 注入脚本实现）
```

- Fusion 不允许外部进程启动 add-in——安装后必须用户在 ADD-INS 面板手动 Run 一次，
  勾 "Run on Startup" 以后自启。
- WSL → Windows Fusion：`127.0.0.1:9099` 直通（localhost 转发）。
- Windows Fusion 读 WSL 文件走 UNC：`\\wsl.localhost\<distro>\home\...`；
  换 distro 名要改脚本里的 SCHEME_PATH 类常量。

## Fusion 自带 Python

- 位置：Win `%LOCALAPPDATA%\Autodesk\webdeploy\production\<hash>\Python\python.exe`。
  当前版本 **3.14**。
- 外部第三方包要装进它的 site-packages（add-in 目录 `.env` 的 PYTHONPATH 指路）。
- 3.14 与 CPython 常见版本差异大，坑见 `api_pitfalls.md`。

## 坐标系三层结构（导出/摆放的核心）

- **Occurrence**（实例）→ `transform2` 决定实例挂哪、怎么转（世界累乘）。
- **Component**（组件）→ **STL 顶点是 component 局部坐标**（mm）。
- **BRepBody** → 共享 component 坐标系（一个 component 多实体合并 1 个 STL）。
- 网页复原：`mesh.position = world_t_mm`、`mesh.rotation = world_rot(3x3)`（均来自
  transform2 累乘；translation ×10 转 mm）。
- occurrence 会重名（复制组件），必须用 full_path 唯一标识。
- 镜像子树旋转 `[1,-1,-1]`（180°绕X，det=+1 合法）会传递整棵子树。

## /exec 调试手段

```bash
# 快速只读探查（一行代码）
curl -G http://127.0.0.1:9099/exec --data-urlencode \
  "code=import adsk.core as c;app=c.Application.get();_result=app.activeDocument.name"

# 整脚本注入
curl -G http://127.0.0.1:9099/exec --data-urlencode "code@scripts/inspect_sketch.py"
```

- 长任务阻塞 HTTP 响应，curl 加 `--max-time 300`。
- 逆向别人的建模操作：`dump_features.py` / `dump_state_detail.py`（时间线逐特征），
  `inspect_*` 系列只读，不改文档。
- 中招文档别修（参考平面孤儿化、时间线缓存污染），直接开新文档重跑构建脚本更快。

## 验收纪律（三关模板）

```python
def verify(doc):
    # ① 几何读回：bbox / 体积对账 / Torus 圆心 / 孔数 / Z 区间 —— 全部断言
    # ② 幂等：脚本重跑第二遍，结果与第一遍逐位一致（特征清理逻辑正确）
    # ③ 篡改拦截：人为改参数（如孔径），校验必须报 FAIL 而非静默通过
```

体积对账用理论公式（如 Pappus 定理算回转体切量）交叉验证，不信任单一来源。
特征 API 返回成功只是"没报错"，读回几何才是交付证据。

## 标准链路脚手架（设计器 → JSON → Fusion）

1. `designer/*.html`：参数滑杆 + 2D 预览 + `💾 保存方案` 按钮 POST。
2. 使用方项目里的预览服务（如 `server/preview_server.py`）：`POST /save_scheme?name=X.json`
   写 `exports/`（文件名白名单防路径穿越）。
3. `gen_*_from_scheme.py`：Fusion 内经 UNC 读 JSON → 建实体；
   **先做派生量交叉校验**（脚本重算 e/槽径/球位/齿顶/齿根/Z栈 对 JSON `derived`
   回显，漂移硬校验中止）再动几何。
4. 实体读回验收 + 幂等重跑。

参数变更只改设计器，不手抄进脚本（口头手抄流程已多次出错过，全部废弃）。
