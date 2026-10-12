# hub-plugin-projects-status

<img src="icon.png" width="256" alt="Статус проектов">

Плагин страницы Agents Hub «Статус проектов»: все проекты из `hub projects` - что ждёт ответа владельца, что идёт
(этап, бэклог направления), что готово, что без направления. Карточка проекта - его память: этап, цель, «что дальше»,
ключевые решения и история правок с автором.

- `main.py` - процесс плагина: сворачивает правки памяти из канала плагина (`hub post projects-status '<json>'`) в
  `<state>/projects-memory/memory.json` и `<проект>.md`, отдаёт данные странице на порту «порт страницы + 12».
- `pmem.py` - для сессий: `pmem.py show [<проект>]`, `pmem.py set <проект> --stage … --note … --goal … --add … --done …`.
- `web/` - вид страницы (API плагинов `^1.7`).

Подключение - строка в `extensions` настроек хаба:

```json
"projects-status": {"path": "<папка плагина>", "run": ["python3", "main.py"], "web": "web/main.js", "hub": "^1.7"}
```

Тесты: `PYTHONPATH=<код хаба> python3 -m unittest discover -s tests`.
