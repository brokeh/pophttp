#!/usr/bin/env python

import socket
from time import time
from collections import defaultdict
import sys
import logging
try:
    import lifx
    from config import Config, ConfigError, format_template
except ImportError:
    from . import lifx
    from .config import Config, ConfigError, format_template
import yaml
from urllib.request import urlopen, HTTPError, Request
from urllib.error import URLError
from http.client import BadStatusLine
from argparse import ArgumentParser


log = logging.Logger('')


class MessageHandler:
    class PopBridgeMessageState:
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
        if self.last_trigger is not None and self.last_trigger[1] == this_trigger and self.last_trigger[0] != sender:
            #There are multiple Pop bridges and another bridge has already triggered this message
            return

        self.last_trigger = (sender, this_trigger)
        self.trigger_action(sender, bridge_state.power_msg, bridge_state.color_msg)

    def trigger_action(self, sender, power_msg, color_msg):
        targets = self.config.get_target_for_switch(
            power = power_msg.level == lifx.DevicePower.ON,
            hue = color_msg.hue,
            saturation = color_msg.saturation,
            brightness = color_msg.brightness,
            kelvin = color_msg.kelvin
        )

        if not targets:
            log.warning('request %dh,%ds,%db,%dk,%s not mapped to a URL',
                color_msg.hue,
                color_msg.saturation,
                color_msg.brightness,
                color_msg.kelvin,
                'on' if power_msg.level == lifx.DevicePower.ON else 'off',
                extra=dict(clientip=sender[0], clientport=sender[1])
            )

        for target in targets:
            endpoint = self.config.get_endpoint_for_url(target.url)
            method = target.method
            headers = target.headers
            body = None
            if endpoint is not None:
                method = endpoint.method or method
                headers = dict(endpoint.headers)
                headers.update(target.headers)
                body = format_template(
                    target.body,
                    power = power_msg.level == lifx.DevicePower.ON,
                    hue = color_msg.hue,
                    saturation = color_msg.saturation,
                    brightness = color_msg.brightness,
                    kelvin = color_msg.kelvin
                )
            try:
                start = time()
                req = Request(target.url, data=body.encode('utf-8'), headers=headers, method=method)
                with urlopen(req) as resp:
                    log.info('resp %d in %dms %s' % (resp.code, (time()-start)*1000, target.url), extra=dict(clientip=sender[0], clientport=sender[1]))
            except HTTPError as err:
                log.error('resp %d in %dms %s' % (err.code, (time()-start)*1000, target.url), extra=dict(clientip=sender[0], clientport=sender[1]))
            except (BadStatusLine, URLError) as err: #BadStatusLine also includes RemoteDisconnected
                log.error('%s in %dms %s' % (err, (time()-start)*1000, target.url), extra=dict(clientip=sender[0], clientport=sender[1]))


def server_loop(address, handler):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((address, 56700))
    print('Server started on on %s' % address)
    while True:
        data, address = sock.recvfrom(4096)
        if not config.is_ip_allowed(address[0]):
            log.debug('recv filtering packet %r', data, extra=dict(clientip=address[0], clientport=address[1]))
            continue
        try:
            packet = lifx.Message.decode(data)
        except Exception as exc:
            log.debug('recv unable to decode packet %r: %r', data, exc, extra=dict(clientip=address[0], clientport=address[1]))
            continue

        if packet is None:
            log.debug('recv Unknown packet type %r', data, extra=dict(clientip=address[0], clientport=address[1]))
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


if __name__ == '__main__':
    parser = ArgumentParser(description='Make a fake LIFX light to allow the Logitech pop to send web requests')
    parser.add_argument('-v', dest='verbosity', action='count', default=0, help='increase verbosity level')
    parser.add_argument('--config', dest='config', metavar='FILE', default='config.yml', help='path to the configuration YAML file to use')
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
    except yaml.parser.ParserError as err:
        print(str(err))
        sys.exit(-1)

    server_loop(config.interface, MessageHandler(config))
