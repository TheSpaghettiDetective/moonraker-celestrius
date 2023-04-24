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
import copy
from configparser import ConfigParser
from datetime import datetime
import requests
import os
import subprocess
from google.cloud import storage
from shapely import geometry

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
        self.temperature_reached = True
        self.object_polygons = []
        self.z_offset_step = None
        self.cur_polygon_idx = None
        self.cur_polygon_linger_start = None
        self.num_polygon_seen = 0
        self.current_z = None
        self.init_z_offset = None

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
                    with self._mutex:
                        printer_stats = copy.deepcopy(self.printer_stats)

                    if printer_stats.get('state') in ['printing',] and printer_stats.get('filename'):
                        if not self.should_collect() or snapshot_num_in_current_print > MAX_SNAPSHOT_NUM_IN_PRINT:
                            continue

                        if data_dirname == None:
                            filename = os.path.basename(printer_stats.get('filename'))
                            if not filename:
                                continue

                            print_id = str(int(datetime.now().timestamp()))
                            data_dirname = os.path.join(os.path.expanduser('~'), 'celestrius-data',f'{filename}.{print_id}')
                            os.makedirs(data_dirname, exist_ok=True)

                            filename_lower = filename.lower()
                            if "celestrius" in filename_lower and "offset" in filename_lower:
                                objs = self.moonrakerconn.find_all_gcode_objects()
                                with self._mutex:
                                    self.num_polygon_seen = 0
                                    self.z_offset_step = None
                                    self.init_z_offset = None
                                    all_objects = objs.get('status', {}).get('exclude_object', {}).get('objects', [])
                                    _logger.debug(f'Found objects: {all_objects}')
                                    for obj in all_objects:
                                        self.object_polygons.append(geometry.Polygon(obj.get('polygon')))

                                    if len(self.object_polygons) > 1:
                                        _logger.warning(f'Found {len(self.object_polygons)} objects. Activating z-offset testing')
                                        self.z_offset_step = int(24/(len(self.object_polygons)-1)) * 0.01
                                        self.init_z_offset = self.current_z_offset

                        ts = datetime.now().timestamp()
                        if ts - last_collect >= SNAPSHOTS_INTERVAL_SECS:
                            last_collect = ts
                            snapshot_num_in_current_print += 1

                            jpg = self.capture_jpeg()
                            with open(f'{data_dirname}/{ts}.jpg', 'wb') as f:
                                f.write(jpg)
                            with open(f'{data_dirname}/{ts}.labels', 'w') as f:
                                with self._mutex:
                                    f.write(f'flow_rate:{self.current_flow_rate}\n')
                                    f.write(f'z_offset:{self.current_z_offset}\n')

                    elif printer_stats.get('state') in ['paused',]:
                        pass
                    else:
                        if data_dirname is not None:
                            data_dirname_to_compress = data_dirname
                            compress_thread = threading.Thread(target=self.compress_and_upload, args=(data_dirname_to_compress,))
                            compress_thread.daemon = True
                            compress_thread.start()

                        if self.init_z_offset is not None:
                            init_z_offset = self.init_z_offset
                            _logger.warning(f'Resetting Z-offset to {init_z_offset}...')
                            z_offset_thread = threading.Thread(target=self.moonrakerconn.api_post, args=('printer/gcode/script',), kwargs=dict(script=f'SET_GCODE_OFFSET Z={init_z_offset} MOVE=1'))
                            z_offset_thread.daemon = True
                            z_offset_thread.start()

                        self.temperature_reached = False
                        self.object_polygons = []
                        self.z_offset_step = None
                        self.init_z_offset = None
                        self.cur_polygon_idx = None
                        self.cur_polygon_linger_start = None
                        self.num_polygon_seen = 0
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
            uploaded_list_file = os.path.join(os.path.expanduser('~'), 'celestrius-data','uploaded_print_list.csv')
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
            blob = bucket.blob(f"{self.config.get('celestrius', 'pilot_email')}/{basename}")
            blob.upload_from_file(f, timeout=None)

    def should_collect(self):
        with self._mutex:
            return self.config.get('celestrius', 'pilot_email') is not None and \
                self.config.get('celestrius', 'enabled', fallback="False").lower() == "true" and self.current_z < 0.5 and \
                    self.temperature_reached

    def on_moonraker_ws_msg(self, msg):
        try:
            print_stats = msg.get('result', {}).get('status', {}).get('print_stats')
            if print_stats:
                with self._mutex:
                    self.printer_stats = print_stats

            gcode_move = msg.get('result', {}).get('status', {}).get('gcode_move')
            if gcode_move:
                with self._mutex:
                    self.current_flow_rate = gcode_move.get('extrude_factor')
                    self.current_z_offset = gcode_move.get('homing_origin', [None, None, None, None])[2]
                    current_position = gcode_move.get('gcode_position', [-1, -1, 100, -1])
                    self.current_z = current_position[2]

                    if self.z_offset_step:
                        point = geometry.Point(current_position[0], current_position[1])
                        cur_polygon_idx = None
                        for idx, poly in enumerate(self.object_polygons):
                            if poly.covers(point):
                                cur_polygon_idx = idx

                        _logger.debug(f'Current polygon {cur_polygon_idx}')
                        if cur_polygon_idx is not None:
                            if self.cur_polygon_idx != cur_polygon_idx:
                                self.cur_polygon_linger_start = datetime.now().timestamp()
                            elif self.cur_polygon_linger_start and (datetime.now().timestamp() - self.cur_polygon_linger_start) > 5:
                                self.cur_polygon_linger_start = None
                                self.num_polygon_seen += 1
                                new_z_offset = round(self.init_z_offset + self.z_offset_step * (self.num_polygon_seen-1), 3)
                                _logger.warning(f'Lingered in {cur_polygon_idx} for longer than 5s. Increasing Z-offset to {new_z_offset}...')
                                z_offset_thread = threading.Thread(target=self.moonrakerconn.api_post, args=('printer/gcode/script',), kwargs=dict(script=f'SET_GCODE_OFFSET Z={new_z_offset} MOVE=1'))
                                z_offset_thread.daemon = True
                                z_offset_thread.start()

                        self.cur_polygon_idx = cur_polygon_idx

            extruder = msg.get('result', {}).get('status', {}).get('extruder')
            if extruder and extruder.get('target', 0) > 150 and extruder.get('temperature', 0) > extruder.get('target') - 2:
                with self._mutex:
                    self.temperature_reached = True

        except Exception as e:
            _logger.exception('Exception occurred: %s', e)

    def on_moonraker_ws_closed(self):
        with self._mutex:
            self.printer_stats = None

    def capture_jpeg(self):
        snapshot_url = self.config.get('nozzle_camera', 'snapshot_url')
        if snapshot_url:
            r = requests.get(snapshot_url, stream=True, timeout=5, verify=False )
            r.raise_for_status()
            jpg = r.content
            return jpg


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-c', '--config', required=True,
        help='Path to config file (cfg)'
    )
    cmd_args = parser.parse_args()
    App(cmd_args).start()
