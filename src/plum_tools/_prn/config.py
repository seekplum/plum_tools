"""读取并校验同步项目配置。"""

import sys

from plum_tools.utils.constants import PathConfig
from plum_tools.utils.exceptions import RunCmdError, SystemTypeError
from plum_tools.utils.printer import print_error
from plum_tools.utils.utils import YmlConfig, get_file_abspath


def get_project_conf(  # noqa: C901
    project: str,
    src: list[str],
    dest: list[str],
    delete: int | None,
    exclude: list[str],
    is_download: bool = False,
    resolve_src: bool = True,
) -> dict:
    """查询项目信息

    :param project 指定的项目名
    :example project plum

    :param src 本地路径
    :example src /tmp

    :param dest 远程机器路径
    :example dest /tmp

    :param exclude 需要过滤的目录
    :example exclude [".git"]

    :param delete 是否删除远程机器目录下非本次上传的文件
    :example delete 0 0|1  0: 不删除 1: 删除

    :param is_download 是否下载文件
    :example is_download True True|False

    :return data 项目的配置信息
    {
        "src": 本地路径,
        "dest": 上传后的目录路径,
        "exclude": 需要过滤不上传的目录,
        "delete": 是否删除远程机器目录下非本次上传的文件
    }
    :example data {
        "src": "/tmp",
        "dest": "/tmp",
        "exclude": [".git"],
        "delete": 0
    }
    """
    yml_data = YmlConfig.parse_config_yml(PathConfig.PLUM_YML_PATH)
    default_exclude = yml_data.get("default_exclude", [])
    data = {}
    try:
        data = dict(yml_data["projects"][project])
    except KeyError:
        if not (src and dest):
            print_error(f"yml文件: {PathConfig.PLUM_YML_PATH} 中没有配置项目: {project} 的信息")
            sys.exit(1)

    # 设置默认值
    data.setdefault("exclude", [])
    data.setdefault("delete", 0)
    data["exclude"].extend(default_exclude)

    # 从命令行中更新对应值
    if src:
        data["src"] = src
    if dest:
        data["dest"] = dest
    if not isinstance(data["src"], list):
        data["src"] = [data["src"]]
    if not isinstance(data["dest"], list):
        data["dest"] = [data["dest"]]
    # 上传时对本地路径取绝对路径
    if not is_download and resolve_src:
        try:
            data["src"] = [get_file_abspath(path) for path in data["src"]]
        except RunCmdError:
            tmp_src = " ".join(data["src"])
            print_error(f"{tmp_src} 文件/目录不存在")
            sys.exit(1)
        except SystemTypeError as e:
            print_error(str(e))
            sys.exit(1)
    if delete is not None:  # 默认值为None
        data["delete"] = delete
    if exclude:
        data["exclude"].extend(exclude)

    return data
