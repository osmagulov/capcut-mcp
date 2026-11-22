"""MCP server for CapCut desktop drafts (Windows). Unofficial, not affiliated with CapCut/ByteDance.

MCP-сервер для CapCut (десктоп, Windows). Неофициальный проект.

У CapCut нет официального скриптового API, поэтому сервер работает через файлы
черновиков (draft_content.json / draft_meta_info.json) в папке черновиков CapCut.
Генерация самого черновика делается библиотекой pycapcut.

Модель работы:
  * Черновики, созданные этим сервером, хранят "план" монтажа в файле
    claude_project.json внутри папки черновика. Любое изменение (добавить клип,
    поменять длительность, переставить) меняет план и заново собирает
    draft_content.json. Перед каждой перезаписью делается резервная копия.
  * Чужие черновики (сделанные руками в CapCut) можно только смотреть
    (inspect_draft) — сервер их не меняет.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

import pycapcut as cc
from mcp.server.mcpserver import MCPServer

# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------

SEC = 1_000_000  # pycapcut считает время в микросекундах
PLAN_FILE = "claude_project.json"
BACKUP_DIR = ".claude_backups"
MAX_BACKUPS = 15

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".heic", ".tif", ".tiff"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma"}


def _find_drafts_root() -> Path:
    env = os.environ.get("CAPCUT_DRAFTS_PATH")
    if env:
        return Path(env)
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    # Новый CapCut хранит путь к папке черновиков в root_meta_info.json
    root_meta = local / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft" / "root_meta_info.json"
    try:
        data = json.loads(root_meta.read_text(encoding="utf-8"))
        for d in data.get("all_draft_store", []):
            p = d.get("draft_root_path")
            if p and Path(p).exists():
                return Path(p)
    except Exception:
        pass
    for cand in (local / "CapCut Drafts", local / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"):
        if cand.exists():
            return cand
    return local / "CapCut Drafts"


DRAFTS_ROOT = _find_drafts_root()

mcp = MCPServer(
    "capcut",
    instructions=(
        "Управление черновиками CapCut (десктоп). Время везде в секундах. "
        "Типичный порядок: create_draft -> add_media (видео/картинки на главную дорожку по порядку) -> "
        "add_media(track='audio') для музыки -> add_text / add_subtitles -> get_project для проверки. "
        "Каждое изменение сразу сохраняется в черновик. Если CapCut открыт на этом черновике, "
        "пользователь должен закрыть его (вернуться на главный экран CapCut) и открыть снова, чтобы увидеть изменения. "
        "Пути к файлам — абсолютные пути Windows."
    ),
)

# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _draft_dir(name: str) -> Path:
    p = DRAFTS_ROOT / name
    if not p.is_dir():
        raise ValueError(f"Черновик '{name}' не найден в {DRAFTS_ROOT}. Посмотрите list_drafts.")
    return p


def _load_plan(name: str) -> dict:
    p = _draft_dir(name) / PLAN_FILE
    if not p.exists():
        raise ValueError(
            f"Черновик '{name}' создан не через Claude, его можно только посмотреть (inspect_draft). "
            "Чтобы смонтировать что-то, создайте новый черновик через create_draft."
        )
    return json.loads(p.read_text(encoding="utf-8"))


def _file_hash(p: Path) -> str:
    if not p.exists():
        return ""
    return hashlib.md5(p.read_bytes()).hexdigest()


def _backup(ddir: Path) -> Optional[str]:
    content = ddir / "draft_content.json"
    if not content.exists():
        return None
    bdir = ddir / BACKUP_DIR
    bdir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dst = bdir / stamp
    dst.mkdir()
    for f in ("draft_content.json", "draft_meta_info.json", PLAN_FILE):
        if (ddir / f).exists():
            shutil.copy2(ddir / f, dst / f)
    backups = sorted(x for x in bdir.iterdir() if x.is_dir())
    for old in backups[:-MAX_BACKUPS]:
        shutil.rmtree(old, ignore_errors=True)
    return str(dst)


def _rgb(color: str) -> tuple[float, float, float]:
    c = color.strip().lstrip("#")
    if len(c) != 6:
        raise ValueError(f"Цвет должен быть в формате #RRGGBB, получено '{color}'")
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _kind_for(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in AUDIO_EXT:
        return "audio"
    return "video"


def _us(seconds: Optional[float]) -> Optional[int]:
    return None if seconds is None else int(round(seconds * SEC))


def _enum_lookup(enum_cls, name: str):
    try:
        return enum_cls.from_name(name)
    except Exception:
        pass
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    for m in enum_cls:
        if m.name.lower() == key or getattr(m.value, "name", getattr(m.value, "title", "")).lower() == name.strip().lower():
            return m
    raise ValueError(f"'{name}' не найдено. Посмотрите список через list_effects.")


_media_cache: dict[str, Any] = {}


def _material(path: str, kind: str):
    key = f"{kind}:{path}:{os.path.getmtime(path)}"
    if key not in _media_cache:
        _media_cache[key] = cc.AudioMaterial(path) if kind == "audio" else cc.VideoMaterial(path)
    return _media_cache[key]


def _media_duration_s(path: str, kind: str) -> Optional[float]:
    if kind == "image":
        return None
    return _material(path, kind).duration / SEC


# ---------------------------------------------------------------------------
# Сборка черновика из плана
# ---------------------------------------------------------------------------


def _layout(plan: dict) -> list[dict]:
    """Возвращает клипы с вычисленными start/duration (секунды)."""
    out = []
    t = 0.0
    for c in plan["clips"]:
        c = dict(c)
        if c["track"] == "main":
            c["_start"] = t
            t += c["duration"]
        else:
            c["_start"] = c["start"]
        out.append(c)
    return out


def _alloc_tracks(clips: list[dict]) -> dict[str, int]:
    """Раскладывает пересекающиеся клипы по разным дорожкам."""
    lanes: list[list[tuple[float, float]]] = []
    res = {}
    for c in sorted(clips, key=lambda x: x["_start"]):
        s, e = c["_start"], c["_start"] + c["duration"]
        for i, lane in enumerate(lanes):
            if all(e <= ls + 1e-6 or s >= le - 1e-6 for ls, le in lane):
                lane.append((s, e))
                res[c["id"]] = i
                break
        else:
            lanes.append([(s, e)])
            res[c["id"]] = len(lanes) - 1
    return res


def _build_script(plan: dict) -> tuple[cc.ScriptFile, list[tuple[str, Any]]]:
    sf = cc.ScriptFile(plan["width"], plan["height"], plan["fps"])
    clips = _layout(plan)
    used: list[tuple[str, Any]] = []

    groups: dict[str, list[dict]] = {"main": [], "overlay": [], "audio": [], "text": []}
    for c in clips:
        groups[c["track"]].append(c)

    if groups["main"]:
        sf.add_track(cc.TrackType.video, "main", relative_index=0)
    ov = _alloc_tracks(groups["overlay"])
    for i in range(max(ov.values(), default=-1) + 1):
        sf.add_track(cc.TrackType.video, f"overlay{i + 1}", relative_index=i + 1)
    au = _alloc_tracks(groups["audio"])
    for i in range(max(au.values(), default=-1) + 1):
        sf.add_track(cc.TrackType.audio, f"audio{i + 1}", relative_index=i)
    tx = _alloc_tracks(groups["text"])
    for i in range(max(tx.values(), default=-1) + 1):
        sf.add_track(cc.TrackType.text, f"text{i + 1}", relative_index=i)

    def clip_settings(c):
        return cc.ClipSettings(
            alpha=c.get("opacity", 1.0),
            scale_x=c.get("scale", 1.0), scale_y=c.get("scale", 1.0),
            transform_x=c.get("x", 0.0), transform_y=c.get("y", 0.0),
            rotation=c.get("rotation", 0.0),
        )

    for c in clips:
        trange = cc.Timerange(_us(c["_start"]), _us(c["duration"]))
        if c["kind"] in ("video", "image"):
            mat = _material(c["path"], c["kind"])
            used.append((c["kind"], mat))
            kw: dict[str, Any] = dict(volume=c.get("volume", 1.0), clip_settings=clip_settings(c))
            if c["kind"] == "video":
                speed = c.get("speed", 1.0)
                src_start = _us(c.get("source_start", 0.0))
                kw["source_timerange"] = cc.Timerange(src_start, int(round(_us(c["duration"]) * speed)))
                kw["speed"] = speed
            seg = cc.VideoSegment(mat, trange, **kw)
            if c["kind"] == "video" and (c.get("fade_in") or c.get("fade_out")):
                seg.add_fade(_us(c.get("fade_in", 0.0)), _us(c.get("fade_out", 0.0)))
            if c.get("transition"):
                seg.add_transition(_enum_lookup(cc.TransitionType, c["transition"]))
            if c.get("intro"):
                seg.add_animation(_enum_lookup(cc.IntroType, c["intro"]))
            if c.get("outro"):
                seg.add_animation(_enum_lookup(cc.OutroType, c["outro"]))
            track = "main" if c["track"] == "main" else f"overlay{ov[c['id']] + 1}"
            sf.add_segment(seg, track)
        elif c["kind"] == "audio":
            mat = _material(c["path"], "audio")
            used.append(("audio", mat))
            speed = c.get("speed", 1.0)
            seg = cc.AudioSegment(
                mat, trange,
                source_timerange=cc.Timerange(_us(c.get("source_start", 0.0)), int(round(_us(c["duration"]) * speed))),
                speed=speed, volume=c.get("volume", 1.0),
            )
            if c.get("fade_in") or c.get("fade_out"):
                seg.add_fade(_us(c.get("fade_in", 0.0)), _us(c.get("fade_out", 0.0)))
            sf.add_segment(seg, f"audio{au[c['id']] + 1}")
        elif c["kind"] == "text":
            style = cc.TextStyle(
                size=c.get("size", 8.0), bold=c.get("bold", False), italic=c.get("italic", False),
                color=_rgb(c.get("color", "#FFFFFF")), align=1, auto_wrapping=True,
            )
            kw = {}
            if c.get("font"):
                kw["font"] = _enum_lookup(cc.FontType, c["font"])
            if c.get("background_color"):
                kw["background"] = cc.TextBackground(color=c["background_color"], alpha=c.get("background_opacity", 0.6), round_radius=0.3)
            if c.get("outline_color"):
                kw["border"] = cc.TextBorder(color=_rgb(c["outline_color"]), width=c.get("outline_width", 40.0))
            seg = cc.TextSegment(c["text"], trange, style=style, clip_settings=clip_settings(c), **kw)
            if c.get("intro"):
                seg.add_animation(_enum_lookup(cc.TextIntro, c["intro"]))
            if c.get("outro"):
                seg.add_animation(_enum_lookup(cc.TextOutro, c["outro"]))
            sf.add_segment(seg, f"text{tx[c['id']] + 1}")
    return sf, used


def _write_meta(ddir: Path, plan: dict, duration_us: int, used: list[tuple[str, Any]]) -> None:
    meta_path = ddir / "draft_meta_info.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        meta = json.loads(Path(cc.assets.get_asset_path("DRAFT_META_TEMPLATE")).read_text(encoding="utf-8"))
    now_us = int(time.time() * SEC)
    meta["draft_name"] = ddir.name
    meta["draft_fold_path"] = str(ddir).replace("\\", "/")
    meta["draft_root_path"] = str(ddir.parent)
    meta.setdefault("draft_id", str(uuid.uuid4()).upper())
    if not meta.get("tm_draft_create"):
        meta["tm_draft_create"] = now_us
    meta["tm_draft_modified"] = now_us
    meta["tm_duration"] = duration_us
    # Регистрируем используемые файлы, иначе новые CapCut просят "перепривязать" медиа
    seen = set()
    entries = []
    for kind, mat in used:
        if mat.path in seen:
            continue
        seen.add(mat.path)
        entries.append({
            "ai_group_type": "", "create_time": -1,
            "duration": 0 if kind == "image" else int(mat.duration),
            "enter_from": 0, "extra_info": os.path.basename(mat.path),
            "file_Path": mat.path.replace("\\", "/"),
            "height": getattr(mat, "height", 0) or 0,
            "id": str(uuid.uuid4()).upper(), "import_time": int(time.time()), "import_time_ms": int(time.time() * 1000),
            "item_source": 1, "material_color_tag": "", "md5": "",
            "metetype": {"video": "video", "image": "photo", "audio": "music"}[kind],
            "roughcut_time_range": {"duration": -1, "start": -1},
            "sub_time_range": {"duration": -1, "start": -1},
            "type": 0, "width": getattr(mat, "width", 0) or 0,
        })
    groups = meta.setdefault("draft_materials", [])
    g0 = next((g for g in groups if g.get("type") == 0), None)
    if g0 is None:
        g0 = {"type": 0, "value": []}
        groups.insert(0, g0)
    g0["value"] = entries
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=4), encoding="utf-8")


def _render(name: str, plan: dict, *, force: bool = False) -> dict:
    ddir = _draft_dir(name)
    content = ddir / "draft_content.json"
    last = plan.get("_last_written_hash")
    if not force and last and content.exists() and _file_hash(content) != last:
        raise ValueError(
            "Черновик был изменён вручную в CapCut после последней правки Claude. "
            "Если продолжить, ручные правки будут перезаписаны (резервная копия всё равно сохранится). "
            "Повторите команду с force=true, только если пользователь согласен."
        )
    sf, used = _build_script(plan)
    backup = _backup(ddir)
    sf.dump(str(content))
    _write_meta(ddir, plan, sf.duration, used)
    plan["_last_written_hash"] = _file_hash(content)
    (ddir / PLAN_FILE).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"duration_sec": round(sf.duration / SEC, 3), "backup": backup}


def _summary(plan: dict) -> dict:
    clips = _layout(plan)
    rows = []
    main_i = 0
    for c in clips:
        r = {"id": c["id"], "track": c["track"], "kind": c["kind"],
             "start": round(c["_start"], 3), "duration": round(c["duration"], 3),
             "end": round(c["_start"] + c["duration"], 3)}
        if c["track"] == "main":
            r["order"] = main_i
            main_i += 1
        if c.get("path"):
            r["file"] = os.path.basename(c["path"])
        if c.get("text"):
            r["text"] = c["text"]
        for k in ("volume", "speed", "source_start", "x", "y", "scale", "transition", "intro", "outro", "size", "color"):
            if k in c:
                r[k] = c[k]
        rows.append(r)
    total = max((r["end"] for r in rows), default=0)
    return {"name": plan["name"], "resolution": f"{plan['width']}x{plan['height']}", "fps": plan["fps"],
            "total_duration": total, "clips": rows}


def _mutate(draft: str, fn, force: bool = False) -> dict:
    plan = _load_plan(draft)
    result = fn(plan) or {}
    info = _render(draft, plan, force=force)
    return {**result, **info, "project": _summary(plan)}


# ---------------------------------------------------------------------------
# Инструменты MCP
# ---------------------------------------------------------------------------


@mcp.tool()
def list_drafts() -> dict:
    """Список черновиков CapCut на компьютере (новые сверху). editable=true — черновик создан через Claude и его можно менять."""
    rows = []
    for d in DRAFTS_ROOT.iterdir():
        if not d.is_dir() or not (d / "draft_content.json").exists():
            continue
        dur = None
        try:
            meta = json.loads((d / "draft_meta_info.json").read_text(encoding="utf-8"))
            dur = round(meta.get("tm_duration", 0) / SEC, 2)
        except Exception:
            pass
        rows.append({"name": d.name, "modified": datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                     "duration_sec": dur, "editable": (d / PLAN_FILE).exists(), "_m": d.stat().st_mtime})
    rows.sort(key=lambda r: r.pop("_m"), reverse=True)
    return {"drafts_folder": str(DRAFTS_ROOT), "drafts": rows}


@mcp.tool()
def inspect_draft(draft: str) -> dict:
    """Показать содержимое любого черновика (дорожки и клипы), включая сделанные вручную. Только чтение."""
    ddir = _draft_dir(draft)
    c = json.loads((ddir / "draft_content.json").read_text(encoding="utf-8"))
    mats: dict[str, str] = {}
    for key in ("videos", "audios"):
        for m in c.get("materials", {}).get(key, []):
            mats[m["id"]] = m.get("material_name") or os.path.basename(m.get("path", ""))
    for m in c.get("materials", {}).get("texts", []):
        txt = m.get("content", "")
        try:
            txt = json.loads(txt).get("text", txt)
        except Exception:
            pass
        mats[m["id"]] = f"текст: {txt}"
    tracks = []
    for t in c.get("tracks", []):
        segs = []
        for s in t.get("segments", []):
            tr = s.get("target_timerange", {})
            segs.append({"what": mats.get(s.get("material_id"), s.get("material_id")),
                         "start": round(tr.get("start", 0) / SEC, 3), "duration": round(tr.get("duration", 0) / SEC, 3)})
        tracks.append({"type": t.get("type"), "segments": segs})
    cv = c.get("canvas_config", {})
    return {"name": draft, "resolution": f"{cv.get('width')}x{cv.get('height')}", "fps": c.get("fps"),
            "duration_sec": round(c.get("duration", 0) / SEC, 3), "editable_by_claude": (ddir / PLAN_FILE).exists(),
            "tracks": tracks}


@mcp.tool()
def create_draft(name: str, width: int = 1920, height: int = 1080, fps: int = 30) -> dict:
    """Создать новый пустой черновик CapCut.

    Размеры: 1920x1080 — обычное горизонтальное видео (YouTube), 1080x1920 — вертикальное (Reels/TikTok/Shorts), 1080x1080 — квадрат.
    """
    if any(ch in name for ch in '\\/:*?"<>|'):
        raise ValueError("Имя черновика не должно содержать символы \\ / : * ? \" < > |")
    ddir = DRAFTS_ROOT / name
    if ddir.exists():
        raise ValueError(f"Черновик '{name}' уже существует. Выберите другое имя.")
    ddir.mkdir(parents=True)
    shutil.copy(cc.assets.get_asset_path("DRAFT_META_TEMPLATE"), ddir / "draft_meta_info.json")
    meta = json.loads((ddir / "draft_meta_info.json").read_text(encoding="utf-8"))
    meta["draft_id"] = str(uuid.uuid4()).upper()
    (ddir / "draft_meta_info.json").write_text(json.dumps(meta, ensure_ascii=False, indent=4), encoding="utf-8")
    plan = {"name": name, "width": width, "height": height, "fps": fps, "clips": [], "next_id": 1}
    (ddir / PLAN_FILE).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    _render(name, plan)
    return {"created": str(ddir), "hint": "Черновик появится на главном экране CapCut (если не видно — перезапустите CapCut).",
            "project": _summary(plan)}


@mcp.tool()
def get_project(draft: str) -> dict:
    """Показать план монтажа черновика, созданного через Claude: все клипы с id, временем начала/конца и настройками."""
    return _summary(_load_plan(draft))


@mcp.tool()
def add_media(
    draft: str,
    path: str,
    track: Literal["main", "overlay", "audio"] = "main",
    duration: Optional[float] = None,
    start: Optional[float] = None,
    source_start: float = 0.0,
    position: Optional[int] = None,
    volume: float = 1.0,
    speed: float = 1.0,
    scale: float = 1.0,
    x: float = 0.0,
    y: float = 0.0,
    opacity: float = 1.0,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    transition: Optional[str] = None,
    intro: Optional[str] = None,
    outro: Optional[str] = None,
) -> dict:
    """Добавить видео, картинку или аудио в черновик.

    track:
      * "main" — главная видеодорожка: клипы идут друг за другом без пауз, в порядке добавления
        (или вставить в место position, считая с 0). start здесь не нужен.
      * "overlay" — видео/картинка поверх главной (картинка-в-картинке, логотип). Нужен start.
      * "audio" — музыка/озвучка. start по умолчанию 0.
    duration — сколько секунд клип идёт на таймлайне (по умолчанию: всё видео/аудио, картинка — 3 с).
    source_start — с какой секунды исходного файла начинать.
    volume 0..2 (0 — без звука), speed — скорость (2 = в 2 раза быстрее).
    scale/x/y — размер и положение: x,y от -1 до 1 (0,0 — центр; y=1 — верх).
    fade_in/fade_out — плавное появление/затухание звука, секунды.
    transition — переход к СЛЕДУЮЩЕМУ клипу (только main), intro/outro — анимация появления/исчезновения.
    Названия эффектов — через list_effects.
    """
    path = str(Path(path).expanduser().resolve())
    if not os.path.exists(path):
        raise ValueError(f"Файл не найден: {path}")
    kind = _kind_for(path)
    if kind == "audio" and track != "audio":
        track = "audio"
    if kind != "audio" and track == "audio":
        raise ValueError("На аудиодорожку можно добавить только аудиофайл. Для звука из видео используйте track='main'.")
    full = _media_duration_s(path, kind)
    if duration is None:
        duration = 3.0 if kind == "image" else (full - source_start) / speed
    if full is not None and source_start + duration * speed > full + 1e-3:
        raise ValueError(f"Файл длится {full:.2f} с — нельзя взять {duration} с начиная с {source_start} с при скорости {speed}.")
    if track == "overlay" and start is None:
        raise ValueError("Для overlay укажите start (секунда, с которой клип появляется).")

    def fn(plan):
        cid = f"c{plan['next_id']}"
        plan["next_id"] += 1
        clip = {"id": cid, "kind": kind, "track": track, "path": path, "duration": round(duration, 4),
                "source_start": source_start, "volume": volume}
        if speed != 1.0:
            clip["speed"] = speed
        if track != "main":
            clip["start"] = start or 0.0
        for k, v, d in (("scale", scale, 1.0), ("x", x, 0.0), ("y", y, 0.0), ("opacity", opacity, 1.0),
                        ("fade_in", fade_in, 0.0), ("fade_out", fade_out, 0.0)):
            if v != d:
                clip[k] = v
        for k, v in (("transition", transition), ("intro", intro), ("outro", outro)):
            if v:
                clip[k] = v
        if track == "main" and position is not None:
            mains = [i for i, c in enumerate(plan["clips"]) if c["track"] == "main"]
            idx = mains[position] if position < len(mains) else len(plan["clips"])
            plan["clips"].insert(idx, clip)
        else:
            plan["clips"].append(clip)
        return {"added_id": cid}

    return _mutate(draft, fn)


@mcp.tool()
def add_text(
    draft: str,
    text: str,
    start: float,
    duration: float,
    size: float = 8.0,
    color: str = "#FFFFFF",
    bold: bool = False,
    italic: bool = False,
    x: float = 0.0,
    y: float = 0.0,
    font: Optional[str] = None,
    background_color: Optional[str] = None,
    outline_color: Optional[str] = None,
    intro: Optional[str] = None,
    outro: Optional[str] = None,
) -> dict:
    """Добавить текст (заголовок, надпись) поверх видео.

    start/duration — в секундах. size — размер шрифта (8 — обычный, 12–15 — крупный заголовок, 5 — как субтитры).
    color/background_color/outline_color — '#RRGGBB'. y: 0 — центр, 0.8 — сверху, -0.8 — снизу.
    font, intro, outro — названия из list_effects (fonts / text_intro / text_outro).
    """
    def fn(plan):
        cid = f"c{plan['next_id']}"
        plan["next_id"] += 1
        clip = {"id": cid, "kind": "text", "track": "text", "text": text, "start": start, "duration": duration,
                "size": size, "color": color}
        for k, v in (("bold", bold), ("italic", italic), ("x", x), ("y", y), ("font", font),
                     ("background_color", background_color), ("outline_color", outline_color),
                     ("intro", intro), ("outro", outro)):
            if v:
                clip[k] = v
        plan["clips"].append(clip)
        return {"added_id": cid}

    return _mutate(draft, fn)


def _parse_srt(srt: str) -> list[tuple[float, float, str]]:
    def ts(s: str) -> float:
        h, m, rest = s.strip().replace(".", ",").split(":")
        sec, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000

    items = []
    for block in srt.replace("\r\n", "\n").strip().split("\n\n"):
        lines = [l for l in block.strip().split("\n") if l.strip()]
        if not lines:
            continue
        if "-->" not in lines[0]:
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            continue
        a, b = lines[0].split("-->")
        items.append((ts(a), ts(b), "\n".join(lines[1:])))
    return items


@mcp.tool()
def add_subtitles(
    draft: str,
    srt_path: Optional[str] = None,
    srt_text: Optional[str] = None,
    lines: Optional[list[dict]] = None,
    size: float = 6.0,
    color: str = "#FFFFFF",
    y: float = -0.75,
    outline_color: Optional[str] = "#000000",
    background_color: Optional[str] = None,
    offset: float = 0.0,
) -> dict:
    """Добавить субтитры. Источник — один из: srt_path (файл .srt), srt_text (текст в формате SRT)
    или lines — список {"start": сек, "end": сек, "text": "..."}. offset сдвигает все субтитры на N секунд.
    """
    if srt_path:
        items = _parse_srt(Path(srt_path).read_text(encoding="utf-8-sig"))
    elif srt_text:
        items = _parse_srt(srt_text)
    elif lines:
        items = [(float(l["start"]), float(l["end"]), str(l["text"])) for l in lines]
    else:
        raise ValueError("Передайте srt_path, srt_text или lines.")
    if not items:
        raise ValueError("Не удалось прочитать ни одного субтитра.")

    def fn(plan):
        ids = []
        for s, e, t in items:
            cid = f"c{plan['next_id']}"
            plan["next_id"] += 1
            clip = {"id": cid, "kind": "text", "track": "text", "text": t, "start": round(s + offset, 3),
                    "duration": round(e - s, 3), "size": size, "color": color, "y": y, "subtitle": True}
            if outline_color:
                clip["outline_color"] = outline_color
            if background_color:
                clip["background_color"] = background_color
            plan["clips"].append(clip)
            ids.append(cid)
        return {"added_ids": ids}

    return _mutate(draft, fn)


@mcp.tool()
def update_clip(draft: str, clip_id: str, changes: dict, force: bool = False) -> dict:
    """Изменить параметры клипа. changes — словарь, например {"duration": 4}, {"start": 2.5}, {"volume": 0.3},
    {"text": "Новый текст"}, {"source_start": 10}, {"speed": 1.5}, {"y": 0.8, "size": 12}, {"transition": null}.
    Допустимые ключи: duration, start (не для main), source_start, volume, speed, scale, x, y, rotation, opacity,
    fade_in, fade_out, transition, intro, outro, text, size, color, bold, italic, font, background_color, outline_color.
    """
    allowed = {"duration", "start", "source_start", "volume", "speed", "scale", "x", "y", "rotation", "opacity",
               "fade_in", "fade_out", "transition", "intro", "outro", "text", "size", "color", "bold", "italic",
               "font", "background_color", "outline_color"}
    bad = set(changes) - allowed
    if bad:
        raise ValueError(f"Нельзя менять: {', '.join(sorted(bad))}")

    def fn(plan):
        c = next((c for c in plan["clips"] if c["id"] == clip_id), None)
        if c is None:
            raise ValueError(f"Клип {clip_id} не найден. Посмотрите get_project.")
        if "start" in changes and c["track"] == "main":
            raise ValueError("Клипы главной дорожки идут подряд — чтобы поменять место, используйте move_clip.")
        for k, v in changes.items():
            if v is None:
                c.pop(k, None)
            else:
                c[k] = v
        if c.get("path") and c["kind"] != "image":
            full = _media_duration_s(c["path"], c["kind"])
            need = c.get("source_start", 0) + c["duration"] * c.get("speed", 1.0)
            if full is not None and need > full + 1e-3:
                raise ValueError(f"Файл длится {full:.2f} с, а нужно {need:.2f} с. Уменьшите duration/source_start/speed.")
        return {"updated_id": clip_id}

    return _mutate(draft, fn, force=force)


@mcp.tool()
def move_clip(draft: str, clip_id: str, new_position: int, force: bool = False) -> dict:
    """Переставить клип главной дорожки на новое место (0 — первый). Остальные клипы сдвигаются автоматически."""
    def fn(plan):
        c = next((c for c in plan["clips"] if c["id"] == clip_id), None)
        if c is None or c["track"] != "main":
            raise ValueError("Переставлять можно только клипы главной дорожки (track=main).")
        plan["clips"].remove(c)
        mains = [i for i, x in enumerate(plan["clips"]) if x["track"] == "main"]
        idx = mains[new_position] if 0 <= new_position < len(mains) else (mains[-1] + 1 if mains else 0)
        plan["clips"].insert(idx, c)
        return {"moved_id": clip_id}

    return _mutate(draft, fn, force=force)


@mcp.tool()
def remove_clip(draft: str, clip_id: str, force: bool = False) -> dict:
    """Удалить клип (видео, картинку, звук или текст) из черновика."""
    def fn(plan):
        n = len(plan["clips"])
        plan["clips"] = [c for c in plan["clips"] if c["id"] != clip_id]
        if len(plan["clips"]) == n:
            raise ValueError(f"Клип {clip_id} не найден.")
        return {"removed_id": clip_id}

    return _mutate(draft, fn, force=force)


@mcp.tool()
def undo_last_change(draft: str) -> dict:
    """Откатить черновик к предыдущей резервной копии (отменить последнее изменение Claude)."""
    ddir = _draft_dir(draft)
    bdir = ddir / BACKUP_DIR
    backups = sorted(x for x in bdir.iterdir() if x.is_dir()) if bdir.exists() else []
    if not backups:
        raise ValueError("Резервных копий нет.")
    last = backups[-1]
    for f in last.iterdir():
        shutil.copy2(f, ddir / f.name)
    shutil.rmtree(last)
    plan = json.loads((ddir / PLAN_FILE).read_text(encoding="utf-8")) if (ddir / PLAN_FILE).exists() else None
    if plan:
        plan["_last_written_hash"] = _file_hash(ddir / "draft_content.json")
        (ddir / PLAN_FILE).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"restored_from": str(last), "project": _summary(plan) if plan else None}


@mcp.tool()
def media_info(path: str) -> dict:
    """Узнать длительность и размер видео/аудио/картинки, чтобы правильно спланировать монтаж."""
    path = str(Path(path).expanduser().resolve())
    kind = _kind_for(path)
    mat = _material(path, kind)
    r = {"path": path, "kind": kind}
    if kind != "image":
        r["duration_sec"] = round(mat.duration / SEC, 3)
    if kind != "audio":
        r["width"], r["height"] = mat.width, mat.height
    return r


_EFFECT_ENUMS = {
    "transitions": "TransitionType",
    "video_intro": "IntroType",
    "video_outro": "OutroType",
    "text_intro": "TextIntro",
    "text_outro": "TextOutro",
    "fonts": "FontType",
}


@mcp.tool()
def list_effects(
    category: Literal["transitions", "video_intro", "video_outro", "text_intro", "text_outro", "fonts"],
    search: Optional[str] = None,
    include_pro: bool = False,
    limit: int = 60,
) -> dict:
    """Найти названия переходов, анимаций и шрифтов CapCut. По умолчанию только бесплатные (без Pro)."""
    enum_cls = getattr(cc, _EFFECT_ENUMS[category])
    out = []
    for m in enum_cls:
        meta = m.value
        title = getattr(meta, "name", None) or getattr(meta, "title", "")
        vip = getattr(meta, "is_vip", False)
        if vip and not include_pro:
            continue
        if search and search.lower() not in (m.name + " " + title).lower():
            continue
        out.append(m.name + (" (Pro)" if vip else ""))
    return {"category": category, "count": len(out), "names": out[:limit]}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
