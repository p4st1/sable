from OpenGL.GL import *


class OpenGLRenderer:
    def __init__(self):
        glEnable(GL_DEPTH_TEST)

        glClearColor(
            0.2,
            0.3,
            0.4,
            1.0
        )

        print("OpenGL:", glGetString(GL_VERSION))
        print("GPU:", glGetString(GL_RENDERER))

    def render(self):
        glClear(
            GL_COLOR_BUFFER_BIT |
            GL_DEPTH_BUFFER_BIT
        )