"""Сеть для игры по локальной сети: соединения, сервер и поиск игр в локалке.

Здесь только доставка сообщений, что в них, решает multiplayer.py.

Сообщение по TCP: заголовок из двух чисел (длина JSON и длина двоичных данных),
затем JSON с полем "type" и двоичный хвост (например, сжатый чанк).
Чтение и запись идут в своих потоках, игра забирает пришедшее раз в кадр
и никогда не ждёт сеть.

Открытые игры объявляют себя раз в ANNOUNCE_INTERVAL секунд в группу
многоадресной рассылки, экран сетевой игры слушает её и показывает список.
"""
import json
import os
import queue
import socket
import struct
import threading
import time

# Меняется, когда клиенты разных версий перестают понимать друг друга.
PROTOCOL = 1
GAME_ID = "sable"

DEFAULT_PORT = 47777
DISCOVERY_GROUP = "239.255.77.77"
DISCOVERY_PORT = 47778
ANNOUNCE_INTERVAL = 1.5
# Игра пропадает из списка, если не объявлялась столько секунд.
GAME_TIMEOUT = 5.0

CONNECT_TIMEOUT = 5.0
MAX_JSON = 4 * 1024 * 1024
MAX_DATA = 16 * 1024 * 1024

HEADER = struct.Struct("!II")


class ProtocolError(Exception):
    pass


def encode(message, data=b""):
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")

    return HEADER.pack(len(body), len(data)) + body + data


def parse_address(text, default_port=DEFAULT_PORT):
    """"host", "host:port" или "[ipv6]:port" в пару (host, port). ValueError, если неверно."""
    text = text.strip()

    if not text:
        raise ValueError("пустой адрес")

    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        port = rest.removeprefix(":") or str(default_port)
    elif text.count(":") == 1:
        host, port = text.split(":")
    else:
        host, port = text, str(default_port)

    if not host or not port.isdigit() or not 0 < int(port) < 65536:
        raise ValueError(f"неверный адрес '{text}'")

    return host, int(port)


def local_address():
    """Адрес этого компьютера в локальной сети, который можно назвать другу."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        # Пакет не отправляется: connect у UDP только выбирает интерфейс.
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]

    except OSError:
        return "127.0.0.1"

    finally:
        probe.close()


class Connection:
    """Одно TCP-соединение. send не ждёт, receive отдаёт всё, что уже пришло."""

    def __init__(self, sock):
        sock.settimeout(None)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        self.sock = sock
        self.inbox = queue.Queue()
        self.outbox = queue.Queue()

        # Почему соединение закрылось: текст для игрока.
        self.reason = None
        self.closed = False

        try:
            self.address = sock.getpeername()[:2]
        except OSError:
            self.address = ("?", 0)

        threading.Thread(target=self.read_loop, daemon=True).start()
        threading.Thread(target=self.write_loop, daemon=True).start()

    @classmethod
    def open(cls, host, port, timeout=CONNECT_TIMEOUT):
        return cls(socket.create_connection((host, port), timeout=timeout))

    def send(self, message, data=b""):
        if not self.closed:
            self.outbox.put(encode(message, data))

    def receive(self):
        """Пришедшие сообщения парами (сообщение, данные). Разрыв не теряется: см. closed."""
        messages = []

        while True:
            try:
                item = self.inbox.get_nowait()
            except queue.Empty:
                return messages

            if item is None:
                self.closed = True
            else:
                messages.append(item)

    def close(self, reason=None):
        """Отправляет то, что уже в очереди, и закрывает соединение."""
        if self.reason is None:
            self.reason = reason

        self.outbox.put(None)

    def read_exact(self, size):
        chunks = []

        while size > 0:
            chunk = self.sock.recv(min(size, 1 << 20))

            if not chunk:
                raise ConnectionError("соединение закрыто")

            chunks.append(chunk)
            size -= len(chunk)

        return b"".join(chunks)

    def read_loop(self):
        try:
            while True:
                body_size, data_size = HEADER.unpack(self.read_exact(HEADER.size))

                if body_size > MAX_JSON or data_size > MAX_DATA:
                    raise ProtocolError("слишком большое сообщение")

                message = json.loads(self.read_exact(body_size))

                if not isinstance(message, dict) or not isinstance(message.get("type"), str):
                    raise ProtocolError("сообщение без типа")

                data = self.read_exact(data_size) if data_size else b""
                self.inbox.put((message, data))

        except (OSError, ValueError, ProtocolError) as error:
            if self.reason is None:
                self.reason = str(error) or type(error).__name__

        finally:
            self.inbox.put(None)
            self.outbox.put(None)

    def write_loop(self):
        try:
            while True:
                packet = self.outbox.get()

                if packet is None:
                    break

                self.sock.sendall(packet)

        except OSError as error:
            if self.reason is None:
                self.reason = str(error)

        finally:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

            self.sock.close()


class Server:
    """Принимает подключения. Если порт по умолчанию занят, берёт свободный."""

    def __init__(self, port=DEFAULT_PORT):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.sock.bind(("", port))
        except OSError:
            self.sock.bind(("", 0))

        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        self.new = queue.Queue()
        self.running = True

        threading.Thread(target=self.accept_loop, daemon=True).start()

    def accept_loop(self):
        while self.running:
            try:
                sock, _ = self.sock.accept()
            except OSError:
                break

            if not self.running:
                sock.close()
                break

            try:
                self.new.put(Connection(sock))
            except OSError:
                sock.close()

    def accept(self):
        """Новые соединения с прошлого вызова."""
        connections = []

        while True:
            try:
                connections.append(self.new.get_nowait())
            except queue.Empty:
                return connections

    def close(self):
        self.running = False
        self.sock.close()


class Announcer:
    """Объявляет открытую игру в локальной сети, пока не остановят."""

    def __init__(self, port, motd):
        self.port = port
        self.motd = motd
        self.players = 1
        self.stopped = threading.Event()

        # Одно объявление уходит несколькими путями: по номеру его узнают как одну игру.
        self.token = os.urandom(6).hex()

        threading.Thread(target=self.loop, daemon=True).start()

    def packet(self):
        return json.dumps({
            "game": GAME_ID,
            "protocol": PROTOCOL,
            "id": self.token,
            "port": self.port,
            "motd": self.motd,
            "players": self.players,
        }).encode("utf-8")

    @staticmethod
    def make_socket(interface=None):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

            if interface is not None:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface))

        except OSError:
            pass

        return sock

    def loop(self):
        # Рассылка по умолчанию может уйти в VPN, поэтому ещё одна через
        # интерфейс локальной сети.
        lan = local_address()
        sockets = [self.make_socket()] + ([self.make_socket(lan)] if lan != "127.0.0.1" else [])

        while not self.stopped.is_set():
            packet = self.packet()

            for sock in sockets:
                try:
                    sock.sendto(packet, (DISCOVERY_GROUP, DISCOVERY_PORT))
                except OSError:
                    pass

            # Без сети многоадресная рассылка не уходит, но на этом же
            # компьютере игру всё равно должно быть видно.
            try:
                sockets[0].sendto(packet, ("127.0.0.1", DISCOVERY_PORT))
            except OSError:
                pass

            self.stopped.wait(ANNOUNCE_INTERVAL)

        for sock in sockets:
            sock.close()

    def stop(self):
        self.stopped.set()


class LanGame:
    def __init__(self, token, host, port, motd, players):
        self.token = token
        self.host = host
        self.port = port
        self.motd = motd
        self.players = players
        self.seen = time.monotonic()

    @property
    def address(self):
        return f"{self.host}:{self.port}"


class Finder:
    """Слушает объявления игр в локальной сети, пока открыт экран сетевой игры."""

    def __init__(self):
        self.found = {}
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.error = None

        try:
            self.sock = self.make_socket()
        except OSError as error:
            self.sock = None
            self.error = str(error)
            return

        threading.Thread(target=self.loop, daemon=True).start()

    @staticmethod
    def make_socket():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Несколько копий игры на одном компьютере слушают один порт.
        if hasattr(socket, "SO_REUSEPORT"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

        sock.bind(("", DISCOVERY_PORT))

        try:
            membership = struct.pack("4s4s", socket.inet_aton(DISCOVERY_GROUP), socket.inet_aton("0.0.0.0"))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        except OSError:
            # Без сети в группу не вступить, но объявления с этого компьютера дойдут.
            pass

        sock.settimeout(0.5)

        return sock

    def loop(self):
        while not self.stopped.is_set():
            try:
                packet, (host, _) = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                info = json.loads(packet)

                if info.get("game") != GAME_ID or info.get("protocol") != PROTOCOL:
                    continue

                port = int(info["port"])
                motd = str(info.get("motd", ""))[:64]
                players = int(info.get("players", 0))
                token = str(info.get("id", f"{host}:{port}"))

            except (ValueError, KeyError, TypeError, AttributeError):
                continue

            with self.lock:
                self.add(LanGame(token, host, port, motd, players))

        self.sock.close()

    def add(self, game):
        """Одна игра приходит несколькими путями. Адрес берём тот, откуда пришло
        не через 127.0.0.1: по нему до хозяина достучится и другой компьютер."""
        known = self.found.get(game.token)

        if known is not None and (game.host == "127.0.0.1" or known.host != "127.0.0.1"):
            known.seen = game.seen
            known.players = game.players
            known.motd = game.motd
            return

        self.found[game.token] = game

    def games(self):
        now = time.monotonic()

        with self.lock:
            for key, game in list(self.found.items()):
                if now - game.seen > GAME_TIMEOUT:
                    del self.found[key]

            return sorted(self.found.values(), key=lambda game: (game.motd, game.address))

    def stop(self):
        self.stopped.set()
