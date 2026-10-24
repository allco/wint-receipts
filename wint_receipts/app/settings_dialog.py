"""Settings: Wint credentials (prefilled from WINT_USER / WINT_TOKEN), recognition and upload options."""
from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from ..core import config
from ..core.config import Credentials, Settings
from ..core.models import ReferenceData
from ..core.wint import WintClient, WintError
from .fonts import PRESETS, apply_font_scale


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, reference: ReferenceData | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._fit_width()
        self._settings = settings

        creds = config.resolve_credentials(settings)
        self.user = QLineEdit(creds.user)
        self.user.setPlaceholderText(f"company id, e.g. from ${config.ENV_USER}")
        self.token = QLineEdit(creds.token)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setCursorPosition(0)  # otherwise a long masked key shows scrolled, with a cut-off dot
        self.token.setPlaceholderText(f"API key (uuid), e.g. from ${config.ENV_TOKEN}")
        show = QCheckBox("Show")
        show.toggled.connect(lambda on: self.token.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        from_env = QPushButton("Fill from environment")
        from_env.clicked.connect(self._fill_from_env)
        test = QPushButton("Test connection")
        test.clicked.connect(self._test)
        token_row = QHBoxLayout()
        token_row.addWidget(self.token)
        token_row.addWidget(show)
        buttons_row = QHBoxLayout()
        buttons_row.addWidget(from_env)
        buttons_row.addWidget(test)
        buttons_row.addStretch()
        self.base_url = QLineEdit(settings.wint_base_url)
        self.log_path = QLineEdit(settings.request_log)
        self.log_on = QCheckBox("Log every Wint request")
        self.log_on.toggled.connect(self.log_path.setEnabled)
        self.log_on.setChecked(settings.request_log_enabled)
        self.log_path.setEnabled(settings.request_log_enabled)

        wint_box = QGroupBox("Wint API")
        wf = QFormLayout(wint_box)
        wf.addRow("User name", self.user)
        wf.addRow("API key", token_row)
        wf.addRow("", buttons_row)
        wf.addRow("Base URL", self.base_url)
        wf.addRow("Request log", self.log_on)
        wf.addRow("", self.log_path)

        self.rec_log_path = QLineEdit(settings.recognition_log)
        self.rec_log_on = QCheckBox("Log app events: readings, approvals, uploads and errors")
        self.rec_log_on.toggled.connect(self.rec_log_path.setEnabled)
        self.rec_log_on.setChecked(settings.recognition_log_enabled)
        self.rec_log_path.setEnabled(settings.recognition_log_enabled)
        self.claude_path = QLineEdit(settings.claude_path)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.addItems(["sonnet", "opus", "haiku"])
        self.model.setCurrentText(settings.claude_model)
        self.dpi = QSpinBox()
        self.dpi.setRange(100, 400)
        self.dpi.setSingleStep(50)
        self.dpi.setValue(settings.recognition_dpi)
        self.parallel = QSpinBox()
        self.parallel.setRange(1, 8)
        self.parallel.setValue(settings.parallel_recognitions)
        rec_box = QGroupBox("Recognition (claude CLI)")
        rf = QFormLayout(rec_box)
        rf.addRow("claude command", self.claude_path)
        rf.addRow("Model", self.model)
        rf.addRow("Render DPI", self.dpi)
        rf.addRow("Pages in parallel", self.parallel)
        rf.addRow("Event log", self.rec_log_on)
        rf.addRow("", self.rec_log_path)

        self.learn_on = QCheckBox("Learn from my corrections")
        self.learn_on.setToolTip("When you correct the AI's category or supplier name, remember it for later receipts")
        self.learn_path = QLineEdit(settings.learnings_file)
        self.learn_on.toggled.connect(self.learn_path.setEnabled)
        self.learn_on.setChecked(settings.learnings_enabled)
        self.learn_path.setEnabled(settings.learnings_enabled)
        open_learnings = QPushButton("Open file")
        open_learnings.clicked.connect(self._open_learnings)
        learn_row = QHBoxLayout()
        learn_row.addWidget(self.learn_path)
        learn_row.addWidget(open_learnings)
        rf.addRow("AI learnings", self.learn_on)
        rf.addRow("", learn_row)

        self.payment = QComboBox()
        self.payment.addItem("(choose per receipt)", None)
        for m in reference.payment_methods if reference else []:
            self.payment.addItem(m.name, m.id)
        idx = self.payment.findData(settings.default_payment_method_id)
        if idx < 0 and settings.default_payment_method_id is not None:
            self.payment.addItem(f"id {settings.default_payment_method_id}", settings.default_payment_method_id)
            idx = self.payment.count() - 1
        self.payment.setCurrentIndex(max(idx, 0))
        self.uploads = QCheckBox("Enable uploads to Wint")
        self.uploads.setChecked(settings.uploads_enabled)
        warn = QLabel("Approved receipts are created in Wint when you click “Upload approved”. "
                      "Turn this off to only preview requests.")
        warn.setWordWrap(True)
        up_box = QGroupBox("Upload")
        uf = QFormLayout(up_box)
        uf.addRow("Default payment method", self.payment)
        self.attach_fmt = QComboBox()
        self.attach_fmt.addItem("JPEG image per page (recommended)", "jpeg")
        self.attach_fmt.addItem("PDF page from the scan", "pdf")
        self.attach_fmt.setCurrentIndex(max(self.attach_fmt.findData(settings.attachment_format), 0))
        uf.addRow("Attachment", self.attach_fmt)
        uf.addRow("", self.uploads)
        uf.addRow("", warn)

        self._original_scale = settings.font_scale
        self.font_scale = QComboBox()
        values = sorted(set(PRESETS) | {round(settings.font_scale, 2)})
        for v in values:
            self.font_scale.addItem(f"{v:.1f}×" if round(v, 1) == v else f"{v:.2f}×", v)
        self.font_scale.setCurrentIndex(values.index(round(settings.font_scale, 2)))
        self.font_scale.currentIndexChanged.connect(self._preview_font)
        ui_box = QGroupBox("Appearance")
        af = QFormLayout(ui_box)
        af.addRow("Font size", self.font_scale)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(wint_box)
        lay.addWidget(rec_box)
        lay.addWidget(up_box)
        lay.addWidget(ui_box)
        lay.addWidget(bb)

    def _fit_width(self) -> None:
        self.setMinimumWidth(self.fontMetrics().averageCharWidth() * 80)

    def _preview_font(self) -> None:
        apply_font_scale(self.font_scale.currentData())
        # Widgets update their size hints when the font-change events arrive; resize after that.
        QTimer.singleShot(0, self._relayout)

    def _relayout(self) -> None:
        self._fit_width()
        self.setMinimumHeight(0)
        self.resize(self.minimumSizeHint().expandedTo(self.sizeHint()).width(), self.sizeHint().height())

    def reject(self) -> None:
        apply_font_scale(self._original_scale)  # undo the live preview
        super().reject()

    def _open_learnings(self) -> None:
        """Open the learnings file in the system's text editor, creating it (with its header) if needed."""
        from pathlib import Path

        from ..core.learnings import Learnings

        path = Path(self.learn_path.text().strip())
        if not path.exists():
            Learnings(path).save()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _fill_from_env(self) -> None:
        env = config.env_credentials()
        if not env.complete:
            QMessageBox.information(self, "Environment", f"${config.ENV_USER} and ${config.ENV_TOKEN} are not both set.")
        if env.user:
            self.user.setText(env.user)
        if env.token:
            self.token.setText(env.token)

    def credentials(self) -> Credentials:
        return Credentials(self.user.text().strip(), self.token.text().strip())

    def _test(self) -> None:
        creds = self.credentials()
        if not creds.complete:
            QMessageBox.warning(self, "Test connection", "Enter both the user name and the API key.")
            return

        client = WintClient(creds, base_url=self.base_url.text().strip(),
                            log_path=self.apply_preview().request_log_path())
        try:
            c = client.get_json("/api/Auth", note="settings: test connection")
            QMessageBox.information(self, "Test connection", f"Connected to {c.get('Name')} (company {c.get('Id')}).")
        except WintError as e:
            QMessageBox.warning(self, "Test connection", str(e))
        finally:
            client.close()

    def apply_preview(self) -> Settings:
        """The settings as currently entered, without saving anything."""
        creds = self.credentials()
        return self._settings.model_copy(update={
            "wint_user": creds.user,
            "wint_base_url": self.base_url.text().strip() or "https://api.wint.se",
            "request_log": self.log_path.text().strip(),
            "recognition_log": self.rec_log_path.text().strip(),
            "request_log_enabled": self.log_on.isChecked(),
            "recognition_log_enabled": self.rec_log_on.isChecked(),
            "learnings_enabled": self.learn_on.isChecked(),
            "learnings_file": self.learn_path.text().strip(),
            "claude_path": self.claude_path.text().strip() or "claude",
            "claude_model": self.model.currentText().strip() or "sonnet",
            "recognition_dpi": self.dpi.value(),
            "parallel_recognitions": self.parallel.value(),
            "default_payment_method_id": self.payment.currentData(),
            "uploads_enabled": self.uploads.isChecked(),
            "attachment_format": self.attach_fmt.currentData(),
            "font_scale": self.font_scale.currentData(),
        })

    def apply(self) -> Settings:
        """Return the updated settings and store the API key in the keyring."""
        creds = self.credentials()
        s = self.apply_preview()
        if creds.token and creds.token != config.load_token(creds.user):
            if not config.save_token(creds.user, creds.token):
                QMessageBox.warning(self, "Keyring", "No system keyring is available, so the API key was not "
                                    f"saved. Set ${config.ENV_TOKEN} in the environment instead.")
        s.save()
        return s
