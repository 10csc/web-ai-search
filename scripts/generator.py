# -*- coding: utf-8 -*-
"""LLM 代码生成器：分析页面 DOM → 生成平台交互脚本 → 缓存"""
import json, os, time, hashlib, importlib.util
from common import SCRIPTS_DIR, load_config
from runtime_paths import PROFILES_DIR

PLATFORMS_DIR = os.path.join(SCRIPTS_DIR, "platforms")


def get_platform_script_path(platform):
    return os.path.join(PLATFORMS_DIR, f"{platform}.py")


def load_platform_module(platform):
    """加载平台脚本模块，所有调用方统一入口。"""
    spec = importlib.util.spec_from_file_location(
        f"platform_{platform}", get_platform_script_path(platform))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def get_profile_path(url):
    h = hashlib.md5(url.encode()).hexdigest()[:8]
    return os.path.join(PROFILES_DIR, f"{h}.json")


def script_exists(platform):
    return os.path.exists(get_platform_script_path(platform))


def generate_interaction_script(page, platform, url):
    """让 LLM 分析页面 DOM，生成该平台的交互脚本"""
    # 1. 提取页面关键 DOM（输入区 + 按钮区）
    dom_info = page.evaluate("""() => {
        let info = {url: location.href, title: document.title, inputArea: null, buttons: []};
        
        // 找输入框
        let inp = document.querySelector('[contenteditable=true], textarea, [role=textbox], #prompt-textarea');
        if (inp) {
            let p = inp;
            for (let i = 0; i < 4; i++) {
                if (p.parentElement) p = p.parentElement;
            }
            info.inputArea = {
                tag: inp.tagName,
                contenteditable: inp.getAttribute('contenteditable'),
                placeholder: inp.getAttribute('placeholder') || '',
                role: inp.getAttribute('role') || '',
                id: inp.id || '',
                className: (inp.className || '').substring(0, 200),
                parentHTML: (p.outerHTML || p.innerHTML || '').substring(0, 3000)
            };
        }
        
        // 找所有可能的按钮（仅输入区附近的，不是消息区的）
        let allBtns = document.querySelectorAll('[role=button], button');
        for (let b of allBtns) {
            let r = b.getBoundingClientRect();
            if (r.width > 10 && r.height > 10 && r.width < 100 && r.height < 100) {
                let hasSVG = !!b.querySelector('svg');
                let svgHTML = '';
                if (hasSVG) {
                    let svg = b.querySelector('svg');
                    svgHTML = (svg.outerHTML || '').substring(0, 300);
                }
                info.buttons.push({
                    tag: b.tagName,
                    role: b.getAttribute('role') || '',
                    ariaLabel: b.getAttribute('aria-label') || '',
                    dataTestId: b.getAttribute('data-testid') || '',
                    className: (b.className || '').substring(0, 200),
                    hasSVG: hasSVG,
                    svgPreview: svgHTML,
                    rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)},
                    text: (b.innerText || '').substring(0, 50)
                });
            }
        }
        
        // 找弹窗/模态框
        let modals = document.querySelectorAll('[class*=dialog], [class*=modal], [class*=overlay], [class*=popup]');
        info.modals = [];
        for (let m of modals) {
            let r = m.getBoundingClientRect();
            if (r.width > 50 && r.height > 50) {
                info.modals.push({
                    className: (m.className || '').substring(0, 200),
                    text: (m.innerText || '').substring(0, 100)
                });
            }
        }
        
        return JSON.stringify(info);
    }""")

    print(f"[*] DOM 分析完成，正在让 LLM 生成 {platform} 交互脚本...")
    
    # 2. 调用 LLM 生成脚本
    script_content = _call_llm_generate(platform, url, dom_info)
    
    # 3. 保存脚本和 profile
    os.makedirs(PLATFORMS_DIR, exist_ok=True)
    os.makedirs(PROFILES_DIR, exist_ok=True)
    
    script_path = get_platform_script_path(platform)
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script_content)
    
    profile = {
        "url": url,
        "platform": platform,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "dom_snapshot": dom_info[:500]
    }
    with open(get_profile_path(url), "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False)
    
    print(f"[*] 脚本已缓存: {script_path}")
    return script_content


def _call_llm_generate(platform, url, dom_info):
    """调用本地 LLM 生成平台交互脚本"""
    config = load_config()
    api_url = config.get("deepseek_api", "http://localhost:3688/v1")
    
    pitfalls_path = os.path.join(SCRIPTS_DIR, "..", "references", "pitfalls.md")
    pitfalls_text = ""
    if os.path.exists(pitfalls_path):
        with open(pitfalls_path, "r", encoding="utf-8") as f:
            pitfalls_text = f.read()

    system_prompt = f"""你是一个 Playwright 自动化脚本生成器。你需要基于给定的网页 DOM 信息，生成一个 Python 模块。

目标平台：{platform}
目标 URL：{url}

生成的模块必须包含以下函数（签名固定）：
1. fill_prompt(page, prompt_text) -> bool
   - 定位输入框并填入文本
   - 返回是否成功
2. dismiss_blockers(page) -> None
   - 检测并关闭所有弹窗/对话框（DOM模态框 + 浏览器原生dialog）
   - 对原生 dialog 用 page.on("dialog", lambda d: d.accept())
3. submit(page) -> bool
   - 点击发送按钮发送消息
   - 必须从输入框出发找最近的发送按钮（避免点到历史消息的编辑按钮）
   - 返回是否发送成功

规则：
- 发送键：DeepSeek 用按钮点击（DOM分析按钮特征），ChatGPT 用 button[data-testid=send-button]，Gemini 用 button[aria-label="Send message"]
- 弹窗处理：每次操作前后都要清弹窗
- 按钮定位：优先用 aria-label、data-testid，其次用 class 名匹配，再次用位置启发式（输入框右下角的按钮）
- 深度搜索优先使用 Playwright 的 JavaScript 注入
- 纯 Python 代码，不要 markdown 代码块标记
- 导入：from playwright.sync_api import Page
- 编码声明：# -*- coding: utf-8 -*-
- 只输出代码，不要任何解释
- 纯中文注释

## 平台特定规则（通用，所有平台都适用）
1. 发送按钮：优先查找 aria-label 含 "发送"/"Send"/"Submit" 的按钮，点击按钮发送，不要用 Enter 键（Quill/ProseMirror 编辑器中 Enter 是换行）
2. 发送后：绝对不要按 Escape 键（会被解释为"停止生成"），dismiss_blockers 只在发送前调用
3. 发送验证：输入框残留 <= 2 字符即视为成功，不要要求完全清零（Quill 编辑器特性）
4. 输入框选择器：优先 [role=textbox]，其次 [contenteditable=true]，最后 textarea

## 已知陷阱（必须遵守）
{ pitfalls_text }
"""

    user_prompt = f"""以下是网页的 DOM 结构信息（JSON）：

{dom_info}

请基于这些信息生成 {platform} 平台的交互模块代码。
重点分析：
1. 输入框的确切选择器（tag、class、role 等特征）
2. 发送按钮的位置特征（相对于输入框的位置、SVG图标特征、class名）
3. 可能的弹窗类型和关闭方式
4. 发送后页面的变化特征（输入框是否清空、是否出现新消息）

生成完整的 Python 模块代码："""

    try:
        from openai import OpenAI
        client = OpenAI(base_url=api_url, api_key="local")
        resp = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1, max_tokens=4096,
        )
        content = resp.choices[0].message.content.strip()
        # 清理 markdown 代码块
        if content.startswith("```"):
            lines = content.split("\n")
            # 去掉第一行 ```python 和最后一行 ```
            content = "\n".join(lines[1:]) if lines[0].startswith("```") else content
            if content.endswith("```"):
                content = content[:-3].strip()
        return content
    except Exception as e:
        print(f"    LLM 生成失败: {e}")
        print(f"[!] 降级到通用兜底模板 -- 发送/提取不受影响，但平台适配可能不完美")
        print(f"[!] 如需优化，可等 LLM API 恢复后 --regenerate 重新定型")
        return _fallback_template(platform)


def _fallback_template(platform):
    """LLM 不可用时的兜底模板，按平台区分"""
    if platform == "chatgpt":
        return _chatgpt_template()
    else:
        return _generic_template()


def _chatgpt_template():
    return '''# -*- coding: utf-8 -*-
"""ChatGPT ProseMirror"""
from playwright.sync_api import Page
import time

def fill_prompt(page, prompt_text):
    page.locator("body").click(timeout=3000)
    time.sleep(1)
    sel = "#prompt-textarea, .ProseMirror[contenteditable=true]"
    page.locator(sel).first.wait_for(state="visible", timeout=10000)
    page.locator(sel).first.click(timeout=5000)
    time.sleep(0.5)
    page.keyboard.press("Control+a")
    page.keyboard.press("Backspace")
    time.sleep(0.2)
    page.keyboard.insert_text(prompt_text)
    time.sleep(1)
    val = page.evaluate("""() => {
        let e = document.querySelector("#prompt-textarea");
        return e ? (e.innerText || e.textContent || "") : "";
    }""")
    return len(val) > 10

def dismiss_blockers(page):
    try:
        page.on("dialog", lambda d: d.accept())
    except Exception:
        pass
    try:
        page.keyboard.press("Escape")
        time.sleep(0.3)
    except Exception:
        pass

def submit(page):
    sel = "button[data-testid=send-button], button[type=submit], [aria-label=Send], button svg"
    try:
        page.locator(sel).first.click(timeout=5000)
        time.sleep(2)
        return True
    except Exception:
        pass
    try:
        page.keyboard.press("Enter")
        time.sleep(2)
        return True
    except Exception:
        return False

'''

def _generic_template():
    return '''# -*- coding: utf-8 -*-
"""{platform} 平台交互模块（兜底模板）"""
from playwright.sync_api import Page
import time

def fill_prompt(page, prompt_text):
    page.locator("[contenteditable=true], textarea, [role=textbox]").first.click(timeout=5000)
    time.sleep(0.5)
    page.keyboard.press("Control+a")
    page.keyboard.press("Backspace")
    page.keyboard.insert_text(prompt_text)
    time.sleep(0.5)
    return True

def dismiss_blockers(page):
    try:
        page.on("dialog", lambda d: d.accept())
    except Exception:
        pass
    try:
        page.keyboard.press("Escape")
        time.sleep(0.3)
    except Exception:
        pass

def submit(page):
    """优先点击发送按钮，兜底 Enter"""
    # Try common send button selectors
    for sel in ["button[aria-label=发送]", "button[aria-label=Send]", "[aria-label=Send message]", "button[aria-label=Send message]", "button[data-testid=send-button]"]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                btn.click(timeout=3000)
                time.sleep(1.5)
                return True
        except Exception:
            continue
    # Fallback: Enter
    try:
        page.keyboard.press("Enter")
        time.sleep(1.5)
        return True
    except Exception:
        return False

'''
