#!/usr/bin/env python

# Copyright (c) 2015 SpinPunch Studios. All rights reserved.
# Use of this source code is governed by an MIT-style license that can be
# found in the LICENSE file.

# AWS REST API usage

import base64, time, calendar, hmac, hashlib
import socket, os, errno, fcntl
from urllib import urlencode
import requests

# wrap urlopen to loop on error since S3 sometimes throws occasional errors
MAX_RETRIES = 10
RETRY_DELAY = 2.0 # number of seconds between retry attempts
S3_REQUEST_TIMEOUT = 60 # timeout (seconds) on any one individual S3 request

class S3Exception(Exception): pass
class S3DummyException(S3Exception): pass # for stubbing out missing module exceptions
class S3TransportException(S3Exception):
    def __init__(self, e):
        self.e = e
    def __repr__(self):
        return 'S3TransportException(%s %s)' % (repr(type(self.e)), repr(self.e))

class S3404Exception(S3Exception):
    def __init__(self, bucket, filename):
        self.bucket = bucket
        self.filename = filename
    def __repr__(self):
        return 'S3404Exception("%s","%s")' % (self.bucket, self.filename)

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
                   'Content-Length': length,
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
        url, headers = self.get_request(bucket, filename)
        if not allow_keepalive:
            headers['Connection'] = 'close'
        attempt = 0
        err_msg = None
        while attempt < MAX_RETRIES:
            try:
                response = self.requests_session.get(url, headers = headers, stream = True, timeout = S3_REQUEST_TIMEOUT)
                if response.status_code == 404:
                    raise S3404Exception(bucket, filename)
                response.raise_for_status()

                if not allow_keepalive:
                    # remove nonblocking mode on the file descriptor
                    fdno = response.raw.fileno()
                    flags = fcntl.fcntl(fdno, fcntl.F_GETFL)
                    if flags & os.O_NONBLOCK:
                        flags = flags & ~os.O_NONBLOCK
                        fcntl.fcntl(fdno, fcntl.F_SETFL, flags)

                return response.raw
            except requests.exceptions.RequestException as e:
                err_msg = 'S3 get_open (requests) RequestException: %s' % repr(e)
                pass # retry
            except requests.exceptions.ConnectionError as e:
                err_msg = 'S3 get_open (requests) ConnectionError %s' % repr(e)
                pass # retry
            except requests.exceptions.HTTPError as e:
                err_msg = 'S3 get_open (requests) HTTPError: %s' % repr(e)
                if e.response.status_code == 500:
                    pass # retry
                else:
                    raise S3Exception(err_msg) # abort immediately
            except socket.timeout as e:
                err_msg = 'socket.timeout'
                pass # retry
            attempt += 1
            time.sleep(RETRY_DELAY)

        raise S3Exception('S3 get_open(%s,%s) giving up after %d HTTP errors, last one was: %s' % (bucket, filename, attempt, err_msg))

    # perform synchronous GET to disk file
    def get_file(self, bucket, filename, dest, bufsize=64*1024):
        attempt = 0
        err_msg = None
        while attempt < MAX_RETRIES:
            try:
                fd = self.get_open(bucket, filename)
                d = open(dest, 'w')

                while True:
                    try:
                        data = fd.read(bufsize)
                        if not data:
                            return # DONE!
                        d.write(data)
                    except requests.packages.urllib3.exceptions.TimeoutError as e:
                        break # retry

            except socket.error as e:
                if e.errno == errno.ECONNRESET:
                    err_msg = 'socket.error %s' % errno.errorcode[e.errno]
                    pass # retry
                else:
                    raise e # break immediately
            except socket.timeout as e:
                err_msg = 'socket.timeout'
                pass # retry
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 500:
                    err_msg = 'requests.exceptions.HTTPError status_code %d' % e.response.status_code
                    pass # retry
                else:
                    raise e # break immediately
            except requests.exceptions.ConnectionError as e:
                err_msg = 'requests.exceptions.ConnectionError %s' % repr(e)
                pass # retry
            # break immediately on any other exception

            attempt += 1
            time.sleep(RETRY_DELAY)

        # XXX delete file on error?
        raise S3Exception('S3 get_file(%s,%s,%s) giving up after %d HTTP errors, last one was: %s' % (bucket, filename, dest, attempt, err_msg))

    # synchronous check if an object exists in S3
    # if it exists, return the mtime as a UNIX timestamp, otherwise return False
    def exists(self, bucket, filename, has_read_permission = True):
        if has_read_permission:
            mtime_str = None

            # use HEAD method on object
            url, headers = self.get_request(bucket, filename, method = 'HEAD')
            attempt = 0
            err_msg = None
            while attempt < MAX_RETRIES:
                try:
                    response = self.requests_session.head(url, headers = headers, timeout = S3_REQUEST_TIMEOUT)
                    if response.status_code == 404:
                        return False
                    response.raise_for_status()
                    mtime_str = response.headers['Last-Modified']
                    break # GOOD!

                except requests.exceptions.RequestException as e:
                    err_msg = 'S3 exists (requests) RequestException: %s' % repr(e)
                    pass # retry
                except requests.exceptions.ConnectionError as e:
                    err_msg = 'S3 exists (requests) ConnectionError %s' % repr(e)
                    pass # retry
                except requests.exceptions.HTTPError as e:
                    err_msg = 'S3 exists (requests) HTTPError: %s' % repr(e)
                    if e.response.status_code == 500:
                        pass # retry
                    else:
                        raise S3Exception(err_msg) # abort immediately
                except socket.timeout as e:
                    err_msg = 'socket.timeout'
                    pass # retry
                attempt += 1
                time.sleep(RETRY_DELAY)

            if mtime_str is None:
                raise S3Exception('S3 exists(%s,%s) giving up after %d HTTP errors, last one was: %s' % (bucket, filename, attempt, err_msg))

            mtime = calendar.timegm(time.strptime(mtime_str, "%a, %d %b %Y %H:%M:%S GMT"))
            return mtime

        else:
            # with no read permission, use ListBucket instead
            ls = [x for x in self.list_bucket(bucket, prefix=filename, max_keys=1)]
            if len(ls) >= 1 and ls[0]['name'] == filename:
                return ls[0]['mtime']
            else:
                return False

    def get_slurp(self, bucket, filename, query = None):
        # get entire contents of an S3 object, retrying and looping upon error
        attempt = 0
        err_msg = None

        while attempt < MAX_RETRIES:

            old_timeout = socket.getdefaulttimeout()
            try:
                socket.setdefaulttimeout(S3_REQUEST_TIMEOUT)
                try:
                    url, headers = self.get_request(bucket, filename, query = query)
                    response = self.requests_session.get(url, headers = headers, timeout = S3_REQUEST_TIMEOUT)
                    if response.status_code == 404:
                        raise S3404Exception(bucket, filename) # abort immediately, do not retry
                    buf = response.content
                    response.raise_for_status()
                    if 'Content-Length' in response.headers:
                        assert len(buf) == int(response.headers['Content-Length'])
                    return buf
                except requests.exceptions.RequestException as e:
                    err_msg = 'S3 get_slurp (requests) RequestException: %s' % repr(e)
                    pass # retry
                except requests.exceptions.ConnectionError as e:
                    err_msg = 'S3 get_slurp (requests) ConnectionError %s' % repr(e)
                    pass # retry
                except requests.exceptions.HTTPError as e:
                    err_msg = 'S3 get_slurp (requests) HTTPError: %s' % repr(e)
                    if e.response.status_code == 500:
                        pass # retry
                    else:
                        raise S3Exception(err_msg) # abort immediately
                except socket.timeout as e:
                    err_msg = 'socket.timeout'
                    pass # retry

            finally:
                socket.setdefaulttimeout(old_timeout)

            attempt += 1
            time.sleep(RETRY_DELAY)

        raise S3Exception('S3 get_slurp giving up after %d HTTP errors, last one was: %s' % (attempt, err_msg))

    # synchronous DELETE
    def do_delete(self, bucket, filename):
        url, headers = self.delete_request(bucket, filename)
        if self.verbose: print 'DELETE', url
        response = self.requests_session.delete(url, headers = headers, timeout = S3_REQUEST_TIMEOUT)
        if response.status_code == 404:
            pass # ignore
        else:
            response.raise_for_status()
        return response.content

    # synchronous PUT from memory buffer
    def put_buffer(self, bucket, filename, raw_buf, **kwargs):
        return self.put_putbuf(bucket, filename, self.PutBuf(buf = raw_buf), **kwargs)

    def put_putbuf(self, bucket, filename, buf, **kwargs):
        url, headers = self.put_request_from_buf(buf, bucket, filename, **kwargs)
        if self.verbose: print 'PUT', len(buf.buffer()), 'bytes to', url

        attempt = 0
        err_msg = None
        while attempt < MAX_RETRIES:
            try:
                response = self.requests_session.put(url, headers = headers, data = buf.buffer(), timeout = S3_REQUEST_TIMEOUT)
                response.raise_for_status()
                return response.content
            except requests.exceptions.HTTPError as e:
                err_msg = 'S3 exists (requests) HTTPError: %s' % repr(e)
                if e.response.status_code == 500:
                    pass # retry
                else:
                    raise S3Exception(err_msg) # abort immediately
            attempt += 1
            time.sleep(RETRY_DELAY)

        raise S3Exception('S3 put_putbuf(%s,%s) giving up after %d HTTP errors, last one was: %s' % (bucket, filename, attempt, err_msg))


    # synchronous PUT from disk file
    def put_file(self, bucket, filename, source_filename, streaming = True, timeout = S3_REQUEST_TIMEOUT, **kwargs):
        fd = open(source_filename)
        if not streaming:
            buf = self.PutBuf()
            while True:
                r = fd.read(64*1024)
                if len(r) == 0: break
                buf.write(r)
            return self.put_putbuf(bucket, filename, buf)
        else:
            size = os.fstat(fd.fileno()).st_size
            url, headers = self.put_request(bucket, filename, size, **kwargs)
            attempt = 0
            while True:
                ret = -1
                err_msg = None

                old_timeout = socket.getdefaulttimeout()
                try:
                    socket.setdefaulttimeout(timeout)

                    response = self.requests_session.put(url, data=fd, headers=headers, timeout = S3_REQUEST_TIMEOUT)
                    response.raise_for_status()

                    ret = size # good! done!

                except Exception as e:
                    err_msg = '%s %s' % (repr(e), repr(type(e)))
                finally:
                    socket.setdefaulttimeout(old_timeout)

                if ret >= 0:
                    return ret

                attempt += 1
                if attempt > MAX_RETRIES:
                    raise S3Exception('S3 put_file giving up after %d HTTP errors, last one was: %s' % (attempt,err_msg))
                time.sleep(RETRY_DELAY) # give S3 time to unscrew itself
                fd.seek(0)


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
            wrote_data = con.do_delete(TEST_BUCKET, filename)
            print 'DELETE OK', wrote_data
