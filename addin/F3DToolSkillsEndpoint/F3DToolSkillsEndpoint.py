# -*- coding: utf-8 -*-
"""F3DToolSkillsEndpoint (F3DToolSkills) - Fusion 360 驻留型 add-in，开本地 HTTP 服务（线程安全版）。

架构（解决 Fusion API 线程安全问题）：
  - HTTP 服务跑后台线程，只接请求
  - 需要执行的请求（调 Fusion API 的）放入队列
  - 主线程用 adsk.core.TimerEventHandler 定时轮询队列执行
  - 后台线程用 Event 等待主线程完成后返回结果

这样所有 Fusion API 调用都在主线程，不会崩溃。

API:
  GET /ping            → 连通测试（纯 Python，不走队列）
  GET /reload          → 热重载模块缓存（纯 Python，不走队列）
  GET /exec?code=...   → 执行任意代码（走队列，主线程执行）
  GET /export?dir=...  → 参数化导出（走队列，用 F3DMaojocoWin 那套）
  GET /export_assembly?dir=... → 一键导出装配体：STL+世界变换→parts_world.json（走队列，occurrence-centric）
  GET /model           → 查询装配体结构（走队列）
  GET /brep_stats      → BRep 曲面统计（走队列）
  GET /modules         → 列出已加载模块（纯 Python，不走队列）
"""
import os
import sys
import json
import socket
import threading
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import adsk.core
import adsk.fusion

app = adsk.core.Application.get()
ui = app.userInterface

PORT = 9099
# 监听所有网卡的 IP（0.0.0.0）：WSL、局域网都能连。
# 想只允许本机访问改回 '127.0.0.1'。
HOST = '0.0.0.0'


def _local_ips():
    """枚举本机所有 IPv4（含 localhost），用于启动横幅和日志。"""
    ips = ['127.0.0.1']
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith('169.254.'):
                ips.append(ip)
    except Exception:
        pass
    # 顺便抓一下出口网卡 IP（容器 / WSL 友好）
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in ips and not ip.startswith('169.254.'):
            ips.append(ip)
    except Exception:
        pass
    return ips
HOT_RELOAD_PREFIXES = ('inf3d', 'common')
SCRIPT_DIRS = []

_server = None
_server_thread = None

# ============ 主线程任务队列 ============
# 每个 pending: {fn: 可调用, event: threading.Event, result: None/值, error: None/异常}
_pending_tasks = []
_pending_lock = threading.Lock()
# 主线程调度：用 Fusion CustomEvent（notify 在主线程被调用）
_CUSTOM_EVENT_ID = 'F3DToolSkillsEndpointMainTask'
_custom_event = None
_custom_handler = None


def _enqueue_main(fn):
    """把一个函数放入主线程队列，阻塞等待结果。返回 (result, error)。

    后台线程调用此函数 → 放队列 → fireCustomEvent 通知主线程 → 主线程 notify 里执行 → 返回。
    """
    task = {'fn': fn, 'event': threading.Event(), 'result': None, 'error': None}
    with _pending_lock:
        _pending_tasks.append(task)
    # 通知主线程有任务
    app.fireCustomEvent(_CUSTOM_EVENT_ID)
    # 阻塞等待主线程执行完
    task['event'].wait(timeout=120)
    if not task['event'].is_set():
        return None, TimeoutError('主线程 120 秒未执行')
    return task['result'], task['error']


def _drain_queue():
    """主线程：执行所有待处理任务。由 CustomEvent.notify 触发。"""
    with _pending_lock:
        tasks = list(_pending_tasks)
        _pending_tasks.clear()
    for task in tasks:
        try:
            task['result'] = task['fn']()
        except Exception as e:
            task['error'] = e
        task['event'].set()


class _MainTaskHandler(adsk.core.CustomEventHandler):
    """CustomEvent 处理器：notify 在主线程被调用。"""

    def notify(self, args):
        try:
            _drain_queue()
        except Exception:
            pass


# ============ 业务逻辑 ============

def _find_script_dirs():
    here = os.path.dirname(os.path.abspath(__file__))
    dirs = []
    for parent in [here, os.path.dirname(here), os.path.dirname(os.path.dirname(here))]:
        for sub in ['F3DMaojocoWin/F3DMaojocoWin', 'F3DMaojocoScripts']:
            p = os.path.join(parent, sub)
            if os.path.isdir(p) and p not in dirs:
                dirs.append(p)
    return dirs


def _do_hot_reload():
    import importlib, shutil
    to_remove = sorted(
        (k for k in sys.modules
         if any(k == p or k.startswith(p + '.') for p in HOT_RELOAD_PREFIXES)),
        reverse=True
    )
    for key in to_remove:
        mod = sys.modules.get(key)
        if mod is not None:
            try:
                getattr(mod, '__dict__', {}).clear()
            except Exception:
                pass
        sys.modules.pop(key, None)
    try:
        importlib.invalidate_caches()
    except Exception:
        pass
    for d in SCRIPT_DIRS:
        for sub in ('inf3d', 'common'):
            pyc_dir = os.path.join(d, sub, '__pycache__')
            if os.path.isdir(pyc_dir):
                shutil.rmtree(pyc_dir, ignore_errors=True)
    # path 只加 Win 版（绝对导入），移除 Mac 版（相对导入会报错）
    win_dir = next((d for d in SCRIPT_DIRS if 'F3DMaojocoWin' in d), None)
    for d in list(SCRIPT_DIRS):
        if d in sys.path and d != win_dir:
            sys.path.remove(d)
    if win_dir:
        if win_dir in sys.path:
            sys.path.remove(win_dir)
        sys.path.insert(0, win_dir)
    return list(reversed(to_remove))


def _do_exec(code):
    """执行任意代码，返回 _result。在主线程调用。"""
    g = globals()
    g.pop('_result', None)
    exec(code, g)
    return g.get('_result', None)


def _do_export(out_dir, quality):
    """执行导出。在主线程调用。"""
    # 优先用 Win 版（绝对导入），避免 Mac 版相对导入报错
    win_dir = next((d for d in SCRIPT_DIRS if 'F3DMaojocoWin' in d), SCRIPT_DIRS[0] if SCRIPT_DIRS else None)
    if win_dir:
        # 移除其他 F3DMaojoco 脚本目录，防止 Mac 版相对导入干扰
        for d in list(SCRIPT_DIRS):
            if d != win_dir and d in sys.path:
                sys.path.remove(d)
        if win_dir in sys.path:
            sys.path.remove(win_dir)
        sys.path.insert(0, win_dir)
    _do_hot_reload()
    from inf3d.fusion_export_manager import FusionExportManager
    from common.data_types import MeshQuality
    from inf3d.logger import initialize_logging
    os.makedirs(out_dir, exist_ok=True)
    logger = initialize_logging(out_dir)
    mgr = FusionExportManager(mesh_quality=MeshQuality.MEDIUM)
    mgr.set_logger(logger)
    result = mgr.export_assembly(out_dir)
    brep_path = os.path.join(out_dir, 'brep_geometry.json')
    brep_info = None
    if os.path.exists(brep_path):
        brep_info = {'size_kb': round(os.path.getsize(brep_path) / 1024, 0)}
    return {
        'ok': result.success,
        'output_dir': result.output_directory,
        'stl_count': len(result.stl_files) if result.stl_files else 0,
        'brep_geometry': brep_info,
        'error': result.error_message
    }


def _do_export_assembly(out_dir):
    """一键导出装配体：所有可见零件的 STL + 世界变换 → parts_world.json。在主线程调用。

    occurrence-centric 导出（已验证位置正确）：
      - 用 full_path 唯一标识每个 occurrence
      - 过滤 isVisible=False（自动排除废弃/隐藏结构）
      - 每个有实体的 occurrence 导出 STL（component 局部坐标）+ 记录 transform2 世界变换
      - COL_ 开头标记 is_collider（碰撞体，viewer 端自行决定显示）
    """
    import math
    design = app.activeProduct
    if not design or 'Design' not in str(design.objectType):
        return {'ok': False, 'error': '无活动 Design'}
    root = design.rootComponent

    os.makedirs(out_dir, exist_ok=True)
    stl_dir = os.path.join(out_dir, 'stl_files')
    os.makedirs(stl_dir, exist_ok=True)

    def safe_filename(name):
        out = ""
        for ch in name:
            if ch.isalnum() or ch in "._-":
                out += ch
            else:
                out += "_"
        return out

    def mat4(mat):
        a = mat.asArray()
        return [[round(a[i], 6) for i in [0, 1, 2, 3]],
                [round(a[i], 6) for i in [4, 5, 6, 7]],
                [round(a[i], 6) for i in [8, 9, 10, 11]],
                [0, 0, 0, 1]]

    def t_mm(m):
        return [round(m[0][3] * 10, 3), round(m[1][3] * 10, 3), round(m[2][3] * 10, 3)]

    def full_path(o):
        chain = []
        x = o
        while x is not None:
            chain.append(x.name)
            x = x.assemblyContext
        return "/".join(reversed(chain))

    parts = []
    exported = 0
    failed = 0
    skipped_invisible = 0
    used_names = {}
    em = design.exportManager

    def walk(o, depth):
        nonlocal exported, failed, skipped_invisible

        # visibility 过滤：不可见的整个子树跳过；但 COL_ 开头保留（碰撞体约定：碰撞体常被设为不可见）
        try:
            if not o.isVisible and not o.name.startswith('COL'):
                skipped_invisible += 1
                return
        except Exception:
            pass

        comp = o.component
        nb = comp.bRepBodies.count if comp else 0

        # 无实体的容器节点：不导 STL，但继续递归子节点
        if nb == 0:
            for c in o.childOccurrences:
                walk(c, depth + 1)
            return

        fp = full_path(o)
        parent = o.assemblyContext
        parent_fp = full_path(parent) if parent else ""

        # STL 文件名：occurrence 名 + 实例序号去重
        base = safe_filename(o.name)
        if base in used_names:
            used_names[base] += 1
            fname = "{}_{}.stl".format(base, used_names[base])
        else:
            used_names[base] = 1
            fname = "{}.stl".format(base)
        fpath = os.path.join(stl_dir, fname)

        # 世界变换（transform2 已验证正确：累乘 root→此处）
        world = mat4(o.transform2)

        # 导出 STL（occurrence 级，镜像 occurrence 自动导镜像几何）
        ok = False
        try:
            opt = em.createSTLExportOptions(o, fpath)
            try:
                opt.angleTolerance = math.radians(8)
                opt.surfaceTolerance = 0.05
            except Exception:
                pass
            ok = em.execute(opt)
        except Exception:
            ok = False

        if ok:
            exported += 1
            parts.append({
                'full_path': fp,
                'occurrence': o.name,
                'component': comp.name,
                'stl_file': 'stl_files/' + fname,
                'world_t_mm': t_mm(world),
                'world_rot': [world[0][:3], world[1][:3], world[2][:3]],
                'bodies': nb,
                'is_collider': o.name.startswith('COL'),
                'depth': depth,
                'parent': parent_fp,
            })
        else:
            failed += 1
            parts.append({
                'full_path': fp,
                'occurrence': o.name,
                'component': comp.name,
                'stl_file': None,
                'error': 'STL导出失败',
                'world_t_mm': t_mm(world),
                'world_rot': [world[0][:3], world[1][:3], world[2][:3]],
                'bodies': nb,
                'is_collider': o.name.startswith('COL'),
                'depth': depth,
                'parent': parent_fp,
            })

        for c in o.childOccurrences:
            walk(c, depth + 1)

    for o in root.occurrences:
        walk(o, 0)

    # 写 parts_world.json（格式和 quad_stl_viewer.html 一致）
    out_path = os.path.join(out_dir, 'parts_world.json')
    out_data = {
        'document': app.activeDocument.name if app.activeDocument else '?',
        'count': len(parts),
        'stl_ok': exported,
        'stl_failed': failed,
        'skipped_invisible': skipped_invisible,
        'note': 'occurrence-centric 导出。STL顶点=component局部坐标(mm)，加载时用 world_t_mm+world_rot 摆放。is_collider 标记碰撞体(COL_)。',
        'parts': parts,
    }
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out_data, f, ensure_ascii=False, indent=1)

    return {
        'ok': True,
        'document': out_data['document'],
        'output_dir': out_dir,
        'parts': len(parts),
        'stl_ok': exported,
        'stl_failed': failed,
        'skipped_invisible': skipped_invisible,
        'colliders': sum(1 for p in parts if p.get('is_collider')),
        'parts_world_json': out_path,
    }


def _do_model():
    """查询装配体结构。在主线程调用。"""
    design = app.activeProduct
    if not design or 'Design' not in str(design.objectType):
        return {'ok': False, 'error': '无活动 Design'}
    root = design.rootComponent
    parts = []
    joint_count = [0]

    def visit(occ, depth=0):
        comp = occ.component
        if not comp or comp.name.startswith('COL_'):
            return
        face_types = {}
        if comp.bRepBodies.count > 0:
            for bi in range(comp.bRepBodies.count):
                body = comp.bRepBodies.item(bi)
                for face in body.faces:
                    geo = face.geometry
                    if geo:
                        t = geo.objectType.split('::')[-1]
                        face_types[t] = face_types.get(t, 0) + 1
        parts.append({
            'name': comp.name, 'occurrence': occ.name,
            'bodies': comp.bRepBodies.count,
            'faces': sum(face_types.values()),
            'surface_types': face_types if face_types else None,
            'depth': depth,
        })
        joint_count[0] += comp.joints.count
        for child in occ.childOccurrences:
            visit(child, depth + 1)

    for occ in root.occurrences:
        visit(occ)
    return {
        'ok': True,
        'document': app.activeDocument.name if app.activeDocument else '无',
        'root': root.name,
        'parts': parts, 'part_count': len(parts),
        'joint_count': joint_count[0],
    }


def _do_brep_stats():
    """BRep 曲面统计。在主线程调用。"""
    design = app.activeProduct
    if not design:
        return {'ok': False, 'error': '无活动 Design'}
    root = design.rootComponent
    type_stats = {}
    total_faces = [0]
    part_count = [0]

    def visit(occ):
        comp = occ.component
        if not comp or comp.name.startswith('COL_'):
            return
        if comp.bRepBodies.count == 0:
            for c in occ.childOccurrences:
                visit(c)
            return
        part_count[0] += 1
        for bi in range(comp.bRepBodies.count):
            body = comp.bRepBodies.item(bi)
            for face in body.faces:
                geo = face.geometry
                if geo:
                    t = geo.objectType.split('::')[-1]
                    type_stats[t] = type_stats.get(t, 0) + 1
                    total_faces[0] += 1
        for c in occ.childOccurrences:
            visit(c)

    for occ in root.occurrences:
        visit(occ)
    tf = total_faces[0]
    sorted_types = sorted(type_stats.items(), key=lambda x: -x[1])
    return {
        'ok': True, 'total_faces': tf, 'part_count': part_count[0],
        'surface_types': {t: n for t, n in sorted_types},
        'regular_pct': round(
            sum(n for t, n in type_stats.items()
                if t in ('Plane', 'Cylinder', 'Cone', 'Sphere', 'Torus'))
            / max(tf, 1) * 100, 1),
    }


# ============ 主页（自包含，亮暗双主题） ============

def _load_home():
    """外置 home.html 优先（改完浏览器刷新即生效），缺文件时用内嵌兜底。"""
    import os as _o
    here = _o.path.dirname(_o.path.abspath(__file__))
    for cand in (_o.path.join(here, 'home.html'),):
        try:
            with open(cand, encoding='utf-8') as f:
                return f.read()
        except Exception:
            pass
    return _HOME_PAGE

_HOME_PAGE = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>F3DToolSkills Endpoint</title><style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#1c2128;--sub:#5a6472;--line:#e3e6ea;--acc:#3b82f6;--ok:#16a34a}
html.dark{--bg:#111418;--card:#1a1f26;--fg:#e6e9ee;--sub:#8b94a1;--line:#2a313a;--acc:#60a5fa;--ok:#4ade80}
*{box-sizing:border-box}body{margin:0;font:14px/1.6 system-ui,'Segoe UI','Microsoft YaHei';background:var(--bg);color:var(--fg);transition:background .2s}
.wrap{max-width:720px;margin:0 auto;padding:32px 20px}
header{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px}
h1{font-size:18px;margin:0;display:flex;align-items:center;gap:10px}
.dot{width:9px;height:9px;border-radius:50%;background:var(--ok);box-shadow:0 0 8px var(--ok);animation:p 2s infinite}
@keyframes p{50%{opacity:.5}}
.theme{cursor:pointer;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:8px;padding:5px 12px;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.k{color:var(--sub);font-size:12px} .v{font-size:15px;font-weight:600;margin-top:2px}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}
h2{font-size:14px;margin:0 0 10px;color:var(--sub);font-weight:600}
textarea{width:100%;min-height:72px;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:10px;font:13px/1.5 Consolas,monospace;resize:vertical}
.row{display:flex;gap:10px;margin-top:10px;flex-wrap:wrap}
button{cursor:pointer;border:0;border-radius:8px;padding:8px 16px;font-size:13px;font-weight:600}
.run{background:var(--acc);color:#fff} .ghost{background:transparent;border:1px solid var(--line);color:var(--fg)}
pre{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:10px;font:12px/1.5 Consolas,monospace;overflow:auto;max-height:240px;white-space:pre-wrap}
a{color:var(--acc);text-decoration:none} .hint{color:var(--sub);font-size:12px}
</style></head><body><div class="wrap">
<header><h1><span class="dot"></span>F3DToolSkills Endpoint</h1>
<button class="theme" onclick="tg()">🌙 / ☀️</button></header>
<div class="grid">
<div class="card"><div class="k">Fusion</div><div class="v" id="v-fusion">…</div></div>
<div class="card"><div class="k">Python</div><div class="v" id="v-py">…</div></div>
<div class="card"><div class="k">端口</div><div class="v">127.0.0.1:9099</div></div>
<div class="card"><div class="k">活动文档</div><div class="v" id="v-doc">…</div></div>
</div>
<section><h2>快捷注入（/exec）</h2>
<textarea id="code">import adsk.core as c
_result = c.Application.get().activeDocument.name</textarea>
<div class="row"><button class="run" onclick="run()">▶ 执行</button>
<span class="hint" style="align-self:center">结果看 _result 变量；print 不回传</span></div>
<pre id="out" style="display:none"></pre></section>
<section><h2>产出</h2>
<div class="row"><a href="/report"><button class="ghost">📄 最新构建报告</button></a></div>
<div class="hint" style="margin-top:8px">报告由 3dprint-bearing 等应用生成，每次构建自动更新。</div></section>
<div class="hint">TeamMaoLab · <a href="https://github.com/TeamMaoLab/F3DToolSkills" target="_blank">GitHub</a> · 本服务只绑定本机回环，勿转发公网</div>
</div>
<script>
const d=document.documentElement,ls=localStorage;
if(ls.theme==='dark'||(!ls.theme&&matchMedia('(prefers-color-scheme: dark)').matches))d.classList.add('dark');
function tg(){d.classList.toggle('dark');ls.theme=d.classList.contains('dark')?'dark':'light'}
fetch('/ping').then(r=>r.json()).then(j=>{document.getElementById('v-py').textContent='Python '+j.python});
fetch('/exec?code='+encodeURIComponent('import adsk.core as c;a=c.Application.get();_result=(a.activeDocument.name)'))
 .then(r=>r.json()).then(j=>{document.getElementById('v-doc').textContent=j.result||'—'});
document.getElementById('v-fusion').textContent='Fusion 360';
function run(){const c=document.getElementById('code').value,o=document.getElementById('out');
o.style.display='block';o.textContent='执行中…';
fetch('/exec?code='+encodeURIComponent(c)).then(r=>r.json())
 .then(j=>o.textContent=JSON.stringify(j,null,2)).catch(e=>o.textContent='错误: '+e)}
</script></body></html>"""



# ============ HTTP Handler ============

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False, indent=2, default=str).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        """POST /exec —— 长/含特殊字符脚本用 POST，无 URL 长度限制。
        Body 三种形态任选：
          1. 纯文本 body 即代码（Content-Type: text/plain 或无类型）
          2. JSON {"code": "..."}
          3. 表单 code=...（curl --data-urlencode "code@script.py" 默认形态）
        """
        parsed = urlparse(self.path)
        if parsed.path != '/exec':
            self._json({'ok': False, 'error': f'POST 只支持 /exec，收到 {parsed.path}'}, 404)
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
            raw = self.rfile.read(length).decode('utf-8', 'replace') if length else ''
            ctype = (self.headers.get('Content-Type') or '').lower()
            code = ''
            if 'json' in ctype:
                try:
                    code = json.loads(raw).get('code', '')
                except Exception:
                    self._json({'ok': False, 'error': 'JSON body 解析失败'}, 400)
                    return
            elif 'form' in ctype:
                code = parse_qs(raw).get('code', [''])[0]
            else:
                code = raw  # 纯文本
            if not code:
                self._json({'ok': False, 'error': 'body 为空或不含 code'}, 400)
                return
            result, error = _enqueue_main(lambda: _do_exec(code))
            if error:
                self._json({'ok': False, 'error': str(error),
                            'traceback': traceback.format_exc()}, 500)
            else:
                self._json({'ok': True, 'result': result})
        except Exception:
            self._json({'ok': False, 'error': traceback.format_exc(limit=5)}, 500)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        try:
            # ---- 主页（插件控制面板）----
            if path == '/' or path == '/index.html':
                _body = _load_home().encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(_body)))
                self.end_headers()
                self.wfile.write(_body)

            # ---- 报告伺服（HTML 直出，给 agent 客户端 webview 用）----
            if path == '/report':
                _home = os.path.expanduser('~')
                _cands = [
                    os.path.join(_home, 'Desktop', 'bearing_report.html'),
                    os.path.join(_home, 'OneDrive', 'Desktop', 'bearing_report.html'),
                    os.path.join(os.environ.get('TEMP', '/tmp'), 'f3d_reports',
                                 'bearing_report.html'),
                ]
                _rp = next((p for p in _cands if os.path.isfile(p)), None)
                if not _rp:
                    self._json({'ok': False,
                                'error': '尚无报告：先跑一次 gen_bearing_full.py'}, 404)
                    return
                with open(_rp, encoding='utf-8') as _rf:
                    _body = _rf.read().encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(_body)))
                self.end_headers()
                self.wfile.write(_body)

            # ---- 纯 Python 端点（不走队列，后台线程直接执行）----
            if path == '/ping':
                self._json({'ok': True, 'msg': 'F3DToolSkillsEndpoint 运行中',
                            'python': sys.version.split()[0],
                            'thread_safe': True})

            elif path == '/reload':
                removed = _do_hot_reload()
                self._json({'ok': True, 'cleared': len(removed),
                            'modules': removed[:20], 'script_dirs': SCRIPT_DIRS})

            elif path == '/modules':
                ours = sorted(k for k in sys.modules
                              if any(k == p or k.startswith(p + '.') for p in HOT_RELOAD_PREFIXES))
                self._json({'ok': True, 'count': len(ours), 'modules': ours})

            # ---- Fusion API 端点（走队列，主线程执行）----
            elif path == '/exec':
                code = params.get('code', [''])[0]
                if not code:
                    self._json({'ok': False, 'error': '缺少 code 参数'}, 400)
                    return
                result, error = _enqueue_main(lambda: _do_exec(code))
                if error:
                    self._json({'ok': False, 'error': str(error),
                                'traceback': traceback.format_exc()}, 500)
                else:
                    self._json({'ok': True, 'result': result})

            elif path == '/export':
                out_dir = params.get('dir', [''])[0]
                if not out_dir:
                    self._json({'ok': False, 'error': '缺少 dir 参数'}, 400)
                    return
                quality = int(params.get('quality', ['15'])[0])
                result, error = _enqueue_main(lambda: _do_export(out_dir, quality))
                if error:
                    self._json({'ok': False, 'error': str(error),
                                'traceback': traceback.format_exc()}, 500)
                else:
                    self._json(result)

            elif path == '/export_assembly':
                out_dir = params.get('dir', [''])[0]
                if not out_dir:
                    self._json({'ok': False, 'error': '缺少 dir 参数'}, 400)
                    return
                result, error = _enqueue_main(lambda: _do_export_assembly(out_dir))
                if error:
                    self._json({'ok': False, 'error': str(error),
                                'traceback': traceback.format_exc()}, 500)
                else:
                    self._json(result)

            elif path == '/model':
                result, error = _enqueue_main(_do_model)
                self._json(result if not error else {'ok': False, 'error': str(error)})

            elif path == '/brep_stats':
                result, error = _enqueue_main(_do_brep_stats)
                self._json(result if not error else {'ok': False, 'error': str(error)})

            else:
                self._json({'ok': False, 'error': '未知路径: ' + path,
                            'routes': ['/', '/ping', '/report', '/exec?code=',
                                       '/reload', '/modules']}, 404)

        except Exception as e:
            self._json({'ok': False, 'error': str(e), 'traceback': traceback.format_exc()}, 500)


# ============ 启动/停止 ============

def _start_server():
    global _server, _server_thread
    _server = HTTPServer((HOST, PORT), Handler)
    _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _server_thread.start()


def run(context):
    global SCRIPT_DIRS, _custom_event, _custom_handler
    try:
        SCRIPT_DIRS = _find_script_dirs()
        _start_server()
        # 注册 CustomEvent（主线程调度）
        _custom_event = app.registerCustomEvent(_CUSTOM_EVENT_ID)
        _custom_handler = _MainTaskHandler()
        _custom_event.add(_custom_handler)
        ips = _local_ips()
        urls = '\n'.join(f'  http://{ip}:{PORT}/ping' for ip in ips)
        msg = (f'F3DToolSkillsEndpoint 运行中 @ {HOST}:{PORT}\n'
               f'可达地址:\n{urls}\n'
               f'线程安全模式（CustomEvent 主线程调度）\n'
               f'脚本目录: {SCRIPT_DIRS}')
        ui.palettes.itemById('TextCommands').writeText(msg)
    except Exception:
        ui.messageBox('F3DToolSkillsEndpoint 启动失败:\n{}'.format(traceback.format_exc()))


def stop(context):
    global _server, _custom_event, _custom_handler
    if _server:
        _server.shutdown()
        _server = None
    if _custom_event and _custom_handler:
        _custom_event.remove(_custom_handler)
        _custom_handler = None
    if _custom_event:
        app.unregisterCustomEvent(_CUSTOM_EVENT_ID)
        _custom_event = None
