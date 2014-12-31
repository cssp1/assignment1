#!/usr/bin/env python

# Copyright (c) 2014 SpinPunch. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# this is a library for use by the game server and analytics code to calculate
# the price for a bundle of fungible resources.

# When using this library from a stand-alone tool, just pass None for the session.

import math

# In order to be callable from both inside server.py and from stand-alone analytics tools,
# this is an adaptor that handles calling get_any_abtest_value where appropriate to handle overrides.
def resolve_value(session, override_name, default_value):
    if session:
        return session.player.get_any_abtest_value(override_name, default_value)
    return default_value

# returns a parameter from store.json that might be overridden by an A/B test, and might also be a per-resource dictionary
def get_resource_parameter(gamedata, session, name, resname):
    ret = resolve_value(session, name, gamedata['store'][name])
    if type(ret) is dict:
        ret = ret[resname]
    return ret

def cost_legacy_exp_log(gamedata, session, resname, amount, currency):
    if amount > 2:
        scale_factor = get_resource_parameter(gamedata, session, 'resource_price_formula_scale', resname)
        coeff = resolve_value(session, 'gamebucks_per_fbcredit', gamedata['store']['gamebucks_per_fbcredit']) if currency == 'gamebucks' else 1
        price = scale_factor * coeff * 0.06 * math.exp(0.75 * (math.log10(amount) - 2.2 * math.pow(math.log10(amount), -1.25)))
        return price
    else:
        return 1

def cost_piecewise_linear(gamedata, session, resname, amount, currency):
    price_points = get_resource_parameter(gamedata, session, 'resource_price_formula_piecewise_linear_points', resname)

    for i in xrange(1, len(price_points)):
        if (amount < price_points[i][0] or i == len(price_points) - 1):
            scale_factor = get_resource_parameter(gamedata, session, 'resource_price_formula_scale', resname)
            coeff = (1 / resolve_value(session, 'gamebucks_per_fbcredit', gamedata['store']['gamebucks_per_fbcredit'])) if currency != 'gamebucks' else 1
            # cast to float so that we don't use integer division
            slope = float(price_points[i][1] - price_points[i - 1][1]) / (price_points[i][0] - price_points[i - 1][0])
            return scale_factor * coeff * (price_points[i - 1][1] + slope * (amount - price_points[i - 1][0]))

    raise Exception('Unhandled case while calculating piecewise_linear prices. This should never happen.')

price_formulas = {
    'legacy_exp_log': cost_legacy_exp_log,
    'piecewise_linear': cost_piecewise_linear
}

# returns the price of an arbitrary amount of fungible resources
def get_resource_price(gamedata, session, resname, amount, currency):
    if amount <= 0:
        return 0
    price_formula_name = get_resource_parameter(gamedata, session, 'resource_price_formula', resname)
    return math.ceil(price_formulas[price_formula_name](gamedata, session, resname, amount, currency))
