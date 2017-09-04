import struct
from collections import namedtuple
from random import randint
import sys

BROADCAST_TARGET = bytearray(8)
BROADCAST_SITE = bytearray(6)

class DevicePower(object):
    OFF = 0
    ON = 0xFFFF

class PayloadDef(object):
    def __init__(self, name, members, fmt):
        self.members = members.split(' ')
        self.type = namedtuple(name, members)
        self.fmt = '<' + fmt
        self.length = struct.calcsize(self.fmt)

    def encode(self, members):
        if sys.version_info > (3, 0):
            members = [m.encode('utf-8') if isinstance(m, str) else m for m in members]
        return struct.pack(self.fmt, *members)

    def decode(self, payload):
        members = struct.unpack(self.fmt, payload)
        if sys.version_info > (3, 0):
            def try_decode(val):
                if isinstance(val, bytes):
                    try:
                        return val.decode('utf-8')
                    except UnicodeDecodeError:
                        pass
                return val
            members = [try_decode(m) for m in members]
        return self.type(*members)

class Packet(object):
    source = randint(1, 0xFFFFFFFF) #a random one per session
    sequence_number = 0

    def __init__(self, pkt_def, *args, **kwargs):
        self.pkt_def = pkt_def
        self.header = kwargs.get('header')
        if 'header' in kwargs:
            del kwargs['header']
        if self.header is None or args or kwargs:
            #constructing from initializer list, rather than for decoding
            self.payload = pkt_def.payload_fmt.type(*args, **kwargs)

    def encode(self, target, site):
        target_vs = target
        site_vs = site
        if sys.version_info < (3, 0):
            target_vs = str(target_vs)
            site_vs = str(site_vs)

        self.sequence_number += 1
        self.header = self.pkt_def.header_fmt.type(
            size = self.pkt_def.header_fmt.length + self.pkt_def.payload_fmt.length,
            protocol_and_flags = 0x800 | (0x2000 if target == BROADCAST_TARGET else 0),
            source = self.source,
            target = target_vs,
            site = site_vs,
            acknowledge = 0,
            sequence = self.sequence_number & 0xFF,
            timestamp = 0,
            code = self.pkt_def.code,
            reserved = 0
        )
        return self.pkt_def.header_fmt.encode(self.header) + self.pkt_def.payload_fmt.encode(self.payload)

    def __getattr__(self, attr):
        return getattr(self.payload, attr)

    def __eq__(self, other):
        if not isinstance(other, Packet) or other.code != self.code:
            return False
        return self.payload == other.payload

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return repr(self.payload)

    code = property(lambda self: self.pkt_def.code)

class PacketDef(object):
    header_fmt = PayloadDef('header', 'size protocol_and_flags source target site acknowledge sequence timestamp code reserved', 'HHI8s6sBBQHH')

    def __init__(self, code, name, members='', fmt=''):
        self.code = code
        self.payload_fmt = PayloadDef(name, members, fmt)

    def __call__(self, *args, **kwargs):
        return Packet(self, *args, **kwargs)

    def decode(self, data, header):
        pkt = Packet(self, header=header)
        pkt.header = self.header_fmt.decode(data[:self.header_fmt.length])
        pkt.payload = self.payload_fmt.decode(data[self.header_fmt.length:])
        return pkt

class Message(object):
    Device_GetVersion = PacketDef(32, 'Device_GetVersion')
    Device_StateVersion = PacketDef(33, 'Device_StateVersion', 'vendor product version', 'III')
    Device_Acknowledgment = PacketDef(45, 'Device_Acknowledgment')
    Light_Get = PacketDef(101, 'Light_Get')
    Light_SetColor = PacketDef(102, 'Light_SetColor', 'stream hue saturation brightness kelvin duration', 'BHHHHI')
    Light_State = PacketDef(107, 'Light_State', 'hue saturation brightness kelvin dim power label tags', 'HHHHhH32sQ')
    Light_SetPower = PacketDef(117, 'Light_SetPower', 'level duration', 'HI')

    @classmethod
    def decode(cls, data):
        header = PacketDef.header_fmt.decode(data[:PacketDef.header_fmt.length])
        for member_name in dir(Message):
            member = getattr(Message, member_name)
            if isinstance(member, PacketDef) and member.code == header.code:
                return member.decode(data, header)
        return None
