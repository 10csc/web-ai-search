# -*- coding: utf-8 -*-
"""SCnet (kimi.moonshot.cn) 平台交互模块"""
from playwright.sync_api import Page
import time

# SCnet 主输入框选择器（用容器定位，避免取到 hidden textarea）
INPUT_SEL = ".textarea-with-prefix textarea.el-textarea__inner"


def fill_prompt(page, prompt_text):
    textarea = page.locator(INPUT_SEL).first
    textarea.wait_for(state="visible", timeout=5000)
    textarea.click(timeout=5000)
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
    """SCnet：Enter 发送"""
    page.keyboard.press("Enter")
    time.sleep(1.5)
    return True


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