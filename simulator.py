'''
This script sends a fake power on message for `25486h,5397s,32768b,3612k,on` acting as a fake pop switch for testing
'''

import socket
try:
    import lifx
except ImportError:
    from . import lifx

def send(msg):
    sock.sendto(msg.encode(b'\x00'*8, b'\x00'*6), ('127.0.0.1', 56700))

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
send(lifx.Message.Light_SetColor(stream=0, hue=25486, saturation=5397, brightness=32768, kelvin=3612, duration=1000))
send(lifx.Message.Light_SetPower(level=lifx.DevicePower.ON, duration=1000))
