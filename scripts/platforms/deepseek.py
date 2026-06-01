# -*- coding: utf-8 -*-
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

def wait_for_response(page, timeout=180):
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        time.sleep(5)
        txt = page.evaluate("() => document.body ? document.body.innerText : ''")
        if txt and len(txt) > len(last) + 50:
            last = txt
        elif txt and len(txt) > 200 and txt == last:
            time.sleep(5)
            t2 = page.evaluate("() => document.body ? document.body.innerText : ''")
            if t2 == txt:
                return t2
        last = txt
    return page.evaluate("() => document.body ? document.body.innerText : ''")
