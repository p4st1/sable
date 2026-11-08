"""Чат: строка ввода, история отправленного и лента сообщений над хотбаром.

T открывает чат, / открывает его сразу с косой чертой. Строка, начинающаяся с /,
выполняется как команда (commands.py), остальное просто пишется в ленту.
Сообщения видны MESSAGE_TIME секунд и гаснут, в открытом чате видна вся лента.
"""
import pygame

from gui import WHITE

INPUT_LIMIT = 256
HISTORY_LIMIT = 100
MESSAGE_LIMIT = 100

MESSAGE_TIME = 10.0
FADE_TIME = 1.0
VISIBLE_CLOSED = 10
VISIBLE_OPEN = 20

# Разметка в единицах интерфейса, как у ленты чата в оригинале.
CHAT_WIDTH = 320
LINE_HEIGHT = 9
CHAT_BOTTOM = 48
INPUT_HEIGHT = 12
CURSOR_BLINK_MS = 300
BACKGROUND_ALPHA = 128

GRAY = (170, 170, 170)
RED = (255, 85, 85)
YELLOW = (255, 255, 85)


class Message:
    def __init__(self, text, color, time):
        self.text = text
        self.color = color
        self.time = time


class Chat:
    def __init__(self):
        self.open = False
        self.input = ""
        self.messages = []
        self.history = []
        self.history_index = None
        self.clock = 0.0

        # Нажатие T или / само по себе ещё и печатает символ. Его надо пропустить.
        self.skip_text = False

    # Ввод.

    def show(self, prefix=""):
        self.open = True
        self.input = prefix
        self.history_index = None
        self.skip_text = True

    def close(self):
        self.open = False
        self.input = ""

    def end_of_events(self):
        """Конец пачки событий: символ от клавиши открытия к этому моменту уже пришёл."""
        self.skip_text = False

    def text(self, text):
        if self.skip_text:
            self.skip_text = False
            return

        text = "".join(char for char in text if char.isprintable())
        self.input = (self.input + text)[:INPUT_LIMIT]

    def key(self, event):
        """Обрабатывает клавишу. Возвращает строку, если её отправили, иначе None."""
        if event.key == pygame.K_ESCAPE:
            self.close()

        elif event.key == pygame.K_BACKSPACE:
            self.input = self.input[:-1]

        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            line = self.input.strip()
            self.close()

            if line:
                if not self.history or self.history[-1] != line:
                    self.history = (self.history + [line])[-HISTORY_LIMIT:]

                return line

        elif event.key == pygame.K_UP and self.history:
            if self.history_index is None:
                self.history_index = len(self.history) - 1
            else:
                self.history_index = max(0, self.history_index - 1)

            self.input = self.history[self.history_index]

        elif event.key == pygame.K_DOWN and self.history_index is not None:
            self.history_index += 1

            if self.history_index >= len(self.history):
                self.history_index = None
                self.input = ""
            else:
                self.input = self.history[self.history_index]

        return None

    # Лента.

    def add(self, text, color=WHITE):
        self.messages = (self.messages + [Message(text, color, self.clock)])[-MESSAGE_LIMIT:]

    def update(self, dt):
        self.clock += dt

    def visible(self):
        """Пары (сообщение, прозрачность от 0 до 1), от старых к новым."""
        if self.open:
            return [(message, 1.0) for message in self.messages[-VISIBLE_OPEN:]]

        shown = []

        for message in self.messages[-VISIBLE_CLOSED:]:
            age = self.clock - message.time

            if age < MESSAGE_TIME:
                shown.append((message, 1.0))
            elif age < MESSAGE_TIME + FADE_TIME:
                shown.append((message, 1.0 - (age - MESSAGE_TIME) / FADE_TIME))

        return shown

    # Отрисовка.

    def wrap(self, gui, text):
        """Разбивает сообщение на строки по ширине ленты, по словам."""
        limit = (CHAT_WIDTH - 4) * gui.scale
        lines, current = [], ""

        for word in text.split(" "):
            candidate = word if not current else current + " " + word

            if gui.font.size(candidate)[0] <= limit:
                current = candidate
                continue

            if current:
                lines.append(current)

            # Слово длиннее строки режем по буквам.
            while gui.font.size(word)[0] > limit:
                cut = len(word)

                while cut > 1 and gui.font.size(word[:cut])[0] > limit:
                    cut -= 1

                lines.append(word[:cut])
                word = word[cut:]

            current = word

        lines.append(current)

        return lines

    def render(self, screen, gui):
        width, height = gui.units(screen)
        scale = gui.scale

        rows = []

        for message, opacity in self.visible():
            for line in self.wrap(gui, message.text):
                rows.append((line, message.color, opacity))

        rows = rows[-(VISIBLE_OPEN if self.open else VISIBLE_CLOSED):]
        y = height - CHAT_BOTTOM - len(rows) * LINE_HEIGHT

        for line, color, opacity in rows:
            alpha = int(BACKGROUND_ALPHA * opacity)

            if alpha > 0:
                gui.shade(screen, (2, y, CHAT_WIDTH, LINE_HEIGHT), alpha)

            surface = gui.render_text(line, color)
            surface.set_alpha(int(255 * opacity))
            screen.blit(surface, (4 * scale, (y + 1) * scale))

            y += LINE_HEIGHT

        if self.open:
            top = height - INPUT_HEIGHT - 2
            gui.shade(screen, (2, top, width - 4, INPUT_HEIGHT), BACKGROUND_ALPHA)

            cursor = "_" if pygame.time.get_ticks() // CURSOR_BLINK_MS % 2 == 0 else ""
            shown = self.input

            # Длинная строка прокручивается: видно её конец.
            while shown and gui.font.size(shown + "_")[0] > (width - 10) * scale:
                shown = shown[1:]

            gui.draw_text(screen, shown + cursor, (4, top + 2), WHITE, 'topleft')
