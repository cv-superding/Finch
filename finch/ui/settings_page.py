from __future__ import annotations

import os
from datetime import datetime
import sys
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..agents import ADAPTER_CLASSES
from ..config import AppConfig, LLMConfig, OptimizerConfig, app_home
from ..core.llm import test_llm
from ..core.optimizer import PromptOptimizer
from ..store import Store
from qfluentwidgets import (
    IconWidget,
    SmoothScrollArea,
    LineEdit,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    TransparentToolButton,
)

from . import theme
from .agent_icons import agent_qicon
from .glyphs import line_icon
from .widgets import (
    HeightGrip,
    BackgroundTask,
    ElidedLabel,
    Select,
    ToggleSwitch,
    divider,
    pick_folder,
)


class SettingsPage(QWidget):
    config_saved = pyqtSignal()
    notify = pyqtSignal(str, str)

    def __init__(self, store: Store, engine, config: AppConfig, parent=None):
        super().__init__(parent)
        self.store = store
        self.engine = engine
        self.config = config
        self._bg_tasks: list[BackgroundTask] = []
        self.setObjectName("Page")
        self.sections: dict[str, QFrame] = {}
        self.side_buttons: dict[str, QPushButton] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(44, 28, 44, 16)
        root.setSpacing(0)
        header = QVBoxLayout()
        header.setSpacing(6)
        title = QLabel("设置")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        subtitle = QLabel("中断阈值、续传与补做策略、解析模型和提示词优化都在本机生效。")
        subtitle.setObjectName("PageSubtitle")
        header.addWidget(subtitle)
        root.addLayout(header)
        root.addSpacing(22)

        body = QHBoxLayout()
        body.setSpacing(16)

        # 分区导航改成顶部下划线标签，内容区拿到全部宽度
        tab_bar = QWidget()
        tab_layout = QHBoxLayout(tab_bar)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.setSpacing(28)
        self._section_order = [
            ("agents", "Agent 接入", "bot"),
            ("runtime", "运行环境", "folder"),
            ("detection", "中断检测", "timer"),
            ("followup", "自动续做", "repeat"),
            ("analyzer", "结果解析", "search"),
            ("optimizer", "提示词优化", "spark"),
            ("data", "数据与日志", "archive"),
        ]
        for key, label, _glyph in self._section_order:
            button = QPushButton(label)
            button.setObjectName("UnderlineTab")
            button.setProperty("active", key == "agents")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self._scroll_to(k))
            tab_layout.addWidget(button)
            self.side_buttons[key] = button
        tab_layout.addStretch(1)
        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("GhostButton")
        self.theme_btn.setFixedHeight(30)
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sync_theme_button()
        self.theme_btn.clicked.connect(self._toggle_theme_mode)
        tab_layout.addWidget(self.theme_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        tip = QLabel("本机存储 · 不上传")
        tip.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
        tab_layout.addWidget(tip, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(tab_bar)
        root.addSpacing(28)

        self.scroll = SmoothScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.host = QWidget()
        self.host_layout = QVBoxLayout(self.host)
        self.host_layout.setContentsMargins(0, 0, 0, 0)
        self.host_layout.setSpacing(0)
        self.scroll.setWidget(self.host)
        self.scroll.verticalScrollBar().valueChanged.connect(self._sync_nav)
        self.sheet = QFrame()
        self.sheet.setObjectName("Workspace")
        self.sections_layout = QVBoxLayout(self.sheet)
        self.sections_layout.setContentsMargins(0, 0, 0, 0)
        self.sections_layout.setSpacing(0)
        self.host_layout.addWidget(self.sheet)
        self.host_layout.addStretch(1)

        right_col = QVBoxLayout()
        right_col.setSpacing(0)
        right_col.addWidget(self.scroll, 1)
        footer_wrap = QFrame()
        footer_wrap.setObjectName("SettingsFooter")
        footer = QHBoxLayout(footer_wrap)
        footer.setContentsMargins(2, 8, 0, 0)
        self.save_status = QLabel("修改后点击保存")
        self.save_status.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12.5px;")
        footer.addWidget(self.save_status)
        footer.addStretch(1)
        self.save_btn = PrimaryPushButton("保存设置")
        self.save_btn.setFixedHeight(40)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # 库自带的 PrimaryPushButton 用的是 qfluent 主题色，这里统一到品牌色
        self.save_btn.setStyleSheet(
            "QPushButton { background: #6E6BF0; color: #FFFFFF; border: none;"
            " border-radius: 10px; padding: 0 24px; font-size: 13.5px; font-weight: 500; }"
            "QPushButton:hover { background: #7C79F5; }"
            "QPushButton:pressed { background: #5A57E0; }"
        )
        self.save_btn.clicked.connect(self.save)
        footer.addWidget(self.save_btn)
        right_col.addWidget(footer_wrap)
        body.addLayout(right_col, 1)
        root.addLayout(body, 1)

        self._section_counter = 0
        self._build_agents()
        self._build_runtime()
        self._build_detection()
        self._build_followup()
        self._build_analyzer()
        self._build_optimizer()
        self._build_data()
        self._reset_cursors()
        self._sync_optimizer_fields()

    # ------------------------------------------------------------------
    def _scroll_to(self, key: str) -> None:
        frame = self.sections.get(key)
        if not frame:
            return
        self.scroll.ensureWidgetVisible(frame, 0, 14)
        self._set_active_tab(key)

    def _set_active_tab(self, key: str) -> None:
        for name, button in self.side_buttons.items():
            active = name == key
            if bool(button.property("active")) == active:
                continue
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)

    def _sync_nav(self, value: int) -> None:
        current = self._section_order[0][0]
        for key, _label, _glyph in self._section_order:
            frame = self.sections.get(key)
            if frame and frame.y() - 24 <= value:
                current = key
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() > 0 and value >= bar.maximum() - 8:
            current = self._section_order[-1][0]
        self._set_active_tab(current)

    def _sync_theme_button(self) -> None:
        light = (getattr(self.config, "theme_mode", "dark") or "dark") == "light"
        self.theme_btn.setText("浅色主题" if light else "深色主题")
        self.theme_btn.setToolTip(
            "当前为浅色，点击切回深色（会重启应用）"
            if light
            else "当前为深色，点击切换到浅色（会重启应用）"
        )

    def _toggle_theme_mode(self) -> None:
        mode = "dark" if (getattr(self.config, "theme_mode", "dark") == "light") else "light"
        window = self.window()
        if hasattr(window, "reload_for_theme"):
            window.reload_for_theme(mode)
            return
        self.config.theme_mode = mode
        self.store.save_config(self.config)
        self._sync_theme_button()

    def _prompt_height(self, key: str, default: int) -> int:
        try:
            value = int(self.store.get_setting(key, str(default)) or default)
        except ValueError:
            value = default
        return max(72, min(460, value))

    def _card(self, key: str, title: str, subtitle: str = "") -> tuple[QWidget, QVBoxLayout]:
        self._section_counter += 1
        frame = QWidget()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        head = QVBoxLayout()
        head.setSpacing(6)
        head_row = QHBoxLayout()
        head_row.setSpacing(10)
        number = QLabel(f"{self._section_counter:02d}")
        number.setStyleSheet(
            f"color: {theme.ACCENT}; font-size: 12px; font-weight: 600;"
            f" font-family: '{theme.mono_family()}';"
        )
        head_row.addWidget(number)
        label = QLabel(title)
        label.setObjectName("CardTitle")
        head_row.addWidget(label)
        head_row.addStretch(1)
        head.addLayout(head_row)
        if subtitle:
            hint = QLabel(subtitle)
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
            head.addWidget(hint)
        layout.addLayout(head)
        layout.addSpacing(20)
        if self._section_counter > 1:
            self.sections_layout.addSpacing(48)
        self.sections_layout.addWidget(frame)
        self.sections[key] = frame
        return frame, layout

    def _row(self, title: str, description: str, control: QWidget, layout: QVBoxLayout, last: bool = False) -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 11, 0, 11)
        row_layout.setSpacing(24)
        text = QVBoxLayout()
        text.setSpacing(4)
        label = QLabel(title)
        label.setStyleSheet(f"font-size: 14px; font-weight: 500; color: {theme.TEXT};")
        text.addWidget(label)
        if description:
            desc = QLabel(description)
            desc.setWordWrap(True)
            desc.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
            text.addWidget(desc)
        row_layout.addLayout(text, 1)
        if not isinstance(control, (QPlainTextEdit, ToggleSwitch)):
            control.setFixedHeight(36)
        row_layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(row)
        if not last:
            layout.addSpacing(22)

    def _line(self, text: str = "", placeholder: str = "", password: bool = False) -> QLineEdit:
        edit = LineEdit()
        edit.setText(text)
        edit.setPlaceholderText(placeholder)
        if password:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        return edit

    def _spin(self, value: int, suffix: str, low: int = 0, high: int = 99999) -> QSpinBox:
        spin = SpinBox()
        spin.setRange(low, high)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setFixedWidth(136)
        spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        return spin

    def _switch_row(self, title: str, description: str, checked: bool, layout: QVBoxLayout, last: bool = False) -> ToggleSwitch:
        switch = ToggleSwitch(checked)
        self._row(title, description, switch, layout, last=last)
        return switch

    def _line_row(self, title: str, description: str, edit: QLineEdit, layout: QVBoxLayout, last: bool = False) -> None:
        holder = QWidget()
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.setSpacing(6)
        edit.setMinimumWidth(260)
        holder_layout.addWidget(edit)
        self._row(title, description, holder, layout, last=last)

    # ------------------------------------------------------------------
    def _build_agents(self) -> None:
        frame, layout = self._card(
            "agents",
            "Agent 接入",
            "自动检测本机 CLI，也可以填写 .exe / .cmd 的完整路径。执行时会话 ID 会随执行记录保存，用于续传。",
        )
        self.agent_path_edits: dict[str, QLineEdit] = {}
        self.agent_status: dict[str, QLabel] = {}
        for index, cls in enumerate(ADAPTER_CLASSES):
            row = QFrame()
            row.setObjectName("AgentCard")
            row.setMinimumHeight(68)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(20, 12, 20, 12)
            row_layout.setSpacing(16)
            icon = IconWidget()
            icon.setIcon(agent_qicon(cls.key))
            icon.setFixedSize(34, 34)
            row_layout.addWidget(icon)
            text = QVBoxLayout()
            text.setSpacing(4)
            name = QLabel(cls.label)
            name.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {theme.TEXT};")
            text.addWidget(name)
            desc = ElidedLabel(cls.description)
            desc.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
            desc.setToolTip(cls.description)
            text.addWidget(desc)
            row_layout.addLayout(text, 3)
            edit = LineEdit()
            edit.setText(self.config.agent_paths.get(cls.key, ""))
            edit.setPlaceholderText("自动查找 PATH" if cls.key != "mock" else "内置示例 Agent")
            edit.setEnabled(cls.key != "mock")
            edit.setMinimumWidth(240)
            edit.setMaximumWidth(300)
            edit.setFixedHeight(36)
            self.agent_path_edits[cls.key] = edit
            row_layout.addWidget(edit, 2)
            status = QLabel("")
            status.setFixedSize(64, 24)
            status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px; font-weight: 500; background: {theme.SLATE_SOFT}; border-radius: 6px;")
            self.agent_status[cls.key] = status
            row_layout.addWidget(status)
            detect = PushButton("检测")
            detect.setObjectName("GhostButton")
            detect.setFixedHeight(36)
            detect.clicked.connect(lambda _=False, k=cls.key, e=edit, s=status: self._detect_agent(k, e, s))
            row_layout.addWidget(detect)
            layout.addWidget(row)
            if index < len(ADAPTER_CLASSES) - 1:
                layout.addSpacing(16)
            self._set_agent_hint(cls.key, status)
        layout.addSpacing(20)
        hint = QLabel("新增 Agent：实现 AgentAdapter（命令构建 + 事件解析 + 会话恢复）后注册即可，无需改动调度核心。")
        hint.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def _set_agent_hint(self, key: str, label: QLabel) -> None:
        if key == "mock":
            label.setText("内置")
            label.setStyleSheet(f"color: {theme.ACCENT_DARK}; font-size: 12px; font-weight: 500; background: {theme.ACCENT_SOFT}; border-radius: 6px;")
            return
        for cls in ADAPTER_CLASSES:
            if cls.key == key:
                adapter = cls(self.config)
                path = adapter.find_executable()
                if path:
                    label.setText("已找到")
                    label.setStyleSheet(f"color: {theme.GREEN_TINT}; font-size: 12px; font-weight: 500; background: {theme.GREEN_SOFT}; border-radius: 6px;")
                    label.setToolTip(path)
                else:
                    label.setText("未找到")
                    label.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px; font-weight: 500; background: {theme.SLATE_SOFT}; border-radius: 6px;")
                    label.setToolTip("可手动填写可执行文件路径")
                return

    def _detect_agent(self, key: str, edit: QLineEdit, label: QLabel) -> None:
        label.setText("检测中…")
        label.setStyleSheet(f"color: {theme.MUTED}; font-size: 12px; font-weight: 500; background: {theme.SLATE_SOFT}; border-radius: 6px;")
        temp = AppConfig.from_json(self.config.to_json())
        temp.agent_paths[key] = edit.text().strip()
        cls = next(cls for cls in ADAPTER_CLASSES if cls.key == key)
        adapter = cls(temp)
        task = BackgroundTask(self)
        self._bg_tasks.append(task)

        def done(ok, value):
            try:
                self._bg_tasks.remove(task)
            except ValueError:
                pass
            if not ok:
                label.setText("检测失败")
                label.setStyleSheet(f"color: {theme.RED_TINT}; font-size: 12px; font-weight: 500; background: {theme.RED_SOFT}; border-radius: 6px;")
                label.setToolTip(str(value))
                return
            avail = value
            if avail.available:
                label.setText("已安装")
                label.setStyleSheet(f"color: {theme.GREEN_TINT}; font-size: 12px; font-weight: 500; background: {theme.GREEN_SOFT}; border-radius: 6px;")
                label.setToolTip(f"{avail.path}\n{avail.version}")
            else:
                label.setText("未找到")
                label.setStyleSheet(f"color: {theme.RED_TINT}; font-size: 12px; font-weight: 500; background: {theme.RED_SOFT}; border-radius: 6px;")
                label.setToolTip(avail.note)

        task.run(adapter.availability, done)

    # ------------------------------------------------------------------
    def _build_runtime(self) -> None:
        frame, layout = self._card("runtime", "运行环境", "默认工作目录用于没有单独指定目录的任务；每个任务也可以覆盖。")
        cwd_row = QWidget()
        row_layout = QHBoxLayout(cwd_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        self.cwd_edit = LineEdit()
        self.cwd_edit.setText(self.config.cwd)
        self.cwd_edit.setMinimumWidth(260)
        self.cwd_edit.setPlaceholderText("留空时为每个任务创建独立目录")
        row_layout.addWidget(self.cwd_edit)
        browse = PushButton("浏览")
        browse.setFixedHeight(32)
        browse.clicked.connect(self._browse_cwd)
        row_layout.addWidget(browse)
        self._row("默认工作目录", "Agent 会在这个目录中执行任务。", cwd_row, layout)
        self.permission_select = Select(
            options=[
                ("acceptEdits", "自动接受文件编辑"),
                ("default", "默认权限询问"),
                ("dontAsk", "不询问（拒绝危险动作）"),
                ("bypassPermissions", "跳过权限检查（谨慎）"),
                ("plan", "计划模式"),
            ],
            value=self.config.permission_mode,
        )
        self.permission_select.setMinimumWidth(210)
        self._row("Claude 权限模式", "仅对 Claude Code 生效，其他 Agent 使用自身配置。", self.permission_select, layout)
        self.isolate_mcp = self._switch_row(
            "跳过 MCP / 插件配置启动 Claude",
            "启动更稳定；需要 MCP 工具时请关闭。",
            self.config.isolate_mcp,
            layout,
            last=True,
        )

    def _browse_cwd(self) -> None:
        path = pick_folder(self.window(), self.cwd_edit.text(), "选择默认工作目录")
        if path:
            self.cwd_edit.setText(path)

    # ------------------------------------------------------------------
    def _build_detection(self) -> None:
        frame, layout = self._card(
            "detection",
            "中断检测与续传",
            "工具执行期间暂停普通超时检测，只受工具超长阈值约束；工具结束后恢复正常文本检测。",
        )
        self.text_timeout = self._spin(self.config.text_idle_timeout, " 秒", 5, 3600)
        self._row("纯文本空闲超时", "无工具调用时，连续多久没有新内容判定为中断。", self.text_timeout, layout)
        self.first_grace = self._spin(self.config.first_output_grace, " 秒", 10, 3600)
        self._row("首包宽限", "启动后等待模型首个输出的上限，避免慢模型被误判。", self.first_grace, layout)
        self.tool_timeout = self._spin(self.config.tool_timeout, " 秒", 10, 7200)
        self._row("工具执行超时", "安装、构建、下载等工具连续无进度输出时的上限。", self.tool_timeout, layout)
        self.max_resume = self._spin(self.config.max_resumes, " 次", 0, 20)
        self._row("最大续传次数", "达到上限后标记「待人工」并弹窗提醒，停止自动重试。", self.max_resume, layout)
        self.max_followup = self._spin(self.config.max_followups, " 轮", 0, 20)
        self._row("最大补做轮次", "验收发现遗留项时，最多自动补做的轮次。", self.max_followup, layout, last=True)

    # ------------------------------------------------------------------
    def _build_followup(self) -> None:
        frame, layout = self._card("followup", "自动续做", "续传只恢复原会话；补做会根据验收出的缺漏生成新指令。")
        self.auto_followup = self._switch_row(
            "自动补做",
            "回复结束后识别未完成项与问题，并自动生成补做提示词。",
            self.config.auto_followup,
            layout,
        )
        self.confirm_followup = self._switch_row(
            "补做前人工确认",
            "补做提示词生成后先暂停，可在任务详情中编辑、下发或跳过。",
            self.config.confirm_followup,
            layout,
        )
        self.optimize_followup = self._switch_row(
            "补做提示词先经过优化",
            "调用 prompt-optimizer 或内置优化模型后再下发，会增加耗时。",
            self.config.optimize_followup,
            layout,
        )
        self.optimize_continue = self._switch_row(
            "续传指令先经过优化",
            "中断续传前先优化续传指令模板，再回到原会话继续。",
            self.config.optimize_continue,
            layout,
        )
        continue_label = QLabel("续传指令模板")
        continue_label.setObjectName("FieldLabel")
        layout.addWidget(continue_label)
        self.continue_prompt = PlainTextEdit()
        self.continue_prompt.setPlainText(self.config.continue_prompt)
        self.continue_prompt.setFixedHeight(
            self._prompt_height("prompt_height_continue", 120)
        )
        self.continue_prompt.setObjectName("PromptEdit")
        self.continue_prompt.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        layout.addWidget(self.continue_prompt)
        continue_grip = HeightGrip(self.continue_prompt, default=120)
        continue_grip.finished.connect(
            lambda height: self.store.set_setting("prompt_height_continue", str(height))
        )
        layout.addWidget(continue_grip)
        followup_label = QLabel("补做指令模板")
        followup_label.setObjectName("FieldLabel")
        layout.addWidget(followup_label)
        self.followup_template = PlainTextEdit()
        self.followup_template.setPlainText(self.config.followup_template)
        self.followup_template.setFixedHeight(
            self._prompt_height("prompt_height_followup", 168)
        )
        self.followup_template.setObjectName("PromptEdit")
        self.followup_template.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        layout.addWidget(self.followup_template)
        followup_grip = HeightGrip(self.followup_template, default=168)
        followup_grip.finished.connect(
            lambda height: self.store.set_setting("prompt_height_followup", str(height))
        )
        layout.addWidget(followup_grip)
        hint = QLabel("可用占位符：{task} 原任务、{summary} 摘要、{items} 缺漏与问题、{title} 标题。")
        hint.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")
        layout.addWidget(hint)

    # ------------------------------------------------------------------
    def _build_analyzer(self) -> None:
        frame, layout = self._card(
            "analyzer",
            "结果解析模型",
            "优先调用 OpenAI 兼容接口做语义提取；未启用或调用失败时自动回退到关键词/正则规则。",
        )
        self.analyzer_enabled = self._switch_row(
            "启用大模型语义解析",
            "需要填写 Base URL、API Key 与模型名。密钥仅保存在本机。",
            self.config.analyzer.enabled,
            layout,
        )
        self.analyzer_base = LineEdit()
        self.analyzer_base.setText(self.config.analyzer.base_url)
        self.analyzer_base.setPlaceholderText("https://api.openai.com/v1")
        self._line_row("Base URL", "例如 https://api.deepseek.com/v1 或本地 Ollama/vLLM 地址。", self.analyzer_base, layout)
        key_holder = QWidget()
        key_layout = QHBoxLayout(key_holder)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.setSpacing(4)
        self.analyzer_key = LineEdit()
        self.analyzer_key.setText(self.config.analyzer.api_key)
        self.analyzer_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.analyzer_key.setPlaceholderText("sk-…")
        key_layout.addWidget(self.analyzer_key)
        show = TransparentToolButton("显示")
        show.setFixedWidth(44)
        show.setCheckable(True)
        show.toggled.connect(
            lambda checked: self.analyzer_key.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        key_layout.addWidget(show)
        self._row("API Key", "仅用于解析结果，不会写入任务日志。", key_holder, layout)
        self.analyzer_model = LineEdit()
        self.analyzer_model.setText(self.config.analyzer.model)
        self.analyzer_model.setPlaceholderText("gpt-4o-mini / deepseek-chat")
        self._line_row("模型", "建议使用支持 JSON 输出的指令模型。", self.analyzer_model, layout)
        self.analyzer_hints = PlainTextEdit()
        self.analyzer_hints.setPlainText(self.config.analyzer_hints)
        self.analyzer_hints.setFixedHeight(56)
        self.analyzer_hints.setObjectName("PromptEdit")
        self.analyzer_hints.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.analyzer_hints.setPlaceholderText("识别偏好，例如：把未运行的测试视为遗留问题")
        self._row("识别偏好", "会附加到解析提示词中；人工修正也会作为示例自动参考。", self.analyzer_hints, layout)
        test_row = QWidget()
        test_layout = QHBoxLayout(test_row)
        test_layout.setContentsMargins(0, 0, 0, 0)
        test_layout.setSpacing(8)
        self.analyzer_test = QLabel("")
        self.analyzer_test.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 13px;")
        test_layout.addWidget(self.analyzer_test)
        test = PushButton("测试连接")
        test.clicked.connect(self._test_analyzer)
        test_layout.addWidget(test)
        self._row("连接检查", "发送一条最小请求验证配置。", test_row, layout, last=True)

    def _analyzer_config_from_form(self) -> LLMConfig:
        return LLMConfig(
            enabled=self.analyzer_enabled.isChecked(),
            base_url=self.analyzer_base.text().strip(),
            api_key=self.analyzer_key.text().strip(),
            model=self.analyzer_model.text().strip(),
            timeout=self.config.analyzer.timeout,
        )

    def _test_analyzer(self) -> None:
        cfg = self._analyzer_config_from_form()
        if not cfg.base_url or not cfg.model:
            self.analyzer_test.setText("请先填写 Base URL 与模型")
            self.analyzer_test.setStyleSheet(f"color: {theme.ORANGE}; font-size: 13px;")
            return
        self.analyzer_test.setText("测试中…")
        self.analyzer_test.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
        task = BackgroundTask(self)
        self._bg_tasks.append(task)

        def done(ok, value):
            try:
                self._bg_tasks.remove(task)
            except ValueError:
                pass
            if ok and value[0]:
                self.analyzer_test.setText("连接成功：" + str(value[1])[:60])
                self.analyzer_test.setStyleSheet(f"color: {theme.GREEN}; font-size: 13px;")
            else:
                self.analyzer_test.setText("失败：" + (str(value[1]) if ok else str(value))[:120])
                self.analyzer_test.setStyleSheet(f"color: {theme.RED}; font-size: 13px;")

        task.run(lambda: test_llm(cfg), done)

    # ------------------------------------------------------------------
    def _build_optimizer(self) -> None:
        frame, layout = self._card(
            "optimizer",
            "提示词优化",
            "调用 prompt-optimizer MCP（推荐 Docker 部署）或内置优化模型，支持用户提示词与系统提示词。",
        )
        self.optimizer_mode = Select(
            options=[
                ("auto", "自动（MCP 优先，失败回退内置）"),
                ("mcp", "仅 prompt-optimizer MCP"),
                ("builtin", "仅内置优化模型"),
                ("off", "关闭优化"),
            ],
            value=self.config.optimizer.mode,
        )
        self.optimizer_mode.setMinimumWidth(250)
        self._row("优化方式", "「优化提示词」按钮与自动补做优化共用此设置。", self.optimizer_mode, layout)
        self.mcp_url = LineEdit()
        self.mcp_url.setText(self.config.optimizer.mcp_url)
        self.mcp_url.setPlaceholderText("http://localhost:8081/mcp")
        self._line_row("MCP 地址", "prompt-optimizer Docker 默认 http://localhost:8081/mcp", self.mcp_url, layout)
        self.optimizer_template = LineEdit()
        self.optimizer_template.setText(self.config.optimizer.template)
        self.optimizer_template.setPlaceholderText("general（可留空）")
        self._line_row("优化模板", "对应 prompt-optimizer 的模板 ID，留空使用默认。", self.optimizer_template, layout)
        test_row = QWidget()
        test_layout = QHBoxLayout(test_row)
        test_layout.setContentsMargins(0, 0, 0, 0)
        test_layout.setSpacing(8)
        self.mcp_test = QLabel("")
        self.mcp_test.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 13px;")
        test_layout.addWidget(self.mcp_test)
        test = PushButton("测试 MCP")
        test.clicked.connect(self._test_mcp)
        test_layout.addWidget(test)
        self._row("MCP 连接检查", "验证服务与 optimize-user/system-prompt 工具是否可用。", test_row, layout)
        self.use_optimizer_model = self._switch_row(
            "使用独立的优化模型",
            "关闭时复用上方「结果解析模型」配置。",
            self.config.optimizer.use_optimizer_model,
            layout,
        )
        self.use_optimizer_model.toggled.connect(lambda _checked: self._sync_optimizer_fields())
        self.opt_base = LineEdit()
        self.opt_base.setText(self.config.optimizer.base_url)
        self.opt_base.setPlaceholderText("https://api.openai.com/v1")
        self._line_row("优化 Base URL", "", self.opt_base, layout)
        self.opt_key = LineEdit()
        self.opt_key.setText(self.config.optimizer.api_key)
        self.opt_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.opt_key.setPlaceholderText("sk-…")
        self._line_row("优化 API Key", "", self.opt_key, layout)
        self.opt_model = LineEdit()
        self.opt_model.setText(self.config.optimizer.model)
        self.opt_model.setPlaceholderText("gpt-4o-mini")
        self._line_row("优化模型", "", self.opt_model, layout, last=True)

    def _sync_optimizer_fields(self) -> None:
        enabled = self.use_optimizer_model.isChecked()
        for edit in (self.opt_base, self.opt_key, self.opt_model):
            edit.setEnabled(enabled)

    def _reset_cursors(self) -> None:
        for edit in self.findChildren(QLineEdit):
            edit.setCursorPosition(0)

    def _test_mcp(self) -> None:
        temp = AppConfig.from_json(self.config.to_json())
        temp.optimizer.mcp_url = self.mcp_url.text().strip()
        self.mcp_test.setText("测试中…")
        self.mcp_test.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
        task = BackgroundTask(self)
        self._bg_tasks.append(task)

        def done(ok, value):
            try:
                self._bg_tasks.remove(task)
            except ValueError:
                pass
            if ok and value[0]:
                self.mcp_test.setText("已连接：" + str(value[1])[:100])
                self.mcp_test.setStyleSheet(f"color: {theme.GREEN}; font-size: 13px;")
            else:
                self.mcp_test.setText("未连接：" + (str(value[1]) if ok else str(value))[:120])
                self.mcp_test.setStyleSheet(f"color: {theme.ORANGE}; font-size: 13px;")

        task.run(lambda: PromptOptimizer(temp).test_mcp(), done)

    # ------------------------------------------------------------------
    def _build_data(self) -> None:
        frame, layout = self._card("data", "数据与日志", "任务队列、执行记录与完整日志全部保存在本机。")
        path_label = QLabel(str(app_home()))
        path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_label.setStyleSheet(f"color: {theme.TEXT_SOFT}; font-size: 13px;")
        holder = QWidget()
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.addWidget(path_label, 1)
        open_btn = PushButton("打开目录")
        open_btn.clicked.connect(self._open_data_dir)
        holder_layout.addWidget(open_btn)
        self._row("数据目录", "可直接备份 finch.db 与 logs 文件夹。", holder, layout, last=True)

    def _open_data_dir(self) -> None:
        path = str(app_home())
        if os.name == "nt":
            os.startfile(path)
        else:
            import subprocess

            subprocess.Popen(["xdg-open", path])

    # ------------------------------------------------------------------
    def reload(self) -> None:
        cfg = self.engine.config
        self.config = cfg
        for key, edit in self.agent_path_edits.items():
            edit.setText(cfg.agent_paths.get(key, ""))
        for key, label in self.agent_status.items():
            self._set_agent_hint(key, label)
        self.cwd_edit.setText(cfg.cwd)
        self.permission_select.set_value(cfg.permission_mode)
        self.isolate_mcp.setChecked(cfg.isolate_mcp)
        self.text_timeout.setValue(cfg.text_idle_timeout)
        self.first_grace.setValue(cfg.first_output_grace)
        self.tool_timeout.setValue(cfg.tool_timeout)
        self.max_resume.setValue(cfg.max_resumes)
        self.max_followup.setValue(cfg.max_followups)
        self.auto_followup.setChecked(cfg.auto_followup)
        self.confirm_followup.setChecked(cfg.confirm_followup)
        self.optimize_followup.setChecked(cfg.optimize_followup)
        self.optimize_continue.setChecked(cfg.optimize_continue)
        self.continue_prompt.setPlainText(cfg.continue_prompt)
        self.followup_template.setPlainText(cfg.followup_template)
        self.analyzer_enabled.setChecked(cfg.analyzer.enabled)
        self.analyzer_base.setText(cfg.analyzer.base_url)
        self.analyzer_key.setText(cfg.analyzer.api_key)
        self.analyzer_model.setText(cfg.analyzer.model)
        self.analyzer_hints.setPlainText(cfg.analyzer_hints)
        self.optimizer_mode.set_value(cfg.optimizer.mode)
        self.mcp_url.setText(cfg.optimizer.mcp_url)
        self.optimizer_template.setText(cfg.optimizer.template)
        self.use_optimizer_model.setChecked(cfg.optimizer.use_optimizer_model)
        self.opt_base.setText(cfg.optimizer.base_url)
        self.opt_key.setText(cfg.optimizer.api_key)
        self.opt_model.setText(cfg.optimizer.model)
        self._sync_optimizer_fields()
        self._reset_cursors()
        self.save_status.setText("当前配置已加载")
        self.save_status.setStyleSheet(f"color: {theme.SUBTLE}; font-size: 12px;")

    def save(self) -> None:
        cfg = self.config
        cfg.agent_paths = {key: edit.text().strip() for key, edit in self.agent_path_edits.items()}
        cfg.cwd = self.cwd_edit.text().strip()
        cfg.permission_mode = self.permission_select.value()
        cfg.isolate_mcp = self.isolate_mcp.isChecked()
        cfg.text_idle_timeout = self.text_timeout.value()
        cfg.first_output_grace = self.first_grace.value()
        cfg.tool_timeout = self.tool_timeout.value()
        cfg.max_resumes = self.max_resume.value()
        cfg.max_followups = self.max_followup.value()
        cfg.auto_followup = self.auto_followup.isChecked()
        cfg.confirm_followup = self.confirm_followup.isChecked()
        cfg.optimize_followup = self.optimize_followup.isChecked()
        cfg.optimize_continue = self.optimize_continue.isChecked()
        cfg.continue_prompt = self.continue_prompt.toPlainText().strip()
        cfg.followup_template = self.followup_template.toPlainText().strip()
        cfg.analyzer = self._analyzer_config_from_form()
        cfg.analyzer_hints = self.analyzer_hints.toPlainText().strip()
        cfg.optimizer = OptimizerConfig(
            mode=self.optimizer_mode.value(),
            mcp_url=self.mcp_url.text().strip(),
            template=self.optimizer_template.text().strip() or "general",
            use_optimizer_model=self.use_optimizer_model.isChecked(),
            base_url=self.opt_base.text().strip(),
            api_key=self.opt_key.text().strip(),
            model=self.opt_model.text().strip(),
        )
        if cfg.analyzer.enabled and (not cfg.analyzer.base_url or not cfg.analyzer.model):
            self.notify.emit("语义解析已启用，但 Base URL / 模型未填写，将回退到规则识别", "warning")
        self.store.save_config(cfg)
        self.engine.update_config(cfg)
        self.save_status.setText("已保存 · " + datetime.now().strftime("%H:%M:%S"))
        self.save_status.setStyleSheet(f"color: {theme.GREEN_TINT}; font-size: 12px;")
        for key, label in self.agent_status.items():
            self._set_agent_hint(key, label)
        self.notify.emit("设置已保存", "success")
        self.config_saved.emit()
