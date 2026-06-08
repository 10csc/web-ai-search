# -*- coding: utf-8 -*-
"""Kimi 平台交互模块 —— 聊天链接由用户提供（config.json sessions）"""

from playwright.sync_api import Page
import time

CAPABILITIES = ["text_input", "file_upload"]
FILL_SEL = "[contenteditable=true]"
EXTRACT_SEL = 'div[class*="chat-content-item-assistant"]'
VERIFY_BY_INPUT_CLEAR = False  # contenteditable 发送后不清空


def fill_prompt(page, prompt_text):
    editor = page.locator(FILL_SEL).first
    if editor.count() == 0:
        editor = page.locator("textarea").first
        if editor.count() == 0:
            return False
    editor.click(timeout=5000)
    time.sleep(0.3)
    # Kimi React contenteditable: Ctrl+A 无效，用 Home+Shift+End 选中全部
    page.keyboard.press("Control+Home")
    time.sleep(0.1)
    page.keyboard.press("Control+Shift+End")
    time.sleep(0.1)
    page.keyboard.press("Backspace")
    time.sleep(0.2)
    page.keyboard.insert_text(prompt_text)
    time.sleep(0.5)
    return True


def dismiss_blockers(page):
    """Kimi: 不按 Escape（React contenteditable 上 Escape 会取消输入清除焦点）"""
    try:
        page.on("dialog", lambda d: d.accept())
    except Exception:
        pass


def submit(page):
    page.keyboard.press("Enter")
    time.sleep(1.5)
    return True


def upload_file(page, file_path):
    """Kimi 文件上传：先点 toolkit 按钮，再找 file input"""
    try:
        for sel in [".toolkit-trigger-btn", "[class*=toolkit] button", "button[class*=toolkit]"]:
            try:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible(timeout=2000):
                    btn.click(timeout=3000)
                    time.sleep(1)
                    break
            except Exception:
                continue
        fi = page.locator('input[type="file"]').first
        if fi.count() > 0:
            fi.set_input_files(file_path)
            time.sleep(3)
            return True
    except Exception as e:
        print(f"  [Kimi] 上传文件失败: {e}")
    return False
