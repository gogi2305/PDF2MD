"""Централизованные опциональные зависимости.

Если requests/numpy не установлены, соответствующее имя будет None.
Модули, которым они реально нужны для работы, сами проверяют
`if requests is None` / `if np is None` и показывают понятную ошибку
пользователю вместо падения с трассировкой прямо на импорте.
"""

try:
    import requests
except ImportError:
    requests = None

try:
    import numpy as np
except ImportError:
    np = None
