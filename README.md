# capcut-mcp

**English** | [Русский](#русский)

An unofficial [MCP](https://modelcontextprotocol.io) server that lets Claude (or any other MCP client)
build and edit **CapCut desktop** drafts: put videos, pictures and music on the timeline, add titles and
subtitles, change clip length and order. You then open the draft in CapCut, check it, tweak it by hand and
export as usual.

CapCut has no public scripting API, so the server writes the draft files (`draft_content.json`,
`draft_meta_info.json`) directly. Draft generation is done by the
[pycapcut](https://github.com/GuanYixuan/pyCapCut) library by GuanYixuan.

> **Disclaimer.** This is an independent community project. It is not affiliated with, endorsed by or
> connected to CapCut or ByteDance in any way. "CapCut" is a trademark of its owner.

## Requirements

- Windows 10/11
- CapCut for desktop (tested with **CapCut 7.9**)
- Python 3.10+ (or [uv](https://docs.astral.sh/uv/), which installs Python for you)

## Installation

Option A — run with `uvx` (no manual install):

```bash
uvx --from git+https://github.com/OWNER/capcut-mcp capcut-mcp
```

Option B — install with `pip`:

```bash
pip install git+https://github.com/OWNER/capcut-mcp
```

This gives you a `capcut-mcp` command. Normally you don't run it yourself: the MCP client starts it.

### Where are the drafts?

The server finds the CapCut drafts folder automatically (from CapCut's `root_meta_info.json`, or
`%LOCALAPPDATA%\CapCut Drafts`). If yours is elsewhere, set the `CAPCUT_DRAFTS_PATH` environment variable
to the folder that contains your draft folders.

## Configuration

### Claude Desktop

Edit `%APPDATA%\Claude\claude_desktop_config.json` and restart Claude completely:

```json
{
  "mcpServers": {
    "capcut": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/OWNER/capcut-mcp", "capcut-mcp"]
    }
  }
}
```

If you installed with `pip`, use `"command": "capcut-mcp"` and `"args": []` (or the full path to
`capcut-mcp.exe`). To set a custom drafts folder add
`"env": {"CAPCUT_DRAFTS_PATH": "D:\\CapCut Drafts"}`.

### Claude Code

```bash
claude mcp add capcut -- uvx --from git+https://github.com/OWNER/capcut-mcp capcut-mcp
```

Then ask, for example: *"Make a vertical CapCut draft 'Holiday' from the videos in D:\Videos\Holiday,
4 seconds each, title 'Summer 2026' on top and D:\Music\song.mp3 quietly underneath."*

## Tools

| Tool | What it does |
|---|---|
| `list_drafts` | List CapCut drafts (newest first), marks which ones this server can edit |
| `inspect_draft` | Show tracks and clips of any draft, including hand-made ones (read-only) |
| `create_draft` | New empty draft (1920x1080, 1080x1920 for Reels/TikTok/Shorts, 1080x1080, …) |
| `get_project` | Show the edit plan of a server-made draft: clip ids, start/end, settings |
| `add_media` | Add a video/picture to the main track or as an overlay, or audio to an audio track |
| `add_text` | Add a title/caption: size, colour, background, outline, font, animation |
| `add_subtitles` | Add subtitles from an `.srt` file, SRT text or a list of lines |
| `update_clip` | Change clip parameters (duration, volume, speed, position, text, …) |
| `move_clip` | Reorder clips on the main track |
| `remove_clip` | Delete a clip |
| `undo_last_change` | Roll the draft back to the previous backup |
| `media_info` | Duration and size of a media file |
| `list_effects` | Names of CapCut transitions, animations and fonts (Pro ones hidden by default) |

All times are in seconds. Tool descriptions and messages are currently in Russian; Claude handles that fine.

## Limitations

- **Only drafts created by this server can be changed.** Other drafts (made by hand in CapCut) can only be
  viewed with `inspect_draft`. The server keeps its edit plan in `claude_project.json` inside the draft folder.
- **Backups before every change.** Before each overwrite the previous files are copied to `.claude_backups`
  inside the draft folder (last 15 kept); `undo_last_change` restores them. If you edited a server-made draft
  by hand in CapCut, the server refuses to overwrite it unless you confirm (`force=true`).
- **CapCut 9.x may ask you to re-link media** when opening a draft. Point it at the same files and continue.
- If the draft is open in CapCut while it is being changed, go back to CapCut's home screen and reopen it.
- Media files are referenced, not copied — keep them where they are.
- Windows only (CapCut desktop and pycapcut target Windows).

## Development

```bash
python -m venv .venv
.venv\Scripts\pip install -e ".[test]"
.venv\Scripts\python -m pytest
```

The tests build a draft in a temporary folder via `CAPCUT_DRAFTS_PATH`; CapCut does not need to be installed.

## License

[MIT](LICENSE). Dependencies keep their own licenses: [pycapcut](https://github.com/GuanYixuan/pyCapCut),
[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (MIT).

---

<a id="русский"></a>

# capcut-mcp (по-русски)

[English](#capcut-mcp) | **Русский**

Неофициальный [MCP](https://modelcontextprotocol.io)-сервер, через который Claude (или другой MCP-клиент)
сам собирает черновики в **CapCut для компьютера**: кладёт видео, картинки и музыку на таймлайн, добавляет
текст и субтитры, меняет длительность и порядок клипов. Потом вы открываете черновик в CapCut, смотрите,
правите руками и экспортируете как обычно.

У CapCut нет официального способа управлять им из программ, поэтому сервер пишет файлы черновика напрямую.
Сам черновик собирает библиотека [pycapcut](https://github.com/GuanYixuan/pyCapCut) (автор — GuanYixuan).

> **Важно.** Это независимый проект. Он никак не связан с CapCut или ByteDance и не одобрен ими.
> «CapCut» — товарный знак его владельца.

## Что нужно

- Windows 10/11
- CapCut для компьютера (проверено на **CapCut 7.9**)
- Python 3.10+ (или [uv](https://docs.astral.sh/uv/) — он сам поставит Python)

## Установка

Вариант А — запуск через `uvx` (ставить вручную ничего не нужно):

```bash
uvx --from git+https://github.com/OWNER/capcut-mcp capcut-mcp
```

Вариант Б — установка через `pip`:

```bash
pip install git+https://github.com/OWNER/capcut-mcp
```

Появится команда `capcut-mcp`. Обычно её не запускают руками — её запускает Claude.

### Где черновики

Сервер сам находит папку черновиков CapCut (по файлу CapCut `root_meta_info.json` или
`%LOCALAPPDATA%\CapCut Drafts`). Если у вас она в другом месте, задайте переменную окружения
`CAPCUT_DRAFTS_PATH` — путь к папке, где лежат папки черновиков.

## Подключение

### Claude Desktop (приложение)

Откройте `%APPDATA%\Claude\claude_desktop_config.json`, добавьте блок и полностью перезапустите Claude:

```json
{
  "mcpServers": {
    "capcut": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/OWNER/capcut-mcp", "capcut-mcp"]
    }
  }
}
```

Если ставили через `pip`, укажите `"command": "capcut-mcp"` и `"args": []` (или полный путь к
`capcut-mcp.exe`). Своя папка черновиков: добавьте `"env": {"CAPCUT_DRAFTS_PATH": "D:\\CapCut Drafts"}`.

### Claude Code

```bash
claude mcp add capcut -- uvx --from git+https://github.com/OWNER/capcut-mcp capcut-mcp
```

Потом попросите, например: «Собери в CapCut вертикальный ролик "Отпуск": видео из папки D:\Видео\Отпуск
по порядку, по 4 секунды, сверху заголовок "Лето 2026", снизу тихо музыка D:\Музыка\song.mp3».

## Инструменты

| Инструмент | Что делает |
|---|---|
| `list_drafts` | Список черновиков (новые сверху), отмечает, какие сервер может менять |
| `inspect_draft` | Показать дорожки и клипы любого черновика, в том числе сделанного руками (только чтение) |
| `create_draft` | Новый пустой черновик (1920x1080, 1080x1920 для Reels/TikTok/Shorts, 1080x1080 и т. д.) |
| `get_project` | План монтажа черновика сервера: id клипов, начало/конец, настройки |
| `add_media` | Видео/картинка на главную дорожку или поверх видео, аудио — на звуковую дорожку |
| `add_text` | Заголовок или надпись: размер, цвет, фон, обводка, шрифт, анимация |
| `add_subtitles` | Субтитры из файла `.srt`, текста SRT или списка строк |
| `update_clip` | Изменить клип (длительность, громкость, скорость, положение, текст и т. д.) |
| `move_clip` | Переставить клип на главной дорожке |
| `remove_clip` | Удалить клип |
| `undo_last_change` | Откатить черновик к предыдущей резервной копии |
| `media_info` | Длительность и размер медиафайла |
| `list_effects` | Названия переходов, анимаций и шрифтов CapCut (платные Pro по умолчанию скрыты) |

Время везде в секундах.

## Ограничения

- **Сервер меняет только черновики, которые создал сам.** Остальные (сделанные руками в CapCut) можно только
  посмотреть через `inspect_draft`. План монтажа хранится в `claude_project.json` внутри папки черновика.
- **Перед каждым изменением делается резервная копия** в папке `.claude_backups` внутри черновика
  (хранятся последние 15), `undo_last_change` возвращает её. Если вы поправили такой черновик руками в CapCut,
  сервер не перезапишет его без вашего согласия (`force=true`).
- **CapCut 9.x может попросить перепривязать медиа** при открытии черновика. Укажите те же файлы и продолжайте.
- Если черновик открыт в CapCut, пока его меняют, выйдите на главный экран CapCut и откройте его заново.
- Видео и музыка не копируются в черновик, он ссылается на них — не перемещайте эти файлы.
- Работает только на Windows.

## Для разработчиков

```bash
python -m venv .venv
.venv\Scripts\pip install -e ".[test]"
.venv\Scripts\python -m pytest
```

Тест собирает черновик во временной папке через `CAPCUT_DRAFTS_PATH`; сам CapCut для этого не нужен.

## Лицензия

[MIT](LICENSE). У зависимостей свои лицензии: [pycapcut](https://github.com/GuanYixuan/pyCapCut),
[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (MIT).
