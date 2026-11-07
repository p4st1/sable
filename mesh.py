import numpy as np

class Mesh:
    def __init__(self, points, triangles, uvs, texture=None, shades=None):
        self.points = np.array(
            points,
            dtype=np.float32
        )
        
        self.triangles = np.array(
            triangles,
            dtype=np.int32
        )

        self.uvs = np.array(
            uvs,
            dtype=np.float32
        )

        self.texture = texture

        # Яркость каждой точки от 0 до 1 (свет и тень) или None: тогда как есть.
        self.shades = None if shades is None else np.ascontiguousarray(shades, dtype=np.float32)