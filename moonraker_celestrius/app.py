from __future__ import absolute_import
from typing import Optional, Dict, List, Tuple
from numbers import Number
import argparse
import dataclasses
import time
import logging
import threading
import collections
import queue
import json
import re
import signal
import backoff
import pathlib
from configparser import ConfigParser
from .logger import setup_logging
from .moonraker_conn import MoonrakerConn, Event

_logger = logging.getLogger('celestrius')


class App(object):

    def __init__(self, cmd_args):
        self.config = ConfigParser()
        self.config.read(cmd_args.config)
        setup_logging(dict(self.config['logging']))

        self.moonrakerconn = None
        self.current_flow_rate = 1.0
        self.current_z_offset = None

    def start(self):
        self.moonrakerconn = MoonrakerConn(dict(self.config['moonraker']), self.on_moonraker_ws_msg)

        thread = threading.Thread(target=self.moonrakerconn.start)
        thread.daemon = True
        thread.start()

        SNAPSHOTS_INTERVAL_SECS = 0.4
        MAX_SNAPSHOT_NUM_IN_PRINT = int(60.0 / SNAPSHOTS_INTERVAL_SECS * 30)  # limit sampling to 30 minutes
        last_collect = 0.0
        data_dirname = None
        snapshot_num_in_current_print = 0
        printer_status = None

        time.sleep(10000)
        while True:
            try:
                if self._printer.get_state_id() in ['PRINTING', 'PAUSING', 'RESUMING', ]:
                    if not self.should_collect() or snapshot_num_in_current_print > MAX_SNAPSHOT_NUM_IN_PRINT:
                        continue

                    if data_dirname == None:
                        filename = self._printer.get_current_job().get('file', {}).get('name')
                        if not filename:
                            continue

                        print_id = str(int(datetime.now().timestamp()))
                        data_dirname = os.path.join(self._data_folder, f'{filename}.{print_id}')
                        os.makedirs(data_dirname, exist_ok=True)

                    ts = datetime.now().timestamp()
                    if ts - last_collect >= SNAPSHOTS_INTERVAL_SECS:
                        last_collect = ts
                        snapshot_num_in_current_print += 1

                        jpg = self.capture_jpeg()
                        with open(f'{data_dirname}/{ts}.jpg', 'wb') as f:
                            f.write(jpg)
                        with open(f'{data_dirname}/{ts}.labels', 'w') as f:
                            with self._mutex:
                                f.write(f'flow_rate:{self.current_flow_rate}')

                elif self._printer.get_state_id() in ['PAUSED']:
                    pass
                else:
                    if data_dirname is not None:
                        data_dirname_to_compress = data_dirname
                        compress_thread = Thread(target=self.compress_and_upload, args=(data_dirname_to_compress,))
                        compress_thread.daemon = True
                        compress_thread.start()

                    self.have_seen_m109 = False
                    self.have_seen_gcode_after_m109 = False
                    snapshot_num_in_current_print = 0
                    data_dirname = None

            except Exception as e:
                _logger.exception('Exception occurred: %s', e)

            time.sleep(0.02)

    def should_collect(self):
        return self.config.get('celestrius', 'pilot_email') is not None

    def on_moonraker_ws_msg(self, msg):
        self.printer_status = msg.get('result', {})

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-c', '--config', required=True,
        help='Path to config file (cfg)'
    )
    cmd_args = parser.parse_args()
    App(cmd_args).start()
