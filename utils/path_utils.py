"""路径解析与越界防护（TDD §4.4）。

统一处理路径相关职责：
1. 虚拟路径清洗（``clean_virtual_path``）：将用户/智能体传入的路径视作
   「相对工作目录的虚拟路径」，剥离绝对路径语义与 ``..`` 穿越成分；
2. 上传/工作目录处理（``get_session_dir`` / ``get_upload_dir``）：
   基于项目根目录解析会话工作目录与上传目录；
3. 嵌套防护 + 越界校验（``resolve_within`` / ``is_within`` / ``validate_path``）：
   确保最终落点仍位于允许的根目录内，防止路径穿越。
"""
from __future__ import annotations

import re
from pathlib import Path

# 项目根目录 = 本文件父目录的父目录（backend 根，含 pyproject.toml）
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 运行时目录（TDD §3 / §9.3）
OUTPUT_DIR = PROJECT_ROOT / "output"      # 各会话工作目录
UPLOAD_DIR = PROJECT_ROOT / "upload"      # 各会话上传目录
_THREAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class PathOutOfBoundsError(ValueError):
    """路径越界异常：目标路径落在允许的根目录之外。"""


def validate_thread_id(thread_id: str) -> str:
    """只允许单个安全路径段作为会话标识。"""
    if not _THREAD_ID_PATTERN.fullmatch(thread_id):
        raise ValueError("无效的会话标识")
    return thread_id


def get_session_dir(thread_id: str) -> Path:
    """会话工作目录：output/session_{thread_id}。"""
    validate_thread_id(thread_id)
    return (OUTPUT_DIR / f"session_{thread_id}").resolve()


def get_upload_dir(thread_id: str) -> Path:
    """会话上传目录：upload/session_{thread_id}。"""
    validate_thread_id(thread_id)
    return (UPLOAD_DIR / f"session_{thread_id}").resolve()


def clean_virtual_path(virtual_path: str) -> str:
    """清洗虚拟路径（TDD §4.4「虚拟路径清洗」）。

    规则：
    - 统一 ``\\`` → ``/``；
    - 剥离 Windows 盘符（``C:``）与 UNC 前缀（``//server/share``）；
    - 剥离首部 ``/``（消除绝对路径语义）；
    - 丢弃 ``.`` / ``..`` / 空段（消除向上穿越）。

    返回清洗后的相对路径（纯 ``/`` 分隔，不含越界成分）。
    """
    if not virtual_path:
        return ""
    p = virtual_path.replace("\\", "/").strip()
    p = re.sub(r"^[a-zA-Z]:", "", p)      # 去盘符 C:
    p = p.lstrip("/")                      # 去绝对路径前缀
    segments = p.split("/")
    cleaned = [s for s in segments if s not in ("", ".", "..")]
    return "/".join(cleaned)


def is_within(path: Path, root: Path) -> bool:
    """越界校验：``path`` 是否位于 ``root`` 目录内（含 root 自身）。"""
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def resolve_within(root: Path, virtual_path: str) -> Path:
    """清洗并解析相对路径，落点必须位于 ``root`` 内（嵌套防护 + 越界校验）。

    先 ``clean_virtual_path`` 清洗虚拟路径，再拼接 ``root`` 并解析为绝对路径；
    若最终落点不在 ``root`` 内，抛 :class:`PathOutOfBoundsError`。
    """
    cleaned = clean_virtual_path(virtual_path)
    target = (Path(root) / cleaned).resolve()
    if not is_within(target, root):
        raise PathOutOfBoundsError(f"路径越界：{virtual_path!r} 落在允许目录之外")
    return target


def validate_path(path: str, root: Path) -> Path | None:
    """校验外部传入的（绝对或相对）路径是否位于 ``root`` 内。

    越界返回 ``None``，合法返回解析后的绝对路径。用于 /api/files、/api/download
    等对外接口的越界校验（TDD §8.1 / §14）。
    """
    target = Path(path).resolve()
    return target if is_within(target, root) else None


if __name__ == "__main__":
    # 快速自检：演示四类职责
    print("PROJECT_ROOT =", PROJECT_ROOT)
    print("session_dir  =", get_session_dir("abc123"))
    print("upload_dir   =", get_upload_dir("abc123"))
    print("clean        =", clean_virtual_path(r"C:/../../a/b/../c.txt"))
    print("resolve_within =", resolve_within(OUTPUT_DIR, "report/结果.md"))
    try:
        resolve_within(OUTPUT_DIR, "../../etc/passwd")
    except PathOutOfBoundsError as e:
        print("越界拦截      =", e)
    print("validate(越界) =", validate_path(PROJECT_ROOT / ".." / "secret.txt", OUTPUT_DIR))
