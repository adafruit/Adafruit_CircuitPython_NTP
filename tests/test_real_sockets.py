# SPDX-FileCopyrightText: 2026 Ted Timmons
#
# SPDX-License-Identifier: MIT

"""Real-socket tests for issue #35.

test_response_validation.py drives the library through a fake socketpool. These tests use
CPython's actual UDP sockets against a local fake server, to show the two
mechanisms are real socket behaviour and not artifacts of the fake:

  1. adafruit_ntp reuses ONE bytearray as both request and response buffer,
     zeroes it before sending, and discards recv_into's return value. Any
     datagram that does not reach offset 40-43 leaves the transmit-timestamp
     field reading as the zeros the client wrote itself.
  2. The socket is never connect()ed, so it accepts a datagram from any peer.

No board and no public NTP server are involved.
"""

import socket
import struct
import threading

import pytest

PACKET_SIZE = 48
NTP_TO_UNIX_EPOCH = 2208988800
VALID_NTP_SECONDS = 3931000000  # a real 2024 timestamp in NTP epoch


def good_packet():
    """A well-formed 48-byte NTP server response."""
    pkt = bytearray(PACKET_SIZE)
    pkt[0] = 0b00100100  # LI=0, VN=4, mode=4 (server)
    pkt[1] = 2  # stratum
    struct.pack_into("!II", pkt, 32, VALID_NTP_SECONDS, 0)  # receive timestamp
    struct.pack_into("!II", pkt, 40, VALID_NTP_SECONDS, 0)  # transmit timestamp
    return pkt


def fresh_request_buffer():
    """Exactly what adafruit_ntp puts on the wire (lines 84-86)."""
    packet = bytearray(PACKET_SIZE)
    packet[0] = 0b00100011  # LI=0, VN=4, mode=3 (client)
    for i in range(1, PACKET_SIZE):
        packet[i] = 0
    return packet


@pytest.fixture(name="server")
def server_fixture():
    """A UDP socket standing in for the NTP server."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    yield sock
    sock.close()


def serve_once(sock, reply):
    """Answer one datagram with `reply` (or stay silent if None)."""

    def run():
        try:
            _, addr = sock.recvfrom(1024)
        except OSError:
            return
        if reply is not None:
            sock.sendto(reply, addr)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


@pytest.mark.parametrize("length", [0, 20, 32, 36, 40])
def test_short_response_leaves_transmit_timestamp_zeroed(server, length):
    """A datagram that stops at or before offset 40 never overwrites the
    transmit-timestamp field, so it parses as the client's own zeros."""
    serve_once(server, bytes(good_packet()[:length]))

    packet = fresh_request_buffer()
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.settimeout(5)
    try:
        client.sendto(packet, server.getsockname())
        nbytes = client.recv_into(packet)  # the library discards this
    finally:
        client.close()

    assert nbytes == length
    srv_send_s = struct.unpack_from("!I", packet, offset=40)[0]
    assert srv_send_s == 0
    assert srv_send_s - NTP_TO_UNIX_EPOCH == -NTP_TO_UNIX_EPOCH


def test_full_response_is_parsed_correctly(server):
    """Control: a complete 48-byte response works."""
    serve_once(server, bytes(good_packet()))

    packet = fresh_request_buffer()
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.settimeout(5)
    try:
        client.sendto(packet, server.getsockname())
        nbytes = client.recv_into(packet)
    finally:
        client.close()

    assert nbytes == PACKET_SIZE
    srv_send_s = struct.unpack_from("!I", packet, offset=40)[0]
    assert srv_send_s == VALID_NTP_SECONDS


def test_response_longer_than_48_bytes_is_harmless(server):
    """NTS/MAC/extension-field responses exceed 48 bytes. recv_into copies only
    len(buf) and reports 48, so the timestamp is still read correctly."""
    serve_once(server, bytes(good_packet()) + b"\xaa" * 20)

    packet = fresh_request_buffer()
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.settimeout(5)
    try:
        client.sendto(packet, server.getsockname())
        nbytes = client.recv_into(packet)
    finally:
        client.close()

    assert nbytes == PACKET_SIZE
    assert struct.unpack_from("!I", packet, offset=40)[0] == VALID_NTP_SECONDS


def test_unconnected_socket_accepts_datagram_from_a_stray_source(server):
    """The library never calls connect(), so an unconnected UDP socket accepts
    whatever is addressed to its ephemeral port -- from anyone. There is no
    source check, and no RFC 5905 sec 9.3 origin-timestamp match is possible
    either, because the request that was sent is all zeros."""
    stray = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    stray.bind(("127.0.0.1", 0))

    packet = fresh_request_buffer()
    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.settimeout(5)
    try:
        # The request goes to the server, which never answers.
        client.sendto(packet, server.getsockname())
        # getsockname() reports the wildcard address; reach the port on loopback.
        client_addr = ("127.0.0.1", client.getsockname()[1])

        stray_payload = b"not an ntp packet"
        stray.sendto(stray_payload, client_addr)

        nbytes = client.recv_into(packet)
    finally:
        client.close()
        stray.close()

    assert nbytes == len(stray_payload), "accepted the stray sender's datagram"
    assert struct.unpack_from("!I", packet, offset=40)[0] == 0
