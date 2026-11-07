import math


class Camera:
    def __init__(self):
        self.position = (0,-1,0)
        self.rotation = (0,0,0)

        self.fov = 70
        self.near = 0.1
        self.sensitivity = 0.003
    
    def rotate(self, dx, dy):
        x = self.rotation[0] - dy * self.sensitivity
        y = self.rotation[1] + dx * self.sensitivity

        x = max(math.radians(-89), min(math.radians(89), x))
        
        self.rotation = (x, y, 0)

    def horizontal_move(self, forward, right, speed):
        """Смещение по x и z для движения относительно взгляда."""
        yaw = self.rotation[1]

        forward_x = math.sin(yaw)
        forward_z = math.cos(yaw)

        right_x = math.cos(yaw)
        right_z = -math.sin(yaw)

        return (
            (forward_x * forward + right_x * right) * speed,
            (forward_z * forward + right_z * right) * speed
        )

    def forward(self):
        """Направление взгляда. Это третья строка camera_matrix из рендерера."""
        pitch, yaw = self.rotation[0], self.rotation[1]

        return (
            math.cos(pitch) * math.sin(yaw),
            -math.sin(pitch),
            math.cos(pitch) * math.cos(yaw)
        )
