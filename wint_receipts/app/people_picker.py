"""Pick people from the Wint receipt address book: search, tick, most used first."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ..core.models import Person

ROLE_PERSON = Qt.ItemDataRole.UserRole


class PeoplePicker(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._people: list[Person] = []
        self._common: set[int] = set()
        self._loading = False
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search people…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.list = QListWidget()
        self.list.itemChanged.connect(self._item_changed)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.search)
        lay.addWidget(self.list)
        lay.addWidget(self.summary)
        self._fit_height()

    def set_people(self, people: list[Person], common_ids: list[int]) -> None:
        selected = {p.id for p in self.selected()}
        self._people, self._common = list(people), set(common_ids)
        self._rebuild(selected)

    def set_selected(self, people: list[Person]) -> None:
        # Someone saved on the receipt but no longer in the address book stays visible and ticked.
        known = {p.id for p in self._people}
        missing = [p for p in people if p.id not in known]
        if missing:
            self._people = missing + self._people
        self._rebuild({p.id for p in people})

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
            else:
                it.setHidden(bool(needle) and needle not in f"{p.name} {p.company}".lower())

    def _item_changed(self, _item) -> None:
        if not self._loading:
            self._update_summary()
            self.changed.emit()

    def _update_summary(self) -> None:
        names = [p.name for p in self.selected()]
        self.summary.setText(f"{len(names)} selected: " + ", ".join(names) if names else "Nobody selected")

    def _fit_height(self) -> None:
        self.list.setMinimumHeight(self.fontMetrics().height() * 9)

    def changeEvent(self, event):  # noqa: N802 - Qt API
        if event.type() == event.Type.FontChange:
            self._fit_height()
        super().changeEvent(event)
