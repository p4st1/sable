"""Фигурка игрока в инвентаре: модель со скином и надетой бронёй.

Рисуется тем же растеризатором в отдельную прозрачную картинку. Голова и тело
поворачиваются к курсору мыши, как в оригинале.
"""
import math
import zlib

import numpy as np
import pygame

import armor
import raster
from chunk import FACE_SHADE, QUAD_TRIANGLES, box_face
from mesh import Mesh
from multiplayer import PARTS, PIXEL, SKIN_SIZE, SKINS, PlayerModel, face_uvs, rotation_x

# Развёртка брони вдвое ниже скина: 64 x 32.
ARMOR_HEIGHT = 32
# Модель ростом 1.8 блока смотрит из такого далека, занимая такую долю высоты картинки.
DISTANCE = 5.0
FILL = 0.86
NEAR = 0.1
# Как сильно голова и тело следят за курсором (в пикселях картинки на радиан).
LOOK_SCALE = 40.0
BODY_SHARE = 0.5
MODEL_HEIGHT = 1.8

PART_INFO = {name: (low, size, pivot) for name, low, size, _, pivot in PARTS}


def skin_for(name):
    """Скин игрока по имени, так же как у других игроков в сетевой игре."""
    return SKINS[zlib.crc32((name or "").encode("utf-8")) % len(SKINS)]


def rotation_y(angle):
    cos, sin = math.cos(angle), math.sin(angle)

    return np.array([[cos, 0, sin], [0, 1, 0], [-sin, 0, cos]], dtype=np.float64)


class PlayerFigure:
    def __init__(self, engine):
        self.engine = engine
        self.model = PlayerModel(engine)
        self.armor_models = {}

    def armor_model(self, item):
        """Меш надетой части брони: бруски чуть шире частей тела."""
        if item not in self.armor_models:
            slot = armor.SLOTS[armor.ARMOR[item].slot]
            meshes = []

            for layer in (1, 2):
                pieces = [piece for piece in armor.MODEL_PARTS[slot] if piece[3] == layer]

                if pieces:
                    texture = self.engine.load_texture(armor.layer_texture(item, layer))
                    meshes.append(self.build_armor(pieces, texture))

            self.armor_models[item] = meshes

        return self.armor_models[item]

    def build_armor(self, pieces, texture):
        points, triangles, uvs, shades, parts = [], [], [], [], []

        for name, grow, uv, _ in pieces:
            low, size, pivot = PART_INFO[name]
            x0, y0, z0 = (low[axis] - grow for axis in range(3))
            x1, y1, z1 = (low[axis] + size[axis] + grow for axis in range(3))

            box_low = (x0 * PIXEL, -y1 * PIXEL, z0 * PIXEL)
            box_high = (x1 * PIXEL, -y0 * PIXEL, z1 * PIXEL)
            center = np.array((pivot[0] * PIXEL, -pivot[1] * PIXEL, pivot[2] * PIXEL))
            start = len(points)

            for face in ("top", "bottom", "front", "back", "right", "left"):
                first = len(points)
                points.extend(box_face(face, box_low, box_high))
                shades.extend([FACE_SHADE[face]] * 4)

                # face_uvs делит на ширину скина и по v тоже: у брони высота вдвое меньше.
                quad = [(u, v * SKIN_SIZE / ARMOR_HEIGHT) for u, v in face_uvs(face, size, uv)]

                for a, b, c in QUAD_TRIANGLES.tolist():
                    triangles.append((first + a, first + b, first + c))
                    uvs.append((quad[a], quad[b], quad[c]))

            parts.append((name, start, len(points), center))

        return Mesh(points, triangles, uvs, texture, shades), np.array(points, dtype=np.float64), parts

    def render(self, skin, worn, width, height, look_x, look_y):
        """Картинка width x height с фигуркой. look_x, look_y: курсор относительно глаз фигурки в пикселях."""
        surface = pygame.Surface((width, height), pygame.SRCALPHA)
        surface.fill((0, 0, 0, 0))

        head_yaw = -math.atan(look_x / LOOK_SCALE)
        head_pitch = math.atan(-look_y / LOOK_SCALE)
        body_yaw = head_yaw * BODY_SHARE

        mesh, local, parts = self.model.get(skin)
        models = [(mesh, local.astype(np.float64), parts)]

        for stack in worn:
            if stack is not None and stack.type in armor.ARMOR:
                models.extend(self.armor_model(stack.type))

        focal = FILL * height * DISTANCE / MODEL_HEIGHT
        depth = np.zeros((height, width), dtype=np.float32)
        pixels = pygame.surfarray.pixels2d(surface).T
        alpha_mask = surface.get_masks()[3]
        body = rotation_y(body_yaw)
        head = rotation_y(head_yaw - body_yaw) @ rotation_x(head_pitch)

        for model_mesh, points, model_parts in models:
            posed = points.copy()

            for name, start, end, center in model_parts:
                if name in ("head", "hat"):
                    posed[start:end] = (points[start:end] - center) @ head.T + center

            world = posed @ body.T

            # Камера перед лицом фигурки смотрит на неё: модель глядит в +z, камера в -z.
            camera = np.empty_like(world)
            camera[:, 0] = -world[:, 0]
            camera[:, 1] = world[:, 1] + MODEL_HEIGHT / 2
            camera[:, 2] = DISTANCE - world[:, 2]

            raster.draw_mesh(
                np.ascontiguousarray(camera, dtype=np.float32),
                model_mesh.triangles,
                model_mesh.uvs,
                self.engine.texture_arrays[id(model_mesh.texture)],
                pixels,
                depth,
                focal,
                NEAR,
                self.engine.texture_alpha[id(model_mesh.texture)],
                256,
                model_mesh.shades,
                1.0,
                alpha_mask
            )

        del pixels

        return surface
