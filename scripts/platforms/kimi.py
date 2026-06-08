# -*- coding: utf-8 -*-
"""Kimi 平台交互 —— 聊天链接由用户提供（config.json sessions）"""
from playwright.sync_api import Page
import time

INPUT_SEL = "[contenteditable=true]"


def fill_prompt(page, prompt_text):
    editor = page.locator(INPUT_SEL).first
    if editor.count() == 0:
        return False
    editor.click(timeout=5000)
    time.sleep(0.5)
    page.evaluate("""
        (text) => {
            let el = document.querySelector('[contenteditable=true]');
            if (el) {
                el.innerText = text;
                el.dispatchEvent(new Event('input', {bubbles: true}));
            }
        }
    """, prompt_text)
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


def upload_file(page, file_path):
    """Kimi 文件上传：找 file input，不存在返回 False"""
    try:
        fi = page.locator('input[type="file"]').first
        if fi.count() > 0:
            fi.set_input_files(file_path)
            time.sleep(3)
            return True
    except Exception:
        pass
    return False


def submit(page):
    page.keyboard.press("Enter")
    time.sleep(1.5)
    return True
