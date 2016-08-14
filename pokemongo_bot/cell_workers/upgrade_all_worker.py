
# upgrade_all_worker.py --- 
# 
# Filename: upgrade_all_worker.py
# Description: 
# Author: Werther Zhang
# Maintainer: 
# Created: Sun Aug 14 12:11:06 2016 (+0800)
# 

# Change Log:
# 
# 

from utils import distance, format_dist
from pokemongo_bot.human_behaviour import sleep
from pokemongo_bot import logger
from sets import Set

class UpgradeAllWorker(object):
    def __init__(self, bot):
        self.api = bot.api
        self.config = bot.config
        self.bot = bot

    def work(self):
        try:
            inventory = reduce(dict.__getitem__, ["responses", "GET_INVENTORY", "inventory_delta", "inventory_items"], self.bot.get_inventory())
        except KeyError:
            pass
        else:
            pokemon_data = self.__get_inventory_pokemon(inventory)
            upgrade_list = self.__sort_by_iv(pokemon_data)
            upgraded_list = []

            for pokemon in upgrade_list:
                if pokemon[3] > 0.95:
                    if pokemon[1] not in upgraded_list:
                        self.__upgrade_pokemon(pokemon)
                        upgraded_list += [pokemon[1]]
                else:
                    break;

    def __upgrade_pokemon(self, pokemon):
        pokemon_id = pokemon[0]
        pokemon_name = pokemon[1]
        pokemon_cp = pokemon[2]
        pokemon_iv = pokemon[3]
        logged = False
        while True:
            response_dict = self.api.upgrade_pokemon(pokemon_id=pokemon_id)
            #logger.log('[#] {}'.format(response_dict))
            status = response_dict['responses']['UPGRADE_POKEMON']['result']
            if status == 1:
                if not logged:
                    logger.log('[#] Successfully upgrade {} with {} IV'.format(pokemon_name, pokemon_iv))
                    logged = True
            else:
                break;
            sleep(5.7)
        sleep(5.7)

    def __get_inventory_pokemon(self, inventory_dict):
        pokemon_data = []
        for inv_data in inventory_dict:
            try:
                pokemon = reduce(dict.__getitem__,['inventory_item_data','pokemon_data'],inv_data)
            except KeyError:
                pass
            else:
                if not pokemon.get('is_egg',False):
                    pokemon_data.append(pokemon)
        return pokemon_data

    def __sort_by_iv(self, pokemon_data):
        pokemons = []
        for pokemon in pokemon_data:
            pokemon_num = int(pokemon['pokemon_id']) - 1
            pokemon_name = self.bot.pokemon_list[int(pokemon_num)]['Name']
            pokemons.append([
                pokemon['id'],
                pokemon_name,
                pokemon['cp'],
                self.__compute_iv(pokemon)
            ])
        pokemons.sort(key=lambda x: x[3], reverse=True)

        return pokemons

    def __compute_iv(self, pokemon):
        total_IV = 0.0
        iv_stats = ['individual_attack', 'individual_defense', 'individual_stamina']
        
        for individual_stat in iv_stats:
            try:
                total_IV += pokemon[individual_stat]
            except:
                pokemon[individual_stat] = 0
                continue
        pokemon_potential = round((total_IV / 45.0), 2)
        return pokemon_potential
