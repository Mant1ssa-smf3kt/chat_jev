"""设置窗口：填 Jev 的 API key、关系、可选的「下一步建议」LLM，保存到 ~/Library/Application Support/chat-jev/.env。

第一次打开 app 没有 key 时模态弹出；之后从菜单栏「设置…」打开，保存后立即生效。必须在主线程调用。
"""

from __future__ import annotations

from typing import Callable

import objc
from AppKit import (
    NSApplication,
    NSBackingStoreBuffered,
    NSButton,
    NSButtonTypeSwitch,
    NSColor,
    NSFont,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSPopUpButton,
    NSSecureTextField,
    NSTextField,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSObject

from .config import CONFIG_FILE, parse_env, write_env

BACKENDS = [("vercel", "Vercel AI Gateway", "AI_GATEWAY_API_KEY"),
            ("typesafe", "TypeSafe 直连", "TYPESAFE_API_KEY")]
FLAVORS = [("anthropic", "Anthropic 格式"), ("openai", "OpenAI 格式")]

W, LABEL_W, PAD, ROW = 480, 130, 20, 34


def install_edit_menu() -> None:
    """菜单栏 app 默认没有主菜单，⌘V / ⌘C / ⌘A 在输入框里就不灵。补一个（不会显示出来）。"""
    app = NSApplication.sharedApplication()
    if app.mainMenu() is not None:
        return
    main, edit = NSMenu.alloc().init(), NSMenu.alloc().initWithTitle_("编辑")
    for title, sel, key in [("撤销", "undo:", "z"), ("剪切", "cut:", "x"), ("拷贝", "copy:", "c"),
                            ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")]:
        edit.addItem_(NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, sel, key))
    holder = NSMenuItem.alloc().init()
    holder.setSubmenu_(edit)
    main.addItem_(holder)
    app.setMainMenu_(main)


class _Target(NSObject):
    def initWithOwner_(self, owner):
        self = objc.super(_Target, self).init()
        if self is None:
            return None
        self.owner = owner
        return self

    def save_(self, sender):
        self.owner._save()

    def cancel_(self, sender):
        self.owner._close(False)

    def backendChanged_(self, sender):
        self.owner._load_key()

    def windowWillClose_(self, note):
        self.owner._closed()


class SettingsWindow:
    def __init__(self, on_saved: Callable[[], None] | None = None, first_run: bool = False) -> None:
        self.on_saved = on_saved
        self.saved = False
        self._modal = False
        self._target = _Target.alloc().initWithOwner_(self)
        self._env = parse_env(CONFIG_FILE)

        rows = 8
        h = PAD * 2 + ROW * rows + 150
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, h), NSWindowStyleMaskTitled | NSWindowStyleMaskClosable, NSBackingStoreBuffered, False)
        self.window.setTitle_("chat-jev 设置")
        self.window.setReleasedWhenClosed_(False)
        self.window.setDelegate_(self._target)
        view = self.window.contentView()

        y = h - PAD - 22
        intro = "欢迎使用 chat-jev，填上 Jev 的 API key 就能开始。" if first_run else "保存后立即生效，不用重启。"
        self._text(view, intro, NSMakeRect(PAD, y, W - 2 * PAD, 20), 13, bold=first_run)
        self._text(view, "保存在 " + str(CONFIG_FILE).replace(str(CONFIG_FILE.home()), "~") + "，只有你自己可读",
                   NSMakeRect(PAD, y - 20, W - 2 * PAD, 18), 11, secondary=True)
        y -= 56

        self.backend = self._popup(view, "Jev 接入方式", [b[1] for b in BACKENDS], y)
        cur = self._env.get("JEV_BACKEND", "vercel")
        self.backend.selectItemAtIndex_(next((i for i, b in enumerate(BACKENDS) if b[0] == cur), 0))
        self.backend.setTarget_(self._target)
        self.backend.setAction_("backendChanged:")
        y -= ROW
        self.key = self._field(view, "Jev API key", y, secure=True, placeholder="必填")
        y -= ROW
        self.relation = self._field(view, "对方是你的", y, placeholder="女朋友")
        self.relation.setStringValue_(self._env.get("JEV_RELATION", "女朋友"))
        y -= ROW + 14

        self._text(view, "「下一步建议」（可选，不填就只判 YES / NO）", NSMakeRect(PAD, y, W - 2 * PAD, 20), 13, bold=True)
        y -= ROW
        self.llm_key = self._field(view, "LLM API key", y, secure=True, placeholder="留空 = 不启用")
        self.llm_key.setStringValue_(self._env.get("LLM_API_KEY", ""))
        y -= ROW
        self.flavor = self._popup(view, "接口格式", [f[1] for f in FLAVORS], y)
        cur = self._env.get("LLM_FLAVOR", "anthropic")
        self.flavor.selectItemAtIndex_(next((i for i, f in enumerate(FLAVORS) if f[0] == cur), 0))
        y -= ROW
        self.llm_base = self._field(view, "接口地址", y, placeholder="直连 Anthropic 留空")
        self.llm_base.setStringValue_(self._env.get("LLM_BASE_URL", ""))
        y -= ROW
        self.llm_model = self._field(view, "模型", y, placeholder="claude-opus-5")
        self.llm_model.setStringValue_(self._env.get("LLM_MODEL", ""))
        y -= ROW + 10

        self.auto_update = NSButton.alloc().initWithFrame_(NSMakeRect(PAD + LABEL_W, y, W - 2 * PAD - LABEL_W, 22))
        self.auto_update.setButtonType_(NSButtonTypeSwitch)
        self.auto_update.setTitle_("有新版本时自动更新")
        self.auto_update.setState_(0 if self._env.get("JEV_AUTO_UPDATE", "1") == "0" else 1)
        view.addSubview_(self.auto_update)

        self.error = self._text(view, "", NSMakeRect(PAD, PAD + 4, W - 2 * PAD - 200, 20), 12)
        self.error.setTextColor_(NSColor.systemRedColor())
        save = self._button(view, "保存", NSMakeRect(W - PAD - 90, PAD, 90, 30), "save:")
        save.setKeyEquivalent_("\r")
        self._button(view, "退出" if first_run else "取消", NSMakeRect(W - PAD - 190, PAD, 90, 30), "cancel:")
        self._load_key()

    # -- 对外 ------------------------------------------------------------------

    def show(self) -> None:
        install_edit_menu()
        self.window.center()
        self.window.makeKeyAndOrderFront_(None)
        self.window.makeFirstResponder_(self.key)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def run_modal(self) -> bool:
        """模态显示，关窗后返回有没有保存。"""
        self._modal = True
        self.show()
        NSApplication.sharedApplication().runModalForWindow_(self.window)
        return self.saved

    # -- 内部 ------------------------------------------------------------------

    def _key_var(self) -> str:
        if self._env.get("JEV_API_KEY"):
            return "JEV_API_KEY"                      # 手写过通用的 key 就沿用
        return BACKENDS[self.backend.indexOfSelectedItem()][2]

    def _load_key(self) -> None:
        self.key.setStringValue_(self._env.get(self._key_var(), ""))

    def _save(self) -> None:
        key = self.key.stringValue().strip()
        if not key:
            self.error.setStringValue_("Jev API key 不能为空")
            return
        values = {
            "JEV_BACKEND": BACKENDS[self.backend.indexOfSelectedItem()][0],
            self._key_var(): key,
            "JEV_RELATION": self.relation.stringValue().strip() or "女朋友",
            "LLM_API_KEY": self.llm_key.stringValue().strip(),
            "LLM_FLAVOR": FLAVORS[self.flavor.indexOfSelectedItem()][0],
            "LLM_BASE_URL": self.llm_base.stringValue().strip(),
            "LLM_MODEL": self.llm_model.stringValue().strip(),
            "JEV_AUTO_UPDATE": "1" if self.auto_update.state() else "0",
        }
        try:
            write_env(CONFIG_FILE, values)
        except OSError as e:
            self.error.setStringValue_(f"保存失败：{e}")
            return
        self.saved = True
        self._close(True)
        if self.on_saved is not None:
            self.on_saved()

    def _close(self, saved: bool) -> None:
        self.saved = saved
        self.window.close()

    def _closed(self) -> None:
        if self._modal:
            self._modal = False
            NSApplication.sharedApplication().stopModal()

    def _text(self, view, text, frame, size, bold=False, secondary=False):
        f = NSTextField.alloc().initWithFrame_(frame)
        f.setStringValue_(text)
        f.setBezeled_(False); f.setDrawsBackground_(False); f.setEditable_(False); f.setSelectable_(False)
        f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
        if secondary:
            f.setTextColor_(NSColor.secondaryLabelColor())
        view.addSubview_(f)
        return f

    def _label(self, view, text, y):
        lab = self._text(view, text, NSMakeRect(PAD, y + 3, LABEL_W - 10, 20), 13)
        lab.setAlignment_(2)                          # 右对齐
        return lab

    def _field(self, view, label, y, secure=False, placeholder=""):
        self._label(view, label, y)
        cls = NSSecureTextField if secure else NSTextField
        f = cls.alloc().initWithFrame_(NSMakeRect(PAD + LABEL_W, y, W - 2 * PAD - LABEL_W, 24))
        f.setPlaceholderString_(placeholder)
        view.addSubview_(f)
        return f

    def _popup(self, view, label, items, y):
        self._label(view, label, y)
        p = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(PAD + LABEL_W - 3, y - 2, 220, 28), False)
        p.addItemsWithTitles_(items)
        view.addSubview_(p)
        return p

    def _button(self, view, title, frame, action):
        b = NSButton.alloc().initWithFrame_(frame)
        b.setTitle_(title)
        b.setBezelStyle_(1)                           # NSBezelStyleRounded
        b.setTarget_(self._target)
        b.setAction_(action)
        view.addSubview_(b)
        return b


_open: SettingsWindow | None = None                   # 非模态打开时留个引用，免得被回收


def open_settings(on_saved: Callable[[], None] | None = None) -> None:
    global _open
    if _open is not None and _open.window.isVisible():
        _open.show()
        return
    _open = SettingsWindow(on_saved=on_saved)
    _open.show()
