import http.cookiejar as cookielib
import urllib
import urllib.request as urllib2
import time
import os
from http.client import BadStatusLine
from excpetions import ServerResponseEmpty

SMART_QQ_REFER = "http://d1.web2.qq.com/proxy.html?v=20030916001&callback=1&id=2"
COOKIE_FILE = 'cookie/cookie.data'

class HttpClient(object):
    _cookie = cookielib.LWPCookieJar(COOKIE_FILE)
    _req = urllib2.build_opener(urllib2.HTTPCookieProcessor(_cookie))
    _req.addheaders = [
        ('Accept', 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'),
        ('User-Agent',
         "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_3) "
         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/47.0.2526.111 Safari/537.36"),
        ('Referer', 'http://s.web2.qq.com/proxy.html?v=20130916001&callback=1&id=1')
    ]
    urllib2.install_opener(_req)

    def __init__(self, load_cookie=False):
        if not os.path.isdir("./cookie"):
            os.mkdir("./cookie")
        if load_cookie:
            self.load_cookie()

    def load_cookie(self):
        try:
            self._cookie.load(ignore_discard=True, ignore_expires=True)
        except Exception:
            self._cookie.save(ignore_discard=True, ignore_expires=True)

    @staticmethod
    def get_timestamp():
        return str(int(time.time()*1000))

    def get(self, url, refer=None):
        try:
            req = urllib2.Request(url)
            req.add_header('Referer', refer or SMART_QQ_REFER)
            tmp_req = urllib2.urlopen(req)
            self._cookie.save('cookie/cookie.data',ignore_discard=True,ignore_expires=True)
            return tmp_req.read().decode('utf8')
        except urllib2.HTTPError as e:
            return e.read()

    def post(self, url, data, refer=None):
        try:
            req = urllib2.Request(url, urllib.parse.urlencode(data).encode('UTF-8'))
            req.add_header('Referer', refer or SMART_QQ_REFER)
            try:
                tmp_req = urllib2.urlopen(req, timeout=180)
            except BadStatusLine:
                raise ServerResponseEmpty("Server response error, check the network connections: %s" % url)
            self._cookie.save('cookie/cookie.data', ignore_discard=True, ignore_expires=True)
            return tmp_req.read().decode('gbk')
        except urllib2.HTTPError as e:
            return e.read()

    def get_cookie(self, key):
        for c in self._cookie:
            if c.name == key:
                return c.value
        return ''

    def set_cookie(self, key, val, domain):
        ck = cookielib.Cookie(
            version=0, name=key, value=val, port=None, port_specified=False, domain=domain,
            domain_specified=False, domain_initial_dot=False, path='/', path_specified=True,
            secure=False, expires=None, discard=True, comment=None, comment_url=None,
            rest={'HttpOnly': None}, rfc2109=False
        )
        self._cookie.set_cookie(ck)
        self._cookie.save(ignore_discard=True, ignore_expires=True)

    @staticmethod
    def download(url, file):
        output = open(file, 'wb')
        output.write(urllib2.urlopen(url).read())
        output.close()
