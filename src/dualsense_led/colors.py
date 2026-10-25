"""Cores prontas do seletor rápido."""

# A chave é o id da cor; o nome exibido vem do catálogo de traduções ("color.<id>").
PRESETS = {
    "blue": (0, 0, 255),
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "purple": (128, 0, 255),
    "cyan": (0, 255, 255),
    "yellow": (255, 200, 0),
    "white": (255, 255, 255),
}

# Cores criadas pelo usuário que ficam salvas no seletor; as mais antigas saem primeiro.
MAX_CUSTOM_COLORS = 16
