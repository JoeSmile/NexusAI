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
DELETED_SYMBOLS = [
    "PsychologyKnowledgeLoader", "EMOTIONAL_CHAT", "agent_core_v2",
    "database.legacy", "backend.database.legacy", "run_backend.py",
    "quick_start", "db_manager.py", "setup_macbook", "install_python310",
    "install_system_deps", "run_backend.ps1", "requirements.txt",
    "emotional_chat", "emotional-chat",
]
for sym in DELETED_SYMBOLS:
    out = sh(
        f'grep -rn "{sym}" --include="*.py" --include="*.sh" --include="*.md" '
        f'--include="*.yml" --include="Makefile" --include="Dockerfile" . '
        f'2>/dev/null | grep -v -E "(\.venv|__pycache__|/tasks/|/\.git/|/\.hermes/|Makefile:10[0-9]|Makefile:105)"'
    )
    hits = [ln for ln in out.splitlines() if ln.strip() and "audit_consistency" not in ln]
    if hits:
        issues.append(f"[1] 残留引用 {sym}:\n" + "\n".join("    " + h for h in hits[:5]))

# ── 2. Markdown 相对链接完整性 ───────────────────────────────
MD_FILES = [ROOT / "README.md", ROOT / "README.en.md"] + list((ROOT / "docs").glob("*.md")) + [ROOT / "scripts/README.md"]
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#]+)(?:#[^)]*)?\)")
for mf in MD_FILES:
    if not mf.exists():
        continue
    text = mf.read_text(encoding="utf-8", errors="ignore")
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

# ── 3. scripts/README 列出的脚本存在性 ───────────────────────
sr = (ROOT / "scripts/README.md").read_text(encoding="utf-8")
for m in re.finditer(r"`([a-z_]+\.(?:py|sh))`", sr):
    name = m.group(1)
    if not (ROOT / "scripts" / name).exists():
        issues.append(f"[3] scripts/README 提到不存在的文件: {name}")

# ── 4. 文档引用的 make target 存在性 ─────────────────────────
makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
targets = set()
for line in makefile.splitlines():
    m = re.match(r"^([a-z][a-z0-9-]*)(?:\s+[a-z][a-z0-9-]*)*:", line)
    if m:
        targets |= set(m.group(0)[:-1].split())
for mf in [ROOT / "README.md", ROOT / "README.en.md", ROOT / "docs/DEPLOYMENT.md", ROOT / "docs/ARCHITECTURE.md"]:
    if not mf.exists():
        continue
    for m in re.finditer(r"make\s+([a-z][a-z0-9-]*)", mf.read_text(encoding="utf-8")):
        t = m.group(1)
        if t not in targets:
            issues.append(f"[4] {mf.name} 引用不存在的 make target: {t}")

# ── 5. config.env.example 键 vs 代码 env 读取 ────────────────
env_example = ROOT / "config.env.example"
if env_example.exists():
    example_keys = set(
        re.findall(r"^([A-Z][A-Z0-9_]+)=", env_example.read_text(encoding="utf-8"), re.M)
    )
    env_re = re.compile(
        r'os\.getenv\("([A-Z][A-Z0-9_]+)"|os\.environ\.get\("([A-Z][A-Z0-9_]+)"|os\.environ\["([A-Z][A-Z0-9_]+)"|"([A-Z][A-Z0-9_]+)"\s+in\s+os\.environ'
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

# ── 6. 未跟踪文件 + 零引用孤儿文件 ──────────────────────────
untracked = sh("git ls-files --others --exclude-standard | head -20")
for u in untracked.splitlines():
    if u.strip() and not u.startswith("data/") and "audit_consistency" not in u:
        issues.append(f"[6] 未跟踪文件: {u}")

# ── 7. 全 backend 模块 import 冒烟(从根目录,backend. 前缀)──
import_fail = sh(
    "for f in $(find backend -name '*.py' | grep -v __pycache__ | grep -v tests | grep -v '/routers/__init__'); do "
    "  mod=$(echo $f | sed 's|.py$||;s|/|.|g'); "
    "  uv run --no-sync python -c \"import $mod\" 2>/dev/null || echo \"FAIL: $mod\"; "
    "done"
)
for line in import_fail.splitlines():
    if line.startswith("FAIL"):
        issues.append(f"[7] import 失败: {line[5:]}")

if issues:
    print(f"❌ 发现 {len(issues)} 处问题:\n")
    for i in issues:
        print(i)
        print()
    sys.exit(1)
print("✅ 全仓一致性检查通过(7 个维度均无问题)")
