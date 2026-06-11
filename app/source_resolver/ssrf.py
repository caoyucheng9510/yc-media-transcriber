from __future__ import annotations

import ipaddress
import socket
from functools import lru_cache
from urllib.parse import urlparse

from app.errors import AppError


BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}
BLOCKED_IPS = {ipaddress.ip_address("169.254.169.254")}


def assert_safe_url(
    url: str,
    *,
    allow_private: bool = False,
    host_allowlist: tuple[str, ...] = (),
    trusted_media_host_suffixes: tuple[str, ...] = (),
    fake_ip_cidrs: tuple[str, ...] = (),
    resolve_dns: bool = True,
) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise AppError("invalid_source", "只支持 http/https 链接。", "downloading")
    host = parsed.hostname
    if not host:
        raise AppError("invalid_source", "链接缺少有效域名。", "downloading")
    normalized_host = host.lower().strip("[]")
    normalized_host_allowlist = tuple(item.lower().strip().strip("[]") for item in host_allowlist)
    if normalized_host in normalized_host_allowlist:
        return
    if normalized_host in BLOCKED_HOSTS:
        raise AppError("invalid_source", "出于安全原因，默认禁止访问本机或元数据地址。", "downloading")
    try:
        ip = ipaddress.ip_address(normalized_host)
    except ValueError:
        ip = None
    if ip is not None:
        _assert_allowed_ip(ip, allow_private)
        return
    if not resolve_dns:
        return
    try:
        infos = socket.getaddrinfo(normalized_host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise AppError("download_failed", f"域名解析失败：{host}", "downloading") from exc
    trusted_suffixes = _normalize_suffixes(trusted_media_host_suffixes)
    fake_networks = _parse_networks(fake_ip_cidrs)
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        _assert_allowed_ip(
            address,
            allow_private,
            host=normalized_host,
            trusted_media_host_suffixes=trusted_suffixes,
            fake_ip_networks=fake_networks,
        )


def _assert_allowed_ip(
    address: ipaddress._BaseAddress,
    allow_private: bool,
    *,
    host: str | None = None,
    trusted_media_host_suffixes: tuple[str, ...] = (),
    fake_ip_networks: tuple[ipaddress._BaseNetwork, ...] = (),
) -> None:
    if address in BLOCKED_IPS:
        raise AppError("invalid_source", "出于安全原因，默认禁止访问云元数据地址。", "downloading")
    if allow_private:
        return
    if _is_restricted_ip(address):
        if (
            host
            and _is_trusted_media_host(host, trusted_media_host_suffixes)
            and _is_fake_ip(address, fake_ip_networks)
        ):
            return
        target = f"host={host} ip={address}" if host else f"ip={address}"
        raise AppError("invalid_source", f"下载地址解析到内网或保留地址：{target}。", "downloading")


def _is_restricted_ip(address: ipaddress._BaseAddress) -> bool:
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _is_trusted_media_host(host: str, suffixes: tuple[str, ...]) -> bool:
    normalized = host.lower().strip(".")
    for suffix in suffixes:
        if normalized == suffix or normalized.endswith(f".{suffix}"):
            return True
    return False


def _is_fake_ip(
    address: ipaddress._BaseAddress,
    fake_ip_networks: tuple[ipaddress._BaseNetwork, ...],
) -> bool:
    for network in fake_ip_networks:
        if address.version == network.version and address in network:
            return True
    return False


def _normalize_suffixes(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(value.lower().strip().strip(".") for value in values if value.strip())


@lru_cache(maxsize=32)
def _parse_networks(values: tuple[str, ...]) -> tuple[ipaddress._BaseNetwork, ...]:
    networks: list[ipaddress._BaseNetwork] = []
    for value in values:
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError as exc:
            raise AppError("invalid_source", f"安全配置中的 Fake-IP 网段无效：{value}", "downloading") from exc
    return tuple(networks)
