#!/usr/bin/env python3
"""Watch a Git worktree and commit/push changed paths in debounced batches."""

import argparse
import hashlib
import os
import stat
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


SECRET_NAMES = {
    "credentials.json",
    "secrets.json",
    "secret.json",
    "id_rsa",
    "id_ed25519",
}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".p7b", ".p7c"}


class GitError(RuntimeError):
    pass


def git(root, *args, check=True):
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError("Git 指令執行超過 120 秒，已停止自動同步。") from exc
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise GitError(detail or "Git 指令執行失敗。")
    return result


def git_text(root, *args):
    return git(root, *args).stdout.decode("utf-8", errors="surrogateescape").strip()


def resolve_root(path):
    root = Path(git_text(path, "rev-parse", "--show-toplevel"))
    return root.resolve()


def check_ready(root):
    git(root, "rev-parse", "--verify", "HEAD")
    upstream = git_text(
        root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    )
    git(root, "rev-parse", "--verify", upstream)
    ahead = int(git_text(root, "rev-list", "--count", f"{upstream}..HEAD"))
    if ahead:
        raise GitError("目前分支已有尚未推送的提交；請先手動處理後再啟動。")
    staged = git(root, "diff", "--cached", "--quiet", check=False)
    if staged.returncode == 1:
        raise GitError("啟動前已有 staged 變更；請先完成或取消暫存，再啟動監看程式。")
    if staged.returncode != 0:
        raise GitError("無法檢查 staged 變更。")
    if git(root, "status", "--porcelain", "--untracked-files=all").stdout:
        raise GitError("啟動前工作目錄不乾淨；請先處理既有變更，避免混入自動提交。")


def tracked_and_untracked_paths(root):
    output = git(
        root, "ls-files", "--cached", "--others", "--exclude-standard", "-z"
    ).stdout
    return [os.fsdecode(item) for item in output.split(b"\0") if item]


def file_signature(root, relative_path):
    path = root.joinpath(*relative_path.split("/"))
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISREG(info.st_mode):
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        content_hash = digest.digest()
    elif stat.S_ISLNK(info.st_mode):
        content_hash = hashlib.sha256(os.fsencode(os.readlink(path))).digest()
    else:
        content_hash = b""
    return (info.st_mtime_ns, info.st_size, info.st_mode, content_hash)


def take_snapshot(root):
    return {
        path: file_signature(root, path)
        for path in tracked_and_untracked_paths(root)
    }


def is_sensitive_path(relative_path):
    name = Path(relative_path).name.lower()
    return (
        name == ".env"
        or name.startswith(".env.")
        or name in SECRET_NAMES
        or Path(name).suffix in SECRET_SUFFIXES
    )


def changed_paths(previous, current):
    return sorted(
        path
        for path in previous.keys() | current.keys()
        if previous.get(path) != current.get(path)
    )


def staged_paths(root):
    output = git(root, "diff", "--cached", "--name-only", "-z").stdout
    return {os.fsdecode(item) for item in output.split(b"\0") if item}


def commit_and_push(root, paths):
    safe_paths = [path for path in paths if not is_sensitive_path(path)]
    skipped = [path for path in paths if is_sensitive_path(path)]
    for path in skipped:
        print(f"略過疑似機密檔案：{path}", file=sys.stderr, flush=True)
    if not safe_paths:
        return

    tracked = {
        os.fsdecode(item)
        for item in git(root, "ls-files", "--cached", "-z").stdout.split(b"\0")
        if item
    }
    stageable_paths = [
        path for path in safe_paths if path in tracked or file_signature(root, path) is not None
    ]
    if not stageable_paths:
        return

    git(root, "--literal-pathspecs", "add", "-A", "--", *stageable_paths)
    staged = staged_paths(root)
    if not staged:
        return
    if not staged.issubset(set(stageable_paths)):
        raise GitError(
            "暫存區內容與本次偵測路徑不一致；為避免提交其他變更，已停止。"
        )

    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M")
    message = f"{timestamp}_自動同步{len(staged)}項變更"
    commit_paths = sorted(staged)
    git(root, "commit", "--only", "-m", message, "--", *commit_paths)
    print(f"已建立 commit：{message}", flush=True)
    git(root, "push")
    print("已推送至目前分支的遠端上游。", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="監看專案檔案變更，穩定後自動 commit 並 push。"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent.parent,
        help="Git 專案路徑（預設為此腳本所在專案）",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="掃描間隔秒數（預設 1 秒）",
    )
    parser.add_argument(
        "--debounce",
        type=float,
        default=3.0,
        help="檔案穩定多久後提交（預設 3 秒）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只檢查 Git／遠端設定，不啟動監看",
    )
    args = parser.parse_args()
    if args.interval <= 0 or args.debounce < 0:
        parser.error("--interval 必須大於 0，且 --debounce 不可小於 0。")

    pending = set()
    try:
        root = resolve_root(args.root.resolve())
        check_ready(root)
        if args.check:
            print(f"設定檢查通過：{root}")
            return 0

        snapshot = take_snapshot(root)
        print(f"開始監看：{root}", flush=True)
        print("按 Ctrl+C 停止；Git 不會追蹤空資料夾。", flush=True)
        last_change = 0.0
        while True:
            time.sleep(args.interval)
            current = take_snapshot(root)
            detected = changed_paths(snapshot, current)
            if detected:
                pending.update(detected)
                last_change = time.monotonic()
                print(f"偵測到 {len(detected)} 個路徑變更，等待檔案穩定。", flush=True)
            snapshot = current

            if pending and time.monotonic() - last_change >= args.debounce:
                commit_and_push(root, sorted(pending))
                pending.clear()
    except KeyboardInterrupt:
        if pending:
            print(f"\n尚有 {len(pending)} 個路徑未同步；它們仍保留在工作目錄。", flush=True)
        print("\n已停止自動監看。", flush=True)
        return 0
    except (GitError, OSError) as exc:
        print(f"自動同步已停止：{exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
