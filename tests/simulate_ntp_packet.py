# SPDX-FileCopyrightText: 2024 H PHil Duby
#
# SPDX-License-Identifier: MIT

"""
Support functions to simulate and access NTP packets.
"""

from collections import namedtuple
import struct
import time
from tests.shared_for_testing import NS_PER_SEC

NTPPacket = namedtuple(
    "NTPPacket",
    [
        "leap",
        "version",
        "mode",
        "stratum",
        "poll",
        "precision",
        "root_delay",
        "root_dispersion",
        "ref_id",
        "ref_ts",
        "orig_ts",
        "recv_ts",
        "tx_ts",
    ],
)

# Constants
# !B «leap:2+version:3+mode:3»
# !B stratum
# !B poll
# !b precision
# !i root delay : signed fixed point, negative is anomaly
# !i root dispersion : signed fixed point, negative is anomaly
# !I reference id : ipv4 32 bit address
# !Q !Q !Q !Q NTP timestamps : reference, origin, receive, transmit
NTP_PACKET_STRUCTURE: str = "!BBBbiiiQQQQ"

NTP_VERSION = 4  # Fixed for packet structure being used
NTP_MODE = 4  # Server: NTP server responding to client requests.
NTP_TO_UNIX_EPOCH_SEC = (
    2208988800  # NTP epoch (1900-01-01) to Unix epoch (1970-01-01) seconds
)
NTP_TO_UNIX_EPOCH_NS = (
    NTP_TO_UNIX_EPOCH_SEC * NS_PER_SEC
)  # NTP to Unix epoch in nanoseconds


def create_ntp_packet(  # pylint:disable=too-many-arguments,too-many-locals
    iso: str = "2024-1-1T10:11:12.5",
    *,
    leap: int = 0,
    mode: int = 4,
    stratum: int = 2,
    poll: int = 6,
    precision: int = -6,
    root_delay: int = 1_000_000_000,
    root_dispersion: int = 1_000_000_000,
    ipv4: str = "10.20.30.40",
    ref_delta: int = 0,
    receive_delta: int = 0,  # , origin_delta: int = 0
    transmit_delay: int = 0,
) -> bytearray:
    """
    Build a sample (simulated) NTP packet.

    :param iso: str: variant of ISO time (y-m-dTh:m:s.f) where (f) can extend to nanoseconds and
            leading zeros are optional.
    :param mode: int «3 bits»: 3 is client, 4 is server
    :param leap: int «2 bits»: Leap indicator (0: no warning, 1: 61 sec last min,
            2: 59 sec last min, 3: alarm).
    :param stratum: int «4 bits»: network distance from specialized time source reference.
    :param poll_interval: int «4 bits»: Poll interval (2^poll_interval seconds).
    :param precision: int: Precision (2^precision seconds).
    :param root_delay: int: Root delay (nanoseconds).
    :param root_dispersion: int: Root dispersion (nanoseconds).
    :param ipv4: str: IPv4 dotted decimal address to use for NTP server reference id.
    :param ref_delta: int: Reference timestamp delta from utc (nanoseconds).
    :param origin_delta: int: Origin timestamp delta from utc (nanoseconds).
            origin could be anything. Not related to the server timestamps. Usually 0.
            Really needs it's own iso utc string, plus nanoseconds offset, with flag value
            to indicate 0, or an absolute NTP timestamp.
    :param receive_delta: int: Receive timestamp delta from utc (nanoseconds).
    :param transmit_delay: int: Transmit timestamp delta from receive_delta (nanoseconds).
    :return: bytearray: NTP version 4, server mode packet.
    """
    packet_size = struct.calcsize(NTP_PACKET_STRUCTURE)
    packet = bytearray(packet_size)

    leap = min(3, max(0, int(leap)))  # 2 bits
    mode = min(7, max(0, int(mode)))  # 3 bits
    poll = min(14, max(4, int(poll)))  # 2^poll seconds: since prev poll?
    stratum = min(16, max(1, int(stratum)))
    precision = min(
        -6, max(-30, int(precision))
    )  # resolution of server clock: -20 = ms
    reference_ntp_ns = NTP_TO_UNIX_EPOCH_NS + iso_to_nanoseconds(iso)
    # Leap Indicator «2 bits» (LI), Version Number «3 bits» (VN), and Mode «3 bits»
    li_vn_mode = (leap << 6) | (NTP_VERSION << 3) | mode

    def offset_timestamp(offset_ns: int) -> int:
        """64 bit NTP timestamp offset from the reference point."""
        return ns_to_ntp_timestamp(reference_ntp_ns + offset_ns)

    ntp_fields = (
        li_vn_mode,
        stratum,
        poll,
        precision,
        ns_to_fixedpoint(root_delay),
        ns_to_fixedpoint(root_dispersion),
        ipv4_to_int(ipv4),
        offset_timestamp(ref_delta),
        0,
        offset_timestamp(receive_delta),
        offset_timestamp(receive_delta + transmit_delay),
    )
    struct.pack_into(NTP_PACKET_STRUCTURE, packet, 0, *ntp_fields)
    return packet


def ipv4_to_int(ipv4: str) -> int:
    """
    Convert a dotted IPv4 address into a 32-bit integer.

    :param ipv4 (str): The IPv4 address in dotted-decimal format (e.g., "192.168.1.1").
    :returns: int: The corresponding 32-bit integer representation of the IPv4 address.
    :raises ValueError: If the input string is not a valid IPv4 address.
    """
    # Split dotted IPv4 address into its four integer octets
    octets = tuple(map(int, ipv4.split(".")))
    # Check that each octet is within the valid range (0-255), and that there are 4 values
    if len(octets) != 4 or any(octet < 0 or octet > 255 for octet in octets):
        raise ValueError("Must be 4 octets, each value must be between 0 and 255.")
    # Combine octet values into a 32-bit integer
    return (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]


def iso_to_nanoseconds(iso: str) -> int:
    """
    Convert an ISO format datetime string to nanoseconds since the Unix epoch.

    iso is not quite a standard iso format datetime string.
    year "-" month "-" day "T" hour ":" minute ":" second, with optional "." nanoseconds
    Normally the numeric fields (other than fraction) are fixed 2 or 4 digits, but this is not
    enforced. The optional fractional field, when provided, is treated as have trailing zeros
    to fill to 9 digits, which is then used as nanoseconds.

    No TZ offset considered: output is UTC time.

    :raises: ValueError if the input input string can not be parsed as an ISO datetime.
    """
    # Naive conversion of y-m-dTh:m:s.fraction string to tuple of integer values. No validation.
    text = iso.replace("-", " ").replace(":", " ").replace("T", " ").replace(".", " ")
    try:
        raw_tuple = tuple(map(int, text.split()))
    except ValueError as ex:
        raise ValueError(f"Invalid ISO datetime string: {iso}") from ex
    nine_tuple = raw_tuple[:6] + (0, -1, -1)
    seconds = int(time.mktime(time.struct_time(nine_tuple)))
    split_fractional = iso.split(".")
    # Handle optional fractional seconds
    fractional_seconds = split_fractional[-1] if len(split_fractional) > 1 else ""
    fractional_digits = len(fractional_seconds)
    nanoseconds = (
        0 if not fractional_seconds else raw_tuple[-1] * (10 ** (9 - fractional_digits))
    )
    return seconds * NS_PER_SEC + nanoseconds


def _ns_to_unsigned_fixed_point(nanoseconds: int, fraction_bits: int) -> int:
    """
    Convert nanoseconds to an unsigned fixed point seconds value.

    :param ns: int: nanoseconds
    :param fraction_bits: int: number of bits for the fraction
    :return: int: signed fixed point number for packing
    """
    # Separate the integer seconds and fractional nanoseconds
    seconds, frac_ns = divmod(abs(nanoseconds), NS_PER_SEC)
    # Convert the fractional part to a binary fraction value
    fixed_frac = (frac_ns << fraction_bits) // NS_PER_SEC
    # Combine the integer part and fractional part into single fixed-point value
    return (seconds << fraction_bits) | fixed_frac


def ns_to_fixedpoint(nanoseconds: int) -> int:
    """
    Convert integer nanoseconds to a signed fixed point format: 16 bits integer, 16 bits fraction

    :param ns: int: nanoseconds
    :return: int: signed fixed point number for packing
    """
    unsigned_fixed_point = _ns_to_unsigned_fixed_point(nanoseconds, 16)
    return unsigned_fixed_point if nanoseconds >= 0 else -unsigned_fixed_point


def ns_to_ntp_timestamp(ns_since_ntp_epoch: int) -> int:
    """
    Convert nanoseconds since the NTP epoch into a 64-bit NTP timestamp format.

    64 bit NTP timestamp is 32 bit integer seconds and 32 bit fractional seconds

    :param ns_since_ntp_epoch: Nanoseconds since the NTP epoch (1900-01-01 00:00:00).
    :returns: int: A 64-bit integer representing the full NTP timestamp.
    """
    return _ns_to_unsigned_fixed_point(ns_since_ntp_epoch, 32)


def format_ns_as_iso_timestamp(unix_ns: int) -> str:
    """
    Convert nanoseconds since the Unix epoch into an approximation of an ISO datetime string.

    The fractional seconds, when not zero, will be extended to 9 digits (nanoseconds)

    :param unix_ns: Nanoseconds since the Unix epoch (1970-01-01 00:00:00).
    :return: str: The corresponding ISO format datetime string.
    """
    # Convert nanoseconds to integer seconds and nanoseconds
    seconds, fraction = divmod(unix_ns, NS_PER_SEC)

    # Determine the fractional suffix for the time string
    tm_suffix = f".{fraction:09}" if fraction != 0 else ""

    tms = time.localtime(seconds)  # Convert seconds to a struct_time

    # Format the full ISO timestamp
    return (
        f"{tms.tm_year:04}-{tms.tm_mon:02}-{tms.tm_mday:02}T"
        + f"{tms.tm_hour:02}:{tms.tm_min:02}:{tms.tm_sec:02}{tm_suffix}"
    )


def ntp_timestamp_to_unix_ns(ntp_timestamp: int) -> int:
    """
    Convert a 64-bit NTP timestamp into nanoseconds since the Unix epoch.

    :param ntp_timestamp: NTP timestamp (32 bits for seconds and 32 bits for fractional seconds)
    :return: int: The number of nanoseconds since the Unix epoch.
    """
    # Split the 64-bit NTP timestamp into 32-bit seconds and 32-bit fractional seconds
    ntp_seconds, ntp_fraction = divmod(ntp_timestamp, 1 << 32)  # 0x100000000

    # Convert NTP seconds to Unix seconds by subtracting the epoch difference
    unix_seconds = ntp_seconds - NTP_TO_UNIX_EPOCH_SEC

    # Convert the fractional part to integer nanoseconds
    # nanoseconds = (ntp_fraction * NS_PER_SEC) >> 32
    nanoseconds, remainder = divmod(ntp_fraction * NS_PER_SEC, 1 << 32)  # 0x100000000
    # For use in testing, round up. That way round trip should be consistent.
    if remainder > 0:
        nanoseconds += 1

    # Combine the seconds and fractional nanoseconds
    unix_ns = (unix_seconds * NS_PER_SEC) + nanoseconds
    return unix_ns
