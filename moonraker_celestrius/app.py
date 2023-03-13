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
import psutil
import shutil
import pathlib
from configparser import ConfigParser
import datetime
from .logger import setup_logging
from .moonraker_conn import MoonrakerConn, Event

_logger = logging.getLogger('celestrius')


class App(object):

    def __init__(self, cmd_args):
        self.config = ConfigParser()
        self.config.read(cmd_args.config)
        setup_logging(dict(self.config['logging']))

        self._mutex = threading.RLock()
        self.moonrakerconn = None
        self.current_flow_rate = 1.0
        self.current_z_offset = None
        self.printer_stats = None

    def start(self):
        self.moonrakerconn = MoonrakerConn(dict(self.config['moonraker']), self.on_moonraker_ws_msg, self.on_moonraker_ws_closed)

        thread = threading.Thread(target=self.moonrakerconn.start)
        thread.daemon = True
        thread.start()

        SNAPSHOTS_INTERVAL_SECS = 0.4
        MAX_SNAPSHOT_NUM_IN_PRINT = int(60.0 / SNAPSHOTS_INTERVAL_SECS * 30)  # limit sampling to 30 minutes
        last_collect = 0.0
        data_dirname = None
        snapshot_num_in_current_print = 0

        while True:
            try:
                if self.printer_stats:
                    if self.printer_stats.get('state') in ['printing',] and self.printer_stats.get('filename'):
                        if not self.should_collect() or snapshot_num_in_current_print > MAX_SNAPSHOT_NUM_IN_PRINT:
                            continue

                        if data_dirname == None:
                            filename = self.printer_stats.get('filename')
                            if not filename:
                                continue

                            print_id = str(int(datetime.now().timestamp()))
                            data_dirname = os.path.join(os.path.expanduser('~'), f'{filename}.{print_id}')
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

                    elif self.printer_stats.get('state') in ['paused',]:
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

    def compress_and_upload(self, data_dirname):
        try:
            parent_dir_name = os.path.dirname((data_dirname))
            basename = os.path.basename((data_dirname))
            tarball_filename = data_dirname + '.tgz'
            _logger.info('Compressing ' + basename)
            proc = psutil.Popen(['tar', '-C', parent_dir_name, '-zcf', tarball_filename, basename], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            proc.nice(10)
            returncode = proc.wait()
            (stdoutdata, stderrdata) = proc.communicate()
            msg = 'RETURN:\n{}\nSTDOUT:\n{}\nSTDERR:\n{}\n'.format(returncode, stdoutdata, stderrdata)
            _logger.debug(msg)
            _logger.info('Deleting ' + basename)
            shutil.rmtree(data_dirname, ignore_errors=True)
            _logger.info('Uploading ' + tarball_filename)
            self.upload_to_data_bucket(tarball_filename)
            _logger.info('Deleting ' + tarball_filename)
            os.remove(tarball_filename)
            uploaded_list_file = os.path.join(os.path.expanduser('~'), 'uploaded_print_list.csv')
            with open(uploaded_list_file, 'a') as file:
                now = datetime.now().strftime('%A, %B %d, %Y')
                line = f'"{os.path.basename(data_dirname)}","{now}"\n'
                file.write(line)

        except Exception as e:
            _logger.exception('Exception occurred: %s', e)

    def upload_to_data_bucket(self, filename):
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts', 'celestrius-data-collector.json')

        client = storage.Client()
        bucket = client.bucket('celestrius-data-collection')
        basename = os.path.basename((filename))
        with open(filename, 'rb') as f:
            blob = bucket.blob(f'{self._settings.get(["pilot_email"])}/{basename}')
            blob.upload_from_file(f, timeout=None)

    def should_collect(self):
        return self.config.get('celestrius', 'pilot_email') is not None

    def on_moonraker_ws_msg(self, msg):
        print_stats = msg.get('result', {}).get('status', {}).get('print_stats')
        if print_stats:
            with self._mutex:
                self.printer_stats = print_stats


    def on_moonraker_ws_closed(self):
        with self._mutex:
            self.printer_stats = None

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-c', '--config', required=True,
        help='Path to config file (cfg)'
    )
    cmd_args = parser.parse_args()
    App(cmd_args).start()
