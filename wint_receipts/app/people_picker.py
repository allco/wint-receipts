"""Pick participants from the Wint receipt address book: search, tick, most used first."""
from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ..core.models import ME_ID, Person
from . import theme

ROLE_PERSON = Qt.ItemDataRole.UserRole


class PeoplePicker(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._people: list[Person] = []
        self._common: set[int] = set()
        self._me: Person | None = None
        self.touched = False  # the user ticked/unticked someone since the page was shown
        self._suggested = False
        self._loading = False
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search participants…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.list = QListWidget()
        self.list.itemChanged.connect(self._item_changed)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.summary.linkActivated.connect(self._remove_link)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.summary)
        lay.addWidget(self.search)
        lay.addWidget(self.list)
        self._fit_height()

    def set_people(self, people: list[Person], common_ids: list[int], me: Person | None = None) -> None:
        selected = {p.id for p in self.selected()}
        self._people, self._common, self._me = list(people), set(common_ids), me
        self._rebuild(selected)

    def set_selected(self, people: list[Person]) -> None:
        # Someone saved on the receipt but no longer in the address book stays visible and ticked.
        known = {p.id for p in self._people}
        missing = [p for p in people if p.id not in known and p.id != ME_ID]
        if missing:
            self._people = missing + self._people
        self.touched = False
        self._suggested = False
        self._rebuild({p.id for p in people})

    def set_suggested(self, suggested: bool) -> None:
        """Show that the ticks are the app's suggestion; approving the receipt accepts them, and the
        first person the user ticks replaces the suggested guest."""
        self._suggested = suggested
        self._update_summary()

    def selected(self) -> list[Person]:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if (p := it.data(ROLE_PERSON)) is not None and it.checkState() is Qt.CheckState.Checked:
                out.append(p)
        return out

    def _rebuild(self, selected: set[int]) -> None:
        self._loading = True
        try:
            self.list.clear()
            if self._me is not None:
                label = f"{self._me.name} — {self._me.company}" if self._me.company else self._me.name
                me = QListWidgetItem(f"{label}   (you, added automatically)")
                me.setData(ROLE_PERSON, self._me)
                me.setFlags(Qt.ItemFlag.ItemIsEnabled)  # ticked and locked
                me.setCheckState(Qt.CheckState.Checked)
                self.list.addItem(me)
            groups = [("Most used", [p for p in self._people if p.id in self._common]),
                      ("Everyone else", [p for p in self._people if p.id not in self._common])]
            for title, people in groups:
                if not people:
                    continue
                header = QListWidgetItem(title)
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                f = header.font()
                f.setBold(True)
                header.setFont(f)
                self.list.addItem(header)
                for p in people:
                    label = f"{p.name} — {p.company}" if p.company else p.name
                    it = QListWidgetItem(label)
                    it.setData(ROLE_PERSON, p)
                    it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                    it.setCheckState(Qt.CheckState.Checked if p.id in selected else Qt.CheckState.Unchecked)
                    self.list.addItem(it)
        finally:
            self._loading = False
        self._filter(self.search.text())
        self._update_summary()

    def _filter(self, text: str) -> None:
        needle = text.strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            p = it.data(ROLE_PERSON)
            if p is None:  # group header: hidden while searching
                it.setHidden(bool(needle))
            elif p.id == ME_ID:
                it.setHidden(False)  # always visible: it's always included
            else:
                it.setHidden(bool(needle) and needle not in f"{p.name} {p.company}".lower())

    def _item_changed(self, item) -> None:
        if self._loading:
            return
        if self._suggested and item.checkState() is Qt.CheckState.Checked:
            self._loading = True
            try:
                for i in range(self.list.count()):
                    it = self.list.item(i)
                    p = it.data(ROLE_PERSON)
                    if it is not item and p is not None and p.id != ME_ID:
                        it.setCheckState(Qt.CheckState.Unchecked)
            finally:
                self._loading = False
        self._suggested = False
        self.touched = True
        self._update_summary()
        self.changed.emit()

    def _remove_link(self, link: str) -> None:
        pid = int(link.removeprefix("remove:"))
        for i in range(self.list.count()):
            it = self.list.item(i)
            p = it.data(ROLE_PERSON)
            if p is not None and p.id == pid and it.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                it.setCheckState(Qt.CheckState.Unchecked)

    def _update_summary(self) -> None:
        chip = f"background:{theme.CHIP_BG}; color:{theme.CHIP_TEXT};"
        parts = []
        for p in self.selected():
            name = escape(p.name)
            if p.id == ME_ID:
                parts.append(f"<span style='{chip}'>&nbsp;{name} (you)&nbsp;</span>")
            else:
                parts.append(f"<span style='{chip}'>&nbsp;{name} <a href='remove:{p.id}' "
                             f"style='text-decoration:none; color:inherit'>✕</a>&nbsp;</span>")
        text = f"<b>{len(parts)} selected:</b> " + " ".join(parts) if parts else "<b>Nobody selected</b>"
        if self._suggested:
            text = ("<span style='color:%s'>Suggested — check who was there; ticking someone replaces "
                    "the suggested guest.</span><br>" % theme.WARNING_TEXT) + text
        self.summary.setText(text)

    def _fit_height(self) -> None:
        self.list.setMinimumHeight(self.fontMetrics().height() * 9)

    def changeEvent(self, event):  # noqa: N802 - Qt API
        if event.type() == event.Type.FontChange:
            self._fit_height()
        super().changeEvent(event)
