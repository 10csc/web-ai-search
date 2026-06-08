# -*- coding: utf-8 -*-
"""DeepSeek 平台交互模块"""

from playwright.sync_api import Page
import time

CAPABILITIES = ["text_input", "file_upload"]
FILL_SEL = "[contenteditable=true], textarea, [role=textbox]"
EXTRACT_SEL = 'div[class*="message"][class*="assistant"]'


def fill_prompt(page, prompt_text):
    el = page.locator(FILL_SEL).first
    el.click(timeout=5000)
    time.sleep(0.5)
    page.keyboard.press("Control+a")
    page.keyboard.press("Backspace")
    time.sleep(0.2)
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
    for sel in ["button[aria-label=发送]", "button[aria-label=Send]",
                "[aria-label=Send message]", "button[data-testid=send-button]"]:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                btn.click(timeout=3000)
                time.sleep(1.5)
                return True
        except Exception:
            continue
    try:
        page.keyboard.press("Enter")
        time.sleep(1.5)
        return True
    except Exception:
        return False


def upload_file(page, file_path):
    try:
        file_input = page.locator('input[type="file"]').first
        file_input.wait_for(state="attached", timeout=5000)
        file_input.set_input_files(file_path)
        time.sleep(2)
        return True
    except Exception as e:
        print(f"  [DeepSeek] 上传文件失败: {e}")
        return False
