#!/usr/bin/env python

import site
import socket
from time import time
from collections import defaultdict
import sys
import logging
import struct
try:
    import lifx
except ImportError:
    from . import lifx
if sys.version_info >= (3, 0):
    from configparser import RawConfigParser, NoOptionError, NoSectionError, ParsingError
    from urllib.request import urlopen, HTTPError, HTTPPasswordMgrWithDefaultRealm, HTTPBasicAuthHandler, build_opener, install_opener
    from urllib.error import URLError
    from http.client import BadStatusLine
else:
    from ConfigParser import RawConfigParser, NoOptionError, NoSectionError, ParsingError
    from urllib2 import urlopen, HTTPError, HTTPPasswordMgrWithDefaultRealm, HTTPBasicAuthHandler, build_opener, install_opener, URLError
    from httplib import BadStatusLine
try:
    from argparse import ArgumentParser
except ImportError:
    from optparse import OptionParser
    class ArgumentParser(OptionParser):
        add_argument = OptionParser.add_option

        def parse_args(self):
            return OptionParser.parse_args(self)[0]

log = logging.Logger('')


class ConfigError(Exception):
    pass

class MessageHandler(object):
    class PopBridgeMessageState(object):
        def __init__(self):
            self.power_msg = None
            self.color_msg = None
            self.last_triggered = None # The Pop sends multiple of the same message over several seconds, this removes the duplicates

        def reset(self):
            self.power_msg = None
            self.color_msg = None
            self.last_triggered = None

    def __init__(self, config):
        self.config = config
        self.bridge_states = defaultdict(self.PopBridgeMessageState)
        self.last_trigger = None

    def handle_msg(self, sender, packet):
        bridge_state = self.bridge_states[sender]
        if bridge_state.last_triggered is not None and time() - bridge_state.last_triggered >= 5:
            bridge_state.reset()

        if packet.code == lifx.Message.Light_Get.code:
            bridge_state.reset()
        elif packet.code == lifx.Message.Light_SetPower.code:
            if bridge_state.power_msg is not None and packet != bridge_state.power_msg:
                bridge_state.reset()
            bridge_state.power_msg = packet
        elif packet.code == lifx.Message.Light_SetColor.code:
            if bridge_state.color_msg is not None and packet != bridge_state.color_msg:
                bridge_state.reset()
            bridge_state.color_msg = packet

        if bridge_state.power_msg is None or bridge_state.color_msg is None:
            #The Pop bridge sends a pair of messages: power & color. We need both to know the full state of what it is sending
            return

        if bridge_state.last_triggered is None:
            bridge_state.last_triggered = time()
        elif time() - bridge_state.last_triggered < 15:
            return

        this_trigger = (bridge_state.power_msg, bridge_state.color_msg)
        if self.last_trigger is not None and self.last_trigger == this_trigger:
            #There are multiple Pop bridges and another bridge has already triggered this message
            return

        self.last_trigger = this_trigger
        self.trigger_action(sender, bridge_state.power_msg, bridge_state.color_msg)

    def trigger_action(self, sender, power_msg, color_msg):
        urls = self.config.get_urls(
            power = power_msg.level == lifx.DevicePower.ON,
            hue = color_msg.hue,
            saturation = color_msg.saturation,
            brightness = color_msg.brightness,
            kelvin = color_msg.kelvin
        )

        if len(urls) == 0:
            log.warning('request %dh,%ds,%db,%dk,%s not mapped to a URL',
                color_msg.hue,
                color_msg.saturation,
                color_msg.brightness,
                color_msg.kelvin,
                'on' if power_msg.level == lifx.DevicePower.ON else 'off',
                extra=dict(clientip=sender[0], clientport=sender[1])
            )

        for url in urls:
            try:
                start = time()
                resp = urlopen(url)
                log.info('resp %d in %dms %s' % (resp.code, (time()-start)*1000, url), extra=dict(clientip=sender[0], clientport=sender[1]))
            except HTTPError as err:
                log.error('resp %d in %dms %s' % (err.code, (time()-start)*1000, url), extra=dict(clientip=sender[0], clientport=sender[1]))
            except (BadStatusLine, URLError) as err: #BadStatusLine also includes RemoteDisconnected
                log.error('%s in %dms %s' % (err, (time()-start)*1000, url), extra=dict(clientip=sender[0], clientport=sender[1]))



def server_loop(address, handler):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.bind((address, 56700))
    print('Server started on on %s' % address)
    while True:
        data, address = sock.recvfrom(4096)
        if not config.ip_allowed(address[0]):
            log.debug('recv filtering packet %s', data, extra=dict(clientip=address[0], clientport=address[1]))
            continue
        packet = lifx.Message.decode(data)
        if packet is None:
            log.debug('recv Unknown packet type %s', data, extra=dict(clientip=address[0], clientport=address[1]))
            continue

        log.debug('recv %r (%r)', packet, packet.header, extra=dict(clientip=address[0], clientport=address[1]))

        resp = None
        if packet.code == lifx.Message.Device_GetVersion.code:
            resp = lifx.Message.Device_StateVersion(vendor=1, product=36, version=0)
        elif packet.code == lifx.Message.Light_Get.code:
            resp = lifx.Message.Light_State(hue=0, saturation=655, brightness=65535, kelvin=2500, dim=0, power=65535, label='Pop HTTP', tags=0)
        elif packet.code in (lifx.Message.Light_SetPower.code, lifx.Message.Light_SetColor.code):
            resp = lifx.Message.Device_Acknowledgment()

        if resp is not None:
            log.debug('send %s', str(resp), extra=dict(clientip=address[0], clientport=address[1]))
            sock.sendto(resp.encode(packet.header.target, packet.header.site), address)

        handler.handle_msg(address, packet)



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
            raise ConfigError('Bad IP address format specified for IP filter')


        if config.has_section('switches'):
            for cfg, url in config.items('switches'):
                parsed_cfg = dict(h=None, s=None, b=None, k=None, p=None)
                for param in cfg.lower().split(','):
                    if param in ('on', 'off'):
                        parsed_cfg['p'] = param == 'on'
                    elif param[-1] in parsed_cfg:
                        parsed_cfg[param[-1]] = int(param[:-1])
                    else:
                        raise ConfigError('Unknown parameter %s while parsing %s = %s' % (param[-1], cfg, url))
                self.switches.append((parsed_cfg, url))

        #special config for specific URLs
        url_openers = []
        for top_level_url in config.sections():
            if not top_level_url.startswith('http://') and top_level_url.startswith('https://'):
                continue
            auth = Config._get_val(config, top_level_url, 'auth', None)
            if auth == 'basic':
                username = Config._get_val(config, top_level_url, 'username', None)
                password = Config._get_val(config, top_level_url, 'password', None)

                if username is None:
                    raise ConfigError("'username' parameter is required when using basic HTTP authentication")
                if password is None:
                    raise ConfigError("'password' parameter is required when using basic HTTP authentication")

                password_mgr = HTTPPasswordMgrWithDefaultRealm()
                password_mgr.add_password(None, top_level_url, username, password)
                url_openers.append(HTTPBasicAuthHandler(password_mgr))
        install_opener(build_opener(*url_openers))

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

if __name__ == '__main__':
    parser = ArgumentParser(description='Make a fake LIFX light to allow the Logitech pop to send web requests')
    parser.add_argument('-v', dest='verbosity', action='count', default=0, help='increase verbosity level')
    parser.add_argument('--config', dest='config', metavar='FILE', default='config.ini', help='path to the configuration INI file to use')
    args = parser.parse_args()

    ch = logging.StreamHandler()
    ch.setLevel([logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG][min(args.verbosity, 3)])
    formatter = logging.Formatter('%(asctime)-15s %(clientip)s %(message)s')
    ch.setFormatter(formatter)
    log.addHandler(ch)


    try:
        config = Config(args.config)
    except ConfigError as err:
        print(str(err))
        sys.exit(-2)
    except ParsingError as err:
        print(str(err))
        sys.exit(-1)

    server_loop(config.interface, MessageHandler(config))
