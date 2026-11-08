"""Пламя на горящих: языки огня вокруг моба и огонь по краям экрана у игрока.

Вокруг горящего существа стоит пламя одним слоем, всегда
повёрнутым к камере, выше и чуть шире его тела. Сам горящий игрок видит
два языка пламени внизу экрана. Текстура та же, что у блока огня, и
анимируется вместе с ним.
"""
import math

import numpy as np
import pygame

from entities import DrawObject
from fire import FIRE_TEXTURE
from mesh import Mesh

# Слоёв пламени (один, во всю высоту), насколько огонь выше и шире тела и как слои заходят друг на друга.
LAYERS = 1
TALLER = 1.4
WIDER = 1.4
OVERLAP = 1.0
# Каждый следующий слой чуть ближе к камере, чтобы слои не спорили в буфере глубины.
LAYER_STEP = 0.03
# Насколько пламя вынесено к камере, в долях ширины тела.
FORWARD = 0.5

# Огонь у игрока: размер языка в долях высоты экрана, где он стоит и насколько прозрачен.
OVERLAY_SIZE = 0.55
OVERLAY_CENTERS = (0.2, 0.8)
OVERLAY_SINK = 0.25
OVERLAY_ALPHA = 225


class BurningModel:
    def __init__(self, engine):
        self.engine = engine
        self.mesh = None

    def build(self):
        """Слои единичной высоты и ширины: снизу вверх, с центром по ширине в нуле."""
        texture = self.engine.load_texture(FIRE_TEXTURE)
        points, triangles, uvs = [], [], []
        layer_height = OVERLAP / LAYERS
        # Чуть внутрь от краёв картинки: иначе по краю проступает полоска с другой стороны.
        low, high = 0.01, 0.99
        corner_uvs = [(low, high), (high, high), (high, low), (low, low)]

        for layer in range(LAYERS):
            bottom = -layer / LAYERS
            top = bottom - layer_height
            depth = -layer * LAYER_STEP
            start = len(points)

            # Ось Y вниз: низ слоя (y больше) внизу картинки.
            points += [(-0.5, bottom, depth), (0.5, bottom, depth), (0.5, top, depth), (-0.5, top, depth)]

            for a, b, c in ((0, 1, 2), (0, 2, 3), (0, 2, 1), (0, 3, 2)):
                triangles.append((start + a, start + b, start + c))
                uvs.append((corner_uvs[a], corner_uvs[b], corner_uvs[c]))

        self.mesh = Mesh(points, triangles, uvs, texture)
        self.local = np.array(points, dtype=np.float64)

    def draw_object(self, feet, width, height, camera):
        """Пламя вокруг тела шириной width и высотой height, стоящего ногами в feet."""
        if self.mesh is None:
            self.build()

        # Плоскости смотрят на камеру: поворот вокруг вертикали по взгляду.
        yaw = camera.rotation[1]
        cos, sin = math.cos(yaw), math.sin(yaw)
        turn = np.array([[cos, 0, sin], [0, 1, 0], [-sin, 0, cos]])
        scale = np.array((width * WIDER, height * TALLER, 1.0))

        # Пламя чуть впереди тела, со стороны камеры: иначе тело закрывало бы его середину.
        toward_camera = -np.array((sin, 0.0, cos)) * width * FORWARD
        points = (self.local * scale) @ turn.T + np.array(feet) + toward_camera

        # Огонь светится сам: полная яркость в любой темноте.
        return DrawObject(self.mesh, np.ascontiguousarray(points, dtype=np.float32), 1.0)


def draw_overlay(screen, frame):
    """Два языка пламени внизу экрана, правый отражён: так игрок видит, что горит."""
    width, height = screen.get_size()
    size = int(height * OVERLAY_SIZE)
    flame = pygame.transform.scale(frame, (size, size))
    flame.set_alpha(OVERLAY_ALPHA)
    mirrored = pygame.transform.flip(flame, True, False)
    mirrored.set_alpha(OVERLAY_ALPHA)

    y = height - int(size * (1 - OVERLAY_SINK))

    for center, image in zip(OVERLAY_CENTERS, (flame, mirrored)):
        screen.blit(image, (int(width * center - size / 2), y))
