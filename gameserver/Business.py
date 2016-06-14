#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# Track time progress for something that a building is doing in-game.
# The hard part here is simulating the passage of time when the action might be completed, ongoing, halted, or halted then resumed.

def reconstitute(klass, persisted_state):
    instance = klass()
    instance.unpersist_state(persisted_state)
    return instance

class AbstractBusiness(object):
    def describe_state(self): return 'unknown'
    def serialize_state(self): return self.persist_state()

class SingleBusiness(AbstractBusiness):
    def __init__(self, init_total_time = -1, init_start_time = -1):
        self.creation_time = init_start_time # time at which action was created
        self.total_time = init_total_time # total time this action will take
        self.start_time = init_start_time # time at which we last resumed action
        self.done_time = 0 # progress made before we last resumed action
    def persist_state(self): return {'creation_time': self.creation_time, 'total_time': self.total_time, 'start_time': self.start_time, 'done_time': self.done_time}
    def unpersist_state(self, state):
        self.total_time = state['total_time']
        self.start_time = state['start_time']
        self.done_time = state['done_time']
        self.creation_time = state.get('creation_time', -1) # legacy support
    def speedup(self):
        assert self.start_time > 0
        self.done_time = self.total_time
    def halt(self, now):
        if self.start_time > 0:
            if self.start_time < now: # record progress we've made so far
                self.done_time += max(0, min(now - self.start_time, self.total_time - self.done_time))
            self.start_time = -1
            return True # return true if we were interrupted (havoc!)
        return False
    def finish_time(self): # time at which we will finish, or -1 if never
        if self.start_time <= 0: return -1
        return self.start_time + max(0, self.total_time - self.done_time)
    def resume(self, undamaged_time, now, delay_start = 0):
        # undamaged_time = time at which we resumed (prior to now), or -1 if we assume nothing happened before resumption
        if self.start_time <= 0:
            if undamaged_time >= 0:
                if self.creation_time >= 0: undamaged_time = max(undamaged_time, self.creation_time)
                # credit the progress made between resumption time and now
                self.done_time += max(0, min(now - undamaged_time - delay_start, self.total_time - self.done_time))
            self.start_time = now + delay_start
        return self.is_complete(now)
    def is_complete(self, now):
        prog = self.done_time
        if self.start_time >= 0 and self.start_time <= now:
            prog += (now - self.start_time)
        return prog >= self.total_time

class CraftingBusiness(SingleBusiness):
    def __init__(self, craft_state = None, *args, **kwargs):
        SingleBusiness.__init__(self, *args, **kwargs)
        self.craft_state = craft_state
    def persist_state(self):
        ret = SingleBusiness.persist_state(self)
        ret['craft'] = self.craft_state
        return ret
    def unpersist_state(self, state):
        SingleBusiness.unpersist_state(self, state)
        self.craft_state = state['craft']
    def describe_state(self): return 'craft,'+self.craft_state['recipe'] # repr(self.craft_state)

class EnhanceBusiness(SingleBusiness):
    def __init__(self, enhance_state = None, *args, **kwargs):
        SingleBusiness.__init__(self, *args, **kwargs)
        self.enhance_state = enhance_state
    def persist_state(self):
        ret = SingleBusiness.persist_state(self)
        ret['enhance'] = self.enhance_state
        return ret
    def unpersist_state(self, state):
        SingleBusiness.unpersist_state(self, state)
        self.enhance_state = state['enhance']
    def describe_state(self): return 'enhance,%s,L%d' % (self.enhance_state['spec'], self.enhance_state['level'])

class QueuedBusiness(AbstractBusiness):
    def __init__(self, klass):
        self.klass = klass
        self.queue = []
    def persist_state(self):
        return {'queue': [x.persist_state() for x in self.queue]}
    def unpersist_state(self, state):
        self.queue = [reconstitute(self.klass, x) for x in state['queue']]
    def describe_state(self): return repr([x.describe_state() for x in self.queue])
    def speedup(self):
        for x in self.queue: x.speedup()
    def halt(self, now):
        ret = False
        for x in self.queue: ret |= x.halt(now)
        return ret
    def finish_time(self):
        t = -1
        for x in self.queue:
            fin = x.finish_time()
            if fin < 0: return -1 # will never finish
            t = max(t, fin)
        return t
    def resume(self, undamaged_time, now, delay_start = 0):
        # this is really tricky....
        ret = False
        delay = 0
        for x in self.queue:
            old_done_time = x.done_time # record previous progress
            ret |= x.resume(undamaged_time, now, delay_start = delay)
            delay = x.total_time - x.done_time # delay start of next action in queue by remaining time on preceding action
            if undamaged_time >= 0:
                undamaged_time += x.done_time - old_done_time # un-credit next action for progress accured to preceding action
        return ret

def test():
    CRAFT_STATE = {'recipe':'foo', 'iron':123}
    server_time = 10000
    job = CraftingBusiness(CRAFT_STATE, init_total_time = 100, init_start_time = server_time)
    print job.persist_state()
    assert not job.resume(-1, server_time)
    print job.persist_state()
    server_time += 25
    assert not job.resume(-1, server_time)
    print job.persist_state()
    server_time += 100
    assert job.resume(-1, server_time)
    assert job.finish_time() == 10100
    print job.persist_state()

    server_time = 10000
    job = CraftingBusiness(CRAFT_STATE, init_total_time = 100, init_start_time = server_time)
    server_time += 25
    assert job.halt(server_time)
    print job.persist_state()
    assert not job.resume(-1, server_time)
    assert job.finish_time() == 10100
    print job.persist_state()

    assert job.halt(server_time)
    server_time += 50
    assert not job.resume(-1, server_time)
    print job.persist_state()
    assert job.finish_time() == 10150

    server_time = 10000
    job = CraftingBusiness(CRAFT_STATE, init_total_time = 100, init_start_time = server_time)
    server_time += 25
    assert job.halt(server_time)
    print job.persist_state()

    server_time += 50
    assert not job.resume(10030, server_time)
    print job.persist_state()
    assert job.finish_time() == 10105

    server_time = 10000
    crafting = QueuedBusiness(CraftingBusiness)
    crafting.queue.append(CraftingBusiness(CRAFT_STATE, init_total_time = 100, init_start_time = server_time))
    crafting.queue.append(CraftingBusiness(CRAFT_STATE, init_total_time = 100, init_start_time = server_time+100))
    print crafting.persist_state()
    assert crafting.finish_time() == 10200

    server_time += 50
    assert not crafting.resume(-1, server_time)
    assert crafting.finish_time() == 10200
    assert crafting.halt(server_time)
    print crafting.persist_state()
    assert not crafting.resume(-1, server_time)
    assert crafting.finish_time() == 10200
    print crafting.persist_state()
    server_time += 100
    assert crafting.resume(-1, server_time)
    assert crafting.finish_time() == 10200
    assert crafting.halt(server_time)
    print crafting.persist_state()
    assert crafting.resume(-1, server_time)
    print crafting.persist_state()
    assert crafting.finish_time() == 10200

    server_time = 10000
    crafting = QueuedBusiness(CraftingBusiness)
    crafting.queue.append(CraftingBusiness(CRAFT_STATE, init_total_time = 100, init_start_time = server_time))
    crafting.queue.append(CraftingBusiness(CRAFT_STATE, init_total_time = 100, init_start_time = server_time+100))
    server_time += 25
    assert crafting.halt(server_time)
    server_time += 50
    assert not crafting.resume(10030, server_time)
    print crafting.persist_state()
    assert crafting.finish_time() == 10205

    server_time = 10000
    crafting = QueuedBusiness(CraftingBusiness)
    crafting.queue.append(CraftingBusiness(CRAFT_STATE, init_total_time = 100, init_start_time = server_time))
    crafting.queue.append(CraftingBusiness(CRAFT_STATE, init_total_time = 100, init_start_time = server_time+100))
    crafting.queue.append(CraftingBusiness(CRAFT_STATE, init_total_time = 100, init_start_time = server_time+200))
    server_time += 125
    assert crafting.halt(server_time)
    server_time += 50
    assert crafting.resume(10130, server_time)
    print crafting.persist_state()
    assert crafting.finish_time() == 10305

    server_time = 10000
    crafting = QueuedBusiness(CraftingBusiness)
    crafting.queue.append(CraftingBusiness(CRAFT_STATE, init_total_time = 100, init_start_time = server_time))
    crafting.queue.append(CraftingBusiness(CRAFT_STATE, init_total_time = 100, init_start_time = server_time+100))
    crafting.queue.append(CraftingBusiness(CRAFT_STATE, init_total_time = 100, init_start_time = server_time+200))
    server_time += 25
    assert crafting.halt(server_time)
    server_time += 500
    assert crafting.resume(10130, server_time)
    print crafting.persist_state()
    assert crafting.finish_time() == server_time

    # test for non-auto-complete jobs hanging out at front of queue -
    # make sure that the start_times for jobs added later are not
    # time-shifted forward before their own creation times!
    server_time = 10000
    crafting = QueuedBusiness(CraftingBusiness)
    crafting.queue.append(CraftingBusiness(CRAFT_STATE, init_total_time = 100, init_start_time = server_time))
    server_time += 500
    crafting.queue.append(CraftingBusiness(CRAFT_STATE, init_total_time = 100, init_start_time = server_time))
    assert crafting.finish_time() == server_time + 100
    assert crafting.halt(server_time)
    assert crafting.resume(0, server_time)
    assert crafting.finish_time() == server_time + 100

if __name__ == '__main__':
    test()


