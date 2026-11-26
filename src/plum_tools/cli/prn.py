"""prn 命令行入口。"""

from plum_tools._prn.config import get_project_conf
from plum_tools._prn.paths import is_directory_target
from plum_tools._prn.sync import sync_files
from plum_tools.utils.cli import cli_entry
from plum_tools.utils.constants import LOCAL_HOST
from plum_tools.utils.parser import get_base_parser
from plum_tools.utils.printer import print_error


@cli_entry
def main() -> None:  # pylint: disable=R0914
    """程序主入口"""
    parser = get_base_parser()
    parser.description = "使用 rsync 上传、下载或在本机同步项目文件。"  # noqa
    parser.epilog = (
        "示例：\n"
        "  prn -s dev -p default --dry-run\n"
        "  prn -s dev -l ./src -r /srv/app --dry-run\n"
        "  prn -s dev -p default --download\n"
        '  prn -s "/Volumes/SANDISK ELE/seekplum" -p python go --dry-run\n\n'
        "目录目标：-s 支持 /、~/、./、../ 开头的路径，将项目 dest 映射到该根目录；\n"
        "~/ 按目标根目录展开，绝对路径按根目录内的相同层级映射；--download 反向恢复，缺项跳过。\n"
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

    if all(is_directory_target(host) for host in host_list):
        projects_conf = [
            get_project_conf(project, src, dest, delete, exclude, is_download, resolve_src=False)
            for project in projects
        ]
    else:
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
        exclude=exclude,
        include=include,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
