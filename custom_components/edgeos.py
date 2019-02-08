"""
This component provides support for Home Automation Manager (HAM).
For more details about this component, please refer to the documentation at
https://home-assistant.io/components/edgeos/
"""
import sys
import logging
import websocket
import ssl
import requests
from time import sleep
from datetime import datetime, timedelta
import json
from urllib.parse import urlparse
import threading
import urllib3

import voluptuous as vol

from homeassistant.helpers import config_validation as cv
from homeassistant.const import (CONF_SSL, CONF_HOST, CONF_USERNAME, CONF_PASSWORD, EVENT_HOMEASSISTANT_START,
                                 EVENT_HOMEASSISTANT_STOP, STATE_OFF, STATE_ON, ATTR_FRIENDLY_NAME, HTTP_OK,
                                 STATE_UNKNOWN, ATTR_NAME, ATTR_UNIT_OF_MEASUREMENT, EVENT_TIME_CHANGED)

from homeassistant.helpers.event import track_time_interval
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.util import slugify

DOMAIN = 'edgeos'
DATA_EDGEOS = 'edgeos_ham'
SIGNAL_UPDATE_EDGEOS = "edgeos_update"
DEFAULT_NAME = 'EdgeOS'

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)

NOTIFICATION_ID = 'edgeos_notification'
NOTIFICATION_TITLE = 'EdgeOS Setup'

CONF_CERT_FILE = 'cert_file'
CONF_MONITORED_INTERFACES = 'monitored_interfaces'
CONF_MONITORED_DEVICES = 'monitored_devices'

API_URL_TEMPLATE = '{}://{}'
WEBSOCKET_URL_TEMPLATE = 'wss://{}/ws/stats'

EDGEOS_API_URL = '{}/api/edge/{}.json'
EDGEOS_API_GET = 'get'
EDGEOS_API_DATA = 'data'
EDGEOS_API_HEARTBREAT = 'heartbeat'

COOKIE_PHPSESSID = 'PHPSESSID'
COOKIE_AS_STR_TEMPLATE = '{}={}'

TRUE_STR = 'true'
FALSE_STR = 'false'

LINK_UP = 'up'

INTERFACES_MAIN_MAP = {
    LINK_UP: {ATTR_NAME: 'Connected', ATTR_UNIT_OF_MEASUREMENT: 'Connectivity'},
    'speed': {ATTR_NAME: 'Link Speed (Mbps)'},
    'duplex': {ATTR_NAME: 'Duplex'},
    'mac': {ATTR_NAME: 'MAC'},
}

INTERFACES_STATS_MAP = {
    # 'rx_packets': {ATTR_NAME: 'Packets (Received)'},
    # 'tx_packets': {ATTR_NAME: 'Packets (Sent)'},
    'rx_bytes': {ATTR_NAME: 'Bytes (Received)', ATTR_UNIT_OF_MEASUREMENT: 'Bytes'},
    'tx_bytes': {ATTR_NAME: 'Bytes (Sent)', ATTR_UNIT_OF_MEASUREMENT: 'Bytes'},
    # 'rx_errors': {ATTR_NAME: 'Errors (Received)'},
    # 'tx_errors': {ATTR_NAME: 'Errors (Sent)'},
    # 'rx_dropped': {ATTR_NAME: 'Dropped Packets (Received)'},
    # 'tx_dropped': {ATTR_NAME: 'Dropped Packets (Sent)'},
    'rx_bps': {ATTR_NAME: 'Bps (Received)', ATTR_UNIT_OF_MEASUREMENT: 'Bps'},
    'tx_bps': {ATTR_NAME: 'Bps (Sent)', ATTR_UNIT_OF_MEASUREMENT: 'Bps'},
    # 'multicast': {ATTR_NAME: 'Multicast'}
}

DEVICE_SERVICES_STATS_MAP = {
    'rx_bytes': {ATTR_NAME: 'Bytes (Received)', ATTR_UNIT_OF_MEASUREMENT: 'Bytes'},
    'tx_bytes': {ATTR_NAME: 'Bytes (Sent)', ATTR_UNIT_OF_MEASUREMENT: 'Bytes'},
    'rx_rate': {ATTR_NAME: 'Bps (Received)', ATTR_UNIT_OF_MEASUREMENT: 'Bps'},
    'tx_rate': {ATTR_NAME: 'Bps (Sent)', ATTR_UNIT_OF_MEASUREMENT: 'Bps'},
}

INTERFACES_STATS = 'stats'

INTERFACES_KEY = 'interfaces'
SYSTEM_STATS_KEY = 'system-stats'
EXPORT_KEY = 'export'
STATIC_DEVICES_KEY = 'static-devices'
DHCP_LEASES_KEY = 'dhcp-leases'
DHCP_STATS_KEY = 'dhcp_stats'
ROUTES_KEY = 'routes'
SYS_INFO_KEY = 'sys_info'
NUM_ROUTES_KEY = 'num-routes'
USERS_KEY = 'users'
DISCOVER_KEY = 'discover'
UNKOWN_DEVICES_KEY = 'unknown-devices'

SYSTEM_STATS_ITEMS = ['cpu', 'mem', 'uptime']
DISCOVER_DEVICE_ITEMS = ['hostname', 'product', 'uptime', 'fwversion', 'system_status']

DEVICE_LIST = 'devices'
ADDRESS_LIST = 'addresses'
ADDRESS_IPV4 = 'ipv4'
ADDRESS_HWADDR = 'hwaddr'

SERVICE = 'service'
DHCP_SERVER = 'dhcp-server'
SHARED_NETWORK_NAME = 'shared-network-name'
SUBNET = 'subnet'
STATIC_MAPPING = 'static-mapping'
IP_ADDRESS = 'ip-address'
MAC_ADDRESS = 'mac-address'
IP = 'ip'
MAC = 'mac'
CONNECTED = 'connected'

DEFAULT_USERNAME = 'ubnt'

EMPTY_LAST_VALID = datetime.fromtimestamp(100000)

RESPONSE_SUCCESS_KEY = 'success'
RESPONSE_ERROR_KEY = 'error'
RESPONSE_OUTPUT = 'output'
RESPONSE_FAILURE_CODE = '0'

HEARTBEAT_MAX_AGE = 15

API_URL_DATA_TEMPLATE = '{}?data={}'
API_URL_HEARTBEAT_TEMPLATE = '{}?t={}'

PROTOCOL_UNSECURED = 'http'
PROTOCOL_SECURED = 'https'

WS_TOPIC_NAME = 'name'
WS_TOPIC_UNSUBSCRIBE = 'UNSUBSCRIBE'
WS_TOPIC_SUBSCRIBE = 'SUBSCRIBE'
WS_SESSION_ID = 'SESSION_ID'
WS_PAYLOAD_ERROR = 'payload_error'
WS_PAYLOAD_EXCEPTION = 'exception'

SSL_OPTIONS_CERT_REQS = 'cert_reqs'
SSL_OPTIONS_SSL_VERSION = 'ssl_version'
SSL_OPTIONS_CA_CERTS = 'ca_certs'

ARG_SSL_OPTIONS = 'sslopt'
ARG_ORIGIN = 'origin'

ENTITY_ID_INTERFACE_BINARY_SENSOR = 'binary_sensor.edgeos_interface_{}'
ENTITY_ID_INTERFACE_SENSOR = 'sensor.edgeos_interface_{}_{}'

ENTITY_ID_DEVICE_BINARY_SENSOR = 'binary_sensor.edgeos_device_{}'
ENTITY_ID_DEVICE_SENSOR = 'sensor.edgeos_device_{}_{}'
ENTITY_ID_UNKNOWN_DEVICES = 'sensor.edgeos_unknown_devices'

ATTR_DEVICE_CLASS = 'device_class'
DEVICE_CLASS_CONNECTIVITY = 'connectivity'

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_USERNAME, default=DEFAULT_USERNAME): cv.string,
        vol.Optional(CONF_SSL, default=False): cv.boolean,
        vol.Optional(CONF_CERT_FILE, default=None): cv.string,
        vol.Optional(CONF_MONITORED_INTERFACES, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_MONITORED_DEVICES, default=[]): vol.All(cv.ensure_list, [cv.string])
    }),
}, extra=vol.ALLOW_EXTRA)


def setup(hass, config):
    """Set up an Home Automation Manager component."""
    try:
        conf = config[DOMAIN]

        is_ssl = conf.get(CONF_SSL)
        host = conf.get(CONF_HOST)
        username = conf.get(CONF_USERNAME)
        password = conf.get(CONF_PASSWORD)
        cert_file = conf.get(CONF_CERT_FILE)
        monitored_interfaces = conf.get(CONF_MONITORED_INTERFACES)
        monitored_devices = conf.get(CONF_MONITORED_DEVICES)

        data = EdgeOS(hass, host, is_ssl, username, password, cert_file, monitored_interfaces, monitored_devices)

        hass.data[DATA_EDGEOS] = data

        return True
    except Exception as ex:
        _LOGGER.error('Error while initializing EdgeOS, exception: {}'.format(str(ex)))

        hass.components.persistent_notification.create(
            'Error: {}<br />'
            'You will need to restart hass after fixing.'
            ''.format(ex),
            title=NOTIFICATION_TITLE,
            notification_id=NOTIFICATION_ID)

        return False


class EdgeOS(requests.Session):
    def __init__(self, hass, host, is_ssl, username, password, cert_file, monitored_interfaces, monitored_devices):
        requests.Session.__init__(self)

        credentials = {
            CONF_USERNAME: username,
            CONF_PASSWORD: password
        }

        self._scan_interval = SCAN_INTERVAL
        self._hass = hass
        self._cert_file = cert_file
        self._monitored_interfaces = monitored_interfaces
        self._monitored_devices = monitored_devices
        self._is_ssl = is_ssl

        protocol = PROTOCOL_UNSECURED
        if is_ssl:
            protocol = PROTOCOL_SECURED

        self._last_valid = EMPTY_LAST_VALID
        self._edgeos_url = API_URL_TEMPLATE.format(protocol, host)

        self._edgeos_data = {}

        self._special_handlers = None
        self._ws_handlers = None
        self._subscribed_topics = []

        self.load_ws_handlers()
        self.load_special_handlers()

        ''' This function turns off InsecureRequestWarnings '''
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        def edgeos_initialize(event_time):
            _LOGGER.info('Initialization begun at {}'.format(event_time))
            if self.login(credentials):
                self.update_edgeos_data()

                self._ws_connection = EdgeOSWebSocket(self._edgeos_url, self.cookies,
                                                      self._subscribed_topics, self.ws_handler,
                                                      self._cert_file, is_ssl)
                self._ws_connection.initialize()

        def edgeos_stop(event_time):
            _LOGGER.info('Stop begun at {}'.format(event_time))
            self._ws_connection.stop()

        def edgeos_refresh(event_time):
            _LOGGER.debug('Refresh begun at {}'.format(event_time))
            self.update_edgeos_data()

        track_time_interval(hass, edgeos_refresh, self._scan_interval)

        hass.bus.listen_once(EVENT_HOMEASSISTANT_START, edgeos_initialize)
        hass.bus.listen_once(EVENT_HOMEASSISTANT_STOP, edgeos_stop)

    def ws_handler(self, payload=None):
        if payload is not None:
            for key in payload:
                if key in self._ws_handlers:
                    data = payload[key]
                    handler = self._ws_handlers[key]

                    handler(data)

    def heartbeat(self, max_age=HEARTBEAT_MAX_AGE):
        try:
            ts = datetime.now()
            current_invocation = datetime.now() - self._last_valid
            if current_invocation > timedelta(seconds=max_age):
                current_ts = str(int(ts.timestamp()))

                heartbeat_req_url = self.get_edgeos_api_endpoint(EDGEOS_API_HEARTBREAT)
                heartbeat_req_full_url = API_URL_HEARTBEAT_TEMPLATE.format(heartbeat_req_url, current_ts)

                if self._is_ssl:
                    heartbeat_response = self.get(heartbeat_req_full_url, verify=False)
                else:
                    heartbeat_response = self.get(heartbeat_req_full_url)

                heartbeat_response.raise_for_status()

                self._last_valid = ts
        except Exception as ex:
            _LOGGER.error('Failed to perform heartbeat, Error: {}'.format(str(ex)))

    def login(self, credentials):
        result = False

        try:
            if self._is_ssl:
                login_response = self.post(self._edgeos_url, data=credentials, verify=False)
            else:
                login_response = self.post(self._edgeos_url, data=credentials)

            login_response.raise_for_status()

            _LOGGER.debug("Sleeping 5 to make sure the session id is in the filesystem")
            sleep(5)

            result = True
        except Exception as ex:
            _LOGGER.error('Failed to login due to: {}'.format(str(ex)))

        return result

    def handle_static_devices(self):
        try:
            result = {}

            previous_result = self.get_devices()
            get_req_url = self.get_edgeos_api_endpoint(EDGEOS_API_GET)

            if self._is_ssl:
                get_result = self.get(get_req_url, verify=False)
            else:
                get_result = self.get(get_req_url)

            if get_result.status_code == HTTP_OK:
                result_json = get_result.json()

                if RESPONSE_SUCCESS_KEY in result_json:
                    success_key = str(result_json[RESPONSE_SUCCESS_KEY]).lower()

                    if success_key == TRUE_STR:
                        if EDGEOS_API_GET.upper() in result_json:
                            get_data = result_json[EDGEOS_API_GET.upper()]

                            if SERVICE in get_data:
                                service_data = get_data[SERVICE]

                                if DHCP_SERVER in service_data:
                                    dhcp_server_data = service_data[DHCP_SERVER]

                                    if SHARED_NETWORK_NAME in dhcp_server_data:
                                        shared_network_name_data = dhcp_server_data[SHARED_NETWORK_NAME]

                                        for shared_network_name_key in shared_network_name_data:
                                            dhcp_network_allocation = shared_network_name_data[shared_network_name_key]

                                            if SUBNET in dhcp_network_allocation:
                                                subnet = dhcp_network_allocation[SUBNET]

                                                for subnet_mask_key in subnet:
                                                    subnet_mask = subnet[subnet_mask_key]

                                                    if STATIC_MAPPING in subnet_mask:
                                                        static_mapping = subnet_mask[STATIC_MAPPING]

                                                        for host_name in static_mapping:
                                                            host_data = static_mapping[host_name]
                                                            host_ip = host_data[IP_ADDRESS]
                                                            host_mac = host_data[MAC_ADDRESS]

                                                            data = {
                                                                IP: host_ip,
                                                                MAC: host_mac
                                                            }

                                                            if host_name in previous_result:
                                                                previous_host_data = previous_result[host_name]

                                                                for previous_key in previous_host_data:
                                                                    data[previous_key] = previous_host_data[previous_key]

                                                            result[host_name] = data

                                                            self.create_device_sensor(host_name, data)
                    else:
                        _LOGGER.error('Failed, {}'.format(result_json[RESPONSE_ERROR_KEY]))
                else:
                    _LOGGER.error('Invalid response, not contain success status')

            else:
                _LOGGER.error('HTTP Status code returned: {}'.format(get_result.status_code))

            self.update_data(STATIC_DEVICES_KEY, result)
        except Exception as ex:
            _LOGGER.error('Failed to load {}, Error: {}'.format(STATIC_DEVICES_KEY, str(ex)))

    def handle_interfaces(self, data):
        try:
            result = self.get_edgeos_data(INTERFACES_KEY)

            for interface in data:
                interface_data = None

                if interface in data:
                    interface_data = data[interface]

                interface_data_item = self.get_interface_data(interface_data)

                self.create_interface_sensor(interface, interface_data_item)

                result[interface] = interface_data_item

            self.update_data(INTERFACES_KEY, result)
        except Exception as ex:
            _LOGGER.error('Failed to load {}, Error: {}'.format(INTERFACES_KEY, str(ex)))

    @staticmethod
    def get_interface_data(interface_data):
        result = {}

        for item in interface_data:
            data = interface_data[item]

            if ADDRESS_LIST == item:
                result[item] = ', '.join(data)

            elif INTERFACES_STATS == item:
                for stats_item in INTERFACES_STATS_MAP:
                    result[stats_item] = data[stats_item]

            else:
                if item in INTERFACES_MAIN_MAP:
                    result[item] = data

        return result

    def handle_system_stats(self, data):
        try:
            for item in data:
                entity_id = 'sensor.edgeos_system_{}'.format(item)
                state = data[item]

                self._hass.states.set(entity_id, state)

            self.update_data(SYSTEM_STATS_KEY, data)
        except Exception as ex:
            _LOGGER.error('Failed to load {}, Error: {}'.format(SYSTEM_STATS_KEY, str(ex)))

    def handle_discover(self, data):
        try:
            result = self.get_edgeos_data(DISCOVER_KEY)

            devices_data = data[DEVICE_LIST]

            for device_data in devices_data:
                for key in DISCOVER_DEVICE_ITEMS:
                    device_data_item = device_data[key]

                    if key == ADDRESS_LIST:
                        discover_addresses = {}

                        for address in device_data_item:
                            hwaddr = address[ADDRESS_HWADDR]
                            ipv4 = address[ADDRESS_IPV4]

                            discover_addresses[hwaddr] = ipv4

                        result[key] = discover_addresses
                    else:
                        result[key] = device_data_item

            self.update_data(DISCOVER_KEY, result)
        except Exception as ex:
            _LOGGER.error('Failed to load {}, Error: {}'.format(DISCOVER_KEY, str(ex)))

    def _data(self, item):
        data_req_url = self.get_edgeos_api_endpoint(EDGEOS_API_DATA)
        data_req_full_url = API_URL_DATA_TEMPLATE.format(data_req_url, item.replace('-', '_'))

        if self._is_ssl:
            data_response = self.get(data_req_full_url, verify=False)
        else:
            data_response = self.get(data_req_full_url)

        data_response.raise_for_status()

        try:
            data = data_response.json()
            if str(data[RESPONSE_SUCCESS_KEY]) == RESPONSE_FAILURE_CODE:
                error = data[RESPONSE_ERROR_KEY]

                _LOGGER.error('Failed to load {}, Reason: {}'.format(item, error))
                result = None
            else:
                result = data[RESPONSE_OUTPUT]
        except Exception as ex:
            _LOGGER.error('Failed to load {}, Error: {}'.format(item, str(ex)))
            result = None

        return result

    def handle_export(self, data):
        try:
            _LOGGER.debug(EXPORT_KEY)

            result = self.get_devices()

            for hostname in result:
                host_data = result[hostname]

                if IP in host_data:
                    host_data_ip = host_data[IP]

                    if host_data_ip in data:

                        host_data_traffic = {}
                        for item in DEVICE_SERVICES_STATS_MAP:
                            host_data_traffic[item] = int(0)

                        host_data[CONNECTED] = TRUE_STR
                        device_data = data[host_data_ip]

                        for service in device_data:
                            service_data = device_data[service]
                            for item in service_data:
                                current_value = int(host_data_traffic[item])
                                service_data_item_value = int(service_data[item])

                                host_data_traffic[item] = current_value + service_data_item_value

                        for traffic_data_item in host_data_traffic:
                            host_data[traffic_data_item] = host_data_traffic[traffic_data_item]

                        del data[host_data_ip]
                    else:
                        host_data[CONNECTED] = FALSE_STR

                self.create_device_sensor(hostname, host_data)

            unknown_devices = []
            for host_ip in data:
                unknown_devices.append(host_ip)

            unknown_devices_count = len(unknown_devices)
            self.create_unknown_device_sensor(', '.join(unknown_devices), unknown_devices_count)

            self.update_data(STATIC_DEVICES_KEY, result)
            self.update_data(UNKOWN_DEVICES_KEY, unknown_devices)
        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno
            _LOGGER.error('Failed to load {}, Error: {}, Line: {}'.format(EXPORT_KEY, str(ex), line_number))

    @staticmethod
    def handle_payload_error(data):
        _LOGGER.error('Invalid payload received, Payload: {}'.format(data))

    def get_edgeos_data(self, storage):
        data = {}

        if storage in self._edgeos_data:
            data = self._edgeos_data[storage]

        return data

    def update_edgeos_data(self):
        self.heartbeat()

        self._special_handlers[STATIC_DEVICES_KEY]()

    def update_data(self, storage, data):
        self._edgeos_data[storage] = data

        if storage in self._special_handlers:
            _LOGGER.debug('Data changed for {}, New data: {}'.format(storage, data))

        dispatcher_send(self._hass, SIGNAL_UPDATE_EDGEOS)

    def load_ws_handlers(self):
        ws_handlers = {
            EXPORT_KEY: self.handle_export,
            INTERFACES_KEY: self.handle_interfaces,
            SYSTEM_STATS_KEY: self.handle_system_stats,
            DISCOVER_KEY: self.handle_discover,
            WS_PAYLOAD_ERROR: self.handle_payload_error
        }

        for handler_name in ws_handlers:
            self._subscribed_topics.append(handler_name)

        self._ws_handlers = ws_handlers

    def load_special_handlers(self):
        special_handlers = {
            STATIC_DEVICES_KEY: self.handle_static_devices
        }

        self._special_handlers = special_handlers

    def get_edgeos_api_endpoint(self, controller):
        url = EDGEOS_API_URL.format(self._edgeos_url, controller)

        return url

    def get_devices(self):
        result = self.get_edgeos_data(STATIC_DEVICES_KEY)

        return result

    def get_device(self, hostname):
        devices = self.get_devices()

        device = None
        if hostname in devices:
            device = devices[hostname]

        return device

    def get_device_name(self, hostname):
        device = self.get_device(hostname)

        name = hostname
        if device is not None:
            name = '{} {}'.format(DEFAULT_NAME, hostname)

        return name

    def get_device_mac(self, hostname):
        device = self.get_device(hostname)

        mac = None
        if device is not None and MAC in device:
            mac = device[MAC]

        return mac

    def is_device_online(self, hostname):
        device = self.get_device(hostname)

        is_online = False
        if device is not None and CONNECTED in device and device[CONNECTED] == TRUE_STR:
            is_online = True

        return is_online

    def create_interface_sensor(self, key, data):
        try:
            if key in self._monitored_interfaces:
                attributes = {}

                for data_item_key in data:
                    value = data[data_item_key]
                    attr = self.get_interface_attributes(data_item_key)

                    if attr is None:
                        attributes[data_item_key] = value
                    else:
                        name = attr[ATTR_NAME]

                        if ATTR_UNIT_OF_MEASUREMENT not in attr:
                            attributes[name] = value

                for data_item_key in data:
                    attr = self.get_interface_attributes(data_item_key)

                    if attr is not None and ATTR_UNIT_OF_MEASUREMENT in attr:
                        value = data[data_item_key]
                        name = attr[ATTR_NAME]
                        unit = attr[ATTR_UNIT_OF_MEASUREMENT]

                        entity_id = ENTITY_ID_INTERFACE_SENSOR.format(slugify(key), slugify(name))

                        device_attributes = {
                            ATTR_UNIT_OF_MEASUREMENT: unit,
                            ATTR_FRIENDLY_NAME: 'EdgeOS {} {}'.format(key, name)
                        }

                        if data_item_key == LINK_UP:
                            device_attributes[ATTR_DEVICE_CLASS] = DEVICE_CLASS_CONNECTIVITY

                            for attr_key in attributes:
                                device_attributes[attr_key] = attributes[attr_key]

                            entity_id = ENTITY_ID_INTERFACE_BINARY_SENSOR.format(slugify(key))

                            if str(value).lower() == TRUE_STR:
                                state = STATE_ON
                            else:
                                state = STATE_OFF
                        else:
                            state = value

                        self._hass.states.set(entity_id, state, device_attributes)

        except Exception as ex:
            exc_type, exc_obj, tb = sys.exc_info()
            line_number = tb.tb_lineno

            _LOGGER.error(
                'Failed to create interface sensor {} with the following data: {}, Error: {}, Line: {}'.format(key, str(
                    data), str(ex), line_number))

    def create_device_sensor(self, key, data):
        try:
            if key in self._monitored_devices:
                attributes = {}

                for data_item_key in data:
                    value = data[data_item_key]
                    attr = self.get_device_attributes(data_item_key)

                    if attr is None:
                        attributes[data_item_key] = value
                    else:
                        name = attr[ATTR_NAME]

                        if ATTR_UNIT_OF_MEASUREMENT not in attr:
                            attributes[name] = value

                for data_item_key in data:
                    attr = self.get_device_attributes(data_item_key)
                    value = data[data_item_key]
                    entity_id = None
                    state = None
                    device_attributes = None

                    if attr is not None and ATTR_UNIT_OF_MEASUREMENT in attr:

                        name = attr[ATTR_NAME]
                        unit = attr[ATTR_UNIT_OF_MEASUREMENT]

                        entity_id = ENTITY_ID_DEVICE_SENSOR.format(slugify(key), slugify(name))

                        device_attributes = {
                            ATTR_UNIT_OF_MEASUREMENT: unit,
                            ATTR_FRIENDLY_NAME: 'EdgeOS {} {}'.format(key, name)
                        }

                        state = value
                    elif data_item_key == CONNECTED:
                        device_attributes = {
                            ATTR_DEVICE_CLASS: DEVICE_CLASS_CONNECTIVITY
                        }

                        for attr_key in attributes:
                            device_attributes[attr_key] = attributes[attr_key]

                        entity_id = ENTITY_ID_DEVICE_BINARY_SENSOR.format(slugify(key))

                        if str(value).lower() == TRUE_STR:
                            state = STATE_ON
                        else:
                            state = STATE_OFF

                        current_entity = self._hass.states.get(entity_id)

                        attributes[EVENT_TIME_CHANGED] = datetime.now()

                        if current_entity is not None and current_entity.state == state:
                            entity_attributes = current_entity.attributes

                            if EVENT_TIME_CHANGED in entity_attributes:
                                attributes[EVENT_TIME_CHANGED] = entity_attributes[EVENT_TIME_CHANGED]

                    if entity_id is not None:
                        self._hass.states.set(entity_id, state, device_attributes)

        except Exception as ex:
            _LOGGER.error(
                'Failed to create device sensor {} with the following data: {}, Error: {}'.format(key, str(data),
                                                                                                  str(ex)))

    def create_unknown_device_sensor(self, devices, devices_count):
        try:
            entity_id = ENTITY_ID_UNKNOWN_DEVICES
            state = devices_count
            attributes = {
                STATE_UNKNOWN: devices
            }

            self._hass.states.set(entity_id, state, attributes)
        except Exception as ex:
            _LOGGER.error(
                'Failed to create unknown device sensor with the following data: {}, Error: {}'.format(str(devices),
                                                                                                       str(ex)))

    @staticmethod
    def get_device_attributes(key):
        result = None

        if key in DEVICE_SERVICES_STATS_MAP:
            result = DEVICE_SERVICES_STATS_MAP[key]

        return result

    @staticmethod
    def get_interface_attributes(key):
        result = None

        if key in INTERFACES_MAIN_MAP:
            result = INTERFACES_MAIN_MAP[key]

        if key in INTERFACES_STATS_MAP:
            result = INTERFACES_STATS_MAP[key]

        return result


class EdgeOSWebSocket:

    def __init__(self, edgeos_url, cookies, subscribed_topics, consumer_handler, cert_file, is_ssl):
        self._subscribed_topics = subscribed_topics
        self._edgeos_url = edgeos_url
        self._consumer_handler = consumer_handler
        self._cert_file = cert_file
        self._cookies = cookies
        self._ssl = is_ssl

        self._delayed_messages = []

        self._subscription_data = None
        self._is_alive = False
        self._session_id = None
        self._ws = None
        self._ws_url = None
        self._thread = None

        self._timeout = SCAN_INTERVAL.seconds

        url = urlparse(self._edgeos_url)
        self._ws_url = WEBSOCKET_URL_TEMPLATE.format(url.netloc)

        self._session_id = self._cookies[COOKIE_PHPSESSID]
        self._cookies_as_str = '; '.join([COOKIE_AS_STR_TEMPLATE.format(*x) for x in self._cookies.items()])

        topics_to_subscribe = [{WS_TOPIC_NAME: x} for x in self._subscribed_topics]
        topics_to_unsubscribe = []

        data = {
            WS_TOPIC_SUBSCRIBE: topics_to_subscribe,
            WS_TOPIC_UNSUBSCRIBE: topics_to_unsubscribe,
            WS_SESSION_ID: self._session_id
        }

        subscription_content = json.dumps(data, separators=(',', ':'))
        subscription_content_length = len(subscription_content)
        subscription_data = "{}\n{}".format(subscription_content_length, subscription_content)

        self._subscription_data = subscription_data

        if self._ssl:
            # if self._cert_file is None:
            self._ssl_options = {
                SSL_OPTIONS_CERT_REQS: ssl.CERT_NONE,
            }
        # else:
        #    self._ssl_options = {
        #        SSL_OPTIONS_CERT_REQS: ssl.CERT_REQUIRED,
        #        SSL_OPTIONS_SSL_VERSION: ssl.PROTOCOL_TLSv1_2,
        #        SSL_OPTIONS_CA_CERTS: self._cert_file
        #    }
        else:
            self._ssl_options = {}

        self._consumer_handler()

    def on_cont_message(self, message, continue_flag):
        _LOGGER.debug('{} - {}'.format(continue_flag, message[:30]))

    def on_message(self, message):
        data_arr = message.split('\n')

        content_length_str = data_arr[0]
        payload = None

        if content_length_str.isdigit():
            content_length = int(content_length_str)
            payload_str = message[len(content_length_str) + 1:]

            if content_length == len(payload_str):
                payload = self.extract_payload(payload_str, message)
            else:
                self._delayed_messages.append(payload_str)

        elif len(self._delayed_messages) == 1:
            self._delayed_messages.append(message)

            payload_str = ''.join(self._delayed_messages)

            payload = self.extract_payload(payload_str, message, message)

        try:
            if payload is None:
                _LOGGER.debug('Payload is empty')
            elif WS_PAYLOAD_ERROR in payload:
                _LOGGER.warning('Unable to parse payload: {}'.format(payload))
            else:
                self._consumer_handler(payload)
        except Exception as ex:
            _LOGGER.error('Failed to invoke handler, Payload: {}, Error: {}'.format(payload, str(ex)))

    def extract_payload(self, payload_json, original_message, delayed_message=None):
        try:
            result = json.loads(payload_json)
            self._delayed_messages = []
        except Exception as ex:
            if delayed_message is None:
                delayed_message = payload_json

            self._delayed_messages.append(delayed_message)
            result = {
                WS_PAYLOAD_ERROR: original_message,
                WS_PAYLOAD_EXCEPTION: str(ex)
            }

        return result

    def on_error(self, error):
        try:
            if 'Connection is already closed' in str(error):
                self.initialize()
            else:
                _LOGGER.warning('Connection error, Description: {}'.format(error))
        except Exception as ex:
            _LOGGER.error('Failed to handle error: {}, Exception: {}'.format(error, str(ex)))

    def on_close(self):
        _LOGGER.info("### closed ###")

        self.initialize()

    def on_open(self):
        _LOGGER.debug("Subscribing")
        self._ws.send(self._subscription_data)
        _LOGGER.info("Subscribed")

    def initialize(self):
        try:
            if self._ws is not None:
                self.stop()

            self._ws = websocket.WebSocketApp(self._ws_url,
                                              on_message=self.on_message,
                                              on_error=self.on_error,
                                              on_close=self.on_close,
                                              on_open=self.on_open,
                                              cookie=self._cookies_as_str)

            kwargs = {
                ARG_SSL_OPTIONS: self._ssl_options,
                ARG_ORIGIN: self._edgeos_url
            }

            self._thread = threading.Thread(target=self._ws.run_forever, kwargs=kwargs)
            self._thread.daemon = True
            self._thread._running = True
            self._thread.start()

        except Exception as ex:
            _LOGGER.error('Failed, {}'.format(str(ex)))

    def stop(self):
        try:
            _LOGGER.info("Stopping")

            if self._ws is not None:
                self._ws.close()
                self._ws = None

            if self._thread is not None:
                self._thread._running = False
                self._thread = None

            _LOGGER.info("Stopped")
        except Exception as ex:
            _LOGGER.error('Failed to stop, Error: {}'.format(str(ex)))
