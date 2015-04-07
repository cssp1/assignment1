#!/usr/bin/env python

# generic functions for working on unit/building equipment dictionaries

def get_leveled_quantity(qty, level): # XXX duplicate
    if type(qty) == list:
        return qty[level-1]
    return qty

class Equipment (object):
    # return iterator through all equipped items, returning a {"spec":"foo", "stack":2} dictionary for each one
    @staticmethod
    def equip_iter(equipment):
        if equipment:
            assert type(equipment) is dict
            for slot_type in equipment:
                for x in equipment[slot_type]:
                    if x:
                        if type(x) is dict:
                            yield x
                        else:
                            yield {'spec': x}
    # return a serialized representation of each equipped item, for sending to the client
    @staticmethod
    def equip_serialize(equipment):
        if equipment:
            assert type(equipment) is dict
            for slot_type in equipment:
                for i, entry in enumerate(equipment[slot_type]):
                    if entry:
                        if type(entry) is dict:
                            yield {'slot_type':slot_type, 'slot_index': i, 'item': entry}
                        else:
                            yield {'slot_type':slot_type, 'slot_index': i, 'item': {'spec': entry}}

    # check that there actually exists an item of the right spec (and optionally level) at this address
    @staticmethod
    def equip_has(equipment, addr, specname = None, level = None):
        assert type(equipment) is dict
        slot_type, slot_num = addr
        if not equipment: return False
        if slot_type not in equipment: return False
        if slot_num >= len(equipment[slot_type]): return False
        if specname:
            if type(equipment[slot_type][slot_num]) is dict:
                if (equipment[slot_type][slot_num]['spec'] != specname) or \
                   (level is not None and equipment[slot_type][slot_num].get('level',1) != level): return False
            else:
                if (equipment[slot_type][slot_num] != specname) or (level is not None and level != 1): return False
        return True

    # get the item at this address (None if missing)
    @staticmethod
    def equip_get(equipment, addr):
        assert type(equipment) is dict
        slot_type, slot_num = addr
        if not equipment: return None
        if slot_type not in equipment: return None
        if slot_num >= len(equipment[slot_type]): return None
        if not equipment[slot_type][slot_num]: return None
        if type(equipment[slot_type][slot_num]) is dict:
            return equipment[slot_type][slot_num]
        else:
            return {'spec': equipment[slot_type][slot_num]}

    @staticmethod
    def equip_remove(equipment, addr, specname = None):
        assert type(equipment) is dict
        slot_type, slot_num = addr
        assert Equipment.equip_has(equipment, addr, specname = specname)
        old_item = {'spec': equipment[slot_type][slot_num]}
        equipment[slot_type][slot_num] = None
        if not any(equipment[slot_type]): del equipment[slot_type]
        return old_item

    @classmethod # XXXXXX handle items with properties
    def equip_add(cls, equipment, my_spec, my_level, addr, item_spec, probe_only = False, probe_will_remove = False):
        assert type(equipment) is dict
        assert type(item_spec) is dict
        slot_type, slot_num = addr

        # check that the slot exists and is empty
        if (not my_spec.equip_slots) or \
           (slot_type not in my_spec.equip_slots) or \
           (get_leveled_quantity(my_spec.equip_slots[slot_type], my_level) < 1) or \
           (slot_num < 0 or slot_num >= get_leveled_quantity(my_spec.equip_slots[slot_type], my_level)) or \
           ((not probe_will_remove) and \
            (equipment and (slot_type in equipment) and \
             (sum((1 for x in equipment[slot_type] if x), 0) >= get_leveled_quantity(my_spec.equip_slots[slot_type], my_level) or \
              len(equipment[slot_type]) >= slot_num+1 and equipment[slot_type][slot_num])
             )):
            return False

        # check slot compatibility
        if not cls.equip_is_compatible_with_slot(my_spec, my_level, slot_type, item_spec): return False

        if probe_only: return True

        assert equipment is not None
        if slot_type not in equipment: equipment[slot_type] = []
        while len(equipment[slot_type]) < slot_num+1:
            equipment[slot_type].append(None)
        equipment[slot_type][slot_num] = item_spec['name']
        return True

    # similar to client's equip_is_compatible_with*() functions
    @staticmethod # XXXXXX handle items with properties
    def equip_is_compatible_with_slot(my_spec, my_level, slot_type, item_spec):
        if 'equip' not in item_spec: return False
        if 'compatible' in item_spec['equip']:
            crit_list = item_spec['equip']['compatible']
        else:
            crit_list = [item_spec['equip']] # legacy items use raw outer JSON
        for crit in crit_list:
            if ('kind' in crit) and (crit['kind'] != my_spec.kind): continue
            if ('name' in crit) and (crit['name'] != my_spec.name): continue
            if ('manufacture_category' in crit) and (crit['manufacture_category'] != my_spec.manufacture_category): continue
            if ('history_category' in crit) and (crit['history_category'] != my_spec.history_category): continue
            if ('slot_type' in crit) and (crit['slot_type'] != slot_type): continue
            if ('min_level' in crit) and (my_level < crit['min_level']): continue
            return True
        return False
