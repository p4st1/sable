import numpy as np

class Object3D:
    def __init__(self, mesh):
        self.mesh = mesh

        self.position = (0, 0, 6)
        self.rotation = (0, 0, 0)
        self.scale = (1, 1, 1)

        self.static = False
        self.world_position = None

        # Множитель яркости всего объекта, вдобавок к яркости точек меша.
        self.brightness = 1.0

    def build_world_points(self):
        self.world_points = self.mesh.points + np.array(
            self.position,
            dtype=np.float32
        )

        low = self.world_points.min(axis=0)
        high = self.world_points.max(axis=0)

        self.center = tuple(float(value) for value in (low + high) / 2)
        self.radius = float(np.linalg.norm(high - low)) / 2
