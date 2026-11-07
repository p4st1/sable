"""Настройки игры в settings.json. Файл создаётся при первом запуске и правится вручную."""
import json
import os
from pathlib import Path
from typing import Callable, NamedTuple

from config import Config

SETTINGS_FILE = Path("settings.json")


def is_number(value):
    return type(value) in (int, float)


def number_between(low, high):
    return lambda value: is_number(value) and low <= value <= high


def integer_between(low, high):
    return lambda value: type(value) is int and low <= value <= high


def one_of(options):
    return lambda value: is_number(value) and value in options


class Field(NamedTuple):
    default: object
    is_valid: Callable


FIELDS = {
    # Меньше 800x480 меню при масштабе 4x не помещается в окно.
    "screen_width": Field(1280, integer_between(800, 7680)),
    "screen_height": Field(720, integer_between(480, 4320)),
    "render_scale": Field(0.25, one_of(Config.RENDER_SCALE)),
    "gui_scale": Field(2, one_of(Config.GUI_SCALE)),
    "fps_limit": Field(240, integer_between(0, 1000)),
    "sound_volume": Field(100, integer_between(0, 100)),
    "music_volume": Field(100, integer_between(0, 100)),
    # Дальность тумана в блоках: дальше всё сливается с небом и не рисуется.
    "fog_distance": Field(64, one_of(Config.FOG_DISTANCE)),
    "fov": Field(70, number_between(30, 120)),
    "mouse_sensitivity": Field(0.003, number_between(0.0001, 0.05)),
    "speed": Field(4.3, number_between(0.1, 100)),
    "gravity": Field(32, number_between(1, 200)),
    "jump_speed": Field(9, number_between(1, 50)),
    "reach": Field(6, number_between(1, 64)),
    "selected_slot": Field(1, integer_between(0, Config.HOTBAR_SIZE - 1)),
    # Мягкий свет: плавные переходы яркости и тени в углах. Без него быстрее.
    "smooth_lighting": Field(True, lambda value: type(value) is bool),
}


# Поля прошлых версий. Хотбар теперь хранится в сохранении мира.
RETIRED = {"hotbar"}


class Settings:
    def __init__(self):
        for name, field in FIELDS.items():
            setattr(self, name, field.default)

    @classmethod
    def load(cls):
        settings = cls()

        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))

            if not isinstance(data, dict):
                raise ValueError("ожидался объект с настройками")

        except FileNotFoundError:
            settings.save()
            return settings

        except ValueError as error:
            # Файл могли править вручную, поэтому не затираем его, а откладываем.
            backup = SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".bad")
            os.replace(SETTINGS_FILE, backup)
            settings.save()

            print(f"{SETTINGS_FILE} повреждён ({error}). Он сохранён как {backup}, настройки сброшены.")
            return settings

        for name, value in data.items():
            if name in RETIRED:
                continue

            if name not in FIELDS:
                print(f"Неизвестная настройка '{name}' пропущена.")

            elif FIELDS[name].is_valid(value):
                setattr(settings, name, value)

            else:
                print(f"Неверное значение {name}: {value!r}, используется {FIELDS[name].default!r}.")

        return settings

    def save(self):
        values = {name: getattr(self, name) for name in FIELDS}

        temporary = SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".tmp")
        temporary.write_text(json.dumps(values, indent=4), encoding="utf-8")

        os.replace(temporary, SETTINGS_FILE)
