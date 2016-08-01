from pokemongo_bot import logger
from pokemongo_bot.human_behaviour import sleep
import traceback

class IncubateEggsWorker(object):
    last_km_walked = 0
    incubating = False
    last_used_incubators = []

    def __init__(self, bot):
        self.bot = bot
        self.ready_incubators = []
        self.used_incubators = []
        self.eggs = []
        self.km_walked = 0
        self.hatching_animation_delay = 4.20
        self.max_iv = 45.0

    def work(self):
        try:
            self._check_inventory()
        except Exception as e:
            logger.log("{}".format(traceback.format_exc()))
            return

        if len(IncubateEggsWorker.last_used_incubators) > len(self.used_incubators) and IncubateEggsWorker.incubating :
            IncubateEggsWorker.last_used_incubators.sort(key=lambda x: x.get("km"))
            km_left = IncubateEggsWorker.last_used_incubators[0]['km'] - self.km_walked
            if km_left <= 0.1:
                self._hatch_eggs()
            else:
                logger.log("incubators infor mismatch: last_used_incubators {} now used incubators {}".format(IncubateEggsWorker.last_used_incubators, self.used_incubators))


        if self.used_incubators and IncubateEggsWorker.last_km_walked != self.km_walked:
            self.used_incubators.sort(key=lambda x: x.get("km"))
            km_left = self.used_incubators[0]['km']-self.km_walked
            if km_left <= 0:
                logger.log('[-] Never come here', 'red')
                self._hatch_eggs()
            else:
                logger.log('[x] Next egg incubates in {:.2f} km'.format(km_left),'yellow')
                IncubateEggsWorker.incubating = True
            IncubateEggsWorker.last_km_walked = self.km_walked
        IncubateEggsWorker.last_used_incubators = self.used_incubators

        sorting = False #self.bot.config.longer_eggs_first
        self.eggs.sort(key=lambda x: x.get("km"), reverse=sorting)

        if self.ready_incubators:
            self._apply_incubators()

    def _apply_incubators(self):
        for incubator in self.ready_incubators:
            for egg in self.eggs:
                if egg["used"] or egg["km"] == -1:
                    continue
                if self.bot.config.debug:
                    logger.log('[x] Attempting to apply incubator {} to egg {}'.format(incubator['id'], egg['id']))
                self.bot.api.use_item_egg_incubator(item_id=incubator["id"], pokemon_id=egg["id"])
                ret = self.bot.api.call()
                if ret:
                    code = ret.get("responses", {}).get("USE_ITEM_EGG_INCUBATOR", {}).get("result", 0)
                    if code == 1:
                        logger.log('[x] Now incubating a ' + str(egg["km"]) + "km egg", 'green')
                        egg["used"] = True
                        incubator["used"] = True
                        break
                    elif code == 5 or code == 7:
                        if self.bot.config.debug:
                            logger.log('[x] Incubator already in use')
                        incubator["used"] = True
                        break
                    elif code == 6:
                        if self.bot.config.debug:
                            logger.log('[x] Egg already incubating')
                        egg["used"] = True

    def _check_inventory(self, lookup_ids=[]):
        inv = {}
        response_dict = self.bot.get_inventory()
        matched_pokemon = []
        temp_eggs = []
        temp_used_incubators = []
        temp_ready_incubators = []
        inv = reduce(
            dict.__getitem__,
            ["responses", "GET_INVENTORY", "inventory_delta", "inventory_items"],
            response_dict
        )
        #logger.log("inv data: {}".format(inv))
        for inv_data in inv:
            inv_data = inv_data.get("inventory_item_data", {})
            if "egg_incubators" in inv_data:
                incubators = inv_data.get("egg_incubators", {}).get("egg_incubator",[])
                if isinstance(incubators, basestring):  # checking for old response
                    incubators = [incubators]
                if 'item_id' in incubators: # for {'item_id': 901, 'incubator_type': 1, 'id': u'EggIncubatorProto6616616845995627119'}
                    incubators = [incubators]
                #logger.log("incubators: {}".format(incubators))
                for incubator in incubators:
                    #logger.log("incubator {}".format(incubator))
                    if 'pokemon_id' in incubator:
                        temp_used_incubators.append({
                            "id": incubator.get('id', -1),
                            "km": incubator.get('target_km_walked', 9001)
                        })
                    else:
                        temp_ready_incubators.append({
                            "id": incubator.get('id', -1)
                        })
                continue
            if "pokemon_data" in inv_data:
                pokemon = inv_data.get("pokemon_data", {})
                if pokemon.get("is_egg", False) and "egg_incubator_id" not in pokemon:
                    temp_eggs.append({
                        "id": pokemon.get("id", -1),
                        "km": pokemon.get("egg_km_walked_target", -1),
                        "used": False
                    })
                elif 'is_egg' not in pokemon and pokemon['id'] in lookup_ids:
                    matched_pokemon.append({
                        "pokemon_id": pokemon.get('pokemon_id', -1),
                        "cp": pokemon.get('cp', -1),
                        "iv": [
                            pokemon.get('individual_attack', -1),
                            pokemon.get('individual_stamina', -1),
                            pokemon.get('individual_defense', -1)
                        ]
                    })
                continue
            if "player_stats" in inv_data:
                self.km_walked = inv_data.get("player_stats", {}).get("km_walked", 0)

        self.used_incubators = temp_used_incubators
        self.ready_incubators = temp_ready_incubators
        self.eggs = temp_eggs

        return matched_pokemon

    def _hatch_eggs(self):
        self.bot.api.get_hatched_eggs()
        response_dict = self.bot.api.call()
        log_color = 'green'
        # logger.log("[ZP] hatch eggs : {}".format(response_dict))
        # [ZP] hatch eggs : {'responses': {'GET_HATCHED_EGGS': {'success': True}}, 'status_code': 1, 'auth_ticket': {'expire_timestamp_ms': 1470046182758L, 'start': '9R5Iu/SArPadTn+U73KfCpM3ViIskNi55W4nd8Np+6U7ciiWWdjTWZHBGlm0DbdPGE7+0jE2qTx+4U7gApslNw==', 'end': 'dtJsnVaR2FCJW5aUQhDphA=='}, 'request_id': 8145806132888207460L}
        try:
            result = reduce(dict.__getitem__, ["responses", "GET_HATCHED_EGGS"], response_dict)
        except KeyError:
            logger.log("hatch eggs failed")
            return
        if 'pokemon_id' in result:
            pokemon_ids = [id for id in result['pokemon_id']]
        stardust = result.get('stardust_awarded', 0)
        candy = result.get('candy_awarded', 0)
        xp = result.get('experience_awarded', 0)
        sleep(self.hatching_animation_delay)
        self.bot.latest_inventory = None
        pokemon_data = []
        try:
            pokemon_data = self._check_inventory(pokemon_ids)
        except:
            pass  # just proceed with what we have
        for pokemon in pokemon_data:
            # pokemon ids seem to be offset by one
            pokemon['name'] = self.bot.pokemon_list[(pokemon['pokemon_id']-1)]['Name']
        logger.log("-"*30, log_color)
        logger.log("[!] {} eggs hatched! Received:".format(len(pokemon_data)), log_color)
        for i in range(len(pokemon_data)):
            logger.log("-"*30,log_color)
            logger.log("[!] Pokemon: {}".format(pokemon_data[i]['name']), log_color)
            logger.log("[!] CP: {}".format(pokemon_data[i]['cp']), log_color)
            logger.log("[!] IV: {}".format("/".join(map(str, pokemon_data[i]['iv']))), log_color)
            logger.log("[!] XP: {}".format(xp[i]), log_color)
            logger.log("[!] Stardust: {}".format(stardust[i]), log_color)
            logger.log("[!] Candy: {}".format(candy[i]), log_color)
        logger.log("-"*30, log_color)

        for pokemon in pokemon_data:
            self.bot.release_pokemon(pokemon)

