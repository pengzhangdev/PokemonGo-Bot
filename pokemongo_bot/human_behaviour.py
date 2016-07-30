# -*- coding: utf-8 -*-

import time
from math import ceil
from random import random, randint, uniform


def sleep(seconds, delta=0.3):
    jitter = ceil(delta * seconds)
    sleep_time = randint(int(seconds - jitter), int(seconds + jitter))
    time.sleep(sleep_time)

def action_delay(low, high):
    # Waits for random number of seconds between low & high numbers
    longNum = uniform(low, high)
    shortNum = float("{0:.2f}".format(longNum))
    time.sleep(shortNum)


def random_lat_long_delta():
    # Return random value from [-.000025, .000025]. Since 364,000 feet is equivalent to one degree of latitude, this
    # should be 364,000 * .000025 = 9.1. So it returns between [-9.1, 9.1]
    return ((random() * 0.00001) - 0.000005) * 5
