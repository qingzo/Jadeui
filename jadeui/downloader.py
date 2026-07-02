"""
JadeUI DLL Downloader

Automatically downloads the JadeView DLL from GitHub releases.
"""

import json
import logging
import os
import platform
import re
import sys
import sysconfig
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# GitHub release URL template
GITHUB_REPO = "JadeViewDocs/JadeView"
GITHUB_RELEASE_URL = f"https://github.com/{GITHUB_REPO}/releases/download"

# SDK 适配的 JadeView API/ABI 版本。自动更新只允许在同一 release tag
# 内更新构建号，不跨 2.2 -> 2.3 这样的兼容性边界。
DLL_API_VERSION = "2.3.0-beta.9"
DLL_VERSION = DLL_API_VERSION

# 构建号（JadeView 2.x 发布包文件名为 vX.Y.Z.<BUILD>）
DLL_BUILD = "26G01"

# 兼容旧代码
VERSION = DLL_VERSION


def get_architecture() -> str:
    """Get the Python interpreter architecture.

    The JadeView DLL is loaded into the Python process via ``ctypes``, so the
    DLL architecture must match the interpreter architecture, not the OS
    architecture. For example, 32-bit Python on 64-bit Windows must use x86.

    Returns:
        'x64', 'x86', or 'arm64'
    """
    platform_tag = sysconfig.get_platform().lower()

    if "arm64" in platform_tag or "aarch64" in platform_tag:
        return "arm64"
    if platform_tag in ("win32", "mingw"):
        return "x86"
    if "amd64" in platform_tag or "x86_64" in platform_tag:
        return "x64"

    # Fallback for unusual Python builds where sysconfig does not expose an
    # architecture-specific tag.
    is_64bit = sys.maxsize > 2**32
    if not is_64bit:
        return "x86"

    machine = platform.machine().lower()

    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("amd64", "x86_64"):
        return "x64"
    if machine in ("x86", "i386", "i686"):
        return "x86"

    return "x64"


def get_dll_filename(arch: str) -> str:
    """Get the DLL filename for the architecture

    JadeView 2.x: 取消 static/dynamic 之分，文件名为 ``JadeView_{arch}.dll``。

    Args:
        arch: 'x64', 'x86', or 'arm64'

    Returns:
        DLL filename
    """
    return f"JadeView_{arch}.dll"


def _build_sort_key(build: str) -> List[object]:
    """Natural sort key for build identifiers such as ``26G01``."""
    parts = re.split(r"(\d+)", build)
    return [int(part) if part.isdigit() else part for part in parts if part]


def _extract_build_from_asset_name(name: str, version: str, arch: str) -> Optional[str]:
    prefix = f"JadeView_win_{arch}_v{version}."
    suffix = ".zip"
    if name.startswith(prefix) and name.endswith(suffix):
        return name[len(prefix) : -len(suffix)]
    return None


def get_dist_dir_name(arch: str, version: Optional[str] = None, build: Optional[str] = None) -> str:
    """Get the local distribution directory name

    JadeView 2.x 发布包内文件位于根目录（无子文件夹），这里的目录名仅用于
    本地下载缓存的组织。

    Args:
        arch: 'x64', 'x86', or 'arm64'

    Returns:
        Distribution directory name
    """
    version = version or DLL_VERSION
    build = build or DLL_BUILD
    return f"JadeView_win_{arch}_v{version}.{build}"


def get_download_url(version: str, arch: str, build: str = DLL_BUILD) -> str:
    """Get the download URL for a specific version and architecture

    Args:
        version: Version string (e.g., '2.2.4')
        arch: 'x64', 'x86', or 'arm64'
        build: Build identifier (e.g., '26F01')

    Returns:
        Download URL
    """
    zip_name = f"JadeView_win_{arch}_v{version}.{build}.zip"
    return f"{GITHUB_RELEASE_URL}/v{version}/{zip_name}"


def get_release_assets(version: str) -> List[dict]:
    """Read assets for a single JadeView release tag.

    This intentionally queries only ``v{version}``, so it can never cross an
    API/ABI boundary such as 2.2 -> 2.3 during automatic build updates.
    """
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/v{version}"
    request = urllib.request.Request(api_url, headers={"User-Agent": f"jadeui/{version}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    assets = data.get("assets", [])
    return assets if isinstance(assets, list) else []


def get_latest_build(version: Optional[str] = None, arch: Optional[str] = None) -> str:
    """Get the latest build for ``version`` and ``arch`` within the same tag.

    Falls back to ``DLL_BUILD`` when the release metadata cannot be read or no
    matching asset exists.
    """
    version = version or DLL_VERSION
    arch = arch or get_architecture()
    try:
        builds = []
        for asset in get_release_assets(version):
            name = str(asset.get("name", ""))
            build = _extract_build_from_asset_name(name, version, arch)
            if build:
                builds.append(build)
        if builds:
            return sorted(builds, key=_build_sort_key)[-1]
    except Exception as e:
        logger.debug(f"Failed to query latest JadeView build: {e}")
    return DLL_BUILD


def get_install_dir() -> Path:
    """Get the installation directory for DLL files

    Returns:
        Path to install directory
    """
    # Try package directory first
    package_dir = Path(__file__).parent
    dll_dir = package_dir / "dll"

    # If not writable, use user data directory
    if not os.access(package_dir, os.W_OK):
        if sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        else:
            base = Path.home() / ".local" / "share"
        dll_dir = base / "jadeui" / "dll"

    return dll_dir


def find_dll() -> Optional[Path]:
    """Find the DLL file in known locations

    Search order:
    1. Package internal dll directory (installed with wheel)
    2. Project root JadeView_win_{arch}_v{version}.{build} directory
    3. Current working directory
    4. User data directory (downloaded DLL)

    Returns:
        Path to DLL if found, None otherwise
    """
    arch = get_architecture()
    dll_name = get_dll_filename(arch)
    dist_dir = get_dist_dir_name(arch)

    package_dir = Path(__file__).parent
    install_dir = get_install_dir()

    # Search locations (in priority order)
    search_paths = [
        # 1. Package internal dll directory (from wheel)
        package_dir / "dll" / dist_dir / dll_name,
        # 2. Package internal lib directory (development)
        package_dir / "lib" / dist_dir / dll_name,
        # 3. Project root lib directory (development)
        package_dir.parent / "lib" / dist_dir / dll_name,
        # 4. Project root directory
        package_dir.parent / dist_dir / dll_name,
        # 5. Current working directory
        Path.cwd() / dist_dir / dll_name,
        # 6. Current working directory lib
        Path.cwd() / "lib" / dist_dir / dll_name,
        # 7. User data directory (downloaded)
        install_dir / dist_dir / dll_name,
    ]

    # Also try PyInstaller/Nuitka paths
    try:
        meipass = Path(sys._MEIPASS)  # type: ignore
        search_paths.insert(0, meipass / dist_dir / dll_name)
    except AttributeError:
        pass

    for path in search_paths:
        if path.exists():
            logger.debug(f"Found DLL at: {path}")
            return path

    # Fall back to any local build for the same API version and architecture.
    candidate_roots = [
        package_dir / "dll",
        package_dir / "lib",
        package_dir.parent / "lib",
        package_dir.parent,
        Path.cwd(),
        Path.cwd() / "lib",
        install_dir,
    ]
    candidates: List[Tuple[str, Path]] = []
    pattern = f"JadeView_win_{arch}_v{DLL_VERSION}.*"
    for root in candidate_roots:
        if not root.exists():
            continue
        for dist in root.glob(pattern):
            if not dist.is_dir():
                continue
            dll_path = dist / dll_name
            if not dll_path.exists():
                continue
            build = dist.name.rsplit(".", 1)[-1]
            candidates.append((build, dll_path))
    if candidates:
        build, path = sorted(candidates, key=lambda item: _build_sort_key(item[0]))[-1]
        logger.debug(f"Found compatible DLL build {build} at: {path}")
        return path

    return None


def download_dll(
    version: Optional[str] = None,
    arch: Optional[str] = None,
    build: Optional[str] = None,
    install_dir: Optional[Path] = None,
    progress_callback: Optional[callable] = None,
    latest_build: bool = True,
) -> Path:
    """Download the DLL from GitHub releases

    Args:
        version: Version to download (default: current version)
        arch: Architecture ('x64', 'x86', or 'arm64', default: auto-detect)
        build: Build identifier (default: latest available build for DLL_VERSION)
        install_dir: Installation directory (default: auto)
        progress_callback: Optional callback for progress updates
            Called with (downloaded_bytes, total_bytes)
        latest_build: If True and build is not provided, choose the latest build
            within the same release tag.

    Returns:
        Path to the installed DLL

    Raises:
        RuntimeError: If download fails
    """
    version = version or DLL_VERSION
    arch = arch or get_architecture()
    build = build or (get_latest_build(version, arch) if latest_build else DLL_BUILD)
    install_dir = install_dir or get_install_dir()

    url = get_download_url(version, arch, build)
    dll_name = get_dll_filename(arch)
    dist_dir = get_dist_dir_name(arch, version, build)

    print("[JadeUI] DLL 下载器")
    print(f"   版本: v{version}.{build}")
    print(f"   架构: {arch}")
    print(f"   下载地址: {url}")
    print(f"   安装目录: {install_dir}")

    # Create install directory
    target_dir = install_dir / dist_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    # Download to temp file
    try:
        print("\n正在下载...")

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_file:
            tmp_path = tmp_file.name

            # Create request with headers
            request = urllib.request.Request(url, headers={"User-Agent": f"jadeui/{version}"})

            with urllib.request.urlopen(request, timeout=60) as response:
                total_size = int(response.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 8192

                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break

                    tmp_file.write(chunk)
                    downloaded += len(chunk)

                    if progress_callback:
                        progress_callback(downloaded, total_size)
                    elif total_size > 0:
                        percent = (downloaded / total_size) * 100
                        bar = "#" * int(percent // 5) + "." * (20 - int(percent // 5))
                        print(f"\r   [{bar}] {percent:.1f}%", end="", flush=True)

                print()  # New line after progress

        print(f"下载完成 ({downloaded / 1024 / 1024:.1f} MB)")

    except urllib.error.HTTPError as e:
        os.unlink(tmp_path) if os.path.exists(tmp_path) else None
        raise RuntimeError(f"下载失败: HTTP {e.code} - {e.reason}")
    except urllib.error.URLError as e:
        os.unlink(tmp_path) if os.path.exists(tmp_path) else None
        raise RuntimeError(f"网络错误: {e.reason}")
    except Exception as e:
        os.unlink(tmp_path) if os.path.exists(tmp_path) else None
        raise RuntimeError(f"下载失败: {e}")

    # Extract ZIP (JadeView 2.x: 包内文件位于根目录，仅需 DLL，跳过 .lib/.h 等)
    try:
        print("正在解压...")

        with zipfile.ZipFile(tmp_path, "r") as zip_ref:
            namelist = zip_ref.namelist()

            # 定位包内的 DLL 条目（兼容是否带子目录前缀）
            dll_member = None
            for name in namelist:
                if name.replace("\\", "/").split("/")[-1] == dll_name:
                    dll_member = name
                    break

            if dll_member is not None:
                # 只提取 DLL 到目标目录（扁平化）
                with zip_ref.open(dll_member) as src:
                    data = src.read()
                (target_dir / dll_name).write_bytes(data)
            else:
                # 回退：找不到精确文件名时整包解压
                zip_ref.extractall(target_dir)

        print("解压完成")

    except zipfile.BadZipFile:
        raise RuntimeError("下载的文件不是有效的 ZIP 文件")
    finally:
        # Clean up temp file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    # Verify DLL exists
    dll_path = target_dir / dll_name
    if not dll_path.exists():
        # Also check if DLL is directly in install_dir (fallback)
        alt_path = install_dir / dll_name
        if alt_path.exists():
            # Move to correct location
            import shutil

            shutil.move(str(alt_path), str(dll_path))
        else:
            raise RuntimeError(f"解压后未找到 DLL 文件: {dll_path}")

    print("\n安装成功!")
    print(f"   DLL 路径: {dll_path}")

    return dll_path


def ensure_dll() -> Path:
    """Ensure DLL is available, downloading if necessary

    Returns:
        Path to the DLL

    Raises:
        RuntimeError: If DLL cannot be found or downloaded
    """
    # Try to find existing DLL
    dll_path = find_dll()
    if dll_path:
        logger.info(f"Found DLL at: {dll_path}")
        return dll_path

    # DLL not found, prompt for download
    print("\n" + "=" * 50)
    print("[WARN] 未找到 JadeView DLL")
    print("=" * 50)
    print("\n需要下载 JadeView DLL 才能运行应用。")
    print(f"下载地址: https://github.com/{GITHUB_REPO}/releases")
    print()

    # Auto-download
    try:
        return download_dll()
    except Exception as e:
        print(f"\n自动下载失败: {e}")
        arch = get_architecture()
        build = get_latest_build(DLL_VERSION, arch)
        zip_name = f"JadeView_win_{arch}_v{DLL_VERSION}.{build}.zip"
        print("\n请手动下载:")
        print(f"  1. 访问 https://github.com/{GITHUB_REPO}/releases")
        print(f"  2. 下载 {zip_name}")
        print(f"  3. 解压到项目目录或 {get_install_dir()}")
        raise RuntimeError(f"无法获取 DLL: {e}")


def cli():
    """Command-line interface for downloading DLL"""
    import argparse

    parser = argparse.ArgumentParser(
        description="下载 JadeView DLL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-v",
        "--version",
        default=DLL_VERSION,
        help=f"DLL 版本号 (默认: {DLL_VERSION})",
    )
    parser.add_argument(
        "-a",
        "--arch",
        choices=["x64", "x86", "arm64"],
        default=get_architecture(),
        help=f"架构 (默认: {get_architecture()})",
    )
    parser.add_argument(
        "-b",
        "--build",
        default=None,
        help=f"构建号 (默认: 同版本最新构建号，离线回退 {DLL_BUILD})",
    )
    parser.add_argument(
        "--no-latest-build",
        action="store_true",
        help="不查询同版本最新构建号，使用内置默认构建号",
    )
    parser.add_argument(
        "-d",
        "--dir",
        type=Path,
        help="安装目录",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="仅检查 DLL 是否存在",
    )

    args = parser.parse_args()

    if args.check:
        dll_path = find_dll()
        if dll_path:
            print(f"找到 DLL: {dll_path}")
            return 0
        else:
            print("未找到 DLL")
            return 1

    try:
        download_dll(
            version=args.version,
            arch=args.arch,
            build=args.build,
            install_dir=args.dir,
            latest_build=not args.no_latest_build,
        )
        return 0
    except Exception as e:
        print(f"错误: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(cli())
