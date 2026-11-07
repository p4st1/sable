class Vertex:
    def __init__(self, world, camera, uv=(0,0)):
        self.world = world
        self.camera = camera
        self.screen = None
        self.uv = uv