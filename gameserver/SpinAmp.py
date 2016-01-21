# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# this is a shim that allows the same IPC IDL to be used for both twisted.amp and ampy
# by converting a generic IDL into the one that each API expects

def init_for_twisted_amp(commands):
    from twisted.protocols import amp
    type_map = { 'string': amp.String(),
                 'unicode': amp.String(), # originally was amp.Unicode() - but I don't think Unicode is necessary for JSON strings
                 'boolean': amp.Boolean(),
                 'float': amp.Float(),
                 'integer': amp.Integer() }
    def convert_args(argdata):
        return [(x[0], type_map[x[1]]) for x in argdata]

    CMD = {}
    for name, data in commands.iteritems():
        CMD[name] = type(name,
                         (amp.Command,),
                         {'commandName': name,
                          'arguments': convert_args(data['arguments']),
                          'response': convert_args(data['response']),
                          'errors': convert_args(data.get('errors', ())),
                          'requiresAnswer': data.get('requiresAnswer', True)
                          })
    return CMD

def init_for_ampy(commands):
    import ampy
    type_map = { 'string': ampy.String(),
                 'unicode': ampy.String(), # originally was ampy.Unicode() - but I don't think Unicode is necessary for JSON strings
                 'boolean': ampy.Boolean(),
                 'float': ampy.Float(),
                 'integer': ampy.Integer() }
    def convert_args(argdata):
        return [(x[0], type_map[x[1]]) for x in argdata]

    CMD = {}
    for name, data in commands.iteritems():
        CMD[name] = type(name,
                         (ampy.Command,),
                         {'commandName': name,
                          'arguments': convert_args(data['arguments']),
                          'response': convert_args(data['response']),
                          'errors': convert_args(data.get('errors', ())),
                          'requiresAnswer': data.get('requiresAnswer', True)
                          })
    return CMD
