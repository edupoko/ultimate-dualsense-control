"""Idioma da interface: português (padrão), inglês e espanhol, com troca ao vivo."""

from __future__ import annotations

import weakref
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from .translations import APP_NAME, STRINGS

# Nome de cada idioma no próprio idioma, como aparece no menu de seleção.
LANGUAGES = {"pt": "Português", "en": "English", "es": "Español"}
DEFAULT_LANGUAGE = "pt"


class _Hub(QObject):
    changed = Signal()


# Quem tem texto montado por código (abas, dicas, a lista de cores) escuta este sinal e refaz.
hub = _Hub()

_current = DEFAULT_LANGUAGE
# (referência ao método que define o texto, chave, valores): refeitos a cada troca de idioma.
_bindings: list[tuple[Callable[[], Callable | None], str, dict]] = []


def language() -> str:
    return _current


def tr(key: str, **values) -> str:
    """Texto da chave no idioma atual; sem tradução no idioma, cai no português."""
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry.get(_current) or entry[DEFAULT_LANGUAGE]
    return text.format(app=APP_NAME, **values)


def bind(setter: Callable[[str], object], key: str, **values) -> None:
    """Define o texto agora e de novo sempre que o idioma mudar (`setter` é ex.: label.setText)."""
    owner = getattr(setter, "__self__", None)
    if owner is not None:
        # Guarda o dono por referência fraca e o nome do método (os slots do Qt, como setText,
        # não são métodos do Python e não aceitam WeakMethod). Assim o widget não fica vivo à toa.
        owner_ref, name = weakref.ref(owner), setter.__name__
        method = lambda: getattr(owner_ref(), name, None)  # noqa: E731
    else:
        method = lambda setter=setter: setter  # noqa: E731
    _bindings.append((method, key, values))
    setter(tr(key, **values))


def set_language(code: str) -> None:
    global _current
    if code not in LANGUAGES:
        code = DEFAULT_LANGUAGE
    if code == _current:
        return
    _current = code
    alive = []
    for method, key, values in _bindings:
        setter = method()
        if setter is None:
            continue
        try:
            setter(tr(key, **values))
        except RuntimeError:
            continue  # o objeto do Qt já foi apagado
        alive.append((method, key, values))
    _bindings[:] = alive
    hub.changed.emit()
