"""Janela para criar e editar os perfis de remapeamento do emulador (ver `emulator/mapping.py`)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from . import i18n
from .emulator.config import default_profiles_dir
from .emulator.mapping import (
    BUTTON_SOURCES,
    CURVE_RANGE,
    EFFECT_POSITION_RANGE,
    EFFECT_STRENGTH_RANGE,
    GYRO_MODES,
    GYRO_SPEED_RANGE,
    KEY_PREFIX,
    MAX_DEADZONE,
    NO_TARGET,
    STICK_AXES,
    STICKS,
    TOUCHPAD_MODES,
    TOUCHPAD_SPEED_RANGE,
    TRIGGER_EFFECTS,
    TRIGGER_MODES,
    TRIGGERS,
    XBOX_TARGETS,
    Profile,
    ProfileExists,
    ProfileStore,
    slug,
    valid_target,
)
from .i18n import tr
from .service import LedService

# Nome de cada botão do DualSense e do Xbox (iguais em todos os idiomas, então ficam fora do catálogo).
SOURCE_LABELS = {
    "south": "✕", "east": "○", "west": "□", "north": "△", "l1": "L1", "r1": "R1", "l2": "L2", "r2": "R2",
    "select": "Create", "start": "Options", "mode": "PS", "l3": "L3", "r3": "R3",
    "dpad_up": "D-pad ↑", "dpad_down": "D-pad ↓", "dpad_left": "D-pad ←", "dpad_right": "D-pad →",
}  # fmt: skip
TARGET_LABELS = {
    "a": "A", "b": "B", "x": "X", "y": "Y", "lb": "LB", "rb": "RB", "lt": "LT", "rt": "RT",
    "back": "Back", "start": "Start", "guide": "Guide", "ls": "LS", "rs": "RS",
    "dpad_up": "D-pad ↑", "dpad_down": "D-pad ↓", "dpad_left": "D-pad ←", "dpad_right": "D-pad →",
}  # fmt: skip
COMMON_KEYS = (
    [f"KEY_{letter}" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    + [f"KEY_{digit}" for digit in "0123456789"]
    + ["KEY_SPACE", "KEY_ENTER", "KEY_ESC", "KEY_TAB", "KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT"]
    + ["KEY_LEFTSHIFT", "KEY_LEFTCTRL", "KEY_LEFTALT"]
    + [f"KEY_F{number}" for number in range(1, 13)]
)  # fmt: skip
STICK_AXIS_LABELS = {"left_x": "L ↔", "left_y": "L ↕", "right_x": "R ↔", "right_y": "R ↕"}


def parse_list(text: str) -> list[str]:
    return [part.strip() for part in text.replace("\n", ",").split(",") if part.strip()]


def target_from_text(text: str) -> str:
    """Destino digitado: aceita "KEY_F5" como atalho de "key:KEY_F5"."""
    text = text.strip()
    return f"{KEY_PREFIX}{text}" if text.startswith("KEY_") else text


class RemapCombo(QComboBox):
    """Destino de um botão: uma opção da lista ou, digitando, qualquer tecla (`KEY_*`)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._fill()
        i18n.hub.changed.connect(self._refill)

    def _fill(self) -> None:
        self.addItem(tr("profiles.default_target"), "")
        self.addItem(tr("profiles.no_target"), NO_TARGET)
        for target in XBOX_TARGETS:
            self.addItem(TARGET_LABELS[target], target)
        for key in COMMON_KEYS:
            self.addItem(key, f"{KEY_PREFIX}{key}")

    def _refill(self) -> None:
        target = self.target()
        self.clear()
        self._fill()
        self.set_target(target)

    def target(self) -> str:
        """"" = padrão; senão o destino. Texto digitado que não está na lista volta como veio."""
        index = self.findText(self.currentText())
        return self.itemData(index) if index >= 0 else target_from_text(self.currentText())

    def set_target(self, target: str) -> None:
        index = self.findData(target)
        if index >= 0:
            self.setCurrentIndex(index)
        else:
            self.setEditText(target)


def _spin(low: float, high: float, step: float, value: float) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setSingleStep(step)
    box.setDecimals(2)
    box.setValue(value)
    return box


class ProfileEditor(QWidget):
    """Formulário de um perfil; `profile()` lê o que está na tela e `load()` preenche."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.changed_callbacks: list = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()
        self._name = QLineEdit()
        self._apps = QLineEdit()
        self._appids = QLineEdit()
        for edit, text_key in ((self._apps, "profiles.apps_hint"), (self._appids, "profiles.appids_hint")):
            i18n.bind(edit.setPlaceholderText, text_key)
            edit.textChanged.connect(self._touch)
        self._name.textChanged.connect(self._touch)
        for label_key, widget in (("profiles.name", self._name), ("profiles.apps", self._apps), ("profiles.appids", self._appids)):
            label = QLabel()
            i18n.bind(label.setText, label_key)
            form.addRow(label, widget)
        layout.addLayout(form)

        layout.addWidget(self._build_sticks())
        layout.addWidget(self._build_triggers())
        layout.addWidget(self._build_trigger_effects())
        layout.addWidget(self._build_mouse())
        layout.addWidget(self._build_remap())

    def _touch(self, *_args) -> None:
        for callback in self.changed_callbacks:
            callback()

    def _build_sticks(self) -> QGroupBox:
        group = QGroupBox()
        i18n.bind(group.setTitle, "profiles.sticks")
        form = QFormLayout(group)
        self._swap = QCheckBox()
        i18n.bind(self._swap.setText, "profiles.swap_sticks")
        self._swap.toggled.connect(self._touch)
        form.addRow(self._swap)
        self._invert = {}
        row = QHBoxLayout()
        for axis in STICK_AXES:
            box = QCheckBox(STICK_AXIS_LABELS[axis])
            box.toggled.connect(self._touch)
            self._invert[axis] = box
            row.addWidget(box)
        invert_label = QLabel()
        i18n.bind(invert_label.setText, "profiles.invert")
        form.addRow(invert_label, row)
        self._deadzone, self._curve = {}, {}
        for stick in STICKS:
            self._deadzone[stick] = _spin(0.0, MAX_DEADZONE, 0.05, 0.0)
            self._curve[stick] = _spin(*CURVE_RANGE, 0.1, 1.0)
            for widget in (self._deadzone[stick], self._curve[stick]):
                widget.valueChanged.connect(self._touch)
            side = QHBoxLayout()
            for key, widget in (("profiles.deadzone", self._deadzone[stick]), ("profiles.curve", self._curve[stick])):
                label = QLabel()
                i18n.bind(label.setText, key)
                side.addWidget(label)
                side.addWidget(widget)
            side_label = QLabel()
            i18n.bind(side_label.setText, f"profiles.{stick}_stick")
            form.addRow(side_label, side)
        return group

    def _build_triggers(self) -> QGroupBox:
        group = QGroupBox()
        i18n.bind(group.setTitle, "profiles.triggers")
        form = QFormLayout(group)
        self._modes = {}
        for trigger in TRIGGERS:
            combo = QComboBox()
            for mode in TRIGGER_MODES:
                combo.addItem(tr(f"profiles.mode_{mode}"), mode)
            combo.currentIndexChanged.connect(self._touch)
            self._modes[trigger] = combo
            form.addRow(SOURCE_LABELS[trigger], combo)
        self._threshold = _spin(0.05, 0.95, 0.05, 0.5)
        self._threshold.valueChanged.connect(self._touch)
        threshold_label = QLabel()
        i18n.bind(threshold_label.setText, "profiles.threshold")
        form.addRow(threshold_label, self._threshold)
        return group

    def _build_trigger_effects(self) -> QGroupBox:
        group = QGroupBox()
        i18n.bind(group.setTitle, "profiles.trigger_effects")
        form = QFormLayout(group)
        self._effects, self._effect_position, self._effect_strength = {}, {}, {}
        for trigger in TRIGGERS:
            combo = QComboBox()
            for effect in TRIGGER_EFFECTS:
                combo.addItem(tr(f"trigger.{effect}"), effect)
            position, strength = QSpinBox(), QSpinBox()
            position.setRange(*EFFECT_POSITION_RANGE)
            strength.setRange(*EFFECT_STRENGTH_RANGE)
            row = QHBoxLayout()
            for key, widget in (("out.position", position), ("out.strength", strength)):
                label = QLabel()
                i18n.bind(label.setText, key)
                row.addWidget(label)
                row.addWidget(widget)
            combo.currentIndexChanged.connect(self._touch)
            combo.currentIndexChanged.connect(self._update_effect_fields)
            position.valueChanged.connect(self._touch)
            strength.valueChanged.connect(self._touch)
            self._effects[trigger], self._effect_position[trigger], self._effect_strength[trigger] = combo, position, strength
            form.addRow(SOURCE_LABELS[trigger], combo)
            form.addRow("", row)
        hint = QLabel()
        hint.setWordWrap(True)
        i18n.bind(hint.setText, "profiles.trigger_effects_hint")
        form.addRow(hint)
        self._update_effect_fields()
        return group

    def _update_effect_fields(self, *_args) -> None:
        for trigger, combo in self._effects.items():
            on = combo.currentData() != "off"
            self._effect_position[trigger].setEnabled(on)
            self._effect_strength[trigger].setEnabled(on)

    def _build_mouse(self) -> QGroupBox:
        group = QGroupBox()
        i18n.bind(group.setTitle, "profiles.mouse")
        form = QFormLayout(group)
        self._touchpad = QComboBox()
        for mode in TOUCHPAD_MODES:
            self._touchpad.addItem(tr(f"profiles.touchpad_{mode}"), mode)
        self._touchpad_speed = _spin(*TOUCHPAD_SPEED_RANGE, 0.1, 1.0)
        self._gyro = QComboBox()
        for mode in GYRO_MODES:
            self._gyro.addItem(tr(f"profiles.gyro_{mode}"), mode)
        self._gyro_button = QComboBox()
        for source in BUTTON_SOURCES:
            self._gyro_button.addItem(SOURCE_LABELS[source], source)
        self._gyro_speed = _spin(*GYRO_SPEED_RANGE, 1.0, 15.0)
        self._gyro_invert_y = QCheckBox()
        i18n.bind(self._gyro_invert_y.setText, "profiles.gyro_invert_y")
        for combo in (self._touchpad, self._gyro, self._gyro_button):
            combo.currentIndexChanged.connect(self._touch)
        for spin in (self._touchpad_speed, self._gyro_speed):
            spin.valueChanged.connect(self._touch)
        self._gyro_invert_y.toggled.connect(self._touch)
        self._touchpad.currentIndexChanged.connect(self._update_mouse_fields)
        self._gyro.currentIndexChanged.connect(self._update_mouse_fields)
        for key, widget in (
            ("profiles.touchpad", self._touchpad),
            ("profiles.touchpad_speed", self._touchpad_speed),
            ("profiles.gyro", self._gyro),
            ("profiles.gyro_activator", self._gyro_button),
            ("profiles.gyro_speed", self._gyro_speed),
        ):
            label = QLabel()
            i18n.bind(label.setText, key)
            form.addRow(label, widget)
        form.addRow(self._gyro_invert_y)
        hint = QLabel()
        hint.setWordWrap(True)
        i18n.bind(hint.setText, "profiles.mouse_hint")
        form.addRow(hint)
        self._update_mouse_fields()
        return group

    def _update_mouse_fields(self, *_args) -> None:
        self._touchpad_speed.setEnabled(self._touchpad.currentData() == "mouse")
        gyro = self._gyro.currentData()
        self._gyro_button.setEnabled(gyro == "button")
        self._gyro_speed.setEnabled(gyro != "off")
        self._gyro_invert_y.setEnabled(gyro != "off")

    def _build_remap(self) -> QGroupBox:
        group = QGroupBox()
        i18n.bind(group.setTitle, "profiles.remap")
        layout = QVBoxLayout(group)
        hint = QLabel()
        hint.setWordWrap(True)
        i18n.bind(hint.setText, "profiles.remap_hint")
        layout.addWidget(hint)
        self._table = QTableWidget(len(BUTTON_SOURCES), 2)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setVisible(False)
        self._table.verticalHeader().setVisible(False)
        self._combos: dict[str, RemapCombo] = {}
        for row, source in enumerate(BUTTON_SOURCES):
            label = QLabel(f" {SOURCE_LABELS[source]}")
            self._table.setCellWidget(row, 0, label)
            combo = RemapCombo()
            combo.currentTextChanged.connect(self._touch)
            self._combos[source] = combo
            self._table.setCellWidget(row, 1, combo)
        self._table.setColumnWidth(0, 90)
        self._table.setMinimumHeight(260)
        layout.addWidget(self._table)
        return group

    def load(self, profile: Profile) -> None:
        widgets = [self._name, self._apps, self._appids, self._swap, self._threshold, *self._invert.values(),
                   *self._deadzone.values(), *self._curve.values(), *self._modes.values(), *self._combos.values(),
                   *self._effects.values(), *self._effect_position.values(), *self._effect_strength.values(),
                   self._touchpad, self._touchpad_speed, self._gyro, self._gyro_button, self._gyro_speed, self._gyro_invert_y]  # fmt: skip
        for widget in widgets:
            widget.blockSignals(True)
        self._name.setText(profile.name)
        self._apps.setText(", ".join(profile.apps))
        self._appids.setText(", ".join(str(app_id) for app_id in profile.steam_appids))
        self._swap.setChecked(profile.swap_sticks)
        for axis, box in self._invert.items():
            box.setChecked(axis in profile.invert)
        for stick in STICKS:
            self._deadzone[stick].setValue(profile.deadzone[stick])
            self._curve[stick].setValue(profile.curve[stick])
        for trigger, combo in self._modes.items():
            combo.setCurrentIndex(combo.findData(profile.triggers[trigger]))
        self._threshold.setValue(profile.trigger_threshold)
        for trigger in TRIGGERS:
            self._effects[trigger].setCurrentIndex(self._effects[trigger].findData(profile.trigger_effect[trigger]))
            self._effect_position[trigger].setValue(profile.trigger_position[trigger])
            self._effect_strength[trigger].setValue(profile.trigger_strength[trigger])
        for source, combo in self._combos.items():
            combo.set_target(profile.remap.get(source, ""))
        self._touchpad.setCurrentIndex(self._touchpad.findData(profile.touchpad))
        self._touchpad_speed.setValue(profile.touchpad_speed)
        self._gyro.setCurrentIndex(self._gyro.findData(profile.gyro))
        self._gyro_button.setCurrentIndex(self._gyro_button.findData(profile.gyro_button))
        self._gyro_speed.setValue(profile.gyro_speed)
        self._gyro_invert_y.setChecked(profile.gyro_invert_y)
        for widget in widgets:
            widget.blockSignals(False)
        self._update_mouse_fields()
        self._update_effect_fields()

    def invalid_targets(self) -> list[str]:
        return [target for combo in self._combos.values() if (target := combo.target()) and not valid_target(target)]

    def profile(self) -> Profile:
        return Profile(
            name=self._name.text().strip(),
            remap={source: target for source, combo in self._combos.items() if (target := combo.target())},
            swap_sticks=self._swap.isChecked(),
            invert=[axis for axis, box in self._invert.items() if box.isChecked()],
            deadzone={stick: self._deadzone[stick].value() for stick in STICKS},
            curve={stick: self._curve[stick].value() for stick in STICKS},
            triggers={trigger: combo.currentData() for trigger, combo in self._modes.items()},
            trigger_threshold=self._threshold.value(),
            trigger_effect={trigger: combo.currentData() for trigger, combo in self._effects.items()},
            trigger_position={trigger: spin.value() for trigger, spin in self._effect_position.items()},
            trigger_strength={trigger: spin.value() for trigger, spin in self._effect_strength.items()},
            apps=parse_list(self._apps.text()),
            steam_appids=[int(part) for part in parse_list(self._appids.text()) if part.isdigit()],
            touchpad=self._touchpad.currentData(),
            touchpad_speed=self._touchpad_speed.value(),
            gyro=self._gyro.currentData(),
            gyro_button=self._gyro_button.currentData(),
            gyro_speed=self._gyro_speed.value(),
            gyro_invert_y=self._gyro_invert_y.isChecked(),
        )

    def invalid_appids(self) -> list[str]:
        return [part for part in parse_list(self._appids.text()) if not part.isdigit()]


class ProfilesDialog(QDialog):
    def __init__(self, service: LedService, store: ProfileStore | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        self._store = store or ProfileStore(default_profiles_dir())
        self._current: str | None = None  # nome do perfil mostrado no formulário (None = novo, ainda não salvo)
        self._dirty = False
        i18n.bind(self.setWindowTitle, "profiles.title")
        self.setMinimumSize(780, 560)

        root = QVBoxLayout(self)
        default_row = QHBoxLayout()
        default_label = QLabel()
        i18n.bind(default_label.setText, "profiles.default")
        default_row.addWidget(default_label)
        self._default = QComboBox()
        self._default.activated.connect(self._on_default_chosen)
        default_row.addWidget(self._default, 1)
        root.addLayout(default_row)
        note = QLabel()
        note.setWordWrap(True)
        i18n.bind(note.setText, "profiles.app_note")
        root.addWidget(note)

        body = QHBoxLayout()
        root.addLayout(body, 1)
        side = QVBoxLayout()
        self._list = QListWidget()
        self._list.setMaximumWidth(200)
        self._list.currentItemChanged.connect(self._on_select)
        side.addWidget(self._list, 1)
        self._buttons = {}
        for key, handler in (
            ("new", self._new),
            ("duplicate", self._duplicate),
            ("delete", self._delete),
            ("import", self._import),
            ("export", self._export),
        ):
            button = QPushButton()
            i18n.bind(button.setText, f"profiles.{key}")
            button.clicked.connect(handler)
            self._buttons[key] = button
            side.addWidget(button)
        body.addLayout(side)

        self._editor = ProfileEditor()
        self._editor.changed_callbacks.append(self._mark_dirty)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._editor)
        body.addWidget(scroll, 1)

        footer = QHBoxLayout()
        self._status = QLabel()
        self._status.setWordWrap(True)
        footer.addWidget(self._status, 1)
        self._save_button = QPushButton()
        i18n.bind(self._save_button.setText, "profiles.save")
        self._save_button.clicked.connect(self._save)
        footer.addWidget(self._save_button)
        close = QPushButton()
        i18n.bind(close.setText, "profiles.close")
        close.clicked.connect(self.close)
        footer.addWidget(close)
        root.addLayout(footer)

        self._reload()
        if self._list.count():
            self._list.setCurrentRow(0)
        else:
            self._show(Profile(), None)

    # --- lista
    def _reload(self, select: str | None = None) -> None:
        profiles = self._store.load_all()
        self._list.blockSignals(True)
        self._list.clear()
        for profile in profiles:
            self._list.addItem(profile.name)
        self._list.blockSignals(False)
        self._default.clear()
        self._default.addItem(tr("profiles.no_changes"), "")
        for profile in profiles:
            self._default.addItem(profile.name, profile.name)
        index = self._default.findData(self._service.default_profile)
        self._default.setCurrentIndex(max(index, 0))
        if select is not None:
            matches = self._list.findItems(select, Qt.MatchFlag.MatchExactly)
            if matches:
                self._list.blockSignals(True)
                self._list.setCurrentItem(matches[0])
                self._list.blockSignals(False)

    def _on_default_chosen(self, index: int) -> None:
        self._service.set_default_profile(self._default.itemData(index) or "")

    def _on_select(self, item) -> None:
        if item is None:
            return
        if item.text() == self._current:
            return
        if not self._confirm_discard():
            self._reload(select=self._current)
            return
        profile = self._store.get(item.text())
        if profile is not None:
            self._show(profile, profile.name)

    def _show(self, profile: Profile, current: str | None) -> None:
        self._current = current
        self._editor.load(profile)
        self._dirty = False
        self._status.clear()

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(self, tr("profiles.title"), tr("profiles.discard"))
        return answer == QMessageBox.StandardButton.Yes

    # --- ações
    def _new(self) -> None:
        if self._confirm_discard():
            self._list.clearSelection()
            self._show(Profile(name=self._free_name(tr("profiles.new_name"))), None)
            self._dirty = True

    def _duplicate(self) -> None:
        if not self._confirm_discard():
            return
        profile = self._editor.profile()
        profile.name = self._free_name(profile.name or tr("profiles.new_name"))
        profile.apps, profile.steam_appids = [], []  # os mesmos aplicativos nos dois perfis brigariam entre si
        self._list.clearSelection()
        self._show(profile, None)
        self._dirty = True

    def _free_name(self, base: str) -> str:
        taken = {existing.name.lower() for existing in self._store.load_all()}
        name, number = base, 2
        while name.lower() in taken or slug(name) in {slug(t) for t in taken}:
            name, number = f"{base} {number}", number + 1
        return name

    def _delete(self) -> None:
        if self._current is None:
            return
        if QMessageBox.question(self, tr("profiles.title"), tr("profiles.confirm_delete", name=self._current)) != QMessageBox.StandardButton.Yes:
            return
        self._store.delete(self._current)
        if self._service.default_profile == self._current:
            self._service.set_default_profile("")
        self._reload()
        self._dirty = False
        if self._list.count():
            self._list.setCurrentRow(0)
        else:
            self._show(Profile(), None)

    def _save(self) -> None:
        profile = self._editor.profile()
        problem = self._problem(profile)
        if problem:
            self._status.setText(problem)
            return
        try:
            self._store.save(profile, previous_name=self._current)
        except OSError as error:
            self._status.setText(tr("profiles.save_failed", error=str(error)))
            return
        if self._current and self._service.default_profile == self._current and self._current != profile.name:
            self._service.set_default_profile(profile.name)
        self._current = profile.name
        self._dirty = False
        self._reload(select=profile.name)
        self._status.setText(tr("profiles.saved"))

    def _problem(self, profile: Profile) -> str:
        if not profile.name:
            return tr("profiles.err_name")
        others = [p.name for p in self._store.load_all() if p.name != self._current]
        if any(slug(profile.name) == slug(other) for other in others):
            return tr("profiles.err_duplicate")
        if bad := self._editor.invalid_targets():
            return tr("profiles.err_target", target=bad[0])
        if bad := self._editor.invalid_appids():
            return tr("profiles.err_appid", value=bad[0])
        return ""

    def _import(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, tr("profiles.import"), "", "JSON (*.json)")
        if not path:
            return
        try:
            try:
                profile = self._store.import_file(Path(path))
            except ProfileExists as exists:
                question = tr("profiles.confirm_overwrite", name=exists.existing)
                if QMessageBox.question(self, tr("profiles.title"), question) != QMessageBox.StandardButton.Yes:
                    return
                profile = self._store.import_file(Path(path), overwrite=True)
        except (OSError, ValueError) as error:
            self._status.setText(tr("profiles.import_failed", error=str(error)))
            return
        self._reload(select=profile.name)
        self._show(profile, profile.name)
        self._status.setText(tr("profiles.imported", name=profile.name))

    def _export(self) -> None:
        profile = self._editor.profile()
        if not profile.name:
            self._status.setText(tr("profiles.err_name"))
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("profiles.export"), f"{slug(profile.name)}.json", "JSON (*.json)")
        if not path:
            return
        try:
            self._store.export_file(profile, Path(path))
        except OSError as error:
            self._status.setText(tr("profiles.save_failed", error=str(error)))
            return
        self._status.setText(tr("profiles.exported", path=path))

    def closeEvent(self, event) -> None:
        if self._confirm_discard():
            super().closeEvent(event)
        else:
            event.ignore()
