#!/usr/bin/env python

# Copyright (c) 2015 Battlehouse Inc. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# AWS REST API usage

import base64, time, calendar, hmac, hashlib
import socket, os, errno, fcntl
from urllib import urlencode
import requests
import AtomicFileWrite
import OpenSSL.SSL
import ssl

class S3Exception(Exception):
    def __init__(self, wrapped, ui_msg, op, bucket, filename, attempt_num):
        self.wrapped = wrapped
        self.ui_msg = ui_msg
        self.op = op
        self.bucket = bucket
        self.filename = filename
        self.attempt_num = attempt_num
    def __repr__(self):
        ret = '%s %s(%s,%s): %s' % (self.__class__.__name__, self.op, self.bucket, self.filename, self.ui_msg)
        if self.attempt_num > 0:
            ret += ' (after %d retries)' % self.attempt_num
        return ret

class S3404Exception(S3Exception): pass

class BadDataException(Exception): pass # to be wrapped inside an S3Exception

# need retry logic since S3 sometimes throws errors
MAX_RETRIES = 10
RETRY_DELAY = 2.0 # number of seconds between retry attempts
S3_REQUEST_TIMEOUT = 60 # timeout (seconds) on any one individual S3 request

class Policy404(object):
    # what to do when server returns 404
    RAISE = 0
    IGNORE = 1

# note: assumes "func" returns a requests response object, or None if you don't care about HTTP errors
def retry_logic(func_name, bucket, filename, policy_404, func, *args, **kwargs):
    attempt = 0
    last_err = None

    while attempt < MAX_RETRIES:
        try:
            response = func(*args, **kwargs)
            if response is None: # quiet success
                return None
            if response.status_code == 404:
                if policy_404 == Policy404.RAISE:
                    raise S3404Exception(None, '404 Not Found', func_name, bucket, filename, attempt)
                elif policy_404 == Policy404.IGNORE:
                    pass
            else:
                response.raise_for_status()
            return response

        except requests.exceptions.HTTPError as e:
            last_err = S3Exception(e, 'requests.exceptions.HTTPError: %r Headers %r Content %r' % (e, e.response.headers, e.response.content), func_name, bucket, filename, attempt)
            if e.response.status_code in (500, 503):
                pass # retry on 500 Internal Server Error or 503 Service Unavailable
            elif e.response.status_code == 400 and e.response.content and ('RequestTimeout' in e.response.content):
                pass # retry on <Error><Code>RequestTimeout</Code><Message>Your socket connection to the server was not read from or written to within the timeout period. Idle connections will be closed.</Message>
            else:
                raise last_err # abort immediately

        except requests.exceptions.RequestException as e:
            last_err = S3Exception(e, 'requests.exceptions.RequestException: %r' % e, func_name, bucket, filename, attempt)
            pass # retry
        except requests.exceptions.ConnectionError as e:
            last_err = S3Exception(e, 'requests.exceptions.ConnectionError: %r' % e, func_name, bucket, filename, attempt)
            pass # retry

        except OpenSSL.SSL.SysCallError as e:
            last_err = S3Exception(e, 'OpenSSL.SSL.SysCallError: %r' % e, func_name, bucket, filename, attempt)
            if e.args in ((errno.EPIPE, 'EPIPE'), (errno.ECONNRESET, 'ECONNRESET')):
                pass # retry
            else:
                raise last_err # abort immediately

        except ssl.SSLError as e:
            last_err = S3Exception(e, 'ssl.SSLError: %r' % e, func_name, bucket, filename, attempt)
            pass # retry

        except socket.timeout as e:
            last_err = S3Exception(e, 'socket.timeout', func_name, bucket, filename, attempt)
            pass # retry
        except socket.error as e:
            last_err = S3Exception(e, 'socket.error: %r %s' % (e, errno.errorcode.get(e.errno,'Unknown')), func_name, bucket, filename, attempt)
            if e.errno == errno.ECONNRESET:
                pass # retry
            else:
                raise last_err # abort immediately
        except BadDataException as e:
            last_err = S3Exception(e, 'SpinS3.BadDataException', func_name, bucket, filename, attempt)
            pass # retry

        attempt += 1
        time.sleep(RETRY_DELAY)

    raise last_err

# hack - patch HTTPResponse to support usage as a standard Python file object
import httplib
@property
def http_fileno(self):
    return self.fp.fileno
@http_fileno.setter
def http_fileno(self, value):
    self.fp.fileno = value
httplib.HTTPResponse.fileno = http_fileno
@property
def http_seekable(self):
    return False
httplib.HTTPResponse.seekable = http_seekable

class S3 (object):

    def __init__(self, keyfile, verbose = False, robust = True, use_ssl = False):
        self.verbose = verbose
        self.use_ssl = use_ssl
        lines = open(keyfile).readlines()
        self.key = lines[0].strip()
        self.secret = lines[1].strip()
        self.requests_session = requests.Session()

    def protocol(self): return 'https://' if self.use_ssl else 'http://'
    def bucket_endpoint(self, bucket):
        if True: # NEW - necessary for read-after-write consistency (?)
            # note: hardcoded to US-EAST-1
            return self.protocol()+'s3-external-1.amazonaws.com/'+bucket
        else: # OLD
            return self.protocol()+bucket+'.s3.amazonaws.com'

    # the CanonicalResource for inclusion in the request signature
    # filename = '' for operations on root
    # see http://docs.aws.amazon.com/AmazonS3/latest/dev/RESTAuthentication.html
    def resource_name(self, bucket, filename):
        resource = ''
        if self.bucket_endpoint(bucket).endswith('amazonaws.com'): # Virtual host-style
            resource += '/'+bucket
            if filename:
                resource += '/'+filename
            else:
                resource += '/'
        else: # path-style
            resource += '/'+bucket
            if filename:
                resource += '/'+filename
        return resource

    # get/put_request do not actually perform I/O, they just return the right URLs and HTTP headers to use
    # filename = '' for operations on root
    def get_request(self, bucket, filename, method = 'GET', query = None):
        url = self.bucket_endpoint(bucket)
        if filename:
            url += '/'+filename
        resource = self.resource_name(bucket, filename)
        if query:
            url += '?'+urlencode(query)

        date = time.strftime('%a, %d %b %Y %X GMT', time.gmtime())
        sig_data = method+'\n\n\n'+date+'\n'+resource
        signature = base64.encodestring(hmac.new(self.secret, sig_data, hashlib.sha1).digest()).strip()
        auth_string = 'AWS '+self.key+':'+signature
        headers = {'Date': date,
                   'Authorization': auth_string}
        return url, headers

    def head_request(self, bucket, filename, query = None):
        return self.get_request(bucket, filename, method = 'HEAD', query=query)

    def delete_request(self, bucket, filename):
        url = self.bucket_endpoint(bucket)+'/'+filename
        resource = self.resource_name(bucket, filename)
        date = time.strftime('%a, %d %b %Y %X GMT', time.gmtime())
        sig_data = 'DELETE\n\n\n'+date+'\n'+resource
        signature = base64.encodestring(hmac.new(self.secret, sig_data, hashlib.sha1).digest()).strip()
        auth_string = 'AWS '+self.key+':'+signature
        headers = {'Date': date,
                   'Authorization': auth_string}
        return url, headers

    def put_request(self, bucket, filename, length, md5sum = '', content_type = 'text/plain', acl = ''):
        md5sum_b64 = base64.encodestring(md5sum).strip() if md5sum else ''
        url = self.bucket_endpoint(bucket)+'/'+filename
        resource = self.resource_name(bucket, filename)
        date = time.strftime('%a, %d %b %Y %X GMT', time.gmtime())
        acl_sig = 'x-amz-acl:'+acl+'\n' if acl else ''
        sig_data = 'PUT\n'+md5sum_b64+'\n'+content_type+'\n'+date+'\n'+acl_sig+resource
        #print 'SIG DATA'
        #print sig_data
        signature = base64.encodestring(hmac.new(self.secret, sig_data, hashlib.sha1).digest()).strip()
        auth_string = 'AWS '+self.key+':'+signature
        headers = {'Date': date,
                   'Content-Type': content_type,
                   'Content-Length': unicode(length),
                   'Authorization': auth_string}
        if md5sum: headers['Content-MD5'] = md5sum_b64
        if acl: headers['x-amz-acl'] = acl
        return url, headers

    # putbuf/put_request_from_buf encapsulate an in-memory buffer, necessary for the mandatory length and
    # optional MD5 argument for PUT requests
    class PutBuf(object):
        def __init__(self, buf = None):
            self.md5 = hashlib.md5()
            if buf:
                self.buf = buf
                self.md5.update(buf)
            else:
                self.buf = str()
        def write(self, data):
            self.buf += data
            self.md5.update(data)
        def buffer(self): return self.buf

    def put_request_from_buf(self, obj, bucket, filename, **kwargs):
        return self.put_request(bucket, filename, len(obj.buf), md5sum = obj.md5.digest(), **kwargs)

    # perform a synchronous GET and return streaming file-like object
    # note! if sharing this socket with an external process like gzip, set allow_keepalive = False,
    # otherwise the socket will not be closed when the server has finished sending all data.
    def get_open(self, bucket, filename, allow_keepalive = True):
        response = retry_logic('get_open', bucket, filename, Policy404.RAISE,
                               self.do_get_open, bucket, filename, allow_keepalive)

        if not allow_keepalive:
            # remove nonblocking mode on the file descriptor
            fdno = response.raw.fileno()
            flags = fcntl.fcntl(fdno, fcntl.F_GETFL)
            if flags & os.O_NONBLOCK:
                flags = flags & ~os.O_NONBLOCK
                fcntl.fcntl(fdno, fcntl.F_SETFL, flags)

        return response.raw

    def do_get_open(self, bucket, filename, allow_keepalive):
        url, headers = self.get_request(bucket, filename)
        if not allow_keepalive:
            headers['Connection'] = 'close'
        return self.requests_session.get(url, headers=headers, stream = True, timeout = S3_REQUEST_TIMEOUT)

    # perform synchronous GET to disk file
    def get_file(self, bucket, filename, dest, bufsize=64*1024):
        retry_logic('get_file', bucket, filename, Policy404.RAISE,
                    self.do_get_file, bucket, filename, dest, bufsize)
    def do_get_file(self, bucket, filename, dest, bufsize):
        fd = self.get_open(bucket, filename)
        atom = AtomicFileWrite.AtomicFileWrite(dest, 'w')

        try:
            while True:
                try:
                    data = fd.read(bufsize)
                    if data:
                        atom.fd.write(data)
                    else: # DONE!
                        atom.complete()
                        return

                except requests.packages.urllib3.exceptions.TimeoutError:
                    break # retry forever here
        except:
            # delete file on error
            atom.abort()

    # synchronous check if an object exists in S3
    # if it exists, return the mtime as a UNIX timestamp, otherwise return False
    def exists(self, bucket, filename, has_read_permission = True):
        if has_read_permission:
            mtime_str = None

            # use HEAD method on object
            response = retry_logic('exists', bucket, filename, Policy404.IGNORE,
                                   self.do_exists, bucket, filename)
            if response.status_code == 404:
                return False
            mtime_str = response.headers['Last-Modified']
            mtime = calendar.timegm(time.strptime(mtime_str, "%a, %d %b %Y %H:%M:%S GMT"))
            return mtime

        else:
            # with no read permission, use ListBucket instead
            ls = [x for x in self.list_bucket(bucket, prefix=filename, max_keys=1)]
            if len(ls) >= 1 and ls[0]['name'] == filename:
                return ls[0]['mtime']
            else:
                return False
    def do_exists(self, bucket, filename):
        url, headers = self.head_request(bucket, filename)
        return self.requests_session.head(url, headers=headers, timeout = S3_REQUEST_TIMEOUT)

    # get entire contents of an S3 object
    def get_slurp(self, bucket, filename, query = None):
        response = retry_logic('get_slurp', bucket, filename, Policy404.RAISE,
                               self.do_get_slurp, bucket, filename, query)
        return response.content

    def do_get_slurp(self, bucket, filename, query):
        url, headers = self.get_request(bucket, filename, query = query)
        response = self.requests_session.get(url, headers=headers, timeout = S3_REQUEST_TIMEOUT)
        buf = response.content
        if 'Content-Length' in response.headers:
            content_length = long(response.headers['Content-Length'])
            if len(buf) != content_length:
                raise BadDataException('Content-Length %d mismatches data size %d' % (len(buf), content_length))
        return response

    # synchronous DELETE
    def delete(self, bucket, filename):
        if self.verbose: print 'DELETE', bucket, filename
        response = retry_logic('delete', bucket, filename, Policy404.IGNORE,
                               self.do_delete, bucket, filename)
        return response.content
    def do_delete(self, bucket, filename):
        url, headers = self.delete_request(bucket, filename)
        return self.requests_session.delete(url, headers=headers, timeout = S3_REQUEST_TIMEOUT)

    # synchronous PUT from memory buffer
    def put_buffer(self, bucket, filename, raw_buf, **kwargs):
        return self.put_putbuf(bucket, filename, self.PutBuf(buf = raw_buf), **kwargs)

    def put_putbuf(self, bucket, filename, buf, **kwargs):
        if self.verbose: print 'PUT', len(buf.buffer()), 'bytes to', bucket, filename
        response = retry_logic('put_putbuf', bucket, filename, Policy404.RAISE,
                               self.do_put_putbuf, bucket, filename, buf, kwargs)
        return response.content
    def do_put_putbuf(self, bucket, filename, buf, kwargs):
        url, headers = self.put_request_from_buf(buf, bucket, filename, **kwargs)
        return self.requests_session.put(url, headers=headers, data=buf.buffer(), timeout = S3_REQUEST_TIMEOUT)

    # synchronous PUT from disk file
    # optionally override timeout for slow/big streaming uploads
    def put_file(self, bucket, filename, source_filename, streaming = True, timeout = S3_REQUEST_TIMEOUT, **kwargs):
        fd = open(source_filename, 'rb')
        if not streaming:
            buf = self.PutBuf()
            while True:
                r = fd.read(64*1024)
                if len(r) == 0: break
                buf.write(r)
            return self.put_putbuf(bucket, filename, buf)
        else:
            size = os.fstat(fd.fileno()).st_size
            retry_logic('put_file', bucket, filename, Policy404.RAISE,
                        self.do_put_file_streaming, bucket, filename, size, fd, timeout, kwargs)
            return size

    def do_put_file_streaming(self, bucket, filename, size, fd, timeout, kwargs):
        fd.seek(0)
        url, headers = self.put_request(bucket, filename, size, **kwargs)
        return self.requests_session.put(url, data=fd, headers=headers, timeout = timeout)

    # synchronous bucket listing
    def list_bucket(self, bucket, prefix='', max_keys = 1000):
        import xml.dom.minidom # for parsing XML list results
        truncated = True
        marker = None
        while truncated:
            query = {'max-keys': str(max_keys)}
            if marker: query['marker'] = marker
            if prefix: query['prefix'] = prefix
            read_data = self.get_slurp(bucket, '', query = query)
            dom = xml.dom.minidom.parseString(read_data)
            truncated = dom.getElementsByTagName('IsTruncated')[0].childNodes[0].data == 'true'
            for cont in dom.getElementsByTagName('Contents'):
                name = cont.getElementsByTagName('Key')[0].childNodes[0].data
                marker = name
                mtime_str = cont.getElementsByTagName('LastModified')[0].childNodes[0].data
                mtime = calendar.timegm(time.strptime(mtime_str.split('.')[0], '%Y-%m-%dT%H:%M:%S'))
                size = int(cont.getElementsByTagName('Size')[0].childNodes[0].data)
                yield {'name': name, 'mtime': mtime, 'size': size}

if __name__ == '__main__':
    MAX_RETRIES = 1
    TEST_BUCKET = 'spinpunch-scratch'
    TEST_KEY_FILE = os.getenv('HOME')+'/.ssh/'+os.getenv('USER')+'-awssecret'

    # GET
    con = S3(TEST_KEY_FILE)
    #con.secret='A' to test failures
    read_data = con.get_slurp(TEST_BUCKET, 'hello.txt')
    assert read_data == 'Hello!\n'
    print 'READ (slurp) OK', len(read_data), 'bytes'

    con.get_file(TEST_BUCKET, 'hello.txt', '/tmp/hello.txt')
    assert open('/tmp/hello.txt').read() == 'Hello!\n'
    print 'READ (file) OK'

    try:
        read_fd = con.get_open(TEST_BUCKET, 'hello.txt-badfile')
        assert 0
    except S3404Exception:
        print '404 get_open CHECK OK'
        pass

    try:
        read_slurp = con.get_slurp(TEST_BUCKET, 'hello.txt-badfile')
        assert 0
    except S3404Exception:
        print '404 get_slurp CHECK OK'
        pass

    try:
        con.get_file(TEST_BUCKET, 'hello.txt-badfile', '/tmp/zzz-badfile')
        assert 0
    except S3404Exception:
        print '404 get_file CHECK OK'
        pass

    read_data = ''
    read_fd = con.get_open(TEST_BUCKET, 'hello.txt')
    while True:
        buf = read_fd.read()
        if not buf: break
        read_data += buf
    assert read_data == 'Hello!\n'
    print 'READ (streaming) OK', len(read_data), 'bytes'

    for perm in (True, False):
        assert con.exists(TEST_BUCKET, 'hello.txt', has_read_permission=perm)
        assert not con.exists(TEST_BUCKET, 'should-not-exist.txt', has_read_permission=perm)
        print "EXISTS CHECK OK perm", perm

    # PUT by buffer
    buf = ''
    fd = open('test-facebook-likes.txt')
    while True:
        r = fd.read(64*1024)
        if not r: break
        buf += r
    wrote_data = con.put_buffer(TEST_BUCKET, 'testdir/zzz.txt', buf, acl='public-read')
    print 'PUT (buf) OK', wrote_data

    # PUT by file
    wrote_data = con.put_file(TEST_BUCKET, 'testdir/zzz2.txt', 'test-facebook-likes.txt', acl='public-read', streaming = True)
    print 'PUT (file, streaming) OK', wrote_data

    # list bucket
    print 'LIST'
    for data in con.list_bucket(TEST_BUCKET, prefix='testdir/', max_keys=1):
        print data
    print 'OK'

    # DELETE
    if 1:
        for filename in ('testdir/zzz.txt', 'testdir/zzz2.txt'):
            wrote_data = con.delete(TEST_BUCKET, filename)
            print 'DELETE OK', wrote_data
