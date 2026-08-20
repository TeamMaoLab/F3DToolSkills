# F3DToolSkills 示例应用：导出当前文档全部可见 occurrence 的 STL
#
# 用法（在仓库根目录）：
#   curl -G http://127.0.0.1:9099/exec --data-urlencode "code@examples/export_stl.py"
#
# 契约（F3DToolSkills 应用的标准写法）：
#   - 结果放 _result 变量（/exec 只回传它）
#   - 自包含：不依赖 /exec 持久命名空间里的任何残留变量
#   - 幂等：重复运行只是覆盖同样的输出文件
#   - lightbulb 坑：STL 导出对不可见 occurrence 返回 True 但不写文件，
#     必须临时打通祖先链 isLightBulbOn，finally 恢复，导完用 os.path.exists 校验
#   - 3.14 坑：Occurrence 无 parentOccurrence——祖先链靠自顶向下递归时随身携带

import os
import tempfile

import adsk.core
import adsk.fusion

_app_ex = adsk.core.Application.get()
_des_ex = _app_ex.activeDocument.design
_exp_ex = _app_ex.activeDocument.products.itemByProductType("DesignProductType").exportManager
_out_ex = os.path.join(tempfile.gettempdir(), "f3dtoolskills_exports")
os.makedirs(_out_ex, exist_ok=True)

_exported_ex = []


def _export_occ_ex(occ, ancestors):
    """导出单个 occurrence：临时打通祖先链 lightbulb，finally 恢复。"""
    saved_ex = [(o, o.isLightBulbOn) for o in ancestors]
    for o in ancestors:
        o.isLightBulbOn = True
    try:
        path_ex = os.path.join(
            _out_ex,
            occ.fullPathName.replace("/", "_").replace(":", "_").replace(";", "_") + ".stl")
        opts_ex = _exp_ex.createSTLExportOptions(occ, path_ex)
        opts_ex.sendToPrintUtility = False
        rc_ex = _exp_ex.execute(opts_ex)  # ⚠ 返回值不可信（lightbulb 假阳性）
        _exported_ex.append({
            "occurrence": occ.fullPathName,
            "api_returned": rc_ex,
            "file_ok": os.path.exists(path_ex) and os.path.getsize(path_ex) > 0,
            "stl": path_ex if os.path.exists(path_ex) else None,
        })
    finally:
        for o, s in saved_ex:
            o.isLightBulbOn = s


def _walk_ex(occs, ancestors):
    for i_ex in range(occs.count):
        occ_ex = occs.item(i_ex)
        if occ_ex.isLightBulbOn:  # 尊重用户隐藏的零件，只导可见的
            _export_occ_ex(occ_ex, ancestors)
        _walk_ex(occ_ex.childOccurrences, ancestors + [occ_ex])


_root_ex = _des_ex.rootComponent.occurrences
for _i_ex in range(_root_ex.count):
    _occ_ex = _root_ex.item(_i_ex)
    if _occ_ex.isLightBulbOn:
        _export_occ_ex(_occ_ex, [])
    _walk_ex(_occ_ex.childOccurrences, [_occ_ex])

_result = {
    "out_dir": _out_ex,
    "count": len(_exported_ex),
    "verified_files": sum(1 for e in _exported_ex if e["file_ok"]),
    "exports": _exported_ex,
}
