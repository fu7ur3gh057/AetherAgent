"""Защита от SSRF: бот не должен открывать через себя то, что недоступно снаружи.

Правила: только http/https, без логина в адресе, порты 80/443/8080/8443; имя хоста резолвится нами, и ВСЕ полученные
адреса обязаны быть публичными (loopback, приватные сети, link-local с облачными «метаданными» 169.254.169.254,
CGNAT, multicast, зарезервированные, а также IPv4 внутри IPv6, 6to4 и Teredo запрещены). Десятичные и шестнадцатеричные формы
адреса («2130706433», «0x7f.1») тоже проходят через резолвер, поэтому ловятся тем же правилом.
Соединение затем идёт на проверенный IP (см. tools.py), иначе DNS мог бы «подменить» адрес между проверкой и запросом.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

ALLOWED_PORTS = {80, 443, 8080, 8443}
MAX_URL = 2000


class UnsafeURL(ValueError):
    """Адрес нельзя открывать (небезопасный или некорректный)."""


@dataclass
class Target:
    scheme: str
    host: str          # имя хоста как в адресе (для Host и SNI)
    port: int
    path: str          # путь с запросом
    ip: str            # проверенный публичный адрес, на который идёт соединение

    @property
    def default_port(self) -> bool:
        return self.port == (443 if self.scheme == "https" else 80)

    @property
    def host_header(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return host if self.default_port else f"{host}:{self.port}"

    @property
    def connect_url(self) -> str:
        ip = f"[{self.ip}]" if ":" in self.ip else self.ip
        return f"{self.scheme}://{ip}:{self.port}{self.path}"


def is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped                      # ::ffff:127.0.0.1 это loopback
        elif ip.sixtofour is not None or ip.teredo is not None:
            return False                             # туннели с вложенным IPv4: не разбираем, не пускаем
    return ip.is_global and not ip.is_multicast


def parse(url: str) -> tuple[str, str, int, str]:
    """(scheme, host, port, path+query) либо UnsafeURL."""
    url = (url or "").strip()
    if not url or len(url) > MAX_URL:
        raise UnsafeURL("Пустой или слишком длинный адрес")
    if any(c in url for c in "\r\n\x00 \t"):
        raise UnsafeURL("В адресе недопустимые символы")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise UnsafeURL("Некорректный адрес") from None
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL("Поддерживаются только http и https")
    if parts.username is not None or parts.password is not None:
        raise UnsafeURL("Адрес с логином и паролем не разрешён")
    host = (parts.hostname or "").strip(".").lower()
    if not host:
        raise UnsafeURL("В адресе нет имени сайта")
    port = port or (443 if parts.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise UnsafeURL(f"Порт {port} не разрешён")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return parts.scheme, host, port, path


async def resolve(host: str, port: int) -> list[str]:
    """Все адреса хоста; ошибка, если хоть один не публичный. Вынесено для подмены в тестах."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise UnsafeURL(f"Сайт «{host}» не найден") from None
    ips: list[str] = []
    for info in infos:
        raw = info[4][0].split("%")[0]               # у IPv6 бывает суффикс зоны
        ip = ipaddress.ip_address(raw)
        if not is_public_ip(ip):
            raise UnsafeURL("Адрес ведёт во внутреннюю сеть или на служебный адрес: такие страницы не открываются")
        if raw not in ips:
            ips.append(raw)
    if not ips:
        raise UnsafeURL(f"Сайт «{host}» не найден")
    return ips


async def check(url: str) -> Target:
    scheme, host, port, path = parse(url)
    ips = await resolve(host, port)
    ips.sort(key=lambda a: ":" in a)                 # IPv4 в приоритете: стабильнее у большинства серверов
    return Target(scheme, host, port, path, ips[0])
