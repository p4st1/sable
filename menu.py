"""Экраны меню: титульный, выбор мира, создание и удаление мира, пауза и настройки.

Координаты здесь в единицах интерфейса (см. gui.py). Меню само меняет страницы,
а за вход в мир, выход и настройки отвечает игра (main.Game).
"""
import random
import time

import pygame

import net
import storage
from config import Config
from terrain import parse_seed
from gui import BAR_WIDTH, BAR_HEIGHT, WHITE, GRAY, SUBTEXT
from worlds import WORLDS


VERSION = "Sable (dev)"

SPLASHES = (
    "Made of sand!",
    "Now with chunks!",
    "100% Python!",
    "Cython inside!",
    "Software rendered!",
    "No GPU required!",
    "Pixels all the way down!",
    "Z-buffered!",
    "Hello, voxel!",
    "Press F3 for numbers!",
    "Sixteen by sixteen!",
    "Now with a title screen!",
    "Hand-made rasterizer!",
    "Triangles everywhere!",
    "Saved as .npz!",
    "Learning by doing!",
    "Raycast approved!",
    "Greedy meshing!",
    "Also try building your own!",
    "Blocks!",
)

FULL = BAR_WIDTH
HALF = (BAR_WIDTH - 4) // 2
WIDE = 150
ROW = 24

ENTRY_WIDTH = 220
ENTRY_HEIGHT = 36
ICON = 32
LIST_TOP = 32
LIST_BOTTOM = 64
LIST_PADDING = 4
SCROLLBAR_WIDTH = 6
DOUBLE_CLICK_MS = 300

NAME_LIMIT = 32
SEED_LIMIT = 32
FIELD_HEIGHT = 20
CURSOR_BLINK_MS = 300
DEFAULT_GENERATOR = 'default'

PLAYER_NAME_LIMIT = 16
ADDRESS_LIMIT = 64

DEATH_TINT = (120, 0, 0)

CLICK_VOLUME = 0.25

BASE_SENSITIVITY = 0.003
UNLIMITED_FPS = 0

# Значения ползунков настроек, по порядку слева направо.
SLIDER_VALUES = {
    'fov': tuple(range(30, 111)),
    'sensitivity': tuple(range(10, 201, 5)),
    'render_scale': Config.RENDER_SCALE,
    'gui_scale': Config.GUI_SCALE,
    'fps': tuple(range(10, 251, 10)) + (UNLIMITED_FPS,),
    'fog': Config.FOG_DISTANCE,
    'volume': tuple(range(0, 101, 5)),
    'music': tuple(range(0, 101, 5)),
}

# Кнопки главной страницы настроек: (действие, надпись). None значит "ещё не сделано".
OPTION_BUTTONS = (
    (None, "Skin Customization..."), ('sounds', "Music & Sounds..."),
    ('video', "Video Settings..."), (None, "Controls..."),
    (None, "Language..."), (None, "Resource Packs..."),
)


def nearest_index(values, value):
    if value in values:
        return values.index(value)

    return min(
        range(len(values)),
        key=lambda index: abs(values[index] - value) if values[index] != UNLIMITED_FPS else float('inf')
    )


def format_time(timestamp):
    return time.strftime("%d.%m.%Y %H:%M", time.localtime(timestamp))


class Menu:
    def __init__(self, game):
        self.game = game

        self.page = 'title'
        self.options_return = 'title'
        self.splash = random.choice(SPLASHES)

        self.saves = []
        self.selected = None
        self.scroll = 0
        self.last_click = (None, 0)
        self.units = (0, 0)

        self.create_return = 'title'
        self.name_input = ""
        self.seed_input = ""
        # Поле, в которое идёт ввод на странице создания: 'name' или 'seed'.
        self.focus = 'name'
        self.generator = DEFAULT_GENERATOR
        self.game_mode = "survival"

        self.dragging = None
        self.pending_gui_scale = None

        # Страница сетевой игры: поиск игр в локалке, имя и адрес, поле ввода.
        self.finder = None
        self.player_input = ""
        self.address_input = ""
        self.network_focus = 'address'

        # Страница с сообщением (не удалось подключиться, связь потеряна) и куда с неё вернуться.
        self.message = ("", "")
        self.message_return = 'title'

    @property
    def gui(self):
        return self.game.gui

    @property
    def typing(self):
        """Пока открыт ввод имени, буквы не должны срабатывать как горячие клавиши."""
        return self.page in ('create', 'multiplayer')

    # Переходы между страницами.

    def show_title(self):
        self.page = 'title'
        self.splash = random.choice(SPLASHES)
        self.stop_finder()

    def open_multiplayer(self):
        self.page = 'multiplayer'
        self.player_input = self.game.settings.player_name
        self.address_input = self.game.settings.last_server
        self.network_focus = 'address'

        if self.finder is None:
            self.finder = net.Finder()

    def stop_finder(self):
        if self.finder is not None:
            self.finder.stop()
            self.finder = None

    def show_message(self, title, text, return_to='title'):
        self.message = (title, text)
        self.message_return = return_to
        self.page = 'message'
        self.game.set_menu(True)

    def close_message(self):
        if self.message_return == 'multiplayer':
            self.open_multiplayer()
        else:
            self.show_title()

    def show_pause(self):
        self.page = 'pause'

    def show_death(self):
        self.page = 'death'

    def open_worlds(self):
        self.saves = storage.list_saves()
        self.scroll = 0

        if self.selected not in (save.folder for save in self.saves):
            self.selected = None

        # Как и в оригинале: если миров нет, сразу открывается создание.
        if not self.saves:
            self.open_create('title')
        else:
            self.page = 'worlds'

    def open_create(self, return_to, name="New World", generator=DEFAULT_GENERATOR, game_mode="survival"):
        self.page = 'create'
        self.create_return = return_to
        self.name_input = name[:NAME_LIMIT]
        self.seed_input = ""
        self.focus = 'name'
        self.generator = generator if generator in WORLDS else DEFAULT_GENERATOR
        self.game_mode = game_mode

    def open_options(self):
        self.options_return = self.page
        self.page = 'options'

    def escape(self):
        """Esc закрывает текущую страницу. Возвращает False, если закрывать нечего."""
        back = {
            'worlds': 'title',
            'create': self.create_return,
            'delete': 'worlds',
            'options': self.options_return,
            'video': 'options',
            'sounds': 'options',
        }

        if self.page == 'pause':
            self.game.set_menu(False)

        elif self.page == 'multiplayer':
            self.show_title()

        elif self.page == 'message':
            self.close_message()

        elif self.page in back:
            self.dragging = None

            if self.page == 'create' and self.create_return == 'worlds':
                self.open_worlds()
            else:
                self.page = back[self.page]

        else:
            return False

        return True

    # Ввод.

    def click(self, position):
        slider = self.gui.slider_at(position)

        if slider is not None:
            self.click_sound()
            self.dragging = slider
            self.drag(position[0])
            return

        if self.page == 'worlds' and self.click_world_list(position):
            return

        action = self.gui.button_at(position)

        if action is not None:
            self.click_sound()
            self.run_action(action)

    def click_sound(self):
        self.game.sounds.play("ui.button.click", CLICK_VOLUME)

    def release(self):
        if self.dragging is None:
            return

        if self.dragging == 'gui_scale' and self.pending_gui_scale is not None:
            self.game.settings.gui_scale = self.pending_gui_scale
            self.pending_gui_scale = None

        self.dragging = None
        self.game.apply_settings()
        self.game.save_settings()

    def motion(self, position):
        if self.dragging is not None:
            self.drag(position[0])

    def wheel(self, step):
        if self.page == 'worlds':
            self.scroll -= step * ENTRY_HEIGHT // 2
            self.clamp_scroll()

    def key(self, event):
        if event.key == pygame.K_ESCAPE:
            self.escape()

        elif self.page == 'create':
            if event.key == pygame.K_BACKSPACE:
                if self.focus == 'seed':
                    self.seed_input = self.seed_input[:-1]
                else:
                    self.name_input = self.name_input[:-1]

            elif event.key == pygame.K_TAB and self.has_seed:
                self.focus = 'seed' if self.focus == 'name' else 'name'

            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.create_world()

        elif self.page == 'multiplayer':
            if event.key == pygame.K_BACKSPACE:
                if self.network_focus == 'player':
                    self.player_input = self.player_input[:-1]
                else:
                    self.address_input = self.address_input[:-1]

            elif event.key == pygame.K_TAB:
                self.network_focus = 'address' if self.network_focus == 'player' else 'player'

            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.join()

        elif self.page == 'message':
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.close_message()

        elif self.page == 'worlds':
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.play_selected()

            elif event.key in (pygame.K_UP, pygame.K_DOWN):
                self.move_selection(-1 if event.key == pygame.K_UP else 1)

    def text(self, text):
        if self.page == 'multiplayer':
            if self.network_focus == 'player':
                # В имени только буквы, цифры и подчёркивание.
                text = "".join(char for char in text if char.isalnum() or char == "_")
                self.player_input = (self.player_input + text)[:PLAYER_NAME_LIMIT]
            else:
                text = "".join(char for char in text if char.isprintable() and not char.isspace())
                self.address_input = (self.address_input + text)[:ADDRESS_LIMIT]

            return

        if self.page != 'create':
            return

        text = "".join(char for char in text if char.isprintable())

        if self.focus == 'seed':
            self.seed_input = (self.seed_input + text)[:SEED_LIMIT]
        else:
            self.name_input = (self.name_input + text)[:NAME_LIMIT]

    @property
    def has_seed(self):
        """Сид есть только у бесконечного мира, тестовые площадки всегда одинаковые."""
        return WORLDS[self.generator].infinite

    def run_action(self, action):
        if action.startswith('lan:'):
            self.click_lan_game(int(action[4:]))
            return

        actions = {
            'singleplayer': self.open_worlds,
            'multiplayer': self.open_multiplayer,
            'focus_player': lambda: setattr(self, 'network_focus', 'player'),
            'focus_address': lambda: setattr(self, 'network_focus', 'address'),
            'join': self.join,
            'cancel_multiplayer': self.escape,
            'message_back': self.close_message,
            'lan': self.game.open_to_lan,
            'options': self.open_options,
            'video': lambda: setattr(self, 'page', 'video'),
            'sounds': lambda: setattr(self, 'page', 'sounds'),
            'done': self.escape,
            'smooth_lighting': self.toggle_smooth_lighting,
            'quit': self.game.quit,

            'play': self.play_selected,
            'create': lambda: self.open_create('worlds'),
            'delete': lambda: setattr(self, 'page', 'delete'),
            'recreate': self.recreate_selected,
            'cancel': self.escape,

            'world_type': self.next_generator,
            'focus_name': lambda: setattr(self, 'focus', 'name'),
            'focus_seed': lambda: setattr(self, 'focus', 'seed'),
            'game_mode': self.next_game_mode,
            'confirm_create': self.create_world,
            'cancel_create': self.escape,

            'confirm_delete': self.delete_selected,
            'cancel_delete': self.escape,

            'continue': self.escape,
            'leave': self.game.leave_world,

            'respawn': self.game.respawn,
            'title_screen': self.game.leave_world,
        }

        actions[action]()

    # Сетевая игра.

    def lan_games(self):
        return self.finder.games() if self.finder is not None else []

    def click_lan_game(self, index):
        games = self.lan_games()

        if index >= len(games):
            return

        address = games[index].address
        now = pygame.time.get_ticks()
        last_address, last_time = self.last_click

        self.address_input = address
        self.last_click = (address, now)

        if last_address == address and now - last_time < DOUBLE_CLICK_MS:
            self.join()

    def join(self):
        name = self.player_input.strip()
        address = self.address_input.strip()

        if not name or not address:
            return

        self.stop_finder()
        self.game.join_server(address, name)

    # Список миров.

    def selected_save(self):
        for save in self.saves:
            if save.folder == self.selected:
                return save

        return None

    def list_bottom(self):
        return self.units[1] - LIST_BOTTOM

    def list_left(self):
        return self.units[0] // 2 - ENTRY_WIDTH // 2

    def max_scroll(self):
        content = len(self.saves) * ENTRY_HEIGHT + LIST_PADDING * 2

        return max(0, content - (self.list_bottom() - LIST_TOP))

    def clamp_scroll(self):
        self.scroll = max(0, min(self.max_scroll(), self.scroll))

    def entry_top(self, index):
        return LIST_TOP + LIST_PADDING + index * ENTRY_HEIGHT - self.scroll

    def entry_at(self, position):
        """Номер мира под курсором и попал ли курсор на иконку."""
        x = position[0] / self.gui.scale
        y = position[1] / self.gui.scale
        left = self.list_left()

        if not (LIST_TOP <= y < self.list_bottom() and left <= x < left + ENTRY_WIDTH):
            return None, False

        offset = y - self.entry_top(0)
        index = int(offset // ENTRY_HEIGHT)

        if offset < 0 or index >= len(self.saves):
            return None, False

        return index, x < left + 2 + ICON

    def click_world_list(self, position):
        index, on_icon = self.entry_at(position)

        if index is None:
            return False

        folder = self.saves[index].folder
        now = pygame.time.get_ticks()
        last_folder, last_time = self.last_click

        double = last_folder == folder and now - last_time < DOUBLE_CLICK_MS

        self.selected = folder
        self.last_click = (folder, now)

        if on_icon or double:
            self.play_selected()

        return True

    def move_selection(self, step):
        if not self.saves:
            return

        folders = [save.folder for save in self.saves]

        if self.selected in folders:
            index = max(0, min(len(folders) - 1, folders.index(self.selected) + step))
        else:
            index = 0

        self.selected = folders[index]

        # Прокручиваем так, чтобы выбранный мир был виден целиком.
        top = self.entry_top(index)
        visible_bottom = self.list_bottom()

        if top < LIST_TOP:
            self.scroll -= LIST_TOP - top
        elif top + ENTRY_HEIGHT > visible_bottom:
            self.scroll += top + ENTRY_HEIGHT - visible_bottom

        self.clamp_scroll()

    def play_selected(self):
        save = self.selected_save()

        if save is None or save.broken:
            return

        self.game.play_world(save.folder, save.generator, save.name)

    def recreate_selected(self):
        save = self.selected_save()

        if save is not None:
            self.open_create('worlds', save.name, save.generator, save.game_mode)

    def delete_selected(self):
        save = self.selected_save()

        if save is not None:
            storage.delete_world(save.folder)
            print(f"Мир удалён: {storage.world_folder(save.folder)}")

        self.selected = None
        self.open_worlds()

    # Создание мира.

    def next_generator(self):
        names = list(WORLDS)
        self.generator = names[(names.index(self.generator) + 1) % len(names)]

        if not self.has_seed:
            self.focus = 'name'

    def toggle_smooth_lighting(self):
        settings = self.game.settings
        settings.smooth_lighting = not settings.smooth_lighting
        self.game.apply_settings()
        self.game.save_settings()

    def next_game_mode(self):
        modes = storage.GAME_MODES
        self.game_mode = modes[(modes.index(self.game_mode) + 1) % len(modes)]

    def create_world(self):
        name = self.name_input.strip()

        if not name:
            return

        seed = parse_seed(self.seed_input) if self.has_seed else None

        self.game.create_new_world(storage.folder_for_name(name), self.generator, name, self.game_mode, seed)

    # Настройки.

    def slider_value(self, name):
        settings = self.game.settings

        if name == 'fov':
            return round(settings.fov)

        if name == 'sensitivity':
            return round(settings.mouse_sensitivity / BASE_SENSITIVITY * 100)

        if name == 'render_scale':
            return settings.render_scale

        if name == 'gui_scale':
            return self.pending_gui_scale or settings.gui_scale

        if name == 'fps':
            return settings.fps_limit

        if name == 'fog':
            return settings.fog_distance

        if name == 'volume':
            return settings.sound_volume

        if name == 'music':
            return settings.music_volume

    def drag(self, mouse_x):
        values = SLIDER_VALUES[self.dragging]
        index = round(self.gui.slider_fraction(self.dragging, mouse_x) * (len(values) - 1))
        value = values[index]

        settings = self.game.settings

        if self.dragging == 'fov':
            settings.fov = value

        elif self.dragging == 'sensitivity':
            settings.mouse_sensitivity = BASE_SENSITIVITY * value / 100

        elif self.dragging == 'render_scale':
            settings.render_scale = value

        elif self.dragging == 'gui_scale':
            # Масштаб меняется при отпускании: иначе ползунок уезжал бы из-под курсора.
            self.pending_gui_scale = value
            return

        elif self.dragging == 'fps':
            settings.fps_limit = value

        elif self.dragging == 'fog':
            settings.fog_distance = value

        elif self.dragging == 'volume':
            settings.sound_volume = value

        elif self.dragging == 'music':
            settings.music_volume = value

        self.game.apply_settings()

    def slider_label(self, name, value):
        if name == 'fov':
            return "FOV: Normal" if value == 70 else f"FOV: {value}"

        if name == 'sensitivity':
            return f"Sensitivity: {value}%"

        if name == 'render_scale':
            return f"Render Scale: {value:.0%}"

        if name == 'gui_scale':
            label = f"GUI Scale: {value}"
            fits = self.gui.max_scale(self.game.screen.get_size())

            return label + f" (max {fits})" if value > fits else label

        if name == 'fps':
            return "Max Framerate: Unlimited" if value == UNLIMITED_FPS else f"Max Framerate: {value} fps"

        if name == 'fog':
            return f"Fog Distance: {value} blocks"

        if name == 'volume':
            return "Master Volume: OFF" if value == 0 else f"Master Volume: {value}%"

        if name == 'music':
            return "Music: OFF" if value == 0 else f"Music: {value}%"

    def draw_slider(self, screen, name, x, y, width=WIDE):
        values = SLIDER_VALUES[name]
        value = self.slider_value(name)
        index = nearest_index(values, value)

        self.gui.draw_slider(
            screen,
            name,
            self.slider_label(name, value),
            x,
            y,
            width,
            index / (len(values) - 1),
            active=self.dragging == name
        )

    # Отрисовка.

    def render(self, screen):
        self.gui.begin_frame()
        self.units = self.gui.units(screen)

        pages = {
            'title': self.render_title,
            'worlds': self.render_worlds,
            'create': self.render_create,
            'delete': self.render_delete,
            'pause': self.render_pause,
            'options': self.render_options,
            'video': self.render_video,
            'death': self.render_death,
            'sounds': self.render_sounds,
            'multiplayer': self.render_multiplayer,
            'message': self.render_message,
        }

        pages[self.page](screen)

    def button(self, screen, action, text, x, y, width=FULL, enabled=True):
        self.gui.draw_button(screen, action, text, x, y, width, enabled)

    def background(self, screen):
        # В мире фон темнее, чтобы меню читалось поверх игры.
        self.gui.darken(screen, 150 if self.game.in_world else 110)

    def render_title(self, screen):
        gui = self.gui
        width, height = self.units

        gui.darken(screen, 50)

        logo = gui.get_logo()
        logo_width = logo.get_width() // gui.scale
        logo_height = logo.get_height() // gui.scale
        logo_top = 30

        screen.blit(logo, logo.get_rect(midtop=(width // 2 * gui.scale, logo_top * gui.scale)))

        gui.draw_splash(
            screen,
            self.splash,
            (width // 2 + logo_width // 2 - 10, logo_top + logo_height - 4)
        )

        x = width // 2 - FULL // 2
        y = height // 4 + 48

        self.button(screen, 'singleplayer', "Singleplayer", x, y)
        self.button(screen, 'multiplayer', "Multiplayer", x, y + ROW)

        y += ROW * 2 + 12

        self.button(screen, 'options', "Options...", x, y, HALF)
        self.button(screen, 'quit', "Quit Game", x + FULL - HALF, y, HALF)

        gui.draw_text(screen, VERSION, (2, height - 1), anchor='bottomleft')
        gui.draw_text(screen, f"pygame-ce {pygame.version.ver}", (width - 2, height - 1), anchor='bottomright')

    def render_worlds(self, screen):
        gui = self.gui
        width, height = self.units

        self.background(screen)
        self.clamp_scroll()

        gui.draw_text(screen, "Select World", (width // 2, 16))

        top, bottom = LIST_TOP, self.list_bottom()

        gui.shade(screen, (0, top, width, bottom - top), 110)
        gui.fill(screen, (0, top - 1, width, 1), (0, 0, 0))
        gui.fill(screen, (0, bottom, width, 1), (0, 0, 0))

        clip = screen.get_clip()
        screen.set_clip(gui.to_pixels((0, top, width, bottom - top)))

        hovered, on_icon = self.entry_at(pygame.mouse.get_pos())

        for index, save in enumerate(self.saves):
            y = self.entry_top(index)

            if y + ENTRY_HEIGHT > top and y < bottom:
                self.render_entry(screen, save, self.list_left(), y, hovered == index and on_icon)

        screen.set_clip(clip)

        self.render_scrollbar(screen, top, bottom)

        save = self.selected_save()
        playable = save is not None and not save.broken

        left = width // 2 - 154
        row = height - 52

        self.button(screen, 'play', "Play Selected World", left, row, WIDE, playable)
        self.button(screen, 'create', "Create New World", left + 158, row, WIDE)

        row = height - 28

        self.button(screen, 'edit', "Edit", left, row, 72, enabled=False)
        self.button(screen, 'delete', "Delete", left + 78, row, 72, save is not None)
        self.button(screen, 'recreate', "Re-Create", left + 158, row, 72, playable)
        self.button(screen, 'cancel', "Cancel", left + 236, row, 72)

    def render_entry(self, screen, save, x, y, icon_hovered):
        gui = self.gui

        if save.folder == self.selected:
            gui.fill(screen, (x, y, ENTRY_WIDTH, ENTRY_HEIGHT), WHITE)
            gui.fill(screen, (x + 1, y + 1, ENTRY_WIDTH - 2, ENTRY_HEIGHT - 2), (0, 0, 0))

        generator = WORLDS.get(save.generator)
        icon = gui.get_block_icon(generator.icon if generator else 'dirt', ICON)

        screen.blit(icon, ((x + 2) * gui.scale, (y + 2) * gui.scale))

        if icon_hovered and not save.broken:
            gui.shade(screen, (x + 2, y + 2, ICON, ICON), 120)

            # Треугольник "играть" поверх иконки.
            left, top = (x + 2) * gui.scale, (y + 2) * gui.scale
            unit = gui.scale

            pygame.draw.polygon(screen, WHITE, (
                (left + 12 * unit, top + 8 * unit),
                (left + 12 * unit, top + 24 * unit),
                (left + 24 * unit, top + 16 * unit),
            ))

        text_x = x + ICON + 5
        text_width = ENTRY_WIDTH - ICON - 8

        if save.broken:
            details = "Save file is damaged"
        elif generator is None:
            details = f"Unknown world type: {save.generator}"
        else:
            details = f"{save.generator.title()}: {generator.description}"

        lines = (
            (save.name, WHITE),
            (f"{save.game_mode.title()}, {format_time(save.last_played)}", SUBTEXT),
            (details, SUBTEXT),
        )

        for number, (text, color) in enumerate(lines):
            gui.draw_text(
                screen,
                gui.fit_text(text, text_width),
                (text_x, y + 3 + number * 11),
                color,
                anchor='topleft'
            )

    def render_scrollbar(self, screen, top, bottom):
        max_scroll = self.max_scroll()

        if max_scroll == 0:
            return

        gui = self.gui
        x = self.list_left() + ENTRY_WIDTH + 6
        visible = bottom - top
        content = visible + max_scroll

        thumb = max(32, visible * visible // content)
        thumb_y = top + self.scroll * (visible - thumb) // max_scroll

        gui.fill(screen, (x, top, SCROLLBAR_WIDTH, visible), (0, 0, 0))
        gui.fill(screen, (x, thumb_y, SCROLLBAR_WIDTH, thumb), (128, 128, 128))
        gui.fill(screen, (x, thumb_y, SCROLLBAR_WIDTH - 1, thumb - 1), (192, 192, 192))

    def draw_field(self, screen, action, text, x, y, focused):
        """Поле ввода. Рамка белая у поля, куда идёт ввод. Клик по полю ставит в него ввод."""
        gui = self.gui

        gui.fill(screen, (x, y, FULL, FIELD_HEIGHT), WHITE if focused else GRAY)
        gui.fill(screen, (x + 1, y + 1, FULL - 2, FIELD_HEIGHT - 2), (0, 0, 0))

        cursor = "_" if focused and pygame.time.get_ticks() // CURSOR_BLINK_MS % 2 == 0 else ""
        shown = text

        # Длинный текст прокручивается: видны последние символы, как в поле ввода.
        while shown and gui.font.size(shown + "_")[0] > (FULL - 8) * gui.scale:
            shown = shown[1:]

        gui.draw_text(screen, shown + cursor, (x + 4, y + 6), anchor='topleft')
        gui.buttons[action] = gui.to_pixels((x, y, FULL, FIELD_HEIGHT))

    def render_create(self, screen):
        gui = self.gui
        width, height = self.units

        self.background(screen)

        gui.draw_text(screen, "Create New World", (width // 2, 20))

        x = width // 2 - FULL // 2

        gui.draw_text(screen, "World Name", (x, 40), GRAY, anchor='topleft')
        self.draw_field(screen, 'focus_name', self.name_input, x, 50, self.focus == 'name')

        name = self.name_input.strip()

        if name:
            gui.draw_text(
                screen,
                gui.fit_text(f"Will be saved in: {storage.folder_for_name(name)}", FULL),
                (x, 74),
                GRAY,
                anchor='topleft'
            )

        self.button(screen, 'game_mode', f"Game Mode: {self.game_mode.title()}", x, 88)
        self.button(screen, 'world_type', f"World Type: {self.generator.title()}", x, 112)

        gui.draw_text(
            screen,
            gui.fit_text(WORLDS[self.generator].description, width - 20),
            (width // 2, 140),
            GRAY
        )

        if self.has_seed:
            gui.draw_text(screen, "Seed for the World Generator", (x, 152), GRAY, anchor='topleft')
            self.draw_field(screen, 'focus_seed', self.seed_input, x, 162, self.focus == 'seed')
            gui.draw_text(screen, "Leave blank for a random seed", (x, 186), GRAY, anchor='topleft')

        self.button(screen, 'confirm_create', "Create New World", width // 2 - 155, height - 28, WIDE, bool(name))
        self.button(screen, 'cancel_create', "Cancel", width // 2 + 5, height - 28, WIDE)

    def render_delete(self, screen):
        gui = self.gui
        width, height = self.units
        save = self.selected_save()

        self.background(screen)

        gui.draw_text(screen, "Are you sure you want to delete this world?", (width // 2, 70))

        if save is not None:
            gui.draw_text(
                screen,
                gui.fit_text(f"'{save.name}' will be lost forever!", width - 20),
                (width // 2, 90),
                GRAY
            )

        y = height // 6 + 96

        self.button(screen, 'confirm_delete', "Delete", width // 2 - 155, y, WIDE)
        self.button(screen, 'cancel_delete', "Cancel", width // 2 + 5, y, WIDE)

    def render_pause(self, screen):
        gui = self.gui
        width, height = self.units

        self.background(screen)

        gui.draw_text(screen, "Game Menu", (width // 2, 40))

        x = width // 2 - FULL // 2
        right = x + FULL - HALF
        y = height // 4 + 8

        self.button(screen, 'continue', "Back to Game", x, y)

        self.button(screen, 'advancements', "Advancements", x, y + ROW, HALF, enabled=False)
        self.button(screen, 'statistics', "Statistics", right, y + ROW, HALF, enabled=False)

        game = self.game
        session = game.net

        self.button(screen, 'options', "Options...", x, y + ROW * 2, HALF)

        # Открыть в локалке можно только свой мир и только один раз.
        lan_text = f"LAN: port {session.port}" if session is not None and session.is_host else "Open to LAN"
        self.button(screen, 'lan', lan_text, right, y + ROW * 2, HALF, enabled=session is None and game.world_folder is not None)

        self.button(screen, 'leave', "Disconnect" if game.is_client else "Save and Quit to Title", x, y + ROW * 3)

    def render_multiplayer(self, screen):
        gui = self.gui
        width, height = self.units

        self.background(screen)

        gui.draw_text(screen, "Play Multiplayer", (width // 2, 12))

        x = width // 2 - FULL // 2

        gui.draw_text(screen, "Name", (x, 24), GRAY, anchor='topleft')
        self.draw_field(screen, 'focus_player', self.player_input, x, 33, self.network_focus == 'player')

        gui.draw_text(screen, "Games on your local network", (x, 58), GRAY, anchor='topleft')

        top = 68
        rows = max(1, (height - 112 - top) // ROW)
        games = self.lan_games()[:rows]

        for index, lan_game in enumerate(games):
            text = f"{lan_game.motd} ({lan_game.players} online)"
            gui.draw_button(screen, f'lan:{index}', text, x, top + index * ROW, FULL, selected=lan_game.address == self.address_input.strip())

        if not games:
            if self.finder is not None and self.finder.error:
                status = "Local network search is unavailable"
            else:
                status = "Scanning for games" + "." * (pygame.time.get_ticks() // 500 % 4)

            gui.draw_text(screen, status, (width // 2, top + 6), SUBTEXT)

        gui.draw_text(screen, "Server Address", (x, height - 76), GRAY, anchor='topleft')
        self.draw_field(screen, 'focus_address', self.address_input, x, height - 66, self.network_focus == 'address')

        ready = bool(self.player_input.strip() and self.address_input.strip())

        self.button(screen, 'join', "Join Server", width // 2 - 155, height - 28, WIDE, ready)
        self.button(screen, 'cancel_multiplayer', "Cancel", width // 2 + 5, height - 28, WIDE)

    def render_message(self, screen):
        gui = self.gui
        width, height = self.units
        title, text = self.message

        self.background(screen)

        gui.draw_text(screen, title, (width // 2, height // 2 - 30))
        gui.draw_text(screen, gui.fit_text(text, width - 20), (width // 2, height // 2 - 12), GRAY)

        back = "Back to Multiplayer" if self.message_return == 'multiplayer' else "Back to Title Screen"
        self.button(screen, 'message_back', back, width // 2 - FULL // 2, height // 2 + 20)

    def render_death(self, screen):
        gui = self.gui
        width, height = self.units

        gui.tint(screen, DEATH_TINT, 110)

        # Заголовок вдвое крупнее обычного текста.
        title = gui.render_text("You died!")
        title = pygame.transform.scale_by(title, 2)
        screen.blit(title, title.get_rect(center=(width // 2 * gui.scale, 60 * gui.scale)))

        x = width // 2 - FULL // 2
        y = height // 4 + 72

        self.button(screen, 'respawn', "Respawn", x, y)
        self.button(screen, 'title_screen', "Title Screen", x, y + ROW)

    def render_options(self, screen):
        gui = self.gui
        width, height = self.units

        self.background(screen)

        gui.draw_text(screen, "Options", (width // 2, 15))

        left = width // 2 - 155
        right = width // 2 + 5
        y = height // 6 - 12

        self.draw_slider(screen, 'fov', left, y)
        self.draw_slider(screen, 'sensitivity', right, y)

        y = height // 6 + 48

        for index, (action, text) in enumerate(OPTION_BUTTONS):
            column = left if index % 2 == 0 else right
            row = y + index // 2 * ROW

            self.button(screen, action or f'todo:{index}', text, column, row, WIDE, enabled=action is not None)

        self.button(screen, 'done', "Done", width // 2 - FULL // 2, height // 6 + 168)

    def render_sounds(self, screen):
        gui = self.gui
        width, height = self.units

        self.background(screen)

        gui.draw_text(screen, "Music & Sound Options", (width // 2, 15))

        self.draw_slider(screen, 'volume', width // 2 - 155, height // 6 - 12, 310)
        self.draw_slider(screen, 'music', width // 2 - 155, height // 6 - 12 + ROW, 310)

        self.button(screen, 'done', "Done", width // 2 - FULL // 2, height // 6 + 168)

    def render_video(self, screen):
        gui = self.gui
        width, height = self.units

        self.background(screen)

        gui.draw_text(screen, "Video Settings", (width // 2, 15))

        left = width // 2 - 155
        right = width // 2 + 5
        y = height // 6 - 12

        self.draw_slider(screen, 'render_scale', left, y)
        self.draw_slider(screen, 'gui_scale', right, y)
        self.draw_slider(screen, 'fps', left, y + ROW)
        self.draw_slider(screen, 'fog', right, y + ROW)

        smooth = "ON" if self.game.settings.smooth_lighting else "OFF"
        self.button(screen, 'smooth_lighting', f"Smooth Lighting: {smooth}", left, y + 2 * ROW, WIDE)

        self.button(screen, 'done', "Done", width // 2 - FULL // 2, height // 6 + 168)
