"""Сохранение миров: saves/<мир>/world.json и saves/<мир>/chunks/<x>_<z>.npz.

world.json записывается последним, поэтому его наличие означает, что сохранение
завершено. Чанк хранит свою палитру блоков и массив номеров в ней на всю высоту мира.
"""
import io
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import NamedTuple

import numpy as np

from block import PALETTE, REMOVED, Block, block_id, decode_state, is_known_type
from chunk import Y_MAX, Y_MIN, Chunk

SAVES_DIR = Path("saves")
FORMAT_VERSION = 1


def world_folder(name):
    return SAVES_DIR / name


def has_save(name):
    return (world_folder(name) / "world.json").exists()


class SaveInfo(NamedTuple):
    folder: str
    name: str
    generator: str | None
    last_played: float
    broken: bool = False
    game_mode: str = "creative"


def read_save_info(folder):
    """Короткие сведения о мире для списка в меню. Битое сохранение не роняет меню."""
    path = world_folder(folder) / "world.json"
    last_played = path.stat().st_mtime

    try:
        meta = json.loads(path.read_text(encoding="utf-8"))

        return SaveInfo(
            folder,
            str(meta.get("name", folder)),
            meta.get("generator", folder),
            last_played,
            game_mode=game_mode_of(meta)
        )

    except (OSError, ValueError, AttributeError):
        return SaveInfo(folder, folder, None, last_played, broken=True)


GAME_MODES = ("survival", "creative")


def game_mode_of(meta):
    # Миры, сохранённые до появления режимов, были творческими.
    mode = meta.get("game_mode")

    return mode if mode in GAME_MODES else "creative"


def list_saves():
    """Все завершённые сохранения, сначала те, в которые играли последними."""
    if not SAVES_DIR.is_dir():
        return []

    saves = [
        read_save_info(path.name)
        for path in SAVES_DIR.iterdir()
        if (path / "world.json").is_file()
    ]

    return sorted(saves, key=lambda save: save.last_played, reverse=True)


def folder_for_name(name):
    """Свободная папка для нового мира: недопустимые символы заменяются на _."""
    base = "".join(
        char if char.isalnum() or char in " -_" else "_"
        for char in name
    ).strip(" .") or "World"

    folder = base
    number = 2

    while world_folder(folder).exists():
        folder = f"{base} ({number})"
        number += 1

    return folder


def delete_world(folder):
    path = world_folder(folder).resolve()

    # Имя приходит из списка миров, но удалять разрешаем только папку внутри saves.
    if path.parent != SAVES_DIR.resolve() or not path.is_dir():
        raise ValueError(f"'{folder}' не является папкой мира")

    shutil.rmtree(path)


def chunk_filename(chunk):
    return f"{chunk.chunk_x}_{chunk.chunk_z}.npz"


def chunk_arrays(chunk):
    """Чанк целиком массивом номеров своей палитры. Сжатый он занимает немного:
    в нём длинные одинаковые ряды воздуха и камня.

    В палитре вместе с типом хранится состояние: у дверей оно своё у каждой.
    Номера в палитре сохранения свои, а не номера block.PALETTE: те меняются от
    запуска к запуску (и у разных игроков в сетевой игре).
    """
    numbers = np.unique(chunk.ids)
    numbers = numbers[numbers != 0]

    local = np.zeros(len(PALETTE), dtype=np.uint16)
    local[numbers] = np.arange(1, len(numbers) + 1, dtype=np.uint16)

    palette = [PALETTE[number].key() for number in numbers.tolist()]

    return {
        "volume": local[chunk.ids],
        "y_min": np.array(Y_MIN),
        "palette": np.array(palette, dtype=str),
    }


def save_chunk(chunk, path):
    # Пишем во временный файл и подменяем целиком: падение на середине записи
    # не испортит предыдущую версию чанка.
    temporary = path.with_suffix(".tmp")

    with open(temporary, "wb") as file:
        np.savez_compressed(file, **chunk_arrays(chunk))

    os.replace(temporary, path)


def encode_chunk(chunk):
    """Чанк в байты для отправки по сети, в том же виде, что и на диске."""
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **chunk_arrays(chunk))

    return buffer.getvalue()


def decode_chunk(data, chunk_x, chunk_z):
    """Чанк из байтов encode_chunk. ValueError, если данные испорчены."""
    try:
        return read_chunk_file(io.BytesIO(data), chunk_x, chunk_z)

    except (OSError, KeyError, zipfile.BadZipFile) as error:
        raise ValueError(f"испорченный чанк: {error!r}")


def block_from_key(key):
    block_type, _, state = key.partition("|")

    if block_type in REMOVED:
        return Block(REMOVED[block_type])

    if not is_known_type(block_type):
        raise ValueError(f"неизвестный тип блока '{block_type}'")

    return Block(block_type, decode_state(block_type, state) if state else None)


def load_chunk(path):
    chunk_x, chunk_z = (int(value) for value in path.stem.split("_"))

    return read_chunk_file(path, chunk_x, chunk_z)


def read_chunk_file(file, chunk_x, chunk_z):
    chunk = Chunk(chunk_x, chunk_z)

    with np.load(file, allow_pickle=False) as data:
        palette = data["palette"].tolist()

        if "volume" in data:
            volume = data["volume"]
            y_min = int(data["y_min"])
            positions = types = None
        else:
            # Первые сохранения: координаты блоков и номер в палитре у каждого.
            volume = None
            positions = data["positions"].reshape(-1, 3)
            types = data["types"]

    if volume is not None:
        if volume.shape != chunk.ids.shape or y_min != Y_MIN:
            raise ValueError(f"чанк другой высоты: {volume.shape}, y от {y_min}")

        numbers = np.array([0] + [block_id(block_from_key(key)) for key in palette], dtype=np.uint16)
        chunk.ids = numbers[volume]

        return chunk

    numbers = np.array([block_id(block_from_key(key)) for key in palette], dtype=np.uint16)

    inside = (positions[:, 1] >= Y_MIN) & (positions[:, 1] <= Y_MAX)

    if not inside.all():
        raise ValueError("блоки за пределами высоты мира")

    if len(positions):
        chunk.ids[positions[:, 0], positions[:, 1] - Y_MIN, positions[:, 2]] = numbers[types]

    return chunk


def chunk_path(name, chunk_x, chunk_z):
    return world_folder(name) / "chunks" / f"{chunk_x}_{chunk_z}.npz"


def write_chunk(name, chunk):
    """Записывает один чанк мира, например перед выгрузкой из памяти."""
    path = chunk_path(name, chunk.chunk_x, chunk.chunk_z)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_chunk(chunk, path)
    chunk.dirty = False


def read_chunk(name, chunk_x, chunk_z):
    """Сохранённый чанк или None, если его ещё не записывали."""
    path = chunk_path(name, chunk_x, chunk_z)

    if not path.is_file():
        return None

    return load_chunk(path)


def saved_chunk_keys(name):
    """Чанки, записанные на диск: они отличаются от того, что построил бы генератор."""
    keys = set()

    for path in (world_folder(name) / "chunks").glob("*.npz"):
        try:
            chunk_x, chunk_z = (int(value) for value in path.stem.split("_"))
        except ValueError:
            continue

        keys.add((chunk_x, chunk_z))

    return keys


def clear_chunks(name):
    """Новый мир в старой папке: чанки прошлой версии мира больше не нужны."""
    for path in (world_folder(name) / "chunks").glob("*.npz"):
        path.unlink()


def save_world(world, player, name, display_name=None, generator=None, extra=None):
    """Записывает изменённые чанки и игрока. Возвращает число записанных чанков.

    extra: дополнительные поля world.json (режим игры, инвентарь, контейнеры).
    """
    folder = world_folder(name)
    chunks_folder = folder / "chunks"
    chunks_folder.mkdir(parents=True, exist_ok=True)

    written = 0

    for chunk in world.chunks.values():
        if chunk.dirty:
            save_chunk(chunk, chunks_folder / chunk_filename(chunk))
            chunk.dirty = False
            written += 1

    temporary = folder / "world.tmp"

    temporary.write_text(json.dumps({
        "format": FORMAT_VERSION,
        "name": display_name or name,
        "generator": generator or name,
        "camera": {
            "position": list(player.camera.position),
            "rotation": list(player.camera.rotation)
        },
        "flying": player.flying,
        **(extra or {})
    }, indent=4), encoding="utf-8")

    os.replace(temporary, folder / "world.json")

    return written


def load_world(world, player, name, load_chunks=True):
    """Загружает чанки и игрока. Возвращает весь world.json: там режим, инвентарь и прочее.

    load_chunks: False у бесконечного мира, он читает чанки сам по мере надобности.
    """
    folder = world_folder(name)

    try:
        meta = json.loads((folder / "world.json").read_text(encoding="utf-8"))

        if meta["format"] != FORMAT_VERSION:
            raise ValueError(f"неподдерживаемая версия формата {meta['format']}")

        position = tuple(meta["camera"]["position"])
        rotation = tuple(meta["camera"]["rotation"])

        paths = (folder / "chunks").glob("*.npz") if load_chunks else ()
        chunks = [load_chunk(path) for path in paths]

        # glob отдаёт файлы в произвольном порядке, а от порядка объектов зависит,
        # какой из них победит при равной глубине на стыке чанков.
        for chunk in sorted(chunks, key=lambda chunk: (chunk.chunk_x, chunk.chunk_z)):
            world.add_chunk(chunk)

    except (OSError, KeyError, TypeError, ValueError, zipfile.BadZipFile) as error:
        raise SystemExit(
            f"Не удалось загрузить сохранение {folder}: {error!r}\n"
            f"Файлы не тронуты. Чтобы начать мир заново: python main.py {name} --new"
        )

    player.camera.position = position
    player.camera.rotation = rotation

    # В сохранениях старых версий этого поля нет.
    player.flying = meta.get("flying") is True

    return meta
