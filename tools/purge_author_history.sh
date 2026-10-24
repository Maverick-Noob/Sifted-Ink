#!/usr/bin/env bash
#
# 从 git 历史中彻底清除 writing_style.json（183 位作家风格库）
#
# 背景：该文件此前已提交过，虽然当前工作树与所有新提交都不再包含它，
# 但它仍完整存在于公开仓库的历史提交里。该文件含 171 位非公版（多数在世）
# 作家信息，属于需要清理的合规负债。
#
# 本脚本做四件事：
#   1. 再做一次备份（bundle + 目录副本）
#   2. 用 git filter-branch --index-filter 重写 dev/main/origin-dev/origin-main
#   3. 清掉 refs/original、reflog、悬空对象
#   4. 用 --force-with-lease 强制推送并校验远端
#
# 用法（在仓库根目录执行）：
#     bash tools/purge_author_history.sh
#
# ⚠️ 这会改写所有提交的 SHA。远端必须 force push。
#    如果有人 clone 过这个仓库，他们的本地历史会与远端不一致，需要重新 clone。
#    当前仓库 star/fork 极少（1 star / 0 fork），是执行此操作的最佳窗口。
#
set -euo pipefail

TARGET="writing_style.json"
REFS=(dev main origin/dev origin/main)
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$(cd .. && pwd)/sifted-ink-backup-${STAMP}"

echo "=============================================================="
echo " 清除 git 历史中的 ${TARGET}"
echo " 仓库: $(pwd)"
echo " 受影响 ref: ${REFS[*]}"
echo "=============================================================="
echo

# ── 0. 前置检查 ────────────────────────────────────────────────────────
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "✗ 不在 git 仓库里"; exit 1
fi

if ! git log --all --oneline -- "${TARGET}" | grep -q .; then
  echo "✓ 历史中已不存在 ${TARGET}，无需清洗。"; exit 0
fi

echo "待清除的提交："
git log --all --oneline -- "${TARGET}" | sed 's/^/    /'
echo

# ── 1. 备份 ────────────────────────────────────────────────────────────
echo "[1/5] 创建备份 …"
mkdir -p "${BACKUP_DIR}"
git bundle create "../sifted-ink-pre-purge-${STAMP}.bundle" --all 2>/dev/null || true
cp -r . "${BACKUP_DIR}/repo" 2>/dev/null || true
echo "    备份目录 : ${BACKUP_DIR}/repo"
echo "    bundle   : ../sifted-ink-pre-purge-${STAMP}.bundle"
echo

# ── 2. 重写历史 ────────────────────────────────────────────────────────
echo "[2/5] 重写历史（filter-branch）…"
FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch --force \
  --index-filter "git rm --cached --ignore-unmatch ${TARGET}" \
  --prune-empty \
  --tag-name-filter cat \
  -- "${REFS[@]}" 2>&1 | tail -8
echo

# ── 3. 清理残留 ────────────────────────────────────────────────────────
echo "[3/5] 清理 refs/original、reflog 与悬空对象 …"
rm -rf .git/refs/original/
git reflog expire --expire=now --all
git gc --prune=now --quiet
git remote set-url origin "$(git remote get-url origin)"
echo "    完成"
echo

# ── 4. 本地校验 ────────────────────────────────────────────────────────
echo "[4/5] 校验本地历史 …"
if git log --all --oneline -- "${TARGET}" | grep -q .; then
  echo "✗ 仍能在历史中找到 ${TARGET}，中止推送"; exit 1
fi
if git rev-list --all --objects | grep -q "${TARGET}"; then
  echo "✗ 对象库中仍有 ${TARGET}，中止推送"; exit 1
fi
echo "    ✓ 历史与对象库中均已无 ${TARGET}"
echo "    当前历史："
git log --oneline --all | head -8 | sed 's/^/        /'
echo

# ── 5. 强制推送 ────────────────────────────────────────────────────────
echo "[5/5] 强制推送到远端 …"
git push --force-with-lease origin dev
git push --force-with-lease origin main
echo

echo "=============================================================="
echo " ✓ 完成"
echo "=============================================================="
echo "远端校验（可手动执行）："
echo "    git fetch origin"
echo "    git log --all --oneline -- ${TARGET}   # 应无输出"
echo "    git rev-list --all --objects | grep ${TARGET}   # 应无输出"
echo
echo "备份位置（确认无误后可删除）："
echo "    ${BACKUP_DIR}"
echo "    ../sifted-ink-pre-purge-${STAMP}.bundle"
echo
echo "提醒：若有他人 clone 过本仓库，需让他们重新 clone 或执行 git fetch && git reset --hard origin/main。"
