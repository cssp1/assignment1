#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

import sys, os, fcntl, select, traceback, signal, cStringIO, errno, struct
from multiprocessing import cpu_count

import SpinJSON

PIPE_BUF = 4096 # should be select.PIPE_BUF

def set_non_blocking(fd):
    f = fcntl
    nb = os.O_NONBLOCK
    oldflags = f.fcntl(fd, f.F_GETFL)
    f.fcntl(fd, f.F_SETFL, oldflags | nb)

# To determine message boundaries when reading continuous input from a slave's output pipe,
# the slave writes a 64-bit message length as the first 8 bytes of its output.
def slave_send(fd, msg):
    fd.write(struct.pack('>Q',len(msg)))
    fd.write(msg)
    fd.flush()

def go(tasks, argv, nprocs = -1, on_error = 'break', verbose = False):
    if nprocs < 0: nprocs = cpu_count()
    pids = []
    pid_fds = {}
    read_fds = {}
    write_fds = {}
    read_buffers = {}

    results = {}
    task_num = 0

    for i in xrange(nprocs):
        down_rd, down_wr = os.pipe()
        up_rd, up_wr = os.pipe()
        pid = os.fork()
        if pid < 0:
            raise Exception("fork() error")
        elif pid == 0:
            # child
            os.dup2(down_rd, sys.stdin.fileno())
            os.close(down_wr)
            os.dup2(up_wr, sys.stdout.fileno())
            os.close(up_rd)
            os.execv(argv[0], argv)
            sys.exit(0)
        else:
            # parent
            if verbose: print 'STARTUP', pid
            pids.append(pid)
            os.close(down_rd)
            os.close(up_wr)
            read_fds[up_rd] = i
            set_non_blocking(up_rd)
            read_buffers[up_rd] = cStringIO.StringIO()
            write_fds[down_wr] = i
            pid_fds[pid] = [up_rd,down_wr]

    stop = False
    report_error = None

    while (len(results) < len(tasks)) and (not stop):
        try:
            readable, writable, errors = select.select(read_fds.keys(), [], read_fds.keys() + write_fds.keys())

            for fd in errors:
                child_num = read_fds[fd] if (fd in read_fds) else write_fds[i]
                raise Exception("FD error on child %d" % child_num)
            for fd in readable:
                child_num = read_fds[fd]
                complete = False

                while True:
                    try:
                        r = os.read(fd, PIPE_BUF)
                    except OSError as e:
                        if e.errno == errno.EAGAIN: # incomplete input
                            break
                        else:
                            raise
                    if not r: # no more to read, or a closed socket
                        complete = True
                        break

                    # accumulate read buffer
                    read_buffers[fd].write(r)

                    # check for complete 8-byte length prefix
                    cur_len = read_buffers[fd].tell()
                    if cur_len >= 8:
                        read_buffers[fd].seek(0,0) # seek to beginning
                        val = read_buffers[fd].read(8)
                        read_buffers[fd].seek(cur_len,0) # return to where we were
                        client_len = struct.unpack('>Q', val)[0]
                        if cur_len-8 >= client_len:
                            # complete input (note: assumes client hasn't gone ahead and written anything else
                            complete = True
                            break
                    if len(r) < PIPE_BUF: # incomplete read
                        break

                if not complete:
                    continue

                read_buffers[fd].seek(8,0) # skip length prefix
                buf = read_buffers[fd].read() # get actual data
                read_buffers[fd] = cStringIO.StringIO() # reset the read buffer

                if verbose: print 'CHILD', child_num, 'SAYS', buf

                if not buf:
                    sys.stderr.write('child process closed the pipe unexpectedly')
                    continue

                try:
                    ret = SpinJSON.loads(buf)
                except:
                    stop = True
                    report_error = 'child sent bad result: "'+buf+'"'
                    continue

                if ret['response'] == 'compute':
                    for i in xrange(len(ret['result_nums'])):
                        status = ret['status'][i]
                        if status == 'error':
                            if on_error == 'break':
                                stop = True
                                report_error = ret['errors'][i]
                            else:
                                sys.stderr.write('ignoring error from child process: '+ret['errors'][i])

                        num = ret['result_nums'][i]
                        results[num] = ret['results'][i]

                if (task_num < len(tasks)) and (not stop):
                    task = tasks[task_num]
                    wr_fd = pid_fds[pids[child_num]][1]
                    if verbose: print 'TASK', task, 'ON CHILD', child_num
                    buf = SpinJSON.dumps({'command':'compute',
                                          'on_error': on_error,
                                          'task_nums': [task_num],
                                          'tasks': [task]},
                                         newline = True)
                    os.write(wr_fd, buf)
                    task_num += 1

        except KeyboardInterrupt:
            print 'INTERRUPTING'
            stop = True
            report_error = 'manual interrupt'

    # shutdown
    for i in xrange(nprocs):
        pid = pids[i]
        if verbose: print 'SHUTDOWN', pid
        try:
            os.write(pid_fds[pid][1], SpinJSON.dumps({'command':'halt'}, newline = True))
            os.close(pid_fds[pid][1])
        except:
            pass
        pid, status = os.waitpid(pid, 0)
        if not (os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0):
            raise Exception("error in child process %d" % pid)
        os.close(pid_fds[pid][0])

    if report_error:
        raise Exception('error: '+report_error)

    return [results.get(i, None) for i in xrange(len(tasks))]

def slave(func, verbose = False):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if verbose: sys.stderr.write('I AM SLAVE %d\n' % os.getpid())
    slave_send(sys.stdout, SpinJSON.dumps({'response':'ready'}, newline = True))

    stop = False
    while (not stop):
        command = sys.stdin.readline()
        if verbose: sys.stderr.write('SLAVE '+repr(command)+'\n')
        if not command: break
        command = SpinJSON.loads(command)
        if command['command'] == 'halt': break
        on_error = command['on_error']
        tasks = command['tasks']
        result_nums = []
        results = []
        status = []
        errors = []
        for i in xrange(len(tasks)):
            task = tasks[i]
            task_num = command['task_nums'][i]
            result_nums.append(task_num)
            try:
                if task == 'inject_error':
                    raise Exception('deliberately injected error')
                else:
                    ret = func(task)
            except Exception as e:
                status.append('error')
                errors.append('%r\n%s' % (e, traceback.format_exc()))
                results.append(None)
                if on_error == 'break':
                    break
            else:
                status.append('OK')
                errors.append(None)
                results.append(ret)

        msg = SpinJSON.dumps({'response':'compute',
                              'status': status,
                              'errors': errors,
                              'result_nums': result_nums,
                              'results':results},
                             newline = True)
        slave_send(sys.stdout, msg)
        if verbose: sys.stderr.write('SLAVE '+repr(command)+' WROTE\n')

def my_slave(input):
    if 0:
        import time
        time.sleep(2)
    return 2*input

if __name__ == '__main__':
    if '--slave' in sys.argv:
        slave(my_slave)
        sys.exit(0)
    input = range(7)
    input[5] = 'inject_error'
    ret = go(input, [sys.argv[0], '--slave'], on_error = 'continue')
    print 'DONE', ret
