from typing import Optional, Dict, List, Tuple
from numbers import Number
import dataclasses
import re
import queue
import threading
import requests  # type: ignore
import logging
import time
import backoff
import json
import bson
import websocket
from random import randrange
from collections import deque, OrderedDict

from .ws import WebSocketClient, WebSocketConnectionException


_logger = logging.getLogger('celestrius.moonraker_conn')
_ignore_pattern=re.compile(r'"method": "notify_proc_stat_update"')

class MoonrakerConn:
    flow_step_timeout_msecs = 2000
    ready_timeout_msecs = 60000

    def __init__(self, config, on_message, on_close):
        self.on_message = on_message
        self.on_close = on_close
        self.config = config
        self.klippy_ready = threading.Event()  # Based on https://moonraker.readthedocs.io/en/latest/web_api/#websocket-setup
        self.ws_message_queue_to_moonraker = queue.Queue(maxsize=16)
        self.api_key = None
        self.conn = None


    def http_address(self):
        if not self.config.get('host') or not self.config.get('port'):
            return None
        return f"http://{self.config.get('host')}:{self.config.get('port')}"

    def ws_url(self):
        return f"ws://{self.config.get('host')}:{self.config.get('port')}/websocket"

    ## REST API part

    def api_get(self, mr_method, timeout=5, raise_for_status=True, **params):
        url = f'{self.http_address()}/{mr_method.replace(".", "/")}'
        _logger.debug(f'GET {url}')

        headers = {'X-Api-Key': self.api_key} if self.api_key else {}
        resp = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=timeout,
        )

        if raise_for_status:
            resp.raise_for_status()

        return resp.json().get('result')

    def api_post(self, mr_method, multipart_filename=None, multipart_fileobj=None, **post_params):
        url = f'{self.http_address()}/{mr_method.replace(".", "/")}'
        _logger.debug(f'POST {url}')

        headers = {'X-Api-Key': self.api_key} if self.api_key else {}
        files={'file': (multipart_filename, multipart_fileobj, 'application/octet-stream')} if multipart_filename and multipart_fileobj else None
        resp = requests.post(
            url,
            headers=headers,
            data=post_params,
            files=files,
        )
        resp.raise_for_status()
        return resp.json()

    @backoff.on_exception(backoff.expo, Exception, max_value=60)
    def ensure_api_key(self):
        _logger.warning('api key is unset, trying to fetch one')
        self.api_key = self.api_get('access/api_key', raise_for_status=True)

    @backoff.on_exception(backoff.expo, Exception, max_value=60)
    def get_server_info(self):
        return self.api_get('server/info')

    @backoff.on_exception(backoff.expo, Exception, max_value=60)
    @backoff.on_predicate(backoff.expo, max_value=60)
    def wait_for_klippy_ready(self):
        return self.get_server_info().get("klippy_state") == 'ready'

    @backoff.on_exception(backoff.expo, Exception, max_value=60)
    def find_all_heaters(self):
        data = self.api_get('printer/objects/query', raise_for_status=True, heaters='') # heaters='' -> 'query?heaters=' by the behavior in requests
        if 'heaters' in data.get('status', {}):
            return data['status']['heaters']
        else:
            return []

    @backoff.on_exception(backoff.expo, Exception, max_value=60)
    def find_most_recent_job(self):
        data = self.api_get('server/history/list', raise_for_status=True, order='desc', limit=1)
        return (data.get('jobs', [None]) or [None])[0]


    ## WebSocket part

    def start(self) -> None:

        thread = threading.Thread(target=self.message_to_moonraker_loop)
        thread.daemon = True
        thread.start()

        while True:
            try:
                if self.klippy_ready.wait():
                    self.request_status_update()

            except Exception as e:
                _logger.exception(e)

            time.sleep(30)

    def message_to_moonraker_loop(self):

        def on_mr_ws_open(ws):
            _logger.info('connection is open')

            self.wait_for_klippy_ready()

            self.klippy_ready.set()

            self.request_subscribe()

        def on_mr_ws_close(ws, **kwargs):
            self.klippy_ready.clear()
            self.on_close()
            self.request_status_update()  # Trigger a re-connection to Moonraker

        def on_message(ws, raw):
            if ( _ignore_pattern.search(raw) is not None ):
                return

            data = json.loads(raw)
            _logger.debug(f'Received from Moonraker: {data}')

            'notify_status_update',
            if data.get('method') == 'notify_status_update':
                self.request_status_update()
                return

            self.on_message(data)

        self.request_status_update()  # "Seed" a request in ws_message_queue_to_moonraker to trigger the initial connection to Moonraker

        while True:
            try:
                data = self.ws_message_queue_to_moonraker.get()

                if not self.conn or not self.conn.connected():
                    self.ensure_api_key()

                    if not self.conn or not self.conn.connected():
                        header=['X-Api-Key: {}'.format(self.api_key), ]
                        self.conn = WebSocketClient(
                                    url=self.ws_url(),
                                    header=header,
                                    on_ws_msg=on_message,
                                    on_ws_open=on_mr_ws_open,
                                    on_ws_close=on_mr_ws_close,)

                        self.klippy_ready.wait()
                        _logger.info('Klippy ready')

                _logger.debug("Sending to Moonraker: \n{}".format(data))
                self.conn.send(json.dumps(data, default=str))
            except Exception as e:
                _logger.exception(e)


    def close(self):
        self.shutdown = True
        if not self.conn:
            self.conn.close()

    def jsonrpc_request(self, method, params=None):
        next_id = randrange(100000)
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "id": next_id
        }

        if params:
            payload['params'] = params

        try:
            self.ws_message_queue_to_moonraker.put_nowait(payload)
        except queue.Full:
            _logger.warning("Moonraker message queue is full, msg dropped")


    def request_subscribe(self, objects=None):
        objects = objects if objects else {
            'print_stats': ('state', 'message', 'filename'),
            'webhooks': ('state', 'state_message'),
            'history': None,
        }
        return self.jsonrpc_request('printer.objects.subscribe', params=dict(objects=objects))

    def request_status_update(self, objects=None):
        if objects is None:
            objects = {
                "webhooks": None,
                "print_stats": None,
            }

        self.jsonrpc_request('printer.objects.query', params=dict(objects=objects))

@dataclasses.dataclass
class Event:
    name: str
    data: Dict
    sender: Optional[str] = None
