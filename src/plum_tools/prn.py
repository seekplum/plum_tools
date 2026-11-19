"""
#=============================================================================
#  ProjectName: plum_tools
#     FileName: prn
#         Desc: 上传文件到服务器
#               命令: prn -s plum -p plum
#               描述: 上传 ~/..yml 中指定项目的文件到ssh_config中配置的服务器
#       Author: seekplum
#        Email: 1131909224m@sina.cn
#     HomePage: seekplum.github.io
#       Create: 2018-07-07 17:26
#=============================================================================
"""

import os
import subprocess
import sys

from .conf import LOCAL_HOST, PathConfig
from .exceptions import RunCmdError, SystemTypeError
from .utils.parser import get_base_parser
from .utils.printer import print_error, print_ok, print_text
from .utils.sshconf import merge_ssh_config
from .utils.utils import YmlConfig, get_file_abspath, run_cmd


def get_project_conf(  # noqa: C901
    project: str,
    src: list[str],
    dest: list[str],
    delete: int | None,
    exclude: list[str],
    is_download: bool = False,
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
    if not is_download:
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


class SyncFiles:  # pylint: disable=too-many-instance-attributes
    """上传文件到服务器"""

    # pylint: disable=too-many-positional-arguments,too-many-arguments
    def __init__(
        self,
        hostname: str,
        user: str,
        port: int,
        identityfile: str,
        src: str,
        dest: str,
        exclude: list[str] | None,
        delete: int,
        is_download: bool = False,
        is_debug: bool = False,
        ignore_rsync_path: bool = False,
        ignore_exclude: bool = False,
        include: list[str] | None = None,
        dry_run: bool = False,
    ):
        """文件上传功能

        :param hostname 主机ip
        :example hostname 10.10.100.1

        :param user ssh登陆使用的用户名
        :example user 10.10.100.1

        :param port ssh登陆使用的端口号
        :example port 22

        :param identityfile 私钥文件路径
        :example identityfile ~/.ssh/id_rsa

        :param src 本地路径
        :example src /tmp

        :param dest 远程机器路径
        :example dest /tmp

        :param exclude 需要过滤的目录
        :example exclude [".git"]

        :param delete 是否删除远程机器目录下非本次上传的文件
        :example delete 0 0|1  0: 不删除 1: 删除

        :param is_download 是否是下载文件，默认是上传
        :example is_download False

        :param is_debug 是否打印详细信息
        :example is_debug False

        :param ignore_rsync_path 是否忽略 rsync-path 参数
        :example ignore_rsync_path False

        :param ignore_exclude 是否忽略 exclude 参数
        :example ignore_exclude False

        :param include 包含的目录
        :example include ["pkg"]
        """
        self._hostname = hostname
        self._user = user
        self._port = port
        self._identity_file = identityfile
        self._src = src
        self._dest = dest
        self._exclude = exclude or []
        self._include = set(include or [])
        self._delete = delete
        self._is_download = is_download
        self._is_debug = is_debug
        self._dry_run = dry_run
        self._ignore_rsync_path = ignore_rsync_path
        self._ignore_exclude = ignore_exclude
        self._is_localhost = hostname == LOCAL_HOST

    @property
    def host_info(self) -> str:
        """主机信息"""
        if self._is_localhost:
            return "本地机器"
        return f"{self._user}@{self._hostname} 服务器(端口: {self._port})"

    @property
    def user_prefix(self) -> str:
        """用户前缀"""
        if self._is_localhost:
            return ""
        return f"{self._user}@{self._hostname}:"

    def _get_sync_option(self) -> str:
        """组合出同步文件的命令"""
        option = ["rsync -rtv"]
        known_host = "UserKnownHostsFile=/dev/null"
        host_key = "StrictHostKeyChecking no"
        timeout = "ConnectTimeout=2"
        # 指定端口
        if self._port:
            ssh_cmd = f"ssh -p {self._port}"
        else:
            ssh_cmd = "ssh"
        if not self._ignore_rsync_path:
            directory = os.path.dirname(self._dest)
            if not directory:
                directory = self._dest
            option.append(f"'--rsync-path=mkdir -p {directory} && rsync'")
        if not self._is_localhost:
            option.append(f'-e \'{ssh_cmd} -i {self._identity_file} -o "{known_host}" -o "{host_key}" -o "{timeout}"\'')
        if self._delete:
            option.append("--delete")
        if not self._ignore_exclude:
            exists = set()
            for item in self._exclude:
                if item in self._include or item in exists:
                    continue
                exists.add(item)
                option.append(f"--exclude '{item}'")
        return " ".join(option)

    def translate(self) -> None:
        """文件上传功能"""
        # pv = "|pv -lep -s 117 >/dev/null"
        pv = ""

        if self._is_download:
            self._src, self._dest = process_remote_paths(self._dest, self.user_prefix, pv), process_paths(self._src)
        else:
            self._src, self._dest = process_paths(self._src, is_local=True), process_paths(self._dest)

        # 从远端下载文件到本地
        if self._is_download:
            src = self._src
            dest = self._dest
            text = f"从 {self.host_info} 下载 {self._src} 到本地 {self._dest} "
        # 从本地上传文件到远端
        else:
            src = self._src
            dest = f"{self.user_prefix}{self._dest}{pv}"
            text = f"上传 {self._src} 到 {self.host_info} {self._dest} "

        rsync = self._get_sync_option()
        cmd = f"{rsync} {src} {dest}"
        if self._dry_run:
            print_text(cmd)
            return
        try:
            if self._is_debug:
                print_text(cmd)
                exit_code = subprocess.call(cmd, shell=True)  # nosec B602
                if exit_code != 0:
                    print_error(f"{text}失败, 错误码: {exit_code}")
                    return
            else:
                run_cmd(cmd)
            print_ok(f"{text}成功")
        except RunCmdError as e:
            print_error(f"{text}失败, 失败原因: {e.err_msg}")


def sync_files(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    host_list: list[str],
    host_type: str,
    user: str,
    port: int,
    identity_file: str,
    projects_conf: list[dict],
    is_download: bool = False,
    is_debug: bool = False,
    ignore_rsync_path: bool = False,
    ignore_exclude: bool = False,
    include: list[str] | None = None,
    dry_run: bool = False,
) -> None:
    """上传文件到服务器上

    :param host_list 服务器列表
    :example host_list [1, 2]

    :param host_type 主机类型
    :example host_type 1

    :param user ssh登陆用户名
    :example user root

    :param port ssh登陆端口
    :example port 22

    :param user ssh登陆用户名
    :example user root

    :param identity_file ssh登陆私钥文件路径
    :example identity_file ~/.ssh/id_rsa

    :param projects_conf 需要上传的项目配置列表
    :example pro_conf [{
        "src": "/tmp",
        "dest": "/tmp",
        "exclude": [".git"],
        "delete": 0
    }]

    :param is_download 是否是下载文件，默认是上传
    :example is_download False

    :param is_debug 是否打印详细信息
    :example is_debug False

    :param ignore_rsync_path 是否忽略 rsync-path 参数
    :example ignore_rsync_path False

    :param ignore_exclude 是否忽略 exclude 参数
    :example ignore_exclude False

    :param include 包含的目录
    :example include ["pkg"]
    """
    for host in host_list:
        if host == LOCAL_HOST:
            ssh_conf = {"hostname": host, "user": "", "port": 0, "identityfile": ""}
        else:
            ssh_conf = merge_ssh_config(host, host_type, user, port, identity_file)
        ssh_conf.update(
            {
                "is_download": is_download,
                "is_debug": is_debug,
                "ignore_rsync_path": ignore_rsync_path,
                "ignore_exclude": ignore_exclude,
                "include": include,
                "dry_run": dry_run,
            }
        )
        for pro_conf in projects_conf:
            sync = SyncFiles(**{**pro_conf, **ssh_conf})
            sync.translate()


def main() -> None:  # pylint: disable=R0914
    """程序主入口"""
    parser = get_base_parser()
    parser.description = "使用 rsync 上传、下载或在本机同步项目文件。"  # noqa
    parser.epilog = (
        "示例：\n"
        "  prn -s dev -p default --dry-run\n"
        "  prn -s dev -l ./src -r /srv/app --dry-run\n"
        "  prn -s dev -p default --download\n\n"
        "配置：项目及默认 SSH 参数读取 ~/.plum_tools.yaml；\n"
        "SSH 参数优先使用命令行值，其次为主机别名配置，最后为 default_ssh_conf。"
    )
    parser.add_argument(
        "-s",
        "--servers",
        required=False,
        action="store",
        dest="servers",
        nargs="+",
        help="服务器 IP、IP 简写或 SSH 主机别名，可指定多个；默认在本机同步",
    )
    parser.add_argument(
        "-p",
        "--projects",
        required=False,
        action="store",
        dest="projects",
        nargs="+",
        default=["default"],
        help="配置中的项目名，可指定多个；默认 default，可选值由 projects 配置决定",
    )

    parser.add_argument(
        "-t",
        "--type",
        action="store",
        required=False,
        dest="type",
        default="default",
        help="主机类型，默认 default；可选值由配置中的 host_type_<类型> 决定",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        required=False,
        dest="download",
        default=False,
        help="从远端下载文件到本地，默认上传",
    )
    parser.add_argument(
        "-i",
        "--identityfile",
        action="store",
        required=False,
        dest="identity_file",
        default="",
        help="SSH 私钥路径，默认读取 SSH 配置",
    )
    parser.add_argument(
        "-u",
        "--username",
        action="store",
        required=False,
        dest="user",
        default="",
        help="SSH 登录用户名，默认读取 SSH 配置",
    )
    parser.add_argument(
        "--port",
        action="store",
        required=False,
        dest="port",
        type=int,
        default=0,
        help="SSH 登录端口，默认读取 SSH 配置",
    )
    parser.add_argument(
        "-l",
        "--local",
        action="store",
        required=False,
        dest="local",
        nargs="+",
        default="",
        help="本地路径，可指定多个；默认读取项目的 src 配置",
    )
    parser.add_argument(
        "-r",
        "--remote",
        action="store",
        required=False,
        dest="remote",
        nargs="+",
        default="",
        help="远端路径，可指定多个；默认读取项目的 dest 配置",
    )
    parser.add_argument(
        "-d",
        "--delete",
        action="store",
        required=False,
        dest="delete",
        type=int,
        default=None,
        help="是否删除目标端多余文件：0 保留，1 删除；默认读取项目 delete 配置，未配置时为 0",
    )
    parser.add_argument(
        "-e",
        "--exclude",
        action="store",
        nargs="+",
        required=False,
        dest="exclude",
        default=[],
        help="追加排除的文件或目录，可指定多个；默认使用项目及全局排除配置",
    )
    parser.add_argument(
        "--include",
        action="store",
        nargs="+",
        required=False,
        dest="include",
        default=[],
        help="取消指定文件或目录的排除，可指定多个；默认无覆盖项",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        required=False,
        dest="debug",
        default=False,
        help="显示完整 rsync 调试输出，默认关闭",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        required=False,
        dest="dry_run",
        default=False,
        help="仅打印将要执行的命令，默认关闭",
    )
    parser.add_argument(
        "--ignore-rsync-path",
        action="store_true",
        required=False,
        dest="ignore_rsync_path",
        default=False,
        help="不使用 --rsync-path 选项，默认使用该选项",
    )
    parser.add_argument(
        "--ignore-exclude",
        action="store_true",
        required=False,
        dest="ignore_exclude",
        default=False,
        help="忽略全部排除规则，默认应用排除规则",
    )

    args = parser.parse_args()
    host_list, host_type, projects = args.servers, args.type, args.projects
    if not host_list:
        host_list = [LOCAL_HOST]

    src, dest, delete, exclude = args.local, args.remote, args.delete, args.exclude
    if len(src) > 1 and len(dest) > 1:
        print_error("本地路径和目标路径不能同时传入多个值")
        return

    user, port, identity_file = args.user, args.port, args.identity_file

    is_download, is_debug = args.download, args.debug
    ignore_rsync_path, ignore_exclude, include = args.ignore_rsync_path, args.ignore_exclude, args.include

    projects_conf = [get_project_conf(project, src, dest, delete, exclude, is_download) for project in projects]
    sync_files(
        host_list,
        host_type,
        user,
        port,
        identity_file,
        projects_conf,
        is_download,
        is_debug,
        ignore_rsync_path=ignore_rsync_path,
        ignore_exclude=ignore_exclude,
        include=include,
        dry_run=args.dry_run,
    )
