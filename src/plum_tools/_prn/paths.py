"""处理本机与远端同步路径。"""

import os


def is_directory_target(target: str) -> bool:
    """识别显式目录路径，避免将主机别名误判为目录。"""
    return target.startswith(("/", "~/", "./", "../")) or target in ("~", ".", "..")


def get_directory_path(root: str, path: str) -> str:
    """将配置路径映射到目录根路径内，拒绝越界路径及其他用户的家目录。"""
    if path == "~":
        relative = ""
    elif path.startswith("~/"):
        relative = path[2:]
    elif path.startswith("~"):
        raise ValueError(f"目录目标不支持其他用户的家目录：{path}")
    else:
        relative = path.lstrip("/")
    directory = os.path.abspath(os.path.join(root, relative))
    if os.path.commonpath([root, directory]) != root:
        raise ValueError(f"配置路径超出目录根路径：{path}")
    return directory


def process_path(path: str, is_local: bool = False) -> str:
    # 本地端目录结尾需要有 /
    if is_local and not path.endswith("/") and os.path.isdir(path):
        path += "/"
    # 目标端目录结尾不能有 /
    if not is_local and path.endswith("/"):
        path = path[:-1]
    return path


def process_paths(paths: str | list[str], is_local: bool = False) -> str:
    if isinstance(paths, str):
        paths = [paths]
    return " ".join([process_path(path, is_local=is_local) for path in paths])


def process_remote_paths(paths: str | list[str], user_prefix: str, pv: str) -> str:
    if isinstance(paths, str):
        paths = [paths]
    return " ".join([f"{user_prefix}{path}{pv}" for path in paths])
