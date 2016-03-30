#!/usr/bin/env python

# Scan a JSON structure for the largest absolute-valued numbers.
# This is used to debug long-int serialization problems.

class OverflowChecker(object):
    def __init__(self, obj):
        # "int" here means "int or long"
        self.largest_int_name = None
        self.largest_int_val = 0
        self.largest_float_name = None
        self.largest_float_val = 0
        self.find_largest(obj)

    def find_largest(self, obj, path=''):
        if obj in (None,True,False) or isinstance(obj, basestring):
            return
        elif isinstance(obj, int) or isinstance(obj, long):
            val = abs(obj)
            if val > self.largest_int_val:
                self.largest_int_val = val
                self.largest_int_name = path
        elif isinstance(obj, float):
            val = abs(obj)
            if val > self.largest_float_val:
                self.largest_float_val = val
                self.largest_float_name = path
        elif isinstance(obj, list):
            for i, entry in enumerate(obj):
                self.find_largest(entry, path = path + ('[%d]'%i))
        elif isinstance(obj, dict):
            for k,v in obj.iteritems():
                self.find_largest(v, path = path + '.' + k)
        else:
            raise Exception('unhandled: %r' % obj)

    def __repr__(self):
        return 'Largest int or long: %s %r ... Largest float: %s %r' % \
               (self.largest_int_name, self.largest_int_val,
                self.largest_float_name, self.largest_float_val)

if __name__ == '__main__':
    import SpinJSON, sys
    print OverflowChecker(SpinJSON.load(open(sys.argv[1])))


