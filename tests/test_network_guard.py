"""No test reaches beyond this machine: ``conftest.py`` stops it first [0013.29].

The fixture checks the address before the real call runs, so a refused connection sends
nothing. 192.0.2.1 and 2001:db8::1 are documentation addresses (RFC 5737, RFC 3849): never
routed, even if the fixture failed.
"""

import socket
from collections.abc import Callable

import pytest

BEYOND = [
    (socket.AF_INET, ("192.0.2.1", 11434)),
    (socket.AF_INET, ("0.0.0.0", 11434)),
    (socket.AF_INET6, ("2001:db8::1", 11434, 0, 0)),
    (socket.AF_INET6, ("::ffff:127.0.0.1", 11434, 0, 0)),  # loopback to 3.13's is_loopback
    (socket.AF_INET, ("localhost", 11434)),  # a name: tests connect to addresses
]


@pytest.mark.parametrize(("family", "address"), BEYOND)
def test_a_connection_beyond_loopback_fails_the_test(
    family: socket.AddressFamily, address: tuple[object, ...]
) -> None:
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        with pytest.raises(AssertionError, match="beyond loopback"):
            sock.connect(address)
        with pytest.raises(AssertionError, match="beyond loopback"):
            sock.connect_ex(address)


@pytest.mark.parametrize(("family", "address"), BEYOND)
def test_a_datagram_beyond_loopback_fails_the_test(
    family: socket.AddressFamily, address: tuple[object, ...]
) -> None:
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        with pytest.raises(AssertionError, match="beyond loopback"):
            sock.sendto(b"query", address)
        with pytest.raises(AssertionError, match="beyond loopback"):
            sock.sendto(b"query", 0, address)


@pytest.mark.parametrize(
    "ask",
    [
        lambda: socket.getaddrinfo("localhost", 11434),
        lambda: socket.getaddrinfo("ollama.example", 11434),
        lambda: socket.getaddrinfo(b"localhost", 11434),
        lambda: socket.gethostbyname("localhost"),
        lambda: socket.gethostbyname_ex("localhost"),
        lambda: socket.gethostbyaddr("127.0.0.1"),  # a reverse lookup asks a resolver too
        lambda: socket.create_connection(("localhost", 11434), timeout=1),
    ],
)
def test_asking_a_resolver_fails_the_test(ask: Callable[[], object]) -> None:
    with pytest.raises(AssertionError, match="asked a resolver"):
        ask()


def test_an_address_needs_no_resolver() -> None:
    assert socket.getaddrinfo("127.0.0.1", 11434, type=socket.SOCK_STREAM)[0][4][0] == "127.0.0.1"
    assert socket.getaddrinfo(None, 11434, type=socket.SOCK_STREAM) != []
    assert socket.gethostbyname("127.0.0.1") == "127.0.0.1"


@pytest.mark.parametrize(
    ("family", "host"), [(socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")]
)
def test_loopback_goes_through(family: socket.AddressFamily, host: str) -> None:
    with (
        socket.create_server((host, 0), family=family) as server,
        socket.socket(family, socket.SOCK_STREAM) as client,
    ):
        client.settimeout(5)
        client.connect(server.getsockname()[:2])
        accepted, _ = server.accept()
        with accepted:
            client.sendall(b"ping")
            assert accepted.recv(4) == b"ping"
    with socket.socket(family, socket.SOCK_DGRAM) as receiver:
        receiver.bind((host, 0))
        with socket.socket(family, socket.SOCK_DGRAM) as sender:
            sender.sendto(b"ping", receiver.getsockname()[:2])
        assert receiver.recv(4) == b"ping"
