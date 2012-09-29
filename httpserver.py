#! /usr/bin/env python
#coding=utf-8

'''
by Lerry  http://lerry.org
Start from 2011/07/27 22:49:51
Last edit at 2012/09/29
'''
import os
import posixpath
import urllib
import mimetypes
import email.utils
import shutil
import time
from BaseHTTPServer import HTTPServer
from SimpleHTTPServer import SimpleHTTPRequestHandler
from SocketServer import ThreadingMixIn
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

def parse_date(ims):
    """ Parse rfc1123, rfc850 and asctime timestamps and return UTC epoch. """
    try:
        ts = email.utils.parsedate_tz(ims)
        return time.mktime(ts[:8] + (0,)) - (ts[9] or 0) - time.timezone
    except (TypeError, ValueError, IndexError, OverflowError):
        return None

def get_mime_type(filename):
    #get mimetype by filename, if none, see as bin file
    mime, encoding = mimetypes.guess_type(filename)
    #add type not supported by gues_type
    if filename.split('.')[-1] in ('py','conf','ini','md','log','vim'):
        mime = 'text/plain'
    return 'application/octet-stream' if not mime else mime

def parse_range_header(header, flen=0):
    ranges = header['range']
    start, end = ranges.strip('bytes=').split('-')
    #print start, end
    try:
        if not start:  # bytes=-100    -> last 100 bytes
            start, end = max(0, flen-int(end)), flen
        elif not end:  # bytes=100-    -> all but the first 99 bytes
           start, end = int(start), flen
        else:          # bytes=100-200 -> bytes 100-200 (inclusive)
            start, end = int(start), min(int(end)+1, flen)
        if 0 <= start < end <= flen:
            return start, end
    except ValueError:
        pass
    return None,None


def _file_iter_range(fp, offset, bytes, maxread=1024*1024):
    ''' Yield chunks from a range in a file. No chunk is bigger than maxread.'''
    fp.seek(offset)
    return fp.read(bytes)
    while bytes > 0:
        part = fp.read(min(bytes, maxread))
        if not part: break
        bytes -= len(part)
        #yield part

def get_handler(root_path):
    class _RerootedHTTPRequestHandler(SimpleHTTPRequestHandler):
        def send_response1(self, code, message=None):
            """Send the response header and log the response code.
    
            Also send two standard headers with the server software
            version and the current date.
    
            """
            self.log_request(code)
            if message is None:
                if code in self.responses:
                    message = self.responses[code][0]
                else:
                    message = ''
            if self.request_version != 'HTTP/0.9':
                self.wfile.write("%s %d %s\r\n" %
                                 (self.protocol_version, code, message))
                # print (self.protocol_version, code, message)
            self.send_header('Server', self.version_string())
            self.send_header('Date', self.date_time_string())
    
        def send_header1(self, keyword, value):
            """Send a MIME header."""
            if self.request_version != 'HTTP/0.9':
                self.wfile.write("%s: %s\r\n" % (keyword, value))
    
            if keyword.lower() == 'connection':
                if value.lower() == 'close':
                    self.close_connection = 1
                elif value.lower() == 'keep-alive':
                    self.close_connection = 0

        def copyfile(self, src_data, dst):
            shutil.copyfileobj(src_data, dst)
            #dst.write(src_data)

        def do_GET(self):
            """Serve a GET request."""
            f = self.send_head()
            if f:
                self.copyfile(f, self.wfile)
                f.close()
    
        def do_HEAD(self):
            """Serve a HEAD request."""
            f = self.send_head()
            if f:
                f.close()
        def send_head(self):
            """Common code for GET and HEAD commands.
    
            This sends the response code and MIME headers.
    
            Return value is either a file object (which has to be copied
            to the outputfile by the caller unless the command was HEAD,
            and must be closed by the caller under all circumstances), or
            None, in which case the caller has nothing further to do.
    
            """
            path = self.translate_path(self.path)
            f = None
            if os.path.isdir(path):
                if not self.path.endswith('/'):
                    # redirect browser - doing basically what apache does
                    self.send_response(301)
                    self.send_header("Location", self.path + "/")
                    self.end_headers()
                    return None
                for index in "index.html", "index.htm":
                    index = os.path.join(path, index)
                    if os.path.exists(index):
                        path = index
                        break
                else:
                    #print self.list_directory(path)
                    return self.list_directory(path)
            
            mimetype = get_mime_type(path)            
            root = os.path.abspath(root_path)

            if not path.startswith(root):
                self.send_error(403, "Access denied.")
                return None
            if not os.path.exists(path) or not os.path.isfile(path):
                self.send_error(404, "File does not exist.")
                return None
            if not os.access(path, os.R_OK):
                self.send_error(403, "You do not have permission to access this file.")
                return None

            headers = dict(self.headers)
            fs = os.stat(path)

            self.send_header("Content-Length", str(fs[6]))
            self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
            self.send_header("Accept-Ranges", "bytes")   

            if 'if-modified-since' in headers:
                ims = headers['if-modified-since'] 
                ims = parse_date(ims.split(";")[0].strip())
                if ims >= int(fs.st_mtime):
                    self.send_response(304)
                    self.send_header('Date', time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime()))
                    self.end_headers()
                    return None

            if 'range' in headers:
                self.send_response(206)
                start, end = parse_range_header(headers, fs.st_size)
                if start!=None and end!=None:
                    f = open(path, 'rb')
                    #if f: f = _file_iter_range(f, start, end-start)
                    f.seek(start)
                    f = f.read(end-start)
                    self.send_header("Content-Range","bytes %d-%d/%d" % (start, end-1, fs.st_size))
                    self.send_header("Content-Length", str(end-start))
                else:
                    self.send_error(416, "Requested Range Not Satisfiable")
                    return None
            else:
                self.send_response(200)
                f = open(path, 'rb').read()
            if mimetype:
                self.send_header("Content-type", mimetype)
            #if encoding:
            #    self.send_header("Content-Encoding", encoding)
            self.end_headers()
            result = StringIO()
            result.write(f)
            result.seek(0)
            return result        

        def translate_path(self, path):
            path = path.split('?',1)[0]
            path = path.split('#',1)[0]
            path = posixpath.normpath(urllib.unquote(path))
            words = path.split('/')
            words = filter(None, words)
            path = root_path#os.getcwd()
            for word in words:
                drive, word = os.path.splitdrive(word)
                head, word = os.path.split(word)
                if word in (os.curdir, os.pardir): continue
                path = os.path.join(path, word)
            #self._test()    
            return path

        def _test(self):
            headers = str(self.headers).split()
            print 'Range' in self.headers
            for index,data in enumerate(headers):
                #print data
                if data.strip().lower().startswith('range'):#.startswith('range:'):
                    #print data, headers[index+1]
                    pass
            #print str(headers)
    return _RerootedHTTPRequestHandler
        
class ThreadingServer(ThreadingMixIn, HTTPServer):
    pass
    
    
def run(port=8080, doc_root=os.getcwd()):
    serveraddr = ('', port)
    serv = ThreadingServer(serveraddr, get_handler(doc_root))
    print 'Server Started at port:', port
    serv.serve_forever()

def test():
    import doctest
    print doctest.testmod()

if __name__=='__main__':
    run()
