"""Edit Wint's receipt address book: the people you can pick as participants."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout,
)

from ..core.models import Person
from ..core.wint import WintClient
from .workers import Job

ROLE_PERSON = Qt.ItemDataRole.UserRole


class PersonDialog(QDialog):
    def __init__(self, title: str, person: Person | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.name = QLineEdit(person.name if person else "")
        self.company = QLineEdit(person.company if person else "")
        self.company.setPlaceholderText("e.g. EasyPark, Private person")
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.save = bb.button(QDialogButtonBox.StandardButton.Save)
        self.name.textChanged.connect(lambda t: self.save.setEnabled(bool(t.strip())))
        self.save.setEnabled(bool(self.name.text().strip()))
        lay = QFormLayout(self)
        lay.addRow("Name", self.name)
        lay.addRow("Company / role", self.company)
        lay.addRow(bb)
        self.setMinimumWidth(self.fontMetrics().averageCharWidth() * 50)

    def values(self) -> tuple[str, str]:
        return self.name.text().strip(), self.company.text().strip()


class AddressBookDialog(QDialog):
    """List with search; Add / Edit / Remove change the address book in Wint right away."""

    def __init__(self, people: list[Person], common_ids: list[int], client_factory: Callable[[], WintClient | None],
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Address book")
        self._people = list(people)
        self._common = set(common_ids)
        self._client_factory = client_factory
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._jobs: set[Job] = set()
        self.changed = False  # the caller reloads Wint data when True

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self._edit())
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())
        self.add_btn = QPushButton("Add…")
        self.add_btn.setObjectName("primary")
        self.add_btn.clicked.connect(self._add)
        self.edit_btn = QPushButton("Edit…")
        self.edit_btn.clicked.connect(self._edit)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove)
        self.status = QLabel()
        self.status.setWordWrap(True)
        buttons = QHBoxLayout()
        for b in (self.add_btn, self.edit_btn, self.remove_btn):
            buttons.addWidget(b)
        buttons.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("The people you can pick as participants on representation receipts. "
                             "Changes are saved in Wint straight away."))
        lay.addWidget(self.search)
        lay.addWidget(self.list)
        lay.addLayout(buttons)
        lay.addWidget(self.status)
        lay.addWidget(close)
        self.resize(self.fontMetrics().averageCharWidth() * 70, self.fontMetrics().height() * 30)
        self._fill()

    # ---- list

    def _fill(self, *_):
        needle = self.search.text().strip().lower()
        current = self._current()
        self.list.clear()
        for p in sorted(self._people, key=lambda p: p.name.lower()):
            if needle and needle not in f"{p.name} {p.company}".lower():
                continue
            label = f"{p.name} — {p.company}" if p.company else p.name
            if p.id in self._common:
                label += "   ★ most used"
            it = QListWidgetItem(label)
            it.setData(ROLE_PERSON, p)
            self.list.addItem(it)
            if current and p.id == current.id:
                self.list.setCurrentItem(it)
        self.status.setText(f"{len(self._people)} people")
        self._update_buttons()

    def _current(self) -> Person | None:
        it = self.list.currentItem()
        return it.data(ROLE_PERSON) if it else None

    def _update_buttons(self, busy: bool = False) -> None:
        self.add_btn.setEnabled(not busy)
        self.edit_btn.setEnabled(not busy and self._current() is not None)
        self.remove_btn.setEnabled(not busy and self._current() is not None)

    # ---- actions

    def _add(self) -> None:
        dlg = PersonDialog("Add person", parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, company = dlg.values()
        if any(p.name.lower() == name.lower() and p.company.lower() == company.lower() for p in self._people):
            QMessageBox.information(self, "Add person", f"{name} is already in the address book.")
            return
        self._call(f"Adding {name}…", lambda c: c.add_person(name, company),
                   lambda new_id: self._people.append(Person(id=new_id, name=name, company=company)))

    def _edit(self) -> None:
        p = self._current()
        if p is None:
            return
        dlg = PersonDialog("Edit person", p, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, company = dlg.values()
        if (name, company) == (p.name, p.company):
            return

        def done(new_id: int) -> None:
            self._people = [q for q in self._people if q.id != p.id] + [Person(id=new_id, name=name, company=company)]

        self._call(f"Saving {name}…", lambda c: c.replace_person(p.id, name, company), done)

    def _remove(self) -> None:
        p = self._current()
        if p is None:
            return
        if QMessageBox.question(
                self, "Remove person",
                f"Remove {p.name} from your Wint address book?\n\n"
                "Receipts that already list them keep their own copy of the name.") != QMessageBox.StandardButton.Yes:
            return
        self._call(f"Removing {p.name}…", lambda c: c.remove_person(p.id, p.name),
                   lambda _: setattr(self, "_people", [q for q in self._people if q.id != p.id]))

    def _call(self, message: str, work: Callable[[WintClient], object], on_done: Callable[[object], None]) -> None:
        client = self._client_factory()
        if client is None:
            QMessageBox.warning(self, "Address book", "Wint credentials are not set — open Settings first.")
            return
        self.status.setText(message)
        self._update_buttons(busy=True)

        def run():
            try:
                return work(client)
            finally:
                client.close()

        job = Job("address-book", run)
        self._jobs.add(job)
        job.signals.done.connect(lambda _tag, result: self._finished(job, on_done, result))
        job.signals.failed.connect(lambda _tag, msg: self._failed(job, msg))
        self._pool.start(job)

    def _finished(self, job: Job, on_done, result) -> None:
        self._jobs.discard(job)
        on_done(result)
        self.changed = True
        self._fill()

    def _failed(self, job: Job, msg: str) -> None:
        self._jobs.discard(job)
        self._update_buttons()
        self.status.setText(f"Wint didn't accept the change: {msg}")

    def done(self, result: int) -> None:  # noqa: D401 - Qt API
        self._pool.waitForDone(10000)
        super().done(result)
