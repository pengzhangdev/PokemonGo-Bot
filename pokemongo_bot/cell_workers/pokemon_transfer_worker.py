import json

from pokemongo_bot.human_behaviour import sleep, action_delay
from pokemongo_bot import logger


class PokemonTransferWorker(object):

    def __init__(self, bot):
        self.config = bot.config
        self.pokemon_list = bot.pokemon_list
        self.api = bot.api
        self.bot = bot
        self.pokemon_id = -1

    def set_pokemon(self, pokemon):
        self.pokemon_id = pokemon["pokemon_id"]

    def __release_certain_pokemon(self, pokemon_id, pokemon_groups):
        if not pokemon_groups.has_key(pokemon_id):
            return

        group = pokemon_groups[pokemon_id]

        if len(group) > 0:
            pokemon_name = self.pokemon_list[pokemon_id - 1]['Name']

            # Always match the release rule
            group = sorted(group, key=lambda x: x['cp'], reverse=False)
            for item in group:
                pokemon_cp = item['cp']
                pokemon_potential = item['iv']

                # logger.log("should_release_pokemon {} cp {} iv {}".format(pokemon_name, pokemon_cp, pokemon_potential))
                if self.should_release_pokemon(pokemon_name, pokemon_cp, pokemon_potential):
                    self.release_pokemon(pokemon_name, item['cp'], item['iv'], item['pokemon_data']['id'])
                    pokemon_groups[pokemon_id].remove(item)

        return pokemon_groups

    def __keep_best_pokemon(self, pokemon_id, pokemon_groups):
        if not pokemon_groups.has_key(pokemon_id):
            return

        group = pokemon_groups[pokemon_id]

        if len(group) > 0:
            pokemon_name = self.pokemon_list[pokemon_id - 1]['Name']
            keep_best, keep_best_cp, keep_best_iv, keep_best_cpiv = self._validate_keep_best_config(pokemon_name)

            # If keep best, release rest
            if keep_best:
                #logger.log("keep_best")
                best_pokemon_ids = set()
                order_criteria = 'none'
                if keep_best_cp >= 1:
                    cp_limit = keep_best_cp
                    best_cp_pokemons = sorted(group, key=lambda x: (x['cp'], x['iv']), reverse=True)[:cp_limit]
                    best_pokemon_ids = set(pokemon['pokemon_data']['id'] for pokemon in best_cp_pokemons)
                    order_criteria = 'cp'

                if keep_best_iv >= 1:
                    iv_limit = keep_best_iv
                    best_iv_pokemons = sorted(group, key=lambda x: (x['iv'], x['cp']), reverse=True)[:iv_limit]
                    best_pokemon_ids |= set(pokemon['pokemon_data']['id'] for pokemon in best_iv_pokemons)
                    if order_criteria == 'cp':
                        order_criteria = 'cp and iv'
                    else:
                        order_criteria = 'iv'

                if keep_best_cpiv >= 1:
                    cpiv_limit = keep_best_cpiv
                    best_cpiv_pokemons = sorted(group, key=lambda x: x['cp'] * x['iv'], reverse = True)[:cpiv_limit]
                    best_pokemon_ids |= set(pokemon['pokemon_data']['id'] for pokemon in best_cpiv_pokemons)
                    order_criteria = 'cp and iv'

                # remove best pokemons from all pokemons array
                all_pokemons = group
                best_pokemons = []
                #logger.log("all_pokemons {}".format(all_pokemons))
                for best_pokemon_id in best_pokemon_ids:
                    for pokemon in all_pokemons:
                        if best_pokemon_id == pokemon['pokemon_data']['id']:
                            all_pokemons.remove(pokemon)
                            best_pokemons.append(pokemon)

                if best_pokemons and all_pokemons:
                    logger.log("Keep {} best {}, based on {}".format(len(best_pokemons),
                                                                     pokemon_name,
                                                                     order_criteria), "green")
                    for best_pokemon in best_pokemons:
                        logger.log("{} [CP {}] [Potential {}]".format(pokemon_name,
                                                                      best_pokemon['cp'],
                                                                      best_pokemon['iv']), 'green')

                    logger.log("Transferring {} pokemon".format(len(all_pokemons)), "green")

                #logger.log("release all_pokemons {}".format(all_pokemons))
                for pokemon in all_pokemons:
                    self.release_pokemon(pokemon_name, pokemon['cp'], pokemon['iv'], pokemon['pokemon_data']['id'])


    def work(self):
        #logger.log("Start release pokemon")
        if self.pokemon_id != -1:
            pokemon_groups = self._release_pokemon_get_groups()
            pokemon_groups = self.__release_certain_pokemon(self.pokemon_id, pokemon_groups)
            #pokemon_groups = self._release_pokemon_get_groups()
            self.__keep_best_pokemon(self.pokemon_id, pokemon_groups)
            #logger.log("Done release pokemon")
            self.pokemon_id = -1
            return

        pokemon_groups = self._release_pokemon_get_groups()
        for pokemon_id in pokemon_groups:
            # if self.pokemon_id != -1 and pokemon_id != self.pokemon_id:
            #     continue
            self.__release_certain_pokemon(pokemon_id, pokemon_groups)


        pokemon_groups = self._release_pokemon_get_groups()
        for pokemon_id in pokemon_groups:
            #self.__release_certain_pokemon(pokemon_id, pokemon_groups)
            self.__keep_best_pokemon(pokemon_id, pokemon_groups)


        #logger.log("Done release pokemon")
        self.pokemon_id = -1

    def _release_pokemon_get_groups(self):
        pokemon_groups = {}
        inventory_req = self.api.get_inventory()
        #inventory_req = self.api.call()

        if inventory_req.get('responses', False) is False:
            return pokemon_groups

        inventory_dict = inventory_req['responses']['GET_INVENTORY']['inventory_delta']['inventory_items']

        user_web_inventory = 'web/inventory-%s.json' % (self.config.username)
        with open(user_web_inventory, 'w') as outfile:
            json.dump(inventory_dict, outfile)

        for pokemon in inventory_dict:
            try:
                reduce(dict.__getitem__, [
                    "inventory_item_data", "pokemon_data", "pokemon_id"
                ], pokemon)
            except KeyError:
                continue

            pokemon_data = pokemon['inventory_item_data']['pokemon_data']
            #logger.log("pokemon_data {}".format(pokemon_data))
            group_id = pokemon_data['pokemon_id']
            group_pokemon_cp = pokemon_data['cp']
            group_pokemon_iv = self.get_pokemon_potential(pokemon_data)

            if group_id not in pokemon_groups:
                pokemon_groups[group_id] = []

            pokemon_groups[group_id].append({
                'cp': group_pokemon_cp,
                'iv': group_pokemon_iv,
                'pokemon_data': pokemon_data
            })

        return pokemon_groups

    def get_pokemon_potential(self, pokemon_data):
        total_iv = 0
        iv_stats = ['individual_attack', 'individual_defense', 'individual_stamina']
        for individual_stat in iv_stats:
            try:
                total_iv += pokemon_data[individual_stat]
            except Exception:
                continue
        return round((total_iv / 45.0), 2)

    def should_release_pokemon(self, pokemon_name, cp, iv):
        release_config = self._get_release_config_for(pokemon_name)
        #logger.log("release config : {}".format(release_config))
        cp_iv_logic = release_config.get('cp_iv_logic')
        if not cp_iv_logic:
            cp_iv_logic = self._get_release_config_for('any').get('logic', 'and')

        release_results = {
            'cp': False,
            'iv': False,
        }

        if release_config.get('never_release', False):
            return False

        if release_config.get('always_release', False):
            return True

        release_cp = release_config.get('release_under_cp', 0)
        if cp < release_cp:
            release_results['cp'] = True

        release_iv = release_config.get('release_under_iv', 0)
        if iv < release_iv:
            release_results['iv'] = True

        logic_to_function = {
            'or': lambda x, y: x or y,
            'and': lambda x, y: x and y
        }

        if logic_to_function[cp_iv_logic](*release_results.values()):
            logger.log(
                "Releasing {} with CP {} and IV {}. Matching release rule: CP < {} {} IV < {}. ".format(
                    pokemon_name,
                    cp,
                    iv,
                    release_cp,
                    cp_iv_logic.upper(),
                    release_iv
                ), 'yellow'
            )

        return logic_to_function[cp_iv_logic](*release_results.values())

    def release_pokemon(self, pokemon_name, cp, iv, pokemon_id):
        logger.log('Exchanging {} [CP {}] [Potential {}] for candy!'.format(pokemon_name,
                                                                            cp,
                                                                            iv), 'green')
        response_dict = self.api.release_pokemon(pokemon_id=pokemon_id)
        #response_dict = self.api.call()
        action_delay(1, 4)

    def _get_release_config_for(self, pokemon):
        release_config = self.config.release_config.get(pokemon)
        if not release_config:
            release_config = self.config.release_config.get('any')
        if not release_config:
            release_config = {}
        return release_config

    def _validate_keep_best_config(self, pokemon_name):
        keep_best = False

        release_config = self._get_release_config_for(pokemon_name)

        keep_best_cp = release_config.get('keep_best_cp', 0)
        keep_best_iv = release_config.get('keep_best_iv', 0)
        keep_best_cpiv = release_config.get('keep_best_cpiv', 0)

        if keep_best_cp or keep_best_iv or keep_best_cpiv:
            keep_best = True
            try:
                keep_best_cp = int(keep_best_cp)
            except ValueError:
                keep_best_cp = 0

            try:
                keep_best_iv = int(keep_best_iv)
            except ValueError:
                keep_best_iv = 0

            try:
                keep_best_cpiv = int(keep_best_cpiv)
            except ValueError:
                keep_best_cpiv = 0

            if keep_best_cp < 0 or keep_best_iv < 0 or keep_best_cpiv < 0:
                logger.log("Keep best can't be < 0. Ignore it.", "red")
                keep_best = False

            if keep_best_cp == 0 and keep_best_iv == 0 and keep_best_cpiv == 0:
                keep_best = False
        #logger.log("keep best {} cp {} iv {} cpiv {}".format(keep_best, keep_best_cp, keep_best_iv, keep_best_cpiv))
        return keep_best, keep_best_cp, keep_best_iv, keep_best_cpiv
