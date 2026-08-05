#!/usr/bin/env python3
"""全仓一致性终检 — 一次性审计(机械扫漏网之鱼)

维度:
1. 已删文件/已改名符号的残留引用
2. Markdown 相对链接完整性(README / docs / scripts/README)
3. scripts/README 列出的文件是否存在
4. 文档里引用的 make target 是否存在
5. config.env.example 键名 vs 代码读取的 env 键名
6. git 未跟踪文件 / 零引用孤儿文件
7. 全 backend 模块 import 冒烟
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
issues: list[str] = []


def sh(cmd: str) -> str:
    r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True)
    return r.stdout + r.stderr


# ── 1. 已删文件/已改名符号残留 ──────────────────────────────
print("▶ 1/7 残留符号扫描...", flush=True)
# 情绪/情感功能已整体移除(2026-08),相关符号不再检查;若未来 reintroduce 另行添加
DELETED_SYMBOLS = [
    "agent_core_v2",
    "database.legacy", "backend.database.legacy", "run_backend.py",
    "quick_start", "db_manager.py", "setup_macbook", "install_python310",
    "install_system_deps", "run_backend.ps1", "requirements.txt",
]
# 单次 grep 扫全部符号(避免每个符号一个子进程);排除 .venv/.git 目录减少遍历
alt = " -e ".join(f'"{s}"' for s in DELETED_SYMBOLS)
out = sh(
    f'grep -rn --exclude-dir=.venv --exclude-dir=.git --exclude-dir=__pycache__ '
    f'--include="*.py" --include="*.sh" --include="*.md" '
    f'--include="*.yml" --include="Makefile" --include="Dockerfile" '
    f'-e {alt} . 2>/dev/null | grep -vE "/tasks/|/\\.hermes/"'
)
for ln in out.splitlines():
    if not ln.strip() or "audit_consistency" in ln or "/Makefile:" in ln:
        continue  # Makefile verify 守卫是故意的防御检查,排除
    sym = next((s for s in DELETED_SYMBOLS if s in ln), "?")
    issues.append(f"[1] 残留引用 {sym}: {ln}")
print("   ✅ 第 1 维完成", flush=True)

# ── 2. Markdown 相对链接完整性 ───────────────────────────────
print("▶ 2/7 Markdown 链接检查...", flush=True)
MD_FILES = [ROOT / "README.md", ROOT / "README.en.md"] + list((ROOT / "docs").glob("*.md")) + [ROOT / "scripts/README.md"]
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#]+)(?:#[^)]*)?\)")
for mf in MD_FILES:
    if not mf.exists():
        continue
    text = mf.read_text(encoding="utf-8")
    for m in LINK_RE.finditer(text):
        target = m.group(1).strip()
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        # 相对链接按所在文件目录解析
        resolved = (mf.parent / target).resolve()
        # 允许指向仓库根或 docs 等
        try:
            resolved.relative_to(ROOT)
        except ValueError:
            continue
        if not resolved.exists():
            issues.append(f"[2] 断链 {mf.relative_to(ROOT)} → {target}")
print("   ✅ 第 2 维完成", flush=True)

# ── 3. scripts/README 列出的脚本存在性 ───────────────────────
print("▶ 3/7 scripts/README 脚本存在性...", flush=True)
sr = (ROOT / "scripts/README.md").read_text(encoding="utf-8")
for m in re.finditer(r"`([a-z_]+\.(?:py|sh))`", sr):
    name = m.group(1)
    if not (ROOT / "scripts" / name).exists():
        issues.append(f"[3] scripts/README 提到不存在的文件: {name}")
print("   ✅ 第 3 维完成", flush=True)

# ── 4. 文档引用的 make target 存在性 ─────────────────────────
print("▶ 4/7 make target 引用检查...", flush=True)
makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
targets = set()
for line in makefile.splitlines():
    m = re.match(r"^([a-z][a-z0-9-]*)(?:\s+[a-z][a-z0-9-]*)*:", line)
    if m:
        targets |= set(m.group(0)[:-1].split())
for mf in [ROOT / "README.md", ROOT / "README.en.md", ROOT / "docs/DEPLOYMENT.md", ROOT / "docs/ARCHITECTURE.md"]:
    if not mf.exists():
        continue
    for t in re.findall(r"`make ([a-z0-9-]+)`", mf.read_text(encoding="utf-8")):
        if t not in targets:
            issues.append(f"[4] {mf.name} 引用不存在的 make target: {t}")
print("   ✅ 第 4 维完成", flush=True)

# ── 5. config.env.example 键 vs 代码 env 读取 ────────────────
print("▶ 5/7 env 键一致性检查...", flush=True)
env_example = ROOT / "config.env.example"
if env_example.exists():
    example_keys = set(
        re.findall(r"^([A-Z][A-Z0-9_]+)=", env_example.read_text(encoding="utf-8"), re.M)
    )
    env_re = re.compile(
        r'os\.getenv\("([A-Z][A-Z0-9_]+)"|os\.environ\.get\("([A-Z][A-Z0-9_]+)"|os\.environ\["([A-Z][A-Z0-9_]+)"|"([A-Z][A-Z0-9_]+)"\s+in\s+os\.environ|_env_(?:bool|int|float)\("([A-Z][A-Z0-9_]+)"'
    )
    code_envs = set()
    for p in list((ROOT / "backend").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py")) + [ROOT / "config.py"]:
        try:
            for m in env_re.finditer(p.read_text(encoding="utf-8")):
                code_envs.add(next(g for g in m.groups() if g))
        except Exception:
            pass
    # pydantic-settings: config.py Settings 字段名自动映射 env(大小写不敏感)
    cfg = (ROOT / "config.py").read_text(encoding="utf-8")
    for m in re.finditer(r"^    ([a-z][a-z0-9_]*):\s*(?:str|bool|int|float)", cfg, re.M):
        code_envs.add(m.group(1).upper())
    missing_in_code = example_keys - code_envs
    if missing_in_code:
        issues.append(f"[5] config.env.example 有但代码没读的键: {sorted(missing_in_code)}")
print("   ✅ 第 5 维完成", flush=True)

# ── 6. 未跟踪文件 + 零引用孤儿文件 ──────────────────────────
print("▶ 6/7 未跟踪/孤儿文件检查...", flush=True)
untracked = sh("git ls-files --others --exclude-standard | head -20")
for u in untracked.splitlines():
    if u.strip() and not u.startswith("data/") and "audit_consistency" not in u:
        issues.append(f"[6] 未跟踪文件: {u}")
print("   ✅ 第 6 维完成", flush=True)

# ── 7. 全 backend 模块 import 冒烟(单进程,秒级)──────────────
print("▶ 7/7 全模块 import 冒烟(单进程)...", flush=True)
# 单进程内遍历 import: 比逐模块起 uv 子进程快一个数量级;模块级依赖传递已覆盖绝大多数
import_fail = sh(
    "uv run --no-sync python -c \""
    "import sys; from pathlib import Path; "
    "mods=[]; "
    "[mods.append(str(p.relative_to('backend')).replace('.py','').replace('/','.')) "
    "for p in Path('backend').rglob('*.py') "
    "if '__pycache__' not in str(p) and 'tests' not in str(p) and p.name != '__init__.py']; "
    "fails=[]; "
    "for m in mods: "
    "  try: __import__('backend.'+m) "
    "  except Exception as e: fails.append(m+' -> '+type(e).__name__+': '+str(e)[:80]); "
    "print('FAILS:' + '|'.join(fails) if fails else 'ALL_OK'); "
    "sys.exit(0)\""
)
if "ALL_OK" not in import_fail:
    for item in import_fail.replace("FAILS:", "").split("|"):
        if item.strip():
            issues.append(f"[7] import 失败: {item.strip()}")
print("   ✅ 第 7 维完成", flush=True)

if issues:
    print(f"❌ 发现 {len(issues)} 处问题:\n")
    for i in issues:
        print(i)
        print()
    sys.exit(1)
print("✅ 全仓一致性检查通过(7 个维度均无问题)")
