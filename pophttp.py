#!/usr/bin/env python

import site
import socket
from time import time
import sys
import logging
import struct
import lifx
if sys.version_info >= (3, 0):
    from configparser import RawConfigParser, NoOptionError, NoSectionError
    from urllib.request import urlopen, HTTPError
else:
    from ConfigParser import RawConfigParser, NoOptionError, NoSectionError
    from urllib2 import urlopen, HTTPError
try:
    from argparse import ArgumentParser
except ImportError:
    from optparse import OptionParser
    class ArgumentParser(OptionParser):
        add_argument = OptionParser.add_option

        def parse_args(self):
            return OptionParser.parse_args(self)[0]


class MessageHandler(object):
    def __init__(self):
        self.power_msg = None
        self.color_msg = None
        self.last_triggered = None # The Pop sends multiple of the same message over several seconds, this removes the duplicates

    def reset(self):
        self.power_msg = None
        self.color_msg = None
        self.last_triggered = None

    def handle_msg(self, sender, packet):
        if self.last_triggered is not None and time() - self.last_triggered >= 5:
            self.reset()

        if packet.code == lifx.Message.Light_Get.code:
            self.reset()
        elif packet.code == lifx.Message.Light_SetPower.code:
            if self.power_msg is not None and packet != self.power_msg:
                self.reset()
            self.power_msg = packet
        elif packet.code == lifx.Message.Light_SetColor.code:
            if self.color_msg is not None and packet != self.color_msg:
                self.reset()
            self.color_msg = packet

        if self.power_msg is None or self.color_msg is None:
            return

        if self.last_triggered is None:
            self.last_triggered = time()
        elif time() - self.last_triggered < 15:
            return

        urls = config.get_urls(
            power = self.power_msg.level == lifx.DevicePower.ON,
            hue = self.color_msg.hue,
            saturation = self.color_msg.saturation,
            brightness = self.color_msg.brightness,
            kelvin = self.color_msg.kelvin
        )

        if len(urls) == 0:
            log.warning('request %dh,%ds,%db,%dk,%s not mapped to a URL',
                self.color_msg.hue,
                self.color_msg.saturation,
                self.color_msg.brightness,
                self.color_msg.kelvin,
                'on' if self.power_msg.level == lifx.DevicePower.ON else 'off',
                extra=dict(clientip=sender[0], clientport=sender[1])
            )

        for url in urls:
            try:
                resp = urlopen(url)
                resp_code = resp.code
            except HTTPError as err:
                resp_code = err.code
            log.info('resp %d %s' % (resp_code, url), extra=dict(clientip=sender[0], clientport=sender[1]))



def server_loop(address, handler):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.bind((address, 56700))
    while True:
        data, address = sock.recvfrom(4096)
        if not config.ip_allowed(address[0]):
            log.debug('recv filtering packet %s', data, extra=dict(clientip=address[0], clientport=address[1]))
            continue
        packet = lifx.Message.decode(data)
        if packet is None:
            log.debug('recv Unknown packet type %s', data, extra=dict(clientip=address[0], clientport=address[1]))
            continue

        log.debug('recv %r', packet, extra=dict(clientip=address[0], clientport=address[1]))
        
        resp = None
        if packet.code == lifx.Message.Device_GetVersion.code:
            resp = lifx.Message.Device_StateVersion(vendor=1, product=36, version=0)
        elif packet.code == lifx.Message.Light_Get.code:
            resp = lifx.Message.Light_State(hue=0, saturation=655, brightness=65535, kelvin=2500, dim=0, power=65535, label='Pop HTTP', tags=0)
        elif packet.code in (lifx.Message.Light_SetPower.code, lifx.Message.Light_SetColor.code):
            resp = lifx.Message.Device_Acknowledgment()

        handler.handle_msg(address, packet)
            
        if resp is not None:
            log.debug('send %s', str(resp), extra=dict(clientip=address[0], clientport=address[1]))
            sock.sendto(resp.encode(packet.header.target, packet.header.site), address)



class Config(object):
    def __init__(self, filename):
        config = RawConfigParser()
        config.read(filename)

        self.switches = []
        self.default_url = Config._get_val(config, 'settings', 'default_url', None)
        self.interface = Config._get_val(config, 'settings', 'interface', '0.0.0.0')
        self.ip_filter = Config._get_val(config, 'settings', 'ip_filter', '0.0.0.0/0').split('/')

        self.ip_filter[0] = struct.unpack('>L', socket.inet_aton(self.ip_filter[0]))[0]
        if len(self.ip_filter) == 1:
            self.ip_filter.append(32)
        elif len(self.ip_filter) == 2:
            self.ip_filter[1] = int(self.ip_filter[1])
        else:
            raise Exception('Bad IP address format specified for IP filter')


        if config.has_section('switches'):
            for cfg, url in config.items('switches'):
                parsed_cfg = dict(h=None, s=None, b=None, k=None, p=None)
                for param in cfg.lower().split(','):
                    if param in ('on', 'off'):
                        parsed_cfg['p'] = param == 'on'
                    elif param[-1] in parsed_cfg:
                        parsed_cfg[param[-1]] = int(param[:-1])
                    else:
                        raise Exception('Unknown parameter %s while parsing %s = %s' % (param[-1], cfg, url))
                self.switches.append((parsed_cfg, url))

    @staticmethod
    def _get_val(config, section, option, default):
        try:
            if isinstance(default, bool):
                return config.getboolean(section, option)
            elif isinstance(default, float):
                return config.getfloat(section, option)
            elif isinstance(default, int):
                return config.getint(section, option)
            else:
                return config.get(section, option)
        except (NoOptionError, NoSectionError):
            return default

    def ip_allowed(self, ip):
        ip = struct.unpack('>L', socket.inet_aton(ip))[0]
        net_mask = ((1 << self.ip_filter[1]) - 1) << (32-self.ip_filter[1])
        return ip & net_mask == self.ip_filter[0] & net_mask

    def get_urls(self, hue, saturation, brightness, kelvin, power):
        url_templates = []

        match = dict(h=hue, s=saturation, b=brightness, k=kelvin, p=power)
        for filter, url_template in self.switches:
            this_match = dict((k, None if filter[k] is None else v) for k, v in match.items())
            if this_match == filter:
                url_templates.append(url_template)

        if not url_templates and self.default_url is not None:
            url_templates.append(self.default_url)

        return [t.format(onoff='on' if power else 'off', hue=hue, saturation=saturation, brightness=brightness, kelvin=kelvin) for t in url_templates]

parser = ArgumentParser(description='Make a fake LIFX light to allow the Logitech pop to send web requests')
parser.add_argument('-v', dest='verbosity', action='count', default=0, help='increase verbosity level')
parser.add_argument('--config', dest='config', metavar='FILE', default='config.ini', help='path to the configuration INI file to use')
args = parser.parse_args()

log = logging.Logger('')
ch = logging.StreamHandler()
ch.setLevel([logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG][min(args.verbosity, 3)])
formatter = logging.Formatter('%(asctime)-15s %(clientip)s %(message)s')
ch.setFormatter(formatter)
log.addHandler(ch)


config = Config(args.config)
server_loop(config.interface, MessageHandler())
