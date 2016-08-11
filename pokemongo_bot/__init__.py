# -*- coding: utf-8 -*-

import logging
import googlemaps
import json
import random
import threading
import datetime
import sys
import yaml
import logger
import re
from pgoapi import PGoApi
from cell_workers import PokemonCatchWorker, SeenFortWorker, MoveToFortWorker, InitialTransferWorker, EvolveAllWorker, PokemonTransferWorker, IncubateEggsWorker, CollectLevelUpReward,NicknamePokemon
from cell_workers.utils import distance
from stepper import Stepper
from geopy.geocoders import GoogleV3
from math import radians, sqrt, sin, cos, atan2
from item_list import Item
from math import ceil
from s2sphere import CellId, LatLng
from pgoapi.utilities import f2i, h2f

import os
import time
import pprint

from math import ceil
from s2sphere import CellId, LatLng
from google.protobuf.internal import encoder

from human_behaviour import sleep, random_lat_long_delta
from cell_workers.utils import distance, i2f, format_time

from pgoapi.utilities import f2i, h2f


class PokemonGoBot(object):
    def __init__(self, config):
        self.config = config
        self.pokemon_list = json.load(open('data/pokemon.json'))
        self.item_list = json.load(open('data/items.json'))
        self.latest_inventory = None
        self.MAX_DISTANCE_FORT_IS_REACHABLE = 40
        self.last_forts = [None] * 5
        self.team = 0         # 0: UNSET; 1: RED; 2. BLUE; 3. YELLOW
        self.last_cell_forts = None

    def start(self):
        self._setup_logging()
        self._setup_api()
        self.stepper = Stepper(self)
        random.seed()

    def take_step(self):
        self.stepper.take_step()

    def __get_cellid(self, lat, long, radius=10):
        origin = CellId.from_lat_lng(LatLng.from_degrees(lat, long)).parent(15)
        walk = [origin.id()]

        # 10 before and 10 after
        next = origin.next()
        prev = origin.prev()
        for i in range(radius):
            walk.append(prev.id())
            walk.append(next.id())
            next = next.next()
            prev = prev.prev()
        return sorted(walk)

    def get_map_objects(self, lat, lng, alt):
        map_cells = []
        cellid= self.__get_cellid(lat, lng)
        timestamp = [0, ] * len(cellid)
        response_dict = self.api.get_map_objects(latitude=f2i(lat),
                                                 longitude=f2i(lng),
                                                 since_timestamp_ms=timestamp,
                                                 cell_id=cellid)

        if response_dict and 'responses' in response_dict:
            if 'GET_MAP_OBJECTS' in response_dict['responses']:
                if 'map_cells' in response_dict['responses'][
                        'GET_MAP_OBJECTS']:
                    user_web_location = 'web/location-%s.json' % (self.config.username)
                    if os.path.isfile(user_web_location):
                        with open(user_web_location, 'w') as outfile:
                            json.dump(
                                {'lat': lat,
                                'lng': lng,
                                'cells': response_dict[
                                    'responses']['GET_MAP_OBJECTS']['map_cells']},
                                outfile)

                    user_data_lastlocation = 'data/last-location-%s.json' % (self.config.username)
                    if os.path.isfile(user_data_lastlocation):
                        with open(user_data_lastlocation, 'w') as outfile:
                            outfile.truncate()
                            json.dump({'lat': lat, 'lng': lng}, outfile)

        if response_dict and 'responses' in response_dict:
            if 'GET_MAP_OBJECTS' in response_dict['responses']:
                if 'status' in response_dict['responses']['GET_MAP_OBJECTS']:
                    if response_dict['responses']['GET_MAP_OBJECTS'][
                            'status'] is 1:
                        map_cells = response_dict['responses'][
                            'GET_MAP_OBJECTS']['map_cells']
                        position = (lat, lng, alt)
                    # Sort all by distance from current pos- eventually this should build graph & A* it
                    # print(map_cells)
                    #print( s2sphere.from_token(x['s2_cell_id']) )
                    map_cells.sort(key=lambda x: distance(lat, lng, x['forts'][0]['latitude'], x[
                                   'forts'][0]['longitude']) if 'forts' in x and x['forts'] != [] else 1e6)
        forts = []
        wild_pokemons = []
        catchable_pokemons = []
        for cell in map_cells:
            if "forts" in cell and len(cell["forts"]):
                forts += cell["forts"]
            if "wild_pokemons" in cell and len(cell["wild_pokemons"]):
                wild_pokemons += cell["wild_pokemons"]
            if "catchable_pokemons" in cell and len(cell["catchable_pokemons"]):
                catchable_pokemons += cell["catchable_pokemons"]
        if len(forts) == 0 and self.last_cell_forts != None:
            return {
                "forts": self.last_cell_forts,
                "wild_pokemons": wild_pokemons,
                "catchable_pokemons": catchable_pokemons
            }

        self.last_cell_forts = forts

        return {
            "forts": forts,
            "wild_pokemons": wild_pokemons,
            "catchable_pokemons": catchable_pokemons
        }

    def __get_nearest_lure_fort(self):
        fort = None
        forts_rest = []
        dist = None
        forts = filter(lambda x: x["id"] not in self.last_forts and 'latitude' in x and 'type' in x, self.last_cell_forts)
        if len(forts) == 0 or len(self.last_forts) > 10:
            self.last_forts = [None] * 5

        lure_forts = filter(lambda x: x.get('lure_info', None) != None, forts)
        if len(lure_forts) == 0:
            return self.__get_nearest_fort(forts)

        lure_forts.sort(key=lambda x: distance(position[0], position[1], x['latitude'], x['longitude']))
        if len(lure_forts) > 1 :
            forts_rest = lure_forts[1:]
        logger.log("[#] Move to lure fort")
        fort = lure_forts[0]
        dist = distance(position[0], position[1], fort['latitude'], fort['longitude'])
        return fort, forts_rest, dist

    def __get_nearest_fort(self, forts = None):
        if forts == None:
            forts = filter(lambda x: x["id"] not in self.last_forts and 'latitude' in x and 'type' in x, self.last_cell_forts)
        position = (self.api._position_lat, self.api._position_lng, 0)
        fort = None
        forts_rest = []
        dist = None

        forts.sort(key=lambda x: distance(position[0], position[1], x['latitude'], x['longitude']))
        if len(forts) > 1 :
            forts_rest = forts[1:]
        fort = forts[0]
        dist = distance(position[0], position[1], fort['latitude'], fort['longitude'])
        return fort, forts_rest, dist

    def work_on_cell(self, cell, position, include_fort_on_path, wander):
        if self.config.evolve_all:
            # Run evolve all once. Flip the bit.
            print('[#] Attempting to evolve all pokemons ...')
            worker = EvolveAllWorker(self)
            worker.work()
            self.config.evolve_all = []

        self._filter_ignored_pokemons(cell)

        if (self.config.mode == "all" or self.config.mode ==
                "poke") and 'catchable_pokemons' in cell and len(cell[
                    'catchable_pokemons']) > 0:
            logger.log('[#] Something rustles nearby!')
            # Sort all by distance from current pos- eventually this should
            # build graph & A* it
            cell['catchable_pokemons'].sort(
                key=
                lambda x: distance(position[0], position[1], x['latitude'], x['longitude']))

            user_web_catchable = 'web/catchable-%s.json' % (self.config.username)
            for pokemon in cell['catchable_pokemons']:
                with open(user_web_catchable, 'w') as outfile:
                    json.dump(pokemon, outfile)

                if self.catch_pokemon(pokemon) == PokemonCatchWorker.NO_POKEBALLS:
                    break
                with open(user_web_catchable, 'w') as outfile:
                    json.dump({}, outfile)

        if (self.config.mode == "all" or self.config.mode == "poke"
            ) and 'wild_pokemons' in cell and len(cell['wild_pokemons']) > 0:
            # Sort all by distance from current pos- eventually this should
            # build graph & A* it
            cell['wild_pokemons'].sort(
                key=
                lambda x: distance(position[0], position[1], x['latitude'], x['longitude']))
            for pokemon in cell['wild_pokemons']:
                if self.catch_pokemon(pokemon) == PokemonCatchWorker.NO_POKEBALLS:
                    break

        if (self.config.mode == 'all' or self.config.mode == 'poke'
        ) and 'forts' in cell:
            pokemons = self.get_lured_pokemon(cell, position)
            if len(pokemons) > 0:
                logger.log('[#] Some lured pokemon nearby!')
            for pokemon in pokemons:
                if self.catch_pokemon(pokemon) == PokemonCatchWorker.NO_POKEBALLS:
                    break

        if (self.config.mode == 'poke') and 'forts' in cell and wander:


            # forts.sort(key=lambda x: distance(position[
            #     0], position[1], x['latitude'], x['longitude']))
            # for fort in forts:
            while self.config.mode == 'poke':
                fort, _, _ = self.__get_nearest_lure_fort()
                if fort == None:
                    break

                worker = MoveToFortWorker(fort, self)
                worker.work()
                # avoid circle
                self.last_forts = self.last_forts[1:] + [fort["id"]]

        if (self.config.mode == "all" or
                self.config.mode == "farm") and include_fort_on_path:
            if 'forts' in cell:
                gyms = [gym for gym in cell['forts'] if 'gym_points' in gym]

                while self.config.mode != 'poke':
                    fort, _, _ = self.__get_nearest_fort()
                    if fort == None:
                        break

                    worker = MoveToFortWorker(fort, self)
                    worker.work()

                    worker = SeenFortWorker(fort, self)
                    hack_chain = worker.work()
                    # incubate eggs after fort
                    # because we will update the invent after fort
                    worker = IncubateEggsWorker(self)
                    worker.work()
                    # check level
                    worker = CollectLevelUpReward(self)
                    worker.work()
                    # avoid circle
                    self.last_forts = self.last_forts[1:] + [fort["id"]]
                    if hack_chain > 10:
                        #print('need a rest')
                        time.sleep(5)
                        continue

    def _setup_logging(self):
        self.log = logging.getLogger(__name__)
        # log settings
        # log format
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s [%(module)10s] [%(levelname)5s] %(message)s')

        if self.config.debug:
            logging.getLogger("requests").setLevel(logging.DEBUG)
            logging.getLogger("pgoapi").setLevel(logging.DEBUG)
            logging.getLogger("rpc_api").setLevel(logging.DEBUG)
        else:
            logging.getLogger("requests").setLevel(logging.ERROR)
            logging.getLogger("pgoapi").setLevel(logging.ERROR)
            logging.getLogger("rpc_api").setLevel(logging.ERROR)

    def _setup_api(self):
        # instantiate pgoapi
        self.api = PGoApi()

        # check if the release_config file exists
        try:
            with open('release_config.json') as file:
                pass
        except:
            # the file does not exist, warn the user and exit.
            logger.log('[#] IMPORTANT: Rename and configure release_config.json.example for your Pokemon release logic first!', 'red')
            exit(0)

        # provide player position on the earth
        self._set_starting_position()

        # no return
        self.api.set_authentication(provider = self.config.auth_service,
                                    username = self.config.username,
                                    password = self.config.password)
            # logger.log('Login Error, server busy', 'red')
            # exit(0)

        self.api.activate_signature(self.config.encryption);

        # chain subrequests (methods) into one RPC call

        # get player profile call
        # ----------------------
        response_dict = self.api.get_player()

        # response_dict = self.api.call()
        #print('Response dictionary: \n\r{}'.format(json.dumps(response_dict, indent=2)))
        currency_1 = "0"
        currency_2 = "0"

        player = response_dict['responses']['GET_PLAYER']['player_data']

        # @@@ TODO: Convert this to d/m/Y H:M:S
        creation_date = datetime.datetime.fromtimestamp(
            player['creation_timestamp_ms'] / 1e3)

        pokecoins = '0'
        stardust = '0'
        items_stock = self.current_inventory()

        if 'amount' in player['currencies'][0]:
            pokecoins = player['currencies'][0]['amount']
        if 'amount' in player['currencies'][1]:
            stardust = player['currencies'][1]['amount']

        logger.log('[#] Username: {username}'.format(**player))
        logger.log('[#] Acccount Creation: {}'.format(creation_date))
        logger.log('[#] Team : {}'.format(player.get('team', 0)))
        logger.log('[#] Bag Storage: {}/{}'.format(
            self.get_inventory_count('item'), player['max_item_storage']))
        logger.log('[#] Pokemon Storage: {}/{}'.format(
            self.get_inventory_count('pokemon'), player[
                'max_pokemon_storage']))
        logger.log('[#] Stardust: {}'.format(stardust))
        logger.log('[#] Pokecoins: {}'.format(pokecoins))
        logger.log('[#] PokeBalls: ' + str(items_stock[1]))
        logger.log('[#] GreatBalls: ' + str(items_stock[2]))
        logger.log('[#] UltraBalls: ' + str(items_stock[3]))

        self.team = player.get('team', 0)
        self.get_player_info()

        # if self.config.initial_transfer:
        #     worker = InitialTransferWorker(self)
        #     worker.work()

        logger.log('[#]')
        self.update_inventory()

        if self.config.initial_transfer:
            logger.log("[#] start to transfter the pokemons with release rules")
            worker = PokemonTransferWorker(self);
            worker.work()
            logger.log("[#] done transfter the pokemons")
        if self.config.nickname:
            logger.log("[#] start to nickname the pokemons with the IV info")
            worker = NicknamePokemon(self)
            worker.work()
            logger.log("[#] done nickname the pokemons")

    def catch_pokemon(self, pokemon):
        worker = PokemonCatchWorker(pokemon, self)
        return_value = worker.work()

        # if return_value == PokemonCatchWorker.BAG_FULL:
        #     worker = InitialTransferWorker(self)
        #     worker.work()

        if return_value == PokemonCatchWorker.CATCHED:
            self.release_pokemon(pokemon)

        return return_value

    def release_pokemon(self, pokemon):
        worker = PokemonTransferWorker(self);
        worker.set_pokemon(pokemon)
        return_value = worker.work()

        return return_value;

    def drop_item(self, item_id, count):
        inventory_req = self.api.recycle_inventory_item(item_id=item_id, count=count)
        #inventory_req = self.api.call()

        # Example of good request response
        #{'responses': {'RECYCLE_INVENTORY_ITEM': {'result': 1, 'new_count': 46}}, 'status_code': 1, 'auth_ticket': {'expire_timestamp_ms': 1469306228058L, 'start': '/HycFyfrT4t2yB2Ij+yoi+on778aymMgxY6RQgvrGAfQlNzRuIjpcnDd5dAxmfoTqDQrbz1m2dGqAIhJ+eFapg==', 'end': 'f5NOZ95a843tgzprJo4W7Q=='}, 'request_id': 8145806132888207460L}
        return inventory_req

    def update_inventory(self):
        response = self.api.get_inventory()
        #response = self.api.call()
        self.inventory = list()
        if 'responses' in response:
            if 'GET_INVENTORY' in response['responses']:
                if 'inventory_delta' in response['responses']['GET_INVENTORY']:
                    if 'inventory_items' in response['responses'][
                            'GET_INVENTORY']['inventory_delta']:
                        for item in response['responses']['GET_INVENTORY'][
                                'inventory_delta']['inventory_items']:
                            if not 'inventory_item_data' in item:
                                continue
                            if not 'item' in item['inventory_item_data']:
                                continue
                            if not 'item_id' in item['inventory_item_data'][
                                    'item']:
                                continue
                            if not 'count' in item['inventory_item_data'][
                                    'item']:
                                continue
                            self.inventory.append(item['inventory_item_data'][
                                'item'])

    def get_lured_pokemon(self, cell, position):
        forts_in_range = []
        pokemon_to_catch = []
        forts = [fort
                 for fort in cell['forts']
                 if 'lure_info' in fort ]
        if len(forts) == 0:
            return []

        #logger.log("[#] lure pokemon list {}".format(forts))
        forts.sort(key=lambda x: distance(
            position[0],
            position[1],
            x['latitude'],
            x['longitude']
        ))

        for fort in forts:
            distance_to_fort = distance(
                position[0],
                position[1],
                fort['latitude'],
                fort['longitude']
            )

            encounter_id = fort.get('lure_info', {}).get('encounter_id', None)
            if distance_to_fort < self.MAX_DISTANCE_FORT_IS_REACHABLE and encounter_id:
                forts_in_range.append(fort)
                result = {
                    'encounter_id': encounter_id,
                    'fort_id': fort['id'],
                    'latitude': fort['latitude'],
                    'longitude': fort['longitude'],
                    'pokemon_id': fort.get('lure_info', {}).get('active_pokemon_id', None)
                }

                pokemon_to_catch.append(result)
            # else:
            #     logger.log("[-] lured pokemon is too far ({},{})".format(fort['latitude'], fort['longitude']))

            if distance_to_fort >= self.MAX_DISTANCE_FORT_IS_REACHABLE:
                break;

        if len(pokemon_to_catch) > 0:
            user_web_lured = 'web/lured-pokemon-%s.json' % (self.config.username)
            for pokemon in pokemon_to_catch:
                with open(user_web_lured, 'w') as outfile:
                    json.dump(pokemon, outfile)

        return pokemon_to_catch

    def current_inventory(self):
        inventory_req = self.api.get_inventory()

        # inventory_req = self.api.call()
        inventory_dict = inventory_req['responses']['GET_INVENTORY'][
            'inventory_delta']['inventory_items']

        user_web_inventory = 'web/inventory-%s.json' % (self.config.username)
        with open(user_web_inventory, 'w') as outfile:
            json.dump(inventory_dict, outfile)

        # get player items stock
        # ----------------------
        items_stock = {x.value: 0 for x in list(Item)}

        for item in inventory_dict:
            try:
                # print(item['inventory_item_data']['item'])
                item_id = item['inventory_item_data']['item']['item_id']
                item_count = item['inventory_item_data']['item']['count']

                if item_id in items_stock:
                    items_stock[item_id] = item_count
            except:
                continue
        return items_stock

    def item_inventory_count(self, id):
        inventory_req = self.api.get_inventory()

        #inventory_req = self.api.call()
        inventory_dict = inventory_req['responses'][
            'GET_INVENTORY']['inventory_delta']['inventory_items']

        item_count = 0

        for item in inventory_dict:
            try:
                if item['inventory_item_data']['item']['item_id'] == int(id):
                    item_count = item[
                        'inventory_item_data']['item']['count']
            except:
                continue
        return item_count

    def _set_starting_position(self):

        if self.config.test:
            # TODO: Add unit tests
            return

        if self.config.location:
            try:
                location_str = str(self.config.location)
                location = (self._get_pos_by_name(location_str.replace(" ", "")))
                self.position = location
                self.api.set_position(*self.position)
                logger.log('')
                logger.log(u'[x] Address found: {}'.format(self.config.location.decode(
                    'utf-8')))
                logger.log('[x] Position in-game set as: {}'.format(self.position))
                logger.log('')
                return
            except:
                logger.log('[x] The location given using -l could not be parsed. Checking for a cached location.')
                pass

        if self.config.location_cache and not self.config.location:
            try:
                #
                # save location flag used to pull the last known location from
                # the location.json
                with open('data/last-location-%s.json' %
                          (self.config.username)) as f:
                    location_json = json.load(f)

                    self.position = (location_json['lat'],
                                     location_json['lng'], 0.0)
                    self.api.set_position(*self.position)

                    logger.log('')
                    logger.log(
                        '[x] Last location flag used. Overriding passed in location')
                    logger.log(
                        '[x] Last in-game location was set as: {}'.format(
                            self.position))
                    logger.log('')

                    return
            except:
                if not self.config.location:
                    sys.exit(
                        "No cached Location. Please specify initial location.")
                else:
                    pass

    def _get_pos_by_name(self, location_name):
        # Check if the given location is already a coordinate.
        if ',' in location_name:
            possibleCoordinates = re.findall("[-]?\d{1,3}[.]\d{6,7}", location_name)
            if len(possibleCoordinates) == 2:
                # 2 matches, this must be a coordinate. We'll bypass the Google geocode so we keep the exact location.
                logger.log(
                    '[x] Coordinates found in passed in location, not geocoding.')
                return (float(possibleCoordinates[0]), float(possibleCoordinates[1]), float("0.0"))

        geolocator = GoogleV3(api_key=self.config.gmapkey)
        loc = geolocator.geocode(location_name, timeout=10)

        #self.log.info('Your given location: %s', loc.address.encode('utf-8'))
        #self.log.info('lat/long/alt: %s %s %s', loc.latitude, loc.longitude, loc.altitude)

        return (loc.latitude, loc.longitude, loc.altitude)

    def _filter_ignored_pokemons(self, cell):
        process_ignore = False
        try:
            with open("./data/catch-ignore.yml", 'r') as y:
                ignores = yaml.load(y)['ignore']
                if len(ignores) > 0:
                    process_ignore = True
        except Exception, e:
            pass

        if process_ignore:
            #
            # remove any wild pokemon
            try:
                for p in cell['wild_pokemons'][:]:
                    pokemon_id = p['pokemon_data']['pokemon_id']
                    pokemon_name = filter(
                        lambda x: int(x.get('Number')) == pokemon_id,
                        self.pokemon_list)[0]['Name']

                    if pokemon_name in ignores:
                        cell['wild_pokemons'].remove(p)
            except KeyError:
                pass

            #
            # remove catchable pokemon
            try:
                for p in cell['catchable_pokemons'][:]:
                    pokemon_id = p['pokemon_id']
                    pokemon_name = filter(
                        lambda x: int(x.get('Number')) == pokemon_id,
                        self.pokemon_list)[0]['Name']

                    if pokemon_name in ignores:
                        cell['catchable_pokemons'].remove(p)
            except KeyError:
                pass

    def heartbeat(self):
        self.api.get_player()
        self.api.get_hatched_eggs()
        self.api.get_inventory()
        self.api.check_awarded_badges()
        #self.api.call()

    def get_inventory(self):
        if self.latest_inventory is None:
            response = self.api.get_inventory()
            #response = self.api.call()
            self.latest_inventory = response
        return self.latest_inventory

    def get_inventory_count(self, what):
        response_dict = self.api.get_inventory()
        #response_dict = self.api.call()
        if 'responses' in response_dict:
            if 'GET_INVENTORY' in response_dict['responses']:
                if 'inventory_delta' in response_dict['responses'][
                        'GET_INVENTORY']:
                    if 'inventory_items' in response_dict['responses'][
                            'GET_INVENTORY']['inventory_delta']:
                        pokecount = 0
                        itemcount = 1
                        for item in response_dict['responses'][
                                'GET_INVENTORY']['inventory_delta'][
                                    'inventory_items']:
                            #print('item {}'.format(item))
                            if 'inventory_item_data' in item:
                                if 'pokemon_data' in item[
                                        'inventory_item_data']:
                                    pokecount = pokecount + 1
                                if 'item' in item['inventory_item_data']:
                                    if 'count' in item['inventory_item_data'][
                                            'item']:
                                        itemcount = itemcount + \
                                            item['inventory_item_data'][
                                                'item']['count']
        if 'pokemon' in what:
            return pokecount
        if 'item' in what:
            return itemcount
        return '0'

    def get_player_info(self):
        response_dict = self.api.get_inventory()
        #response_dict = self.api.call()
        if 'responses' in response_dict:
            if 'GET_INVENTORY' in response_dict['responses']:
                if 'inventory_delta' in response_dict['responses'][
                        'GET_INVENTORY']:
                    if 'inventory_items' in response_dict['responses'][
                            'GET_INVENTORY']['inventory_delta']:
                        pokecount = 0
                        itemcount = 1
                        for item in response_dict['responses'][
                                'GET_INVENTORY']['inventory_delta'][
                                    'inventory_items']:
                            #print('item {}'.format(item))
                            if 'inventory_item_data' in item:
                                if 'player_stats' in item[
                                        'inventory_item_data']:
                                    playerdata = item['inventory_item_data'][
                                        'player_stats']

                                    nextlvlxp = (
                                        int(playerdata.get('next_level_xp', 0)) -
                                        int(playerdata.get('experience', 0)))

                                    if 'level' in playerdata:
                                        logger.log(
                                            '[#] -- Level: {level}'.format(
                                                **playerdata))

                                    if 'experience' in playerdata:
                                        logger.log(
                                            '[#] -- Experience: {experience}'.format(
                                                **playerdata))
                                        logger.log(
                                            '[#] -- Experience until next level: {}'.format(
                                                nextlvlxp))

                                    if 'pokemons_captured' in playerdata:
                                        logger.log(
                                            '[#] -- Pokemon Captured: {pokemons_captured}'.format(
                                                **playerdata))

                                    if 'poke_stop_visits' in playerdata:
                                        logger.log(
                                            '[#] -- Pokestops Visited: {poke_stop_visits}'.format(
                                                **playerdata))
