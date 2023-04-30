import struct
import yaml
from base64 import b64encode
from collections import namedtuple
from socket import inet_aton


class ConfigError(Exception):
    pass

SwitchConfig = namedtuple("SwitchConfig", "url method body headers")
EndpointConfig = namedtuple("EndpointConfig", "method headers")


def format_template(template, hue, saturation, brightness, kelvin, power):
    return template.format(onoff='on' if power else 'off', hue=hue, saturation=saturation, brightness=brightness, kelvin=kelvin)


def _basic_auth_header(username, password):
    base64string = b64encode(f'{username}:{password}')
    return "Basic %s" % base64string


def _parse_cidr(cidr_address):
    ip, *rest = cidr_address.split('/')
    try:
        ip = struct.unpack('>L', inet_aton(ip))[0]
    except (struct.error, OSError):
        raise ConfigError(f'Could not parse {ip} as a valid IPv4 address')
    if not rest:
        net_mask = 32
    elif len(rest) == 1:
        try:
            net_mask = int(rest[0])
        except ValueError:
            raise ConfigError(f'Subnet mask {rest[0]} is not an integer')
        if net_mask > 32 or net_mask < 0:
            raise ConfigError(f'Subnet mask {net_mask} must be in the range of 0-32')
    else:
        raise ConfigError('Bad IP address format specified for IP filter')
    return ip, net_mask


def _parse_switch_filter(filter):
    parsed_filter = dict(h=None, s=None, b=None, k=None, p=None)
    for param in filter.lower().split(','):
        if param in ('on', 'off'):
            parsed_filter['p'] = param == 'on'
        elif param[-1] in parsed_filter:
            parsed_filter[param[-1]] = int(param[:-1])
        else:
            raise ConfigError(f'Unknown parameter {param[-1]} while parsing switch filter {filter!r}')
    return parsed_filter


def _parse_target_url(target, filter):
    if isinstance(target, str):
        target = dict(url=target)
    elif not isinstance(target, dict):
        raise ConfigError(f'Expected a single URL or mapping with parameters for filter {filter!r}, but got {type(target).__name__}')
    url = target.pop("url", None)
    if url is None:
        raise ConfigError(f'Section for switch filter {filter!r} is missing the `url` parameter')
    body = target.pop("body", None)
    method = target.pop("method", None)
    headers = target.pop("headers", {})
    if target:
        raise ConfigError(f'Section for switch filter {filter!r} contains unknown parameters {",".join(target)}')
    return SwitchConfig(url, method, body, headers)


def _parse_endpoint_config(config, endpoint):
    if not isinstance(config, dict):
        raise ConfigError(f'Expected a mapping with parameters for endpoint {endpoint!r} config, but got {type(config).__name__}')
    
    headers = config.pop("headers", {})
    method = config.pop("method", None)
    
    auth = config.pop("auth", None)
    if auth == "basic":
        try:
            username = config.pop("username")
            password = config.pop("password")
        except KeyError as err:
            raise ConfigError(f'HTTP basic auth config for endpoint {endpoint!r} is missing the {err.args[0]} parameter')
        headers['Authorization'] = _basic_auth_header(username, password)
    elif auth == "bearer":
        try:
            token = config.pop("token")
        except KeyError as err:
            raise ConfigError(f'HTTP bearer auth config for endpoint {endpoint!r} is missing the {err.args[0]} parameter')
        headers['Authorization'] = f'Bearer {token}'
    else:
        raise ConfigError(f'Unknown auth type {auth} for endpoint {endpoint!r}. Expecting 1 of basic or bearer')

    if config:
        raise ConfigError(f'Section endpoint {endpoint} contains unknown parameters {",".join(config)}')
    return EndpointConfig(method, headers)


class Config:
    def __init__(self, filename):
        with open(filename, 'r') as cfg_file:
            config = yaml.load(cfg_file, yaml.SafeLoader)

        default_url = config.get('default_url')
        self.default_url = _parse_target_url(default_url, 'default_url') if default_url is not None else None
        self.interface = config.get('interface', '0.0.0.0')
        self.ip_filter = _parse_cidr(config.get('ip_filter', '0.0.0.0/0'))
        self.switches = [(_parse_switch_filter(f), _parse_target_url(url, f)) for f, url in config.get('switches', {}).items()]
        self.endpoints = [(e, _parse_endpoint_config(cfg, e)) for e, cfg in config.get('endpoints', {}).items()]

    def is_ip_allowed(self, ip):
        ip = struct.unpack('>L', inet_aton(ip))[0]
        net_mask = ((1 << self.ip_filter[1]) - 1) << (32-self.ip_filter[1])
        return ip & net_mask == self.ip_filter[0] & net_mask

    def get_target_for_switch(self, hue, saturation, brightness, kelvin, power):
        targets = []

        match = dict(h=hue, s=saturation, b=brightness, k=kelvin, p=power)
        for filter, target in self.switches:
            this_match = dict((k, None if filter[k] is None else v) for k, v in match.items())
            if this_match == filter:
                targets.append(target)

        if not targets and self.default_url is not None:
            targets.append(self.default_url)

        return [
            SwitchConfig(format_template(t.url, hue, saturation, brightness, kelvin, power), t.method, t.body, t.headers)
            for t in targets
        ]
    
    def get_endpoint_for_url(self, url):
        matches = [(e, c) for (e, c) in self.endpoints if url.startswith(e)]
        if not matches:
            return None
        return sorted(matches, key=lambda e: len(e[0]), reverse=True)[0][1]
