"""Cartão "Informações do controle": resumo de 5 linhas e "Mostrar tudo" em Software/Hardware."""

from __future__ import annotations

import logging

from PySide6.QtGui import QFontDatabase, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QGridLayout, QGroupBox, QLabel, QPushButton, QToolButton, QToolTip, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt

from . import i18n
from .battery import describe, usb_max_power
from .ds5.info import ControllerInfo, read_info
from .i18n import tr
from .responsive import Columns
from .service import LedService

log = logging.getLogger(__name__)

SUMMARY = ("serial", "color", "board", "build", "device_type")
SOFTWARE = ("build", "fw_type", "fw_series", "fw_version", "fw_update", "sbl_version", "venom_version", "spider_version")
HARDWARE = ("serial", "mcu_id", "pcba_id", "battery_barcode", "vcm_left", "vcm_right", "color", "board",
            "hw_model", "device_type", "bd_addr")
COPYABLE = {"serial", "mcu_id", "pcba_id", "battery_barcode", "vcm_left", "vcm_right", "color", "board", "bd_addr"}

# Leitura por (endereço, conexão): só lê de novo se o controle reconectar de outro jeito.
_cache: dict[tuple[str, str], ControllerInfo] = {}


def info_for(controller) -> ControllerInfo | None:
    """Lê (uma vez) as informações do controle; None se o hidraw não abre."""
    key = (controller.uid, controller.connection)
    if key in _cache:
        return _cache[key]
    if not controller.hidraw:
        return None
    try:
        device = controller.open_device()
    except OSError as error:
        log.warning("Não consegui abrir %s para ler as informações: %s", controller.hidraw, error)
        return None
    try:
        info = read_info(device, controller.connection == "USB")
    finally:
        device.close()
    _cache[key] = info
    return info


def _value_text(name: str, info: ControllerInfo) -> str | None:
    value = getattr(info, name)
    if name == "device_type":
        return tr(f"info.type_{value}" if value else "info.type_unknown")
    return value


class _Rows(QWidget):
    """Grade rótulo · valor (monoespaçado, selecionável) · copiar."""

    def __init__(self, names: tuple[str, ...], parent: QWidget | None = None):
        super().__init__(parent)
        self._names = names
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setColumnStretch(1, 1)
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._values: dict[str, QLabel] = {}
        for row, name in enumerate(names):
            label = QLabel()
            i18n.bind(label.setText, f"info.{name}")
            value = QLabel()
            value.setFont(mono)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setWordWrap(name == "device_type")
            self._grid.addWidget(label, row, 0, Qt.AlignmentFlag.AlignVCenter)
            self._grid.addWidget(value, row, 1, Qt.AlignmentFlag.AlignVCenter)
            self._values[name] = value
            if name in COPYABLE:
                copy = QToolButton()
                copy.setIcon(QIcon.fromTheme("edit-copy"))
                if copy.icon().isNull():
                    copy.setText("⧉")
                copy.setAutoRaise(True)
                copy.setMinimumSize(32, 32)
                i18n.bind(copy.setToolTip, "info.copy")
                i18n.bind(copy.setAccessibleName, "info.copy")
                copy.clicked.connect(lambda _c=False, name=name, button=copy: self._copy(name, button))
                self._grid.addWidget(copy, row, 2)
                value.setProperty("copy_button", copy)
        self._grid.setRowStretch(len(names), 1)  # sobra embaixo, não entre as linhas

    def show_info(self, info: ControllerInfo) -> None:
        for name, label in self._values.items():
            text = _value_text(name, info)
            label.setText(text if text else tr("info.unavailable"))
            label.setEnabled(bool(text))
            label.setProperty("raw", getattr(info, name) if name != "device_type" else text)
            button = label.property("copy_button")
            if button is not None:
                button.setEnabled(bool(text))

    def _copy(self, name: str, button: QToolButton) -> None:
        text = self._values[name].property("raw")
        if text:
            QGuiApplication.clipboard().setText(str(text))
            QToolTip.showText(button.mapToGlobal(button.rect().bottomLeft()), tr("info.copied"), button)


class ControllerInfoCard(QGroupBox):
    """Informações do controle selecionado; lidas ao aparecer e ao trocar de controle."""

    def __init__(self, service: LedService, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        i18n.bind(self.setTitle, "info.title")
        layout = QVBoxLayout(self)
        self._message = QLabel()
        self._message.setWordWrap(True)
        layout.addWidget(self._message)
        self._summary = _Rows(SUMMARY)
        layout.addWidget(self._summary)

        software, hardware = QGroupBox(), QGroupBox()
        i18n.bind(software.setTitle, "info.software")
        i18n.bind(hardware.setTitle, "info.hardware")
        self._software, self._hardware = _Rows(SOFTWARE), _Rows(HARDWARE)
        QVBoxLayout(software).addWidget(self._software)
        QVBoxLayout(hardware).addWidget(self._hardware)
        self._details = Columns(software, hardware)
        self._details.hide()
        layout.addWidget(self._details)

        self._toggle = QPushButton()
        self._toggle.setCheckable(True)
        self._toggle.toggled.connect(self._on_toggle)
        layout.addWidget(self._toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self._note = QLabel()
        self._note.setWordWrap(True)
        layout.addWidget(self._note)

        self._info: ControllerInfo | None = None
        service.controllers_changed.connect(self.refresh)
        i18n.hub.changed.connect(self._render)
        self._on_toggle(False)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        if not self.isVisible():
            return
        controller = self._service.controller_for_uid(self._service.selected_uid or "")
        self._controller = controller
        self._info = info_for(controller) if controller is not None else None
        self._render()

    def _on_toggle(self, checked: bool) -> None:
        self._details.setVisible(checked)
        self._summary.setVisible(not checked)
        self._toggle.setText(tr("info.show_less" if checked else "info.show_all"))

    def _render(self) -> None:
        self._toggle.setText(tr("info.show_less" if self._toggle.isChecked() else "info.show_all"))
        info = self._info
        has = info is not None and not info.is_empty()
        self._message.setVisible(not has)
        self._message.setText(tr("info.none"))
        for widget in (self._summary, self._toggle):
            widget.setEnabled(has)
        controller = getattr(self, "_controller", None)
        self._note.setVisible(has and controller is not None and controller.connection != "USB")
        self._note.setText(tr("info.bluetooth_note"))
        if has:
            for rows in (self._summary, self._software, self._hardware):
                rows.show_info(info)


class ChargeCard(QGroupBox):
    """Estado da carga e **estimativa** de velocidade (o controle não informa corrente nem tensão)."""

    def __init__(self, service: LedService, parent: QWidget | None = None):
        super().__init__(parent)
        self._service = service
        i18n.bind(self.setTitle, "charge.title")
        layout = QVBoxLayout(self)
        self._state = QLabel()
        self._rate = QLabel()
        self._port = QLabel()
        self._note = QLabel()
        self._note.setWordWrap(True)
        i18n.bind(self._note.setText, "charge.note")
        for widget in (self._state, self._rate, self._port, self._note):
            layout.addWidget(widget)
        service.battery_changed.connect(self._render)
        service.controllers_changed.connect(self._render)
        i18n.hub.changed.connect(self._render)
        self._render()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._render()

    def _render(self) -> None:
        uid = self._service.selected_uid
        battery = self._service.battery_for(uid) if uid else None
        self._state.setText(describe(battery) if battery else tr("charge.unavailable"))
        estimate = self._service.charge_estimate(uid) if uid else None
        if estimate is None:
            text = tr("charge.not_charging") if battery is not None else ""
        elif estimate.rate_per_min is None:
            text = tr("charge.measuring")
        else:
            text = tr("charge.rate", rate=f"{estimate.rate_per_min:.2f}")
            if estimate.remaining_min is not None:
                text += " · " + tr("charge.remaining", minutes=round(estimate.remaining_min))
        if estimate is not None and estimate.intervals_min:
            text += "\n" + tr("charge.steps", list=", ".join(f"{m:.1f}" for m in estimate.intervals_min[-5:]))
        self._rate.setText(text)
        self._rate.setVisible(bool(text))
        controller = self._service.controller_for_uid(uid or "")
        power = usb_max_power(controller.hidraw) if controller is not None and controller.connection == "USB" else None
        self._port.setText(tr("charge.port", power=power) if power else "")
        self._port.setVisible(bool(power))
