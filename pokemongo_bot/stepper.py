# -*- coding: utf-8 -*-

import os
import json
import time
import pprint

from math import ceil
from s2sphere import CellId, LatLng
from google.protobuf.internal import encoder

from human_behaviour import sleep, random_lat_long_delta
from cell_workers.utils import distance, i2f, format_time

from pgoapi.utilities import f2i, h2f
import logger


class Stepper(object):
    def __init__(self, bot):
        self.bot = bot
        self.api = bot.api
        self.config = bot.config

        self.pos = 1
        self.x = 0
        self.y = 0
        self.dx = 0
        self.dy = -1
        self.steplimit = self.config.max_steps
        self.steplimit2 = self.steplimit**2
        self.origin_lat = self.bot.position[0]
        self.origin_lon = self.bot.position[1]

    def take_step(self):
        position = (self.origin_lat, self.origin_lon, 0.0)

        self.api.set_position(*position)
        for step in range(self.steplimit2):
            # starting at 0 index
            logger.log('[#] Scanning area for objects ({} / {})'.format(
                (step + 1), self.steplimit**2))
            if self.config.debug:
                logger.log(
                    'steplimit: {} x: {} y: {} pos: {} dx: {} dy {}'.format(
                        self.steplimit2, self.x, self.y, self.pos, self.dx,
                        self.dy))
            # Scan location math
            if -self.steplimit2 / 2 < self.x <= self.steplimit2 / 2 and -self.steplimit2 / 2 < self.y <= self.steplimit2 / 2:
                position = (self.x * 0.0025 + self.origin_lat,
                            self.y * 0.0025 + self.origin_lon, 0)
                if self.config.walk > 0:
                    self._walk_to(self.config.walk, *position)
                else:
                    self.api.set_position(*position)
                print('[#] {}'.format(position))
            if self.x == self.y or self.x < 0 and self.x == -self.y or self.x > 0 and self.x == 1 - self.y:
                (self.dx, self.dy) = (-self.dy, self.dx)

            (self.x, self.y) = (self.x + self.dx, self.y + self.dy)

            self._work_at_position(position[0], position[1], position[2], True, True)
            sleep(5)

    def _walk_to(self, speed, lat, lng, alt):
        dist = distance(
            self.api._position_lat, self.api._position_lng, lat, lng)
        steps = (dist + 0.0) / (speed + 0.0)  # may be rational number
        intSteps = int(steps)
        residuum = steps - intSteps
        logger.log('[#] Walking from ' + str((self.api._position_lat,
                                              self.api._position_lng)) + " to " + str(str((lat, lng))) +
                   " for approx. " + str(format_time(ceil(steps))))
        if steps != 0:
            dLat = (lat - self.api._position_lat) / steps
            dLng = (lng - self.api._position_lng) / steps
            last_pos_lat = self.api._position_lat
            last_pos_lng = self.api._position_lng
            for i in range(intSteps):
                cLat = self.api._position_lat + \
                    dLat + random_lat_long_delta()
                cLng = self.api._position_lng + \
                    dLng + random_lat_long_delta()
                delta_distance = distance(last_pos_lat, last_pos_lng, cLat, cLng)
                self.api.set_position(cLat, cLng, alt)
                self.bot.heartbeat()
                sleep(1)  # sleep one second plus a random delta
                #if i != intSteps - 1 and i % 3 != 0:
                #    continue;
                #logger.log('[#] Walking {} m'.format(delta_distance))
                if delta_distance < self.bot.MAX_DISTANCE_FORT_IS_REACHABLE / 7:
                    continue

                last_pos_lat = self.api._position_lat
                last_pos_lng = self.api._position_lng
                self._work_at_position(
                    self.api._position_lat, self.api._position_lng,
                alt, False)

            self.api.set_position(lat, lng, alt)
            self.bot.heartbeat()
            logger.log("[#] Finished walking")

    def _work_at_position(self, lat, lng, alt, pokemon_only=False, wander=False):
        position = (lat, lng, alt)
        cells = self.bot.get_map_objects(lat, lng, alt);

        user_cells_data = 'data/cells-%s.json' % (self.config.username)
        if os.path.isfile(user_cells_data):
            with open(user_cells_data, 'w') as outfile:
                json.dump(cells, outfile)

        self.bot.work_on_cell(cells, position, pokemon_only, wander)

    def _encode(self, cellid):
        output = []
        encoder._VarintEncoder()(output.append, cellid)
        return ''.join(output)
