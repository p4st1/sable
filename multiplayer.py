"""Сетевая игра по локальной сети: сервер в игре у хозяина мира и клиенты.

Хозяин открывает свой мир кнопкой "Open to LAN" и ведёт его: сохраняет,
считает воду, печки и лежащие предметы. Каждый игрок сам двигается, ломает и
ставит блоки у себя, без задержки, и сообщает хозяину, какие клетки поменялись.
Хозяин применяет эти правки и рассылает всем все изменения клеток мира.

Нетронутые чанки бесконечного мира клиент строит своим генератором с тем же
сидом, а изменённые запрашивает у хозяина. Тестовые миры маленькие, их хозяин
отдаёт целиком при входе.

Инвентарь, здоровье и место игрока хозяин хранит в своём сохранении под его
именем, так что вернувшийся игрок продолжает с того же места.
"""
import math
import random
import time
import zlib

import numpy as np
import pygame

import net
import storage
from chat import GRAY, YELLOW
from chunk import FACE_SHADE, QUAD_TRIANGLES, Chunk, box_face, in_height
from collision import FEET, player_box
from containers import KINDS
from entities import DrawObject, ItemEntity, scatter_velocity
from gui import WHITE
from items import Stack, armor_from_json, max_stack, slots_from_json
from mesh import Mesh

HOST_ID = 0
NAME_LIMIT = 16
CHAT_LIMIT = 256

# Как часто отправляется положение игроков и снимок лежащих предметов.
STATE_INTERVAL = 0.05
ITEMS_INTERVAL = 0.1
# Время суток у гостей идёт само, хозяин лишь изредка его поправляет.
TIME_INTERVAL = 5.0
# Клиент присылает хозяину инвентарь и прочее для сохранения раз в столько секунд.
SAVE_INTERVAL = 5.0

# Сколько ждать ответа сервера при входе и приветствия от нового клиента.
JOIN_TIMEOUT = 15.0
HELLO_TIMEOUT = 10.0

# Хозяин держит загруженными чанки вокруг чужих игроков: там падают их предметы
# и течёт вода, которую они пролили.
REMOTE_CHUNK_RADIUS = 1

# Чужой игрок плавно догоняет присланное положение, а не прыгает 20 раз в секунду.
FOLLOW_SPEED = 15.0
# Размах ног и рук при ходьбе: полный на обычной скорости, шаг на столько блоков.
WALK_SPEED = 4.3
STRIDE = 0.6
LIMB_SWING = 0.9
SWING_TIME = 0.3

NAMETAG_HEIGHT = 0.45
NAMETAG_DISTANCE = 64
NAMETAG_ALPHA = 90
NEAR = 0.2


class ConnectError(Exception):
    """Не удалось войти на сервер, текст для игрока."""


# Проверка присланного: всё, что не так, превращается в ValueError.

def world_time(value):
    """Время мира из сообщения: неотрицательное конечное число."""
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("неверное время мира")

    return float(value)


def vector(value, size=3):
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ValueError(f"ожидался вектор из {size} чисел")

    result = tuple(float(number) for number in value)

    if not all(math.isfinite(number) for number in result):
        raise ValueError("бесконечное число в векторе")

    return result


def cell_of(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3 or not all(type(number) is int for number in value):
        raise ValueError("ожидалась клетка из трёх целых")

    return tuple(value)


def block_key(block):
    return "" if block is None else block.key()


def decode_block(key):
    if not isinstance(key, str):
        raise ValueError("ключ блока должен быть строкой")

    return None if key == "" else storage.block_from_key(key)


def clean_name(text):
    name = "".join(char for char in str(text) if char.isalnum() or char == "_")[:NAME_LIMIT]

    return name or "Player"


def color_of(value):
    if isinstance(value, list) and len(value) == 3 and all(type(channel) is int and 0 <= channel <= 255 for channel in value):
        return tuple(value)

    return WHITE


def room_of(slots):
    """Куда ещё влезут предметы: есть ли пустая ячейка и каких типов стаки не полны."""
    return {
        "free": any(stack is None for stack in slots),
        "types": sorted({stack.type for stack in slots if stack is not None and stack.count < max_stack(stack.type)}),
    }


def has_room(room, item):
    return room.get("free") is True or item in room.get("types", ())


def chunk_key(x, z):
    return x // Chunk.SIZE, z // Chunk.SIZE


def angle_step(current, target, amount):
    """Поворот на долю amount к target кратчайшим путём."""
    difference = (target - current + math.pi) % (2 * math.pi) - math.pi

    return current + difference * amount


# Модель игрока.

SKINS = (
    "assets/minecraft/textures/entity/player/wide/steve.png",
    "assets/minecraft/textures/entity/player/wide/alex.png",
)
SKIN_SIZE = 64
# Игрок ростом 1.8 блока, в модели 32 пикселя.
PIXEL = 1.8 / 32
# Слой шапки поверх головы, на полпикселя шире с каждой стороны.
HAT_GROW = 0.5

# Части модели: начало и размер бруска в пикселях (y вверх от ног, +x справа
# от игрока, +z вперёд), место развёртки в скине и точка, вокруг которой часть
# поворачивается.
PARTS = (
    ("head", (-4, 24, -4), (8, 8, 8), (0, 0), (0, 24, 0)),
    ("hat", (-4, 24, -4), (8, 8, 8), (32, 0), (0, 24, 0)),
    ("body", (-4, 12, -2), (8, 12, 4), (16, 16), (0, 18, 0)),
    ("right_arm", (4, 12, -2), (4, 12, 4), (40, 16), (6, 22, 0)),
    ("left_arm", (-8, 12, -2), (4, 12, 4), (32, 48), (-6, 22, 0)),
    ("right_leg", (0, 0, -2), (4, 12, 4), (0, 16), (2, 12, 0)),
    ("left_leg", (-4, 0, -2), (4, 12, 4), (16, 48), (-2, 12, 0)),
)


def rotation_x(angle):
    cos, sin = math.cos(angle), math.sin(angle)

    return np.array([[1, 0, 0], [0, cos, -sin], [0, sin, cos]], dtype=np.float32)


def face_uvs(face, size, origin):
    """Углы грани в развёртке скина, в том же порядке, что у chunk.box_face.

    Развёртка бруска как в скинах: сверху верх и низ, под ними по кругу правый
    бок, перед, левый бок и спина. Ось Y модели здесь уже вниз.
    """
    width, height, depth = size
    u, v = origin
    top, bottom = v + depth, v + depth + height

    corners = {
        "top": ((u + depth + width, v), (u + depth, v), (u + depth, v + depth), (u + depth + width, v + depth)),
        "bottom": ((u + depth + 2 * width, v + depth), (u + depth + 2 * width, v), (u + depth + width, v), (u + depth + width, v + depth)),
        "front": ((u + depth + width, top), (u + depth, top), (u + depth, bottom), (u + depth + width, bottom)),
        "back": ((u + 2 * depth + width, top), (u + 2 * depth + width, bottom), (u + 2 * depth + 2 * width, bottom), (u + 2 * depth + 2 * width, top)),
        "right": ((u, top), (u, bottom), (u + depth, bottom), (u + depth, top)),
        "left": ((u + 2 * depth + width, top), (u + depth + width, top), (u + depth + width, bottom), (u + 2 * depth + width, bottom)),
    }[face]

    # Чуть внутрь от края: иначе на границе грани проступил бы пиксель соседней.
    us = [corner[0] for corner in corners]
    vs = [corner[1] for corner in corners]

    def inset(value, values):
        return value + 0.01 if value == min(values) else value - 0.01

    return [(inset(cu, us) / SKIN_SIZE, inset(cv, vs) / SKIN_SIZE) for cu, cv in corners]


class PlayerModel:
    """Меши игрока по скинам. Вершины частей хранятся вокруг их точек поворота."""

    def __init__(self, engine):
        self.engine = engine
        self.models = {}

    def get(self, skin):
        if skin not in self.models:
            self.models[skin] = self.build(skin)

        return self.models[skin]

    def build(self, skin):
        points, triangles, uvs, shades, parts = [], [], [], [], []

        for name, low, size, uv, pivot in PARTS:
            grow = HAT_GROW if name == "hat" else 0.0
            x0, y0, z0 = (low[axis] - grow for axis in range(3))
            x1, y1, z1 = (low[axis] + size[axis] + grow for axis in range(3))

            # В пиксели мира: ось Y вниз, от ног вверх это минус.
            box_low = (x0 * PIXEL, -y1 * PIXEL, z0 * PIXEL)
            box_high = (x1 * PIXEL, -y0 * PIXEL, z1 * PIXEL)
            center = np.array((pivot[0] * PIXEL, -pivot[1] * PIXEL, pivot[2] * PIXEL), dtype=np.float32)
            start = len(points)

            for face in ("top", "bottom", "front", "back", "right", "left"):
                first = len(points)
                points.extend(box_face(face, box_low, box_high))
                shades.extend([FACE_SHADE[face]] * 4)

                quad = face_uvs(face, size, uv)

                for a, b, c in QUAD_TRIANGLES.tolist():
                    triangles.append((first + a, first + b, first + c))
                    uvs.append((quad[a], quad[b], quad[c]))

            parts.append((name, start, len(points), center))

        mesh = Mesh(points, triangles, uvs, self.engine.load_texture(skin), shades)
        local = np.array(points, dtype=np.float32)

        return mesh, local, parts

    def draw_object(self, player, brightness):
        mesh, local, parts = self.get(player.skin)
        pitch, yaw = player.shown_rotation

        posed = np.empty_like(local)

        for name, start, end, center in parts:
            turn = rotation_x(player.limb_angle(name, pitch))
            posed[start:end] = (local[start:end] - center) @ turn.T + center

        # Модель смотрит в +z, поворачиваем её по взгляду игрока.
        cos, sin = math.cos(yaw), math.sin(yaw)
        body = np.array([[cos, 0, sin], [0, 1, 0], [-sin, 0, cos]], dtype=np.float32)
        x, y, z = player.shown
        feet = np.array((x, y + FEET, z), dtype=np.float32)

        return DrawObject(mesh, np.ascontiguousarray(posed @ body.T + feet, dtype=np.float32), brightness)


class RemotePlayer:
    """Другой игрок: что о нём известно по сети и как его показывать."""

    def __init__(self, player_id, name=None, connection=None):
        self.id = player_id
        self.name = name
        self.connection = connection
        self.joined = False
        self.connected_at = time.monotonic()

        # Присланное положение глаз и то, что сейчас на экране (догоняет присланное).
        self.position = None
        self.rotation = (0.0, 0.0)
        self.shown = None
        self.shown_rotation = (0.0, 0.0)

        self.sneaking = False
        self.dead = False
        self.swings = 0
        self.swing_time = None
        self.walk_phase = 0.0
        self.walk_amount = 0.0

        # Куда ещё влезут предметы (room_of): хозяин не отдаёт то, что некуда положить.
        self.room = {"free": True, "types": []}

    @property
    def skin(self):
        return SKINS[zlib.crc32((self.name or "").encode("utf-8")) % len(SKINS)]

    def set_state(self, position, rotation, sneaking=False, swings=0, dead=False):
        if self.position is None:
            self.shown = position
            self.shown_rotation = rotation
        elif swings != self.swings:
            self.swing_time = 0.0

        self.position = position
        self.rotation = rotation
        self.sneaking = sneaking
        self.swings = swings
        self.dead = dead

    def update(self, dt):
        if self.shown is None:
            return

        amount = min(1.0, dt * FOLLOW_SPEED)
        old = self.shown

        self.shown = tuple(shown + (target - shown) * amount for shown, target in zip(self.shown, self.position))
        self.shown_rotation = (
            self.shown_rotation[0] + (self.rotation[0] - self.shown_rotation[0]) * amount,
            angle_step(self.shown_rotation[1], self.rotation[1], amount),
        )

        moved = math.hypot(self.shown[0] - old[0], self.shown[2] - old[2])
        speed = moved / dt if dt > 0 else 0.0

        self.walk_phase += moved / STRIDE
        target = min(1.0, speed / WALK_SPEED)
        self.walk_amount += (target - self.walk_amount) * min(1.0, dt * 10)

        if self.swing_time is not None:
            self.swing_time += dt

            if self.swing_time >= SWING_TIME:
                self.swing_time = None

    def limb_angle(self, part, pitch):
        """Наклон части вперёд (+) или назад (-) вокруг её точки поворота."""
        swing = math.sin(self.walk_phase) * LIMB_SWING * self.walk_amount

        if part in ("head", "hat"):
            return pitch

        if part == "right_leg":
            return swing

        if part == "left_leg":
            return -swing

        if part == "left_arm":
            return swing

        if part == "right_arm":
            angle = -swing

            if self.swing_time is not None:
                angle += math.sin(self.swing_time / SWING_TIME * math.pi) * 1.4

            return angle

        return 0.0


class Session:
    """Общее у хозяина и клиента: правки клеток, чужие игроки, звуки."""

    is_host = False

    def __init__(self, game):
        self.game = game
        self.players = {}
        self.model = PlayerModel(game.engine)

        # Клетки, поменявшиеся в этом мире с прошлой отправки.
        self.changed = set()
        # Сейчас применяются чужие правки: их не надо отправлять обратно.
        self.applying = False

        self.swings = 0
        self.last_swing = None
        self.state_time = 0.0

    def attach(self, world):
        world.listener = self.cell_changed

    def detach(self):
        if self.game.world.listener == self.cell_changed:
            self.game.world.listener = None

    def cell_changed(self, x, y, z):
        if not self.applying:
            self.changed.add((x, y, z))

    def take_changes(self):
        world = self.game.world
        cells = [[x, y, z, block_key(world.get_block(x, y, z))] for x, y, z in self.changed]
        self.changed.clear()

        return cells

    def track_swing(self):
        """Взмахи своей руки считаются, чтобы другие видели их у нашей модели."""
        swing_time = self.game.hand.swing_time

        if swing_time is not None and (self.last_swing is None or swing_time < self.last_swing):
            self.swings += 1

        self.last_swing = swing_time

    def visible_players(self):
        return [
            player for player in self.players.values()
            if player.joined and player.shown is not None and not player.dead
        ]

    def update_players(self, dt):
        for player in self.players.values():
            player.update(dt)

    def apply_cells(self, cells):
        """Ставит присланные клетки и перестраивает меши. Возвращает применённые
        тройки (клетка, старый блок, новый блок)."""
        world = self.game.world
        applied = []

        for entry in cells:
            if not isinstance(entry, list) or len(entry) != 4:
                raise ValueError("клетка должна быть [x, y, z, блок]")

            cell = cell_of(entry[:3])
            block = decode_block(entry[3])

            if not in_height(cell[1]):
                continue

            chunk = self.chunk_for(cell)

            if chunk is None:
                continue

            x, y, z = cell
            old = world.get_block(x, y, z)

            if block_key(old) == entry[3]:
                continue

            if block is None:
                world.remove_block(x, y, z)
            else:
                world.set_block(x, y, z, block)

            applied.append((cell, old, block))

        full, water_only = [], []

        for (x, _, z), old, new in applied:
            # Вода не меняет граней блоков: хватит перестроить меш воды.
            if (old is None or old.is_liquid) and (new is None or new.is_liquid):
                water_only.append((x, z))
            else:
                full.append((x, z))

        self.game.rebuild_cells(full, water_only)

        return applied

    def chunk_for(self, cell):
        return self.game.world.get_chunk(*chunk_key(cell[0], cell[2]))

    # Звуки: свои слышат все рядом.

    def sound_message(self, position, event=None, block=None, action=None, volume=1.0):
        message = {"type": "sound", "position": list(position), "volume": volume}

        if block is not None:
            message.update(block=block, action=action)
        else:
            message["event"] = event

        return message

    def play_sound(self, message):
        game = self.game
        position = vector(message["position"])
        volume = float(message.get("volume", 1.0))

        if not 0 <= volume <= 1:
            raise ValueError("громкость вне 0..1")

        try:
            if "block" in message:
                game.sounds.block_sound(str(message["block"]), str(message["action"]), position, game.camera, volume)
            else:
                game.sounds.play_at(str(message["event"]), position, game.camera, volume)

        except (KeyError, ValueError, pygame.error):
            pass

    # Отрисовка чужих игроков.

    def draw_objects(self):
        game = self.game
        eye = game.camera.position
        limit = game.engine.fog_distance + 2
        objects = []

        for player in self.visible_players():
            if math.dist(player.shown, eye) > limit:
                continue

            objects.append(self.model.draw_object(player, game.brightness_at(*player.shown)))

        return objects

    def render_nametags(self, screen, camera, gui):
        width, height = screen.get_size()
        focal = (height / 2) / math.tan(math.radians(camera.fov) / 2)

        pitch, yaw = -camera.rotation[0], -camera.rotation[1]
        cos_pitch, sin_pitch = math.cos(pitch), math.sin(pitch)
        cos_yaw, sin_yaw = math.cos(yaw), math.sin(yaw)

        # Та же матрица камеры, что у рендерера.
        matrix = (
            (cos_yaw, 0, sin_yaw),
            (sin_pitch * sin_yaw, cos_pitch, -sin_pitch * cos_yaw),
            (-cos_pitch * sin_yaw, sin_pitch, cos_pitch * cos_yaw),
        )

        tags = []

        for player in self.visible_players():
            x, y, z = player.shown
            # Над макушкой: ноги на FEET ниже глаз, рост модели 1.8.
            point = (x - camera.position[0], y + FEET - 1.8 - NAMETAG_HEIGHT - camera.position[1], z - camera.position[2])
            distance = math.sqrt(sum(value * value for value in point))

            if distance > NAMETAG_DISTANCE:
                continue

            cx, cy, cz = (sum(row[axis] * point[axis] for axis in range(3)) for row in matrix)

            if cz < NEAR:
                continue

            tags.append((cz, player.name, width / 2 + cx * focal / cz, height / 2 + cy * focal / cz, player.sneaking))

        # Дальние раньше, ближние поверх.
        for _, name, sx, sy, sneaking in sorted(tags, reverse=True):
            text = gui.render_text(name, GRAY if sneaking else WHITE, shadow=False)
            rect = text.get_rect(midbottom=(int(sx), int(sy)))
            gui.shade(screen, rect.inflate(2 * gui.scale, 0), NAMETAG_ALPHA, pixels=True)
            screen.blit(text, rect)


class HostSession(Session):
    """Сервер в игре хозяина мира."""

    is_host = True

    def __init__(self, game, port=net.DEFAULT_PORT):
        super().__init__(game)

        self.name = clean_name(game.settings.player_name)
        self.server = net.Server(port)
        self.port = self.server.port
        self.announcer = net.Announcer(self.port, f"{self.name} - {game.world_name}")

        self.next_id = HOST_ID + 1
        self.items_time = 0.0
        self.time_time = 0.0

        # Открытые чужими игроками сундуки и печки: клетка -> номер игрока.
        self.locks = {}
        # Сломанные, пока их держал открытыми другой игрок: высыплется то, что он вернёт.
        self.broken = {}

        self.attach(game.world)

    @property
    def address(self):
        return f"{net.local_address()}:{self.port}"

    def joined(self):
        return [player for player in self.players.values() if player.joined]

    def send_all(self, message, data=b"", exclude=None):
        for player in self.joined():
            if player is not exclude:
                player.connection.send(message, data)

    def say(self, text, color=WHITE):
        """Сообщение в чат всем, и себе тоже."""
        self.game.chat.add(text, color)
        self.send_all({"type": "chat", "text": text, "color": list(color)})

    def chat(self, line):
        self.say(f"<{self.name}> {line}")

    def sound(self, position, **kwargs):
        self.send_all(self.sound_message(position, **kwargs))

    # Каждый кадр.

    def update(self, dt):
        for connection in self.server.accept():
            player = RemotePlayer(self.next_id, connection=connection)
            self.players[player.id] = player
            self.next_id += 1

        for player in list(self.players.values()):
            for message, data in player.connection.receive():
                if player.id not in self.players:
                    break

                try:
                    self.handle(player, message, data)
                except (KeyError, TypeError, ValueError) as error:
                    self.kick(player, f"Bad message: {error}")

            if player.id not in self.players:
                continue

            if player.connection.closed:
                self.remove(player, player.connection.reason)
            elif not player.joined and time.monotonic() - player.connected_at > HELLO_TIMEOUT:
                self.kick(player, "Timed out")

        loader = self.game.loader

        for player in self.joined():
            if loader is not None and player.position is not None:
                loader.ensure(player.position[0], player.position[2], REMOTE_CHUNK_RADIUS)

        self.update_players(dt)
        self.announcer.players = 1 + len(self.joined())

    def flush(self, dt):
        """Конец кадра: рассылаем изменённые клетки, положения игроков и предметы."""
        self.track_swing()

        if self.changed:
            self.send_all({"type": "blocks", "cells": self.take_changes()})

        self.state_time += dt

        if self.state_time >= STATE_INTERVAL:
            self.state_time = 0.0
            self.send_players()

        self.items_time += dt

        if self.items_time >= ITEMS_INTERVAL:
            self.items_time = 0.0

            items = [
                [entity.id, entity.stack.type, *(round(value, 3) for value in entity.position)]
                for entity in self.game.world.items
            ]
            self.send_all({"type": "items", "items": items})

        self.time_time += dt

        if self.time_time >= TIME_INTERVAL:
            self.send_time()

    def send_rules(self):
        """Правила мира гостям, сразу после команды /gamerule."""
        self.send_all({"type": "rules", "keep_inventory": self.game.keep_inventory})

    def send_time(self):
        """Время суток гостям: по таймеру и сразу после команды /time."""
        self.time_time = 0.0
        self.send_all({"type": "time", "time": round(self.game.world.time, 2)})

    def send_players(self):
        game = self.game
        pitch, yaw = game.camera.rotation[:2]

        everyone = [[HOST_ID, self.name, *game.camera.position, pitch, yaw, game.player.sneaking, self.swings, game.player.dead]]

        for player in self.joined():
            if player.position is not None:
                everyone.append([player.id, player.name, *player.position, *player.rotation, player.sneaking, player.swings, player.dead])

        for player in self.joined():
            player.connection.send({"type": "players", "players": [entry for entry in everyone if entry[0] != player.id]})

    # Сообщения клиентов.

    def handle(self, player, message, data):
        kind = message["type"]

        if not player.joined:
            if kind != "hello":
                raise ValueError(f"ожидалось приветствие, пришло '{kind}'")

            self.hello(player, message)
            return

        handler = {
            "state": self.on_state,
            "blocks": self.on_blocks,
            "chunk": self.on_chunk,
            "item": self.on_item,
            "chat": self.on_chat,
            "sound": self.on_sound,
            "open": self.on_open,
            "close": self.on_close,
            "save": self.on_save,
            "bye": lambda player, message: self.remove(player, "left"),
        }.get(kind)

        if handler is not None:
            handler(player, message)

    def unique_name(self, name):
        taken = {self.name.lower()} | {other.name.lower() for other in self.joined()}
        candidate, number = name, 2

        while candidate.lower() in taken:
            suffix = str(number)
            candidate = name[:NAME_LIMIT - len(suffix)] + suffix
            number += 1

        return candidate

    def modified_chunks(self):
        """Чанки, которые у хозяина не такие, какими их построил бы генератор."""
        game = self.game
        keys = storage.saved_chunk_keys(game.world_folder)
        keys.update(key for key, chunk in game.world.chunks.items() if chunk.dirty)

        return sorted(keys)

    def hello(self, player, message):
        if message.get("protocol") != net.PROTOCOL:
            self.kick(player, "Outdated client" if (message.get("protocol") or 0) < net.PROTOCOL else "Outdated server")
            return

        game = self.game
        name = self.unique_name(clean_name(message.get("name", "")))
        infinite = game.loader is not None
        saved = game.saved_players.get(name)

        player.connection.send({
            "type": "welcome",
            "id": player.id,
            "name": name,
            "world_name": game.world_name,
            "generator": game.world_generator,
            "seed": game.seed,
            "infinite": infinite,
            "game_mode": game.game_mode,
            "spawn": list(game.spawn_point),
            "time": round(game.world.time, 2),
            "keep_inventory": game.keep_inventory,
            "player": saved if isinstance(saved, dict) else None,
            "modified": [list(key) for key in self.modified_chunks()] if infinite else [],
        })

        # Тестовый мир маленький: отдаём его целиком сразу.
        if not infinite:
            for key, chunk in game.world.chunks.items():
                player.connection.send({"type": "chunk", "key": list(key), "found": True}, storage.encode_chunk(chunk))

            player.connection.send({"type": "ready"})

        player.name = name
        player.joined = True

        self.say(f"{name} joined the game", YELLOW)

    def on_state(self, player, message):
        player.set_state(
            vector(message["position"]),
            vector(message["rotation"], 2),
            message.get("sneaking") is True,
            int(message.get("swings", 0)),
            message.get("dead") is True,
        )

        room = message.get("room")

        if isinstance(room, dict) and isinstance(room.get("types"), list):
            player.room = {"free": room.get("free") is True, "types": [str(item) for item in room["types"]]}

    def chunk_for(self, cell):
        """Чужая правка может прийти в чанк, который у хозяина не загружен: грузим его."""
        game = self.game

        if game.loader is not None:
            game.loader.ensure(cell[0], cell[2], 0)

        return game.world.get_chunk(*chunk_key(cell[0], cell[2]))

    def on_blocks(self, player, message):
        cells = message["cells"]

        if not isinstance(cells, list):
            raise ValueError("cells должен быть списком")

        world = self.game.world

        for cell, old, new in self.apply_cells(cells):
            world.notify(*cell)

            # Сломали сундук или печку: содержимое высыпается.
            container = world.containers.get(cell)

            if container is not None and (new is None or new.type != container.kind):
                del world.containers[cell]

                if cell in self.locks:
                    self.broken[cell] = container
                else:
                    self.spill(container, cell)

    def on_chunk(self, player, message):
        key = tuple(int(value) for value in message["key"])

        if len(key) != 2:
            raise ValueError("ключ чанка из двух чисел")

        game = self.game
        chunk = game.world.chunks.get(key)

        if chunk is None and game.world_folder is not None:
            chunk = storage.read_chunk(game.world_folder, *key)

        if chunk is None:
            player.connection.send({"type": "chunk", "key": list(key), "found": False})
        else:
            player.connection.send({"type": "chunk", "key": list(key), "found": True}, storage.encode_chunk(chunk))

    def on_item(self, player, message):
        stack = Stack.from_json(message["stack"])

        if stack is None:
            raise ValueError("пустой стак")

        delay = float(message.get("delay", 0))
        entity = ItemEntity(stack, vector(message["position"]), vector(message["velocity"]), max(0.0, min(delay, 10.0)))
        self.game.world.items.append(entity)

    def on_chat(self, player, message):
        text = "".join(char for char in str(message["text"]) if char.isprintable())[:CHAT_LIMIT].strip()

        if text:
            self.say(f"<{player.name}> {text}")

    def on_sound(self, player, message):
        self.play_sound(message)
        self.send_all(message, exclude=player)

    def on_save(self, player, message):
        data = message["data"]

        if not isinstance(data, dict):
            raise ValueError("данные игрока должны быть объектом")

        self.game.saved_players[player.name] = data

    # Сундуки и печки чужих игроков.

    def container_busy(self, position, player_id):
        owner = self.locks.get(position)

        if owner is not None and owner != player_id:
            return True

        # Сам хозяин держит его открытым.
        if player_id != HOST_ID:
            screen = self.game.open_screen
            container = self.game.world.containers.get(position)
            held = getattr(screen, "chest", None) or getattr(screen, "furnace", None)

            if container is not None and held is container:
                return True

        return False

    def on_open(self, player, message):
        position = cell_of(message["position"])
        world = self.game.world
        block = world.get_block(*position)

        if block is None or block.type not in KINDS:
            return

        if self.container_busy(position, player.id):
            player.connection.send({"type": "chat", "text": f"This {block.type} is being used by someone else", "color": list(GRAY)})
            return

        container = world.containers.get(position)

        if container is None:
            container = world.containers[position] = KINDS[block.type]()

        self.locks[position] = player.id

        player.connection.send({
            "type": "container",
            "position": list(position),
            "kind": container.kind,
            "data": container.to_json(),
        })

    def on_close(self, player, message):
        position = cell_of(message["position"])

        if self.locks.get(position) != player.id:
            return

        del self.locks[position]

        kind = KINDS[message["kind"]]
        container = kind.from_json(message["data"])
        world = self.game.world
        block = world.get_block(*position)

        if position in self.broken or block is None or block.type != container.kind:
            # Пока сундук был открыт, его сломали: высыпается то, что в нём осталось.
            self.broken.pop(position, None)
            world.containers.pop(position, None)
            self.spill(container, position)
        else:
            world.containers[position] = container

    def spill(self, container, position):
        x, y, z = position

        for stack in container.slots:
            if stack is not None:
                spot = (x + random.uniform(0.25, 0.75), y + random.uniform(0.25, 0.75), z + random.uniform(0.25, 0.75))
                self.game.world.items.append(ItemEntity(stack.copy(), spot, scatter_velocity()))

    def container_broken(self, position):
        """Хозяин сам сломал сундук. Если его держит открытым другой, высыплет он."""
        container = self.game.world.containers.get(position)

        if position in self.locks and container is not None:
            self.broken[position] = container
            return True

        return False

    # Предметы.

    def pickup(self, entity):
        """Подбирает ли лежащий предмет кто-то из чужих игроков. Тогда он уходит ему."""
        for player in self.joined():
            if player.position is None or player.dead or not has_room(player.room, entity.stack.type):
                continue

            low, high = player_box(player.position)

            if entity.touches(low, high):
                player.connection.send({"type": "give", "stack": entity.stack.to_json()})
                return True

        return False

    # Отключение.

    def kick(self, player, reason):
        player.connection.send({"type": "kick", "reason": reason})
        self.remove(player, reason)

    def remove(self, player, reason=None):
        if self.players.pop(player.id, None) is None:
            return

        player.connection.close(reason)

        for position, owner in list(self.locks.items()):
            if owner == player.id:
                del self.locks[position]

                # Ушёл, не закрыв сломанный сундук: высыпается то, что было у хозяина.
                if position in self.broken:
                    self.spill(self.broken.pop(position), position)

        if player.joined:
            self.say(f"{player.name} left the game", YELLOW)

    def stop(self, reason="Server closed"):
        for player in list(self.players.values()):
            self.kick(player, reason)

        self.server.close()
        self.announcer.stop()
        self.detach()

        # Даём потокам записи дослать последние сообщения.
        time.sleep(0.05)


class ClientSession(Session):
    """Игра на чужом сервере."""

    def __init__(self, game, connection, welcome, chunks, backlog):
        super().__init__(game)

        self.connection = connection
        self.welcome = welcome
        self.initial_chunks = chunks
        self.backlog = backlog

        self.id = welcome["id"]
        self.name = welcome["name"]
        self.save_time = 0.0

        # Чанки, которые надо взять у сервера, пришедшие и уже запрошенные.
        self.modified = {tuple(key) for key in welcome.get("modified", [])}
        self.received = {}
        self.requested = set()

        # Лежащие предметы с сервера по номерам: только чтобы рисовать их.
        self.ghosts = {}

    @classmethod
    def connect(cls, game, address, name, wait=None):
        """Подключается и ждёт приветствия. wait() вызывается, пока ждём ответа."""
        try:
            host, port = net.parse_address(address)
        except ValueError as error:
            raise ConnectError(f"Invalid address: {error}")

        try:
            connection = net.Connection.open(host, port)
        except OSError as error:
            raise ConnectError(error.strerror or str(error))

        connection.send({"type": "hello", "protocol": net.PROTOCOL, "name": clean_name(name)})

        deadline = time.monotonic() + JOIN_TIMEOUT
        welcome, chunks, backlog, ready = None, [], [], False

        while not (welcome is not None and ready):
            for message, data in connection.receive():
                kind = message["type"]

                if kind == "kick":
                    connection.close()
                    raise ConnectError(str(message.get("reason", "Disconnected")))

                if kind == "welcome" and welcome is None:
                    welcome = message
                    ready = ready or welcome.get("infinite") is True

                elif kind == "chunk" and welcome is not None and not welcome.get("infinite"):
                    key = message["key"]
                    try:
                        chunks.append(storage.decode_chunk(data, int(key[0]), int(key[1])))
                    except (ValueError, TypeError, IndexError) as error:
                        connection.close()
                        raise ConnectError(f"Bad world data: {error}")

                elif kind == "ready":
                    ready = True

                else:
                    backlog.append((message, data))

            if welcome is not None and ready:
                break

            if connection.closed:
                raise ConnectError(connection.reason or "Connection closed")

            if time.monotonic() > deadline:
                connection.close()
                raise ConnectError("Timed out")

            if wait is not None:
                wait()

            time.sleep(0.01)

        return cls(game, connection, welcome, chunks, backlog)

    # Подгрузка чанков (см. streaming.ChunkLoader.remote).

    def available(self, key):
        if key not in self.modified or key in self.received:
            return True

        if key not in self.requested:
            self.requested.add(key)
            self.connection.send({"type": "chunk", "key": list(key)})

        return False

    def take(self, key):
        self.requested.discard(key)

        return self.received.pop(key, None)

    def cell_changed(self, x, y, z):
        if not self.applying:
            self.changed.add((x, y, z))

        # Чанк уже не такой, как у генератора: после выгрузки берём его у сервера.
        self.modified.add(chunk_key(x, z))

    def chunk_for(self, cell):
        key = chunk_key(cell[0], cell[2])
        chunk = self.game.world.get_chunk(*key)

        if chunk is None:
            # Чанк пришёл, но ещё не в мире: правку положим прямо в него (см. apply_cells).
            # Не пришёл: после неё он отличается от генератора, возьмём его у сервера.
            if key in self.received:
                self.pending_cells.append(cell)

            self.modified.add(key)

        return chunk

    def apply_cells(self, cells):
        self.pending_cells = []
        self.applying = True

        try:
            applied = super().apply_cells(cells)
        finally:
            self.applying = False

        # Клетки чанков, что пришли, но ещё не в мире.
        if self.pending_cells:
            wanted = {tuple(entry[:3]): entry[3] for entry in cells}

            for x, y, z in self.pending_cells:
                chunk = self.received[chunk_key(x, z)]
                block = decode_block(wanted[(x, y, z)])
                local_x, local_z = x % Chunk.SIZE, z % Chunk.SIZE

                if block is None:
                    chunk.remove_block(local_x, y, local_z)
                else:
                    chunk.set_block(local_x, y, local_z, block)

        return applied

    # Каждый кадр.

    def update(self, dt):
        messages, self.backlog = self.backlog + self.connection.receive(), []

        for message, data in messages:
            try:
                self.handle(message, data)
            except (KeyError, TypeError, ValueError, IndexError) as error:
                self.connection.close(f"Bad message from server: {error}")
                self.game.connection_lost(f"Bad message from server: {error}")
                return

            if self.game.net is not self:
                return

        if self.connection.closed:
            self.game.connection_lost(self.connection.reason or "Connection closed")
            return

        self.update_players(dt)
        self.update_ghosts(dt)

    def flush(self, dt):
        game = self.game
        self.track_swing()

        if self.changed:
            self.connection.send({"type": "blocks", "cells": self.take_changes()})

        self.state_time += dt

        if self.state_time >= STATE_INTERVAL:
            self.state_time = 0.0
            pitch, yaw = game.camera.rotation[:2]

            self.connection.send({
                "type": "state",
                "position": list(game.camera.position),
                "rotation": [pitch, yaw],
                "sneaking": game.player.sneaking,
                "swings": self.swings,
                "dead": game.player.dead,
                "room": room_of(game.inventory.slots),
            })

        self.save_time += dt

        if self.save_time >= SAVE_INTERVAL:
            self.save_time = 0.0
            self.send_save()

    def handle(self, message, data):
        kind = message["type"]
        game = self.game

        if kind == "blocks":
            if not isinstance(message["cells"], list):
                raise ValueError("cells должен быть списком")

            self.apply_cells(message["cells"])

        elif kind == "chunk":
            key = (int(message["key"][0]), int(message["key"][1]))
            self.requested.discard(key)

            if key in game.world.chunks:
                return

            if message.get("found") is True:
                self.received[key] = storage.decode_chunk(data, *key)
            else:
                self.modified.discard(key)

            if game.loader is not None:
                game.loader.settled = False

        elif kind == "players":
            self.on_players(message["players"])

        elif kind == "time":
            game.world.time = world_time(message["time"])

        elif kind == "rules":
            game.keep_inventory = message.get("keep_inventory") is True

        elif kind == "items":
            self.on_items(message["items"])

        elif kind == "give":
            stack = Stack.from_json(message["stack"])

            if stack is not None:
                game.receive_stack(stack)

        elif kind == "chat":
            game.chat.add(str(message["text"])[:CHAT_LIMIT * 2], color_of(message.get("color")))

        elif kind == "sound":
            self.play_sound(message)

        elif kind == "container":
            position = cell_of(message["position"])
            container = KINDS[message["kind"]].from_json(message["data"])
            game.open_remote_container(position, container)

        elif kind == "kick":
            reason = str(message.get("reason", "Disconnected"))
            self.connection.close(reason)
            game.connection_lost(reason)

    def on_players(self, entries):
        seen = set()

        for entry in entries:
            player_id, name = int(entry[0]), clean_name(entry[1])
            position, rotation = vector(entry[2:5]), vector(entry[5:7], 2)
            seen.add(player_id)

            player = self.players.get(player_id)

            if player is None:
                player = self.players[player_id] = RemotePlayer(player_id, name)
                player.joined = True

            player.name = name
            player.set_state(position, rotation, entry[7] is True, int(entry[8]), entry[9] is True)

        for player_id in list(self.players):
            if player_id not in seen:
                del self.players[player_id]

    def on_items(self, entries):
        seen = set()

        for entry in entries:
            item_id, item = int(entry[0]), str(entry[1])
            position = vector(entry[2:5])
            seen.add(item_id)

            ghost = self.ghosts.get(item_id)

            if ghost is None:
                ghost = self.ghosts[item_id] = ItemEntity(Stack(item), position)
                ghost.target = position
            else:
                ghost.target = position

        for item_id in list(self.ghosts):
            if item_id not in seen:
                del self.ghosts[item_id]

        self.game.world.items = list(self.ghosts.values())

    def update_ghosts(self, dt):
        amount = min(1.0, dt * FOLLOW_SPEED)

        for ghost in self.ghosts.values():
            ghost.age += dt
            ghost.position = tuple(shown + (target - shown) * amount for shown, target in zip(ghost.position, ghost.target))

    # Что клиент отправляет по своим действиям.

    def chat(self, line):
        self.connection.send({"type": "chat", "text": line})

    def sound(self, position, **kwargs):
        self.connection.send(self.sound_message(position, **kwargs))

    def drop_item(self, stack, position, velocity, delay):
        """Выпавший или выброшенный предмет живёт у хозяина."""
        self.connection.send({
            "type": "item",
            "stack": stack.to_json(),
            "position": list(position),
            "velocity": list(velocity),
            "delay": delay,
        })

    def request_container(self, position):
        self.connection.send({"type": "open", "position": list(position)})

    def close_container(self, position, container):
        self.connection.send({"type": "close", "position": list(position), "kind": container.kind, "data": container.to_json()})

    def send_save(self):
        self.connection.send({"type": "save", "data": self.game.player_data()})

    def stop(self):
        if not self.connection.closed:
            self.send_save()
            self.connection.send({"type": "bye"})
            self.connection.close("left")

        self.detach()
        time.sleep(0.05)


def load_player_data(data, slots_count):
    """Сохранённый хозяином игрок: проверенные поля, которые можно применить."""
    result = {}

    if not isinstance(data, dict):
        return result

    for name, size in (("position", 3), ("rotation", 3), ("spawn", 3)):
        try:
            result[name] = vector(data[name], size)
        except (KeyError, ValueError, TypeError):
            pass

    health = data.get("health")

    if type(health) is int and health > 0:
        result["health"] = health

    if "inventory" in data:
        result["inventory"] = slots_from_json(data["inventory"], slots_count)
        result["armor"] = armor_from_json(data.get("armor"))

    if data.get("game_mode") in storage.GAME_MODES:
        result["game_mode"] = data["game_mode"]

    result["flying"] = data.get("flying") is True

    return result
