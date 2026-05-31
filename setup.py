# -*- coding: utf-8 -*-
"""一次性环境配置脚本 —— 探测并写入 config.json，之后 Agent 不再需要手动自举"""
import json
import os
import platform
import subprocess
import sys
import venv

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
CONFIG_PATH = os.path.join(SKILL_DIR, "config.json")
VENV_DIR = os.path.join(SKILL_DIR, "venv")

MIN_PYTHON = (3, 8)

# 国内镜像源（按优先级，pip 默认源失败时自动切换）
MIRRORS = [
    ("清华源", "https://pypi.tuna.tsinghua.edu.cn/simple"),
    ("阿里源", "https://mirrors.aliyun.com/pypi/simple"),
    ("中科大源", "https://pypi.mirrors.ustc.edu.cn/simple"),
]


def _check_python_version():
    current = sys.version_info[:2]
    if current < MIN_PYTHON:
        print(f"[setup] 错误: 当前 Python {current[0]}.{current[1]} 版本过低")
        print(f"         需要 Python >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}（playwright 要求）")
        print(f"         当前路径: {sys.executable}")
        print(f"         请安装更高版本的 Python 后重试。")
        sys.exit(1)
    print(f"[setup] Python {current[0]}.{current[1]}  OK")


def _detect_os():
    system = platform.system()
    if system == "Windows":
        return {
            "type": "windows", "encoding": "utf-8", "path_sep": "\\",
            "temp_dir": os.environ.get("TEMP", os.environ.get("TMP", "C:\\Temp")),
        }, os.path.join(VENV_DIR, "Scripts", "python.exe")
    elif system == "Darwin":
        return {
            "type": "macos", "encoding": "utf-8", "path_sep": "/",
            "temp_dir": os.environ.get("TMPDIR", "/tmp"),
        }, os.path.join(VENV_DIR, "bin", "python3")
    else:
        return {
            "type": "linux", "encoding": "utf-8", "path_sep": "/",
            "temp_dir": os.environ.get("TMPDIR", "/tmp"),
        }, os.path.join(VENV_DIR, "bin", "python3")


def _detect_shell():
    system = platform.system()
    if system == "Windows":
        for p in [
            os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32",
                         "WindowsPowerShell", "v1.0", "powershell.exe"),
        ]:
            if os.path.exists(p):
                return {"type": "powershell", "path": p, "version": "unknown"}
        return {"type": "cmd", "path": "cmd.exe", "version": "unknown"}
    else:
        shell_path = os.environ.get("SHELL", "/bin/bash")
        return {"type": os.path.basename(shell_path), "path": shell_path, "version": "unknown"}


def _detect_python():
    return {"path": sys.executable, "version": platform.python_version()}


def _detect_browser(os_type):
    if os_type == "windows":
        candidates = [
            (os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
                          "Microsoft", "Edge", "Application", "msedge.exe"), "edge"),
            (os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"),
                          "Microsoft", "Edge", "Application", "msedge.exe"), "edge"),
            (os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
                          "Google", "Chrome", "Application", "chrome.exe"), "chrome"),
            (os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"),
                          "Google", "Chrome", "Application", "chrome.exe"), "chrome"),
        ]
    elif os_type == "macos":
        candidates = [
            ("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "edge"),
            ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "chrome"),
        ]
    else:
        candidates = [
            ("/usr/bin/microsoft-edge", "edge"),
            ("/usr/bin/google-chrome", "chrome"),
            ("/usr/bin/chromium-browser", "chrome"),
            ("/snap/bin/chromium", "chrome"),
        ]
    for p, t in candidates:
        if os.path.exists(p):
            return {"type": t, "path": p}
    return {"type": "unknown", "path": ""}


def _pip_install(python_path, packages, timeout=60):
    """pip install，默认源失败后自动切换国内镜像源"""
    base_cmd = [python_path, "-m", "pip", "install", "--quiet"] + packages

    # 先试默认源
    print(f"[setup] pip install (默认源) ...")
    result = subprocess.run(base_cmd, check=False, capture_output=True, text=True, timeout=timeout)
    if result.returncode == 0:
        print(f"[setup] pip install 成功")
        return True

    # 默认源失败，切换镜像源
    stderr_tail = result.stderr.strip()[-200:] if result.stderr else ""
    print(f"[setup] 默认源失败，尝试国内镜像源 ...")

    for name, url in MIRRORS:
        cmd = base_cmd + ["-i", url]
        print(f"[setup]   尝试 {name} ({url}) ...")
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout * 2)
            if result.returncode == 0:
                print(f"[setup] {name} 成功")
                return True
            else:
                print(f"[setup]   {name} 失败: {result.stderr.strip()[-100:]}")
        except subprocess.TimeoutExpired:
            print(f"[setup]   {name} 超时")
    return False


def _setup_venv(python_venv_path):
    """创建 venv 并安装依赖，返回 venv 中实际可用的 Python 路径"""
    if not os.path.exists(python_venv_path):
        print("[setup] 创建 venv ...")
        venv.create(VENV_DIR, with_pip=True)
        if not os.path.exists(python_venv_path):
            bin_dir = os.path.dirname(python_venv_path)
            if os.path.isdir(bin_dir):
                for name in sorted(os.listdir(bin_dir)):
                    if name.startswith("python"):
                        candidate = os.path.join(bin_dir, name)
                        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                            python_venv_path = candidate
                            break
        if not os.path.exists(python_venv_path):
            print(f"[setup] 错误: venv 创建后未找到 Python: {python_venv_path}")
            sys.exit(1)

    print(f"[setup] Venv Python: {python_venv_path}")

    if not _pip_install(python_venv_path, ["playwright", "openai"]):
        print("[setup] 错误: 所有 pip 源均失败，请检查网络连接或手动安装。")
        print(f"         手动: {python_venv_path} -m pip install playwright openai")
        sys.exit(1)

    print("[setup] 安装 Chromium 浏览器 ...")
    playwright_cmd = [python_venv_path, "-m", "playwright", "install", "chromium"]
    subprocess.run(playwright_cmd, check=False)

    return python_venv_path


def main():
    print("=== WebAISearch 环境配置 ===")

    _check_python_version()

    print(f"[setup] 探测环境 ...")
    os_info, python_venv_path = _detect_os()
    shell_info = _detect_shell()
    python_info = _detect_python()
    browser_info = _detect_browser(os_info["type"])

    python_venv_path = _setup_venv(python_venv_path)

    config = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            config = json.load(f)

    config["version"] = 6
    config["local_env"] = {
        "initialized": True,
        "os": os_info,
        "shell": shell_info,
        "python": python_info,
        "python_venv": python_venv_path,
        "browser": {**browser_info, "cdp_port": config.get("cdp_port", 9222)},
    }

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"\n[setup] 完成！")
    print(f"  OS:       {os_info['type']}")
    print(f"  Shell:    {shell_info['type']}")
    print(f"  Python:   {python_info['version']} ({python_info['path']})")
    print(f"  Venv:     {python_venv_path}")
    print(f"  Browser:  {browser_info['type']} ({browser_info['path']})")
    print(f"  CDP Port: {config.get('cdp_port', 9222)}")


if __name__ == "__main__":
    main()

