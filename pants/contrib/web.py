###############################################################################
#
# Copyright 2011 Stendec <stendec365@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
###############################################################################

###############################################################################
# Imports
###############################################################################

import base64
import logging
import mimetypes
import os
import re
import time
import traceback
import urllib

from datetime import datetime, timedelta
from pants import __version__ as pants_version
from http import CRLF, HTTP, HTTPServer, HTTPRequest

try:
    import simplejson as json
except ImportError:
    import json

__all__ = ('Application','HTTPException','HTTPTransparentRedirect','abort',
    'all_or_404','error','json_response','jsonify','redirect','url_for',
    'HTTPServer','FileServer')

###############################################################################
# Cross Platform Hidden File Detection
###############################################################################
def _is_hidden(file, path):
    return file.startswith(u'.')
if os.name == 'nt':
    try:
        import win32api, win32con
        def _is_hidden(file, path):
            if file.startswith(u'.'):
                return True
            file = os.path.join(path, file)
            try:
                if win32api.GetFileAttributes(file) & win32con.FILE_ATTRIBUTE_HIDDEN:
                    return True
            except Exception:
                return True
            return False
    except ImportError:
        pass
    
###############################################################################
# Logging
###############################################################################
log = logging.getLogger('web')

###############################################################################
# Constants
###############################################################################

SERVER      = 'HTTPants (pants/%s)' % pants_version
SERVER_URL  = 'http://www.pantsweb.org/'

HAIKUS = {
    400: u'Something you entered<br>'
         u'transcended parameters.<br>'
         u'So much is unknown.',
    
    401: u'To access this page,<br>'
         u'one must know oneself; but then:<br>'
         u'inform the server.',
    
    403: u'Unfortunately,<br>'
         u'permissions insufficient.<br>'
         u'This, you cannot see.',
    
    404: u'You step in the stream,<br>'
         u'But the water has moved on.<br>'
         u'This page is not here.',
    
    410: u'A file that big?<br>'
         u'It might be very useful.<br>'
         u'But now it is Gone.',
    
    413: u'Out of memory.<br>'
         u'We wish to hold the whole sky,<br>'
         u'But we never will.',
    
    418: u'You requested coffee,<br>'
         u'it is neither short nor stout.<br>'
         u'I am a teapot.',
    
    500: u'Chaos reigns within.<br>'
         u'Reflect, repent, and reboot.<br>'
         u'Order shall return.'
}

if os.name == 'nt':
    HAIKUS[500] = (u'Yesterday it worked.<br>'
        u'Today, it is not working.<br>'
        u'Windows is like that.')

HTTP_MESSAGES = {
    401: u'You must sign in to access this page.',
    403: u'You do not have permission to view this page.',
    404: u'The page at <code>%(uri)s</code> cannot be found.',
    500: u'The server encountered an internal error and cannot display '
         u'this page.'
}

IMAGES = {
    'audio'     : u"iVBORw0KGgoAAAANSUhEUgAAABIAAAAQCAYAAAAbBi9cAAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAAZpJREFUeNqsU01Lw0AQbdI0aVIVUiSlWKiV/gARiveC2ptehf4Rz+JJ0aM38ebJgzfvvQiWUhooqAeLYCkRUYRa8tHEN7IpIRS3ogsvuzs782Yz81YIgiDxH0P6ha/QbrdLvu/XgC1cIFWpVLZhd7lEpmlmXdetImgTwRuYl2Muc8DbT0SpZrN5huD65DqCkBBFkTAE3pFgCWaNR5RB9joFS5L0Ksvyg6qq97qum0CPJTrHLPJqlKFPPp8/KRQKDSw/IvgEsqw2AY/oOxNILjE9sWCbwSOCINZuXtf6wDPg81oqcs69WUhmIfq7IGMlEFut1u54PN6HvYROXpMiphEJnU5n1bbtUziuwbER41VBcowzgzZY1yANZ9qvKSC5gOM6acTzvCppKDI00hLZQruiKDfR+oVEmWQyqYWOBOz7EZ14xWLxMJ1Od6FqV9O023K5fAD7aKJ8VovFwWCwY1nWnuM4K8h2l8vljgzDuMLZCyCTPoESsMCexSNgAU6USAXo7dCjnGcK7jEdjVhhZaZ4mQlzGJLQ+BJgAITfplvWq5n7AAAAAElFTkSuQmCC",
    'document'  : u"iVBORw0KGgoAAAANSUhEUgAAABIAAAAQCAYAAAAbBi9cAAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAAS1JREFUeNpi/P//PwM1AAsan+306dPngYZr4dPEyMh4zdTU1BDI/IXLIF4g1mJiYgIpBgsguxjEhvK1oGrf4jKIE0QoKCjUi4iI3AaxX79+rfXw4cMaqEvAGGoYJz6vgZ1x//79RiCGuwpmCFp4MuIzCAykpaXLpaSkjkNdZAh00URSAxts65MnTzqBGEUcFG4kGQQLB2RvoVtElEEgoKKiUiEgIPAIpA/dnhcvXug/fvy4nCiDbt++3UFpggQDCQmJBllZ2X1A5j80KeZnz55ZP336tI0og4DObwBhil0kIyNTJikpeRLI/IsmxfTy5UvjR48e9RMV/cDA7AJiksIIPXH8Y2dnvwBKM/gwSA16+DGipQshINYAYilc3gaCP0D8DIhvAPE7mCBAgAEAx0h2pQytmCsAAAAASUVORK5CYII=",
    'folder'    : u"iVBORw0KGgoAAAANSUhEUgAAABIAAAAKCAYAAAC5Sw6hAAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAAQ9JREFUeNqsUT2LwkAQvd3EaDDIESxiaQqLgCDk59z9Gu9XWN8/sUzE0i4iNloEES3EZJP1jWRExK/Chbezszvzdt6M0Fp/fWKZN349iqItbIMcwzD+wjAc4qheEUnakiRpxXH8n6ZpVwjRAM6PqPYHxn63IlkURR9Jv5ZljeiSicqy9FHh7kn+1nGcQRAES6pI+L6/llIeIKXJJPBJ2hl0vgXFAd+e51ExgrbSNM0MCbM8z+v3vmXySu7lDti4rkv901QRvRxBNFVKCQ58Z5rIWVWD0Dy1I/ozQbJiEvrxERnfQ8kSJr8ef4amjaG9A2QItK7lPFq2bcdMxFKIsAa0gV5lXzHtgTmwAA4nAQYAHA9ij4jhqJgAAAAASUVORK5CYII=",
    'icon'      : u"iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAYAAACM/rhtAAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAAQ5JREFUeNpiYWBg+M8wiAELiGhI9RuUjmuYvYmBiWGQA8YhEcVT995EETx96TrDgsIAhoT+DUQbBFJvnNEL5+uqK5OkF2SXqZ4mini2szrEgeiOQwaXb94ly+fE6kP2CMhudEeyYHMUqaFHKQDZBbMT3S1Y0yDMcaSE3tkZxShRTAqAhSLIkVjTILbQIjdqyU0OIEeiuwPkYJaBcBAxaRYWqoO+HByZDgRlGKoW1NR2GLm5maYOpKajhlQapEoI4qp3qVF0US2K0WsBalWVVI3i////M4LwaDk46sBRB446cNSBow4cdeCoA0cdOOrAUQeOOpDUThMpI6KU9vZIAVQdo4Z1mBgZGalmJkCAAQB+2V2B4VtJPwAAAABJRU5ErkJggg==",
    'image'     : u"iVBORw0KGgoAAAANSUhEUgAAABUAAAATCAYAAAB/TkaLAAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAAphJREFUeNqsVE1rE1EU7UxmEjMl0QYxIU4SRi2KH9CkBhWKC3FbRfAH+AfcuBH/hZsiCC66U1y4URcKFnQjk5As1G6UhsQmJCkGZpIxyeRjPDe8J9OhaSL44DBvHu/dc9+55z7BcZyF/z0kQM7n80/H4/E9WhAEYd8GTor1r9lsdhVTe56gi8DdWCz2IJlM5jEfe/YItVrtYrVafVKv11Xs25kVVASCdDASiXzBdxeoeLAbj8eL+FqdTudCoVBI0/5ZmfpwRWcwGOyxICNvpqQCyWLb9rXhcPgol8tVRVF8ibU3mUzmg/d2kks7CnZQ1RxOlEqlPrZarQoyvtzr9dZAcB8ELQR/C5LnIHhHBNK8FaXbjEajdiKR2MIvaX+k3+8r0PtSu92+CpLXxWLxYTqdfiz9i1UoKJNIpqCBQEDRNI3q8BkBz/l8vmXMAyI/0Gw2M1MKIJRKpTNIVAFIuz5g0hHgJ1CyLMsEoRYOh3UqPs9UME1zU9f1zRnJeklJa7tcLl8hdVRVpaADiRl73+ZpDTDlJgG44o7f79clSTIoqDiPlkRCaDQaN9F9z6DfDebxBbhhCXa8HgwGP+H3N6/+SFGU991udx0Zid4s+ZBleRu2OUHtTICVKijMC+zXSO9oNEqu6E2SwMJRfKlqKlXU3W2wywpsEyU7IVDXMIx1FOQkEbsfIhB+g5VuMWcMKVML+A7UqLtcQRfR7xs4fOwgKdyBcXWdxRnyjqKJweAex7F5C6a+zfWbNmAlatXuX+JD3tOJLGjF0/DwKrx4HgRnUelTpD13BXT9hfZcw+8OfxYP6yi6zg/YZA+v1DYlRICmS3DBCpGguMuhUOgVu+Vgnkzdz6Of/MigACFGIrHOqrAkJuOPAAMATZ5MP7rfmUUAAAAASUVORK5CYII=",
    'pants'     : u"iVBORw0KGgoAAAANSUhEUgAAAKAAAACgCAYAAACLz2ctAAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAAhxJREFUeNrs3U1OwkAYgGEHJyndsSKkm3I9E6/jNbgLN+gJum9Cp8q2CsbYH1qeZwmE6PBm5kuLMZxOp/cQwgtM7XA4pLjb7br9fp8sB1PLsixsLANzEiCziv0HjsejVWE0VVXZAXEEgwARIAIEASJAmN6364D96zRgB0SAIEDWPwMOfS+4P1Mu7V7z0n/+R/t93QvGEQwCRIAgQASIAGEWceg3fLbrZmvT/7zG/jztgDiCESA8xgz43+8Dmvmeaya0A+IIBgGyjhnQDMeYM77vA+IIBgEiQBAgAkSAIEAECAJEgCBABAgCRIAwimgJhuXvou2ACBAEiBlw/TNen5nPDogAQYCYAZfPTGcHRIAgQAQIAkSAIEAECAJEgCBAFsi94F/4vyl2QAQIjuDZbbfbEGMMVz893zRNulwuXUrJYglwhONiswllWX7ce835fH77itRiOYKH17Ztd+/568ZY17U1FeD0bpzKOIJFZwcEASJAECACBAEiQARoCRAgAgQBIkAQIAIEASJAECACBAEiQBAgAgQBIkAQIAIEASJAECACBAEiQBAgAgQBIkAQIAIEASJABAgCRIAgQAQIAkSAIEAECAJEgCBABAgCRIAgQAQIAkSAIEAECAJEgCBABAgCRIAgQAQIAkSAIEAEiABBgAgQBIgAQYAIEMYV+w9UVWVVBmQ97YAIEG4cwUVRpDzPXy3FMKzn33wKMACVd1AkmFTspgAAAABJRU5ErkJggg==",
    'video'     : u"iVBORw0KGgoAAAANSUhEUgAAABIAAAAPCAYAAADphp8SAAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAAe9JREFUeNqsU0tLAlEUdmZ8Tki5qHxvtV3gLgmC6C+06me06CG5KFBo0b6lEEI7qWVB5CJCXKuLFsngeyEjk4yOY98d7pWrGW0aOJxz73z3O+d+51xhOp3a/uOzUy+Wy+VDj8dTHI/H27quPzKAIAiW5xO6XK59OMUwjK1EIvGA2GRE8mQyuYU/crvd66PRyOb3+48jkcg74WDJ6vV6st1uZ2RZ3kCyTeCusf8E0yyibrcbRGavpmkFlhUkb3BNmMGqj0ajRRDZ+v1+nrvVCiMSJElykp1QKJQ2TdPVbDbPKMknKZtVxE4SHG7gbLVa51g6mUYoRhCJBtBHB5FJ9TA4EhuNjSU4gRfbErXT6WTZulqt7sXj8Tu+okqlckAChmONmCMiHwTOiqJoNBqN1GAwyJVKpdxim8lhgoM3IEHqBxEpE+3UoJdO1sFgMA0tXhBOKETCwR1FUTIMx4/E3NV6vd4lJ+gzXIPvWiAQeAXRDPfr1cLh8AWyyejGCSVZ2rUF3NKrDWDCX11bwM2Ipj6fT4XIQ2S4YT9qtVoyFovd8xWhk7skYDjo1GKTb6fBCGNf8Hq9Hw6HYwgdrlRVzaNr+cWuISGZ+lM8ERnzZJ219KLlrZJGwdx0UtdoJUP+rcE8dAD7sC/yNGBt4r8FGADC3BrRMDVuEAAAAABJRU5ErkJggg==",
    'zip'       : u"iVBORw0KGgoAAAANSUhEUgAAABIAAAAQCAYAAAAbBi9cAAAAGXRFWHRTb2Z0d2FyZQBBZG9iZSBJbWFnZVJlYWR5ccllPAAAAVdJREFUeNpi/P//PwM1AAsan+306dPngYZrIQtyc3Pr/fnzR+Lnz5+7QHxGRsZrpqamhkDmL1wG8QKxFlQxg5ycXMbfv3+/Pn369BJMDOoDLajat7gM4oRpAIHHjx/PANGysrKZQAMEnzx50gaTg6nFZRBcFUiDoqJi7u/fv/8ADZiO5iIUtdgMYkB20f379yeDaAUFhYR///6JPHr0qAfNMPwGgRSCNMjLyxcCDfj64MGDBaTGGgp4+PBhP4iWkZHJBFLgMMKllgmfQVJSUrUmJiZ2P378YAUGfBvQdQzkGrQPSD0ChtEekFeZmJjIMwgI3p06derSx48feQmFEU6DQN64c+eOvZmZmcHr169N8XmLYGC/e/duBtBFGDFKkkGwtISUkhnwZXB0r/1jZ2e/BNIMC1wYGxmD1IDUoliMZosQEGuAIgyPa/8A8TMgvgHyPUwQIMAA22WMeFl8he8AAAAASUVORK5CYII="
}

IMAGES['icon'] = base64.b64decode(IMAGES['icon'])

PAGE_CSS = u"""html, body { margin: 0; padding: 0; min-height: 100%%; }
body {
	font-family: Calibri,"Trebuchet MS",sans-serif;
	background: #EEE;
	background-image: -webkit-gradient( linear, left bottom, left top,
		color-stop(0, #ccc), color-stop(0.5, #eee) );
    background-image: -moz-linear-gradient( center bottom, #ccc 0%%, #eee 50%% );
}

table.dir td,a { color: #666; }
h1, a:hover { color: #444; }

a { text-decoration: none; }
a:hover { text-decoration: underline; }

div.document,.left,pre,table.dir th:first-child,table.dir td:first-child {
    text-align: left; }
.thingy,.center,.footer { text-align: center; }
table.dir td,table.dir th,.right { text-align: right; }

table.dir td,table.dir th,.thingy > h1 { margin: 0; }
p { margin-bottom: 0; }
table.dir a,pre { display: block; }
pre {
	background: #ddd;
    background-color: rgba(199,199,199,0.5);
	text-align: left;
	border-radius: 5px;
	-moz-border-radius: 5px;
	padding: 5px;
}

table.dir { width:100%%; border-spacing: 0; }
table.dir td,table.dir th { padding: 2px 5px; }
table.dir td { border-top: 1px solid transparent; border-bottom: 1px solid transparent; }
table.dir tr:first-child td { border-top: none; }
table.dir tr:hover td { border-color: #ccc; }
table.dir td.noborder { border-color: transparent !important; }
table.dir th { border-bottom: 1px solid #ccc; }

.footer,.faint { color: #aaa; }
.footer .debug { font-size: 11px; font-family: Consolas,monospace; }
.haiku { margin-top: 20px; }
.haiku + p { color: #777; }
.spacer { padding-top: 50px; }
.column { max-width: 1000px; min-width: 600px; margin: 0px auto; }
.footer { padding-top: 10px; }

a.icon { padding-left: 23px; background-position: left; }
a.icon,.thingy { background-repeat: no-repeat; }

a.folder { background-image: url("data:image/png;base64,%s"); }
a.document { background-image: url("data:image/png;base64,%s"); }
a.image { background-image: url("data:image/png;base64,%s"); }
a.zip { background-image: url("data:image/png;base64,%s"); }
a.audio { background-image: url("data:image/png;base64,%s"); }
a.video { background-image: url("data:image/png;base64,%s"); }

.thingy { background-color: #FFF; background-position: center; color: #000;
	background-image: url("data:image/png;base64,%s"),
        -webkit-gradient(
            linear, left bottom, left top,
            color-stop(0, rgb(239, 239, 239)),
            color-stop(0.5, rgb(255,255,255))
        );
    background-image: url("data:image/png;base64,%s"),
        -moz-linear-gradient( center bottom, #efefef 0%%, #fff 50%%);
    
	border: 5px #ddd solid;
	-moz-border-radius: 25px;
	border-radius: 25px;
	padding: 50px;
	margin: 0 50px;
}""" % (IMAGES['folder'], IMAGES['document'], IMAGES['image'], IMAGES['zip'],
    IMAGES['audio'], IMAGES['video'], IMAGES['pants'], IMAGES['pants'])
PAGE_CSS = PAGE_CSS.replace('%','%%%%')

PAGE = u"""<!DOCTYPE html>
<html><head><title>%%s</title><style>%s</style></head><body>
<div class="column"><div class="spacer"></div><div class="thingy">
%%s
</div><div class="footer"><i><a href="%s">%s</a><br>%%%%s</i>
<div class="debug">%%%%s</div></div>
<div class="spacer"></div></div></body></html>""".replace('\n','') % (
    PAGE_CSS, SERVER_URL, SERVER)

DIRECTORY_PAGE = PAGE % (
    u'Index of %s',
    u"""<h1>Index of %s</h1>%s<table class="dir"><thead><tr>
<th style="width:50%%">Name</th><th>Size</th>
<th class="center" colspan="2">Last Modified</th></tr></thead>%s
</table>"""
    )

ERROR_PAGE = PAGE % (
    u'%d %s',
    u'<h1>%d<br>%s</h1>%s%s'
    )

# Regular expressions used for various types.
REGEXES = {
    int     : r'(-?\d+)',
    float   : r'(-?\d+(?:\.\d+)?)',
}

###############################################################################
# Special Exceptions
###############################################################################

class HTTPException(Exception):
    """
    This exception will force the webserver to display an error page to the
    client of your choice.
    
    To invoke this, use the abort() helper.
    """
    def __init__(self, status=404, message=None, headers=None):
        self.status = status
        self.message = message
        self.headers = headers

class HTTPTransparentRedirect(Exception):
    """
    This exception will redirect the current request to the given URI in a way
    that's transparent to the client.
    """
    def __init__(self, uri):
        self.uri = uri

###############################################################################
# Application Class
###############################################################################

class Application(object):
    """
    An application is a HTTP server with routing logic, allowing you to easilly
    use more than one request handler.
    
    More than that, it makes it easy to send responses to the client by just
    returning values from your functions, rather than messing around with the
    write and finish functions of the request object.
    
    Instances of this class are callable and can be used as an HTTPServer's
    request handler. Example:
        
        from pants.contrib.http import HTTPServer
        from pants.contrib.web import Application
        from pants import engine
        
        app = Application()
        
        @app.route('/')
        def hello_world():
            return 'Hiya!'
        
        HTTPServer(app).listen()
        engine.start()
    """
    current_app = None
    
    def __init__(self, debug=False):
        """
        Initialize an Application instance.
        
        Args:
            debug: If debug is set to True, HTTP responses will include
                tracebacks when errors are encountered running routes. If it's
                False, then generic pages will be displayed and tracebacks
                will merely be logged. Defaults to False.
        """
        
        # Internal Stuff
        self._routes    = {}
        self._names     = {}
        
        # External Stuff
        self.debug = debug
    
    def run(self, port=80, host=''):
        """
        For testing, setup pants and go nuts. Example:
            
            from pants.contrib.web import *
            app = Application()
            
            @app.route("/")
            def hello():
                return "Hello, world!"
            
            app.run()
        
        Args:
            port: The port to listen on. Defaults to 80.
            host: The host to listen on. Optional.
        """
        from pants import engine
        HTTPServer(self).listen(port, host)
        engine.start()
    
    ##### Route Management Methods ############################################
    
    def basic_route(self, rule, name=None, methods=['GET','HEAD']):
        """
        This method is a decorator that registers a route without holding your
        hand about it.
        
        It functions almost the same as the route decorator, but doesn't wrap
        your function to handle arguments for it. Instead, you'll have to deal
        with the request object and the regex match yourself.
        
        Example Usage:
            
            @app.basic_route("/char/<char>/")
            def my_route(request):
                char, = request.match.groups()
                return 'The character is %s!' % char
        
        That's essentially equivilent to:
            
            @app.route("/char/<char>/")
            def my_route(char):
                return 'The character is %s!' % char
        
        """
        def decorator(func):
            regex, arguments, names, namegen = _route_to_regex(rule)
            _regex = re.compile(regex)
            
            if name is None:
                name = "%s.%s" % (func.__module__, func.__name__)
            
            self._insert_route(_regex, func, name, methods, names,namegen)
            return func
        return decorator
    
    def route(self, rule, name=None, methods=['GET','HEAD'], auto404=False):
        """
        This method is a decorator that's used to register a new request handler
        for a given URI rule. Example:
            
            @app.route("/")
            def index():
                return "Hello, World!"
        
        Variable parts in the route can be specified with inequality signs (for
        example: <variable_name>). By default, a variable part accepts any
        characters except a slash (/) and returns a string. However, you can
        specify a specific type to be returned by using <type:name>.
        
        Converters are simply callables that accept a string and return
        something. Built-in types, such as int and float, work well for this.
        So, for example, in:
            
            @app.route("/user/<int:id>/")
            def user(id):
                # Code Here
        
        The id is automatically converted to a number for you, and the view
        function is never even called if id isn't a valid number.
        
        View functions are easy to write, and are expected to return either a
        single value (a string or unicode value), or a tuple to the form of:
        body, status, headers. Status is an integer HTTP status code, and
        headers are a dictionary of optional HTTP headers to send with the
        response. You may also specify a status code and no headers.
        
        The following example returns a page with the 404 status code:
            
            @app.route("/nowhere")
            def nowhere():
                return 'This does not exist.', 404
        
        Args:
            rule: The URI rule to trigger this route. It's internally
                converted to regex for fast processing.
            name: A name to use for this route. If not specified, the name of
                the decorated function is used. Optional.
            methods: The HTTP methods valid for this route. Defaults to GET
                and HEAD.
            auto404: If this is True, all arguments to the view will be checked
                for truthiness, and if any fail, a 404 page will be displayed
                rather than your view function.
        """
        if callable(name):
            self._add_route(rule, name, None, methods, auto404)
            return
        
        def decorator(func):
            self._add_route(rule, func, name, methods, auto404)
            return func
        return decorator
    
    ##### Error Handlers ######################################################
    
    def handle_404(self, request, exception):
        if isinstance(exception, HTTPException):
            return error(exception.message, 404)
        return error(404)
    
    def handle_500(self, request, exception):
        log.exception('Error handling HTTP request: %s %%s' % request.method,
            request.uri) #, traceback.format_exc())
        if not self.debug:
            return error(500)
        
        resp = u''.join([
            u"<h2>Traceback</h2>\n",
            u"<pre>%s</pre>\n" % traceback.format_exc(),
            u"<h2>Route</h2>\n<pre>",
            u"route name   = %r\n" % self._routes[request.route][1],
            u"match groups = %r" % (request.match.groups(),),
            u"</pre>\n",
            u"<h2>HTTP Request</h2>\n",
            request.__html__(),
            ])
        
        return error(resp, 500)
    
    ##### The Request Handler #################################################
    
    def __call__(self, request):
        """
        This function is responsible for determining what view to call, via
        regex matching of the uri, then calling that view, and processing the
        result into a suitable HTTP response.
        """
        Application.current_app = self
        self.request = request
        
        try:
            request.auto_finish = True
            self.handle_output(self.handle_request(request))
        finally:
            request.route = None
            request.match = None
            
            Application.current_app = None
            self.request = None
    
    def handle_output(self, result):
        """ Process the output of handle_request. """
        request = self.request
        
        if not request.auto_finish or result is None or \
                request._finish is not None:
            if request.auto_finish and request._finish is None:
                request.finish()
            return
        
        status = 200
        if type(result) is tuple:
            if len(result) == 3:
                body, status, headers = result
            else:
                body, status = result
                headers = {}
        else:
            body = result
            headers = {}
        
        # Set a Content-Type header if there isn't already one.
        if not 'Content-Type' in headers:
            if (isinstance(body, basestring) and 
                    body[:5].lower() in ('<html','<!doc')) or \
                    hasattr(body, '__html__'):
                headers['Content-Type'] = 'text/html'
            else:
                headers['Content-Type'] = 'text/plain'
        
        # Convert the body to something sendable.
        try:
            body = body.__html__()
        except AttributeError:
            pass
        
        if isinstance(body, unicode):
            encoding = headers['Content-Type']
            if 'charset=' in encoding:
                before, sep, enc = encoding.partition('charset=')
            else:
                before = encoding
                sep = '; charset='
                enc = 'UTF-8'
            
            body = body.encode(enc)
            headers['Content-Type'] = '%s%s%s' % (before, sep, enc)
        
        elif not isinstance(body, str):
            body = str(body)
        
        # More headers!
        headers['Content-Length'] = len(body)
        if not 'Date' in headers:
            headers['Date'] = _date(datetime.utcnow())
        if not 'Server' in headers:
            headers['Server'] = SERVER
        
        # Send the response.
        request.send_status(status)
        request.send_headers(headers)
        
        if request.method == 'HEAD':
            request.finish()
            return
        
        request.write(body)
        request.finish()
    
    def handle_request(self, request):
        path = request.path
        
        for route in self._routes:
            match = route.match(path)
            if match is None:
                continue
            
            # Process this route.
            request.route = route
            request.match = match
            
            func, name, methods = self._routes[route][:3]
            if request.method not in methods:
                return error(
                    'The method %s is not allowed for %r.' % (
                        request.method, path), 405, {
                            'Allow': ', '.join(methods)
                        })
            else:
                try:
                    return func(request)
                except HTTPException, e:
                    if hasattr(self, 'handle_%d' % e.status):
                        return getattr(self, 'handle_%d' % e.status)(request, e)
                    else:
                        return error(e.message, e.status, e.headers)
                except HTTPTransparentRedirect, e:
                    request.uri = e.uri
                    request._parse_uri()
                    return self.handle_request(request)
                except Exception, e:
                    return self.handle_500(request, e)
            break
        else:
            # No matching routes.
            if not path.endswith('/'):
                p = '%s/' % path
                for route in self._routes:
                    if route.match(p):
                        if request.query:
                            return redirect('%s?%s' % (p,request.query))
                        else:
                            return redirect(p)
        
        return self.handle_404(request, None)
    
    ##### Internal Methods and Event Handlers #################################
    
    def _insert_route(self, route, handler, name, methods, nms, namegen):
        if isinstance(route, basestring):
            route = re.compile(route)
        self._routes[route] = (handler, name, methods, nms, namegen)
        self._names[name] = route
    
    def _add_route(self, route, view, name=None, methods=['GET','HEAD'],
            auto404=False):
        """ See: Application.route """
        if name is None:
            if view is None:
                raise Exception('No name or view specified!')
            if hasattr(view, '__name__'):
                name = view.__name__
            elif hasattr(view, '__class__'):
                name = view.__class__.__name__
            else:
                raise NameError("Cannot find name for this route.")
        
        if not callable(view):
            raise Exception('View must be callable.')
        
        # Parse the route.
        regex, arguments, names, namegen = _route_to_regex(route)
        _regex = re.compile(regex)
        
        if not arguments:
            arguments = False
        
        def view_runner(request):
            request.__viewmodule__ = view.__module__
            match = request.match
            try:
                try:
                    view.func_globals['request'] = request
                except AttributeError:
                    view.__call__.func_globals['request'] = request
                if arguments is False:
                    return view()
                
                out = []
                for val,type in zip(match.groups(), arguments):
                    if type is not None:
                        try:
                            val = type(val)
                        except Exception:
                            return error('Unable to parse data %r.' % val, 400)
                    out.append(val)
                
                if auto404 is True:
                    all_or_404(*out)
                
                return view(*out)
            finally:
                try:
                    view.func_globals['request'] = None
                except AttributeError:
                    view.__call__.func_globals['request'] = None
        
        view_runner.__name__ = name
        self._insert_route(_regex, view_runner, "%s.%s" %(view.__module__,name),
            methods, names, namegen)

###############################################################################
# FileServer Class
###############################################################################

class FileServer(object):
    """
    The FileServer is a request handling class that, as it sounds, serves files
    to the client. It also supports the Content-Range header, HEAD requests,
    and last modified dates.
    
    It attempts to serve the files as efficiently as possible.
    
    Using it is simple. It only requires a single argument: the path to serve
    files from. You can also supply a list of default files to check to serve
    rather than a file listing.
    
    When used with an Application, the FileServer is not created in the usual
    way with the route decorator, but rather with a method of the FileServer
    itself. Example:
        
        FileServer("/tmp/path").attach(app)
    
    If you wish to listen on a path other than /static/, you can also use that
    when attaching:
        
        FileServer("/tmp/path").attach(app, "/files/")
    """
    def __init__(self, path, blacklist=[re.compile('.*\.pyc?$')],
            defaults=['index.html','index.html'],
            renderers=None):
        """
        Initialize the FileServer.
        
        Args:
            path: The path to serve.
            blacklist: A list of regular expressions to test filenames against.
                If any match a given file, it will not be downloadable via
                this class. Optional.
                
                Any blacklist items are expected to be either a regex pattern
                object, a unicode string, or a regular string. In the event
                of a regular string, it will be compiled into a regex pattern
                object.
                
                By default, all .py and .pyc files are blacklisted.
            defaults: A list of default files, such as index.html. Optional.
            renderers: A dictionary of methods for rendering files into
                suitable output, useful for processing CSS and JavaScript, or
                converting structured text documents into HTML for display in
                a browser. Optional.
        """
        # Make sure our path is unicode.
        if not isinstance(path, unicode):
            path = _decode(path)
        
        self.path = os.path.normpath(os.path.realpath(path))
        self.defaults = defaults
        self.renderers = renderers or {}
        
        # Build the blacklist.
        self.blacklist = []
        for bl in blacklist:
            if isinstance(bl, str):
                bl = re.compile(bl)
            self.blacklist.append(bl)
    
    def attach(self, app, route='/static/'):
        """
        Attach this fileserver to an application, bypassing the usual route
        decorator to ensure things are done right.
        
        Args:
            app: The application to attach to.
            route: The path to listen on. Defaults to '/static/'.
        """
        route = re.compile("^%s(.*)$" % re.escape(route))
        app._insert_route(route, self, "FileServer", ['HEAD','GET'], None, None)
    
    def check_blacklist(self, path):
        """
        Check the given path to make sure it isn't blacklisted. If it is
        blacklisted, then raise an HTTPException via abort.
        
        Args:
            path: The path to check.
        """
        for bl in self.blacklist:
            if isinstance(bl, unicode):
                if bl in path:
                    abort(403)
            elif bl.match(path):
                abort(403)
    
    def __call__(self, request):
        """
        Serve a request.
        """
        
        try:
            path = request.match.group(1)
        except (AttributeError, IndexError):
            path = request.path
        
        # Conver the path to unicode.
        path = _decode(urllib.unquote(path))
        
        # Normalize the path.
        full_path = os.path.normpath(os.path.join(self.path, path))
        
        # Validate the request.
        if not full_path.startswith(self.path):
            abort(403)
        if not os.path.exists(full_path):
            abort(404)
        
        # Is this a directory?
        if os.path.isdir(full_path):
            # Check defaults.
            for f in self.defaults:
                full = os.path.join(full_path, f)
                if os.path.exists(full):
                    request.path = urllib.quote(full.encode('utf8'))
                    if hasattr(request, 'match'):
                        del request.match
                    return self.__call__(request)
            
            # Guess not. List it.
            return self.list_directory(request, path)
        
        # Blacklist Checking.
        self.check_blacklist(full_path)
        
        # Try rendering the content.
        ext = os.path.basename(full_path).rpartition('.')[-1]
        if ext in self.renderers:
            f, mtime, size, type = self.renderers[ext](request, full_path)
        else:
            # Get the information for the actual file.
            f = None
            stat = os.stat(full_path)
            mtime = stat.st_mtime
            size = stat.st_size
            type = mimetypes.guess_type(full_path)[0]
        
        # If we don't have a type, text/plain it.
        if type is None:
            type = 'text/plain'
        
        # Generate a bunch of data for headers.
        modified = datetime.fromtimestamp(mtime)
        expires = datetime.utcnow() + timedelta(days=7)
        
        etag = '"%x-%x"' % (size, int(mtime))
        
        headers = {
            'Last-Modified' : _date(modified),
            'Expires'       : _date(expires),
            'Cache-Control' : 'max-age=604800',
            'Content-Type'  : type,
            'Date'          : _date(datetime.utcnow()),
            'Server'        : SERVER,
            'Accept-Ranges' : 'bytes',
            'ETag'          : etag    
        }
        
        do304 = False
        
        if 'If-Modified-Since' in request.headers:
            try:
                since = _parse_date(request.headers['If-Modified-Since'])
            except ValueError:
                since = None
            if since and since >= modified:
                do304 = True
        
        if 'If-None-Match' in request.headers:
            if etag == request.headers['If-None-Match']:
                do304 = True
        
        if do304:
            if f:
                f.close()
            request.auto_finish = False
            request.send_status(304)
            request.send_headers(headers)
            request.finish()
            return
        
        if 'If-Range' in request.headers:
            if etag != request.headers['If-Range'] and \
                    'Range' in request.headers:
                del request.headers['Range']
        
        last = size - 1
        range = 0, last
        status = 200
        
        if 'Range' in request.headers:
            if request.headers['Range'].startswith('bytes='):
                try:
                    val = request.headers['Range'][6:].split(',')[0]
                    start, end = val.split('-')
                except ValueError:
                    if f:
                        f.close()
                    abort(416)
                try:
                    if end and not start:
                        end = last
                        start = last - int(end)
                    else:
                        start = int(start or 0)
                        end = int(end or last)
                    
                    if start < 0 or start > end or end > last:
                        if f:
                            f.close()
                        abort(416)
                    range = start, end
                except ValueError:
                    pass
                if range[0] != 0 or range[1] != last:
                    status = 206
                    headers['Content-Range'] = 'bytes %d-%d/%d' % (
                        range[0], range[1], size)
        
        # Set the content length header.
        if range[0] == range[1]:
            headers['Content-Length'] = 0
        else:
            headers['Content-Length'] = 1 + (range[1] - range[0])
        
        # Send the headers and status line.
        request.auto_finish = False
        request.send_status(status)
        request.send_headers(headers)
        
        # Don't send the body if this is head.
        if request.method == 'HEAD':
            if f:
                f.close()
            request.finish()
            return
        
        # Open the file and send it.
        if range[0] == range[1]:
            if f:
                f.close()
            request.finish()
            return
        
        if f is None:
            f = open(full_path, 'rb')
        
        f.seek(range[0])
        if range[1] != last:
            length = 1 + (range[1] - range[0])
        else:
            length = None
        
        def on_write():
            del request.connection.handle_write_file
            request.finish()
        
        request.connection.handle_write_file = on_write
        request.connection.write_file(f, length)
        
    def list_directory(self, request, path):
        """
        Generate a directory listing and return it.
        """
        
        # Normalize the path.
        full_path = os.path.normpath(os.path.join(self.path, path))
        
        # Get the URI, which is just request.path decoded.
        uri = _decode(urllib.unquote(request.path))
        if not uri.startswith(u'/'):
            uri = u'/%s' % uri
        if not uri.endswith(u'/'):
            return redirect(u'%s/' % uri)
        
        go_up = u''
        url = uri.strip(u'/')
        if url:
            go_up = u'<p><a href="..">Up to Higher Directory</a></p>'
        
        files = []
        dirs = []
        
        for p in sorted(os.listdir(full_path), key=unicode.lower):
            if _is_hidden(p, full_path):
                continue
            
            full = os.path.join(full_path, p)
            try:
                fp = full
                if os.path.isdir(full):
                    fp += '/'
                self.check_blacklist(fp)
            except HTTPException:
                continue
            
            stat = os.stat(full)
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime(
                u'<td class="right">%Y-%m-%d</td>'
                u'<td class="left">%I:%M:%S %p</td>'
                )
            
            if os.path.isdir(full):
                cls = u'folder'
                link = u'%s/' % p
                size = u'<span class="faint">Directory</span>'
                obj = dirs
            
            elif os.path.isfile(full):
                cls = 'document'
                ext = p[p.rfind('.')+1:]
                if ext in ('jpg','jpeg','png','gif','bmp'):
                    cls = 'image'
                elif ext in ('zip','gz','tar','7z','tgz'):
                    cls = 'zip'
                elif ext in ('mp3','mpa','wma','wav','flac','mid','midi','raw',
                        'mod','xm','aac','m4a','ogg','aiff','au','voc','m3u',
                        'pls','asx'):
                    cls = 'audio'
                elif ext in ('mpg','mpeg','mkv','mp4','wmv','avi','mov'):
                    cls = 'video'
                link = p
                size = _human_readable_size(stat.st_size)
                obj = files
            
            else:
                continue
            
            obj.append(
                u'<tr><td><a class="icon %s" href="%s%s">%s</a></td><td>%s'
                u'</td>%s</tr>' % (
                    cls, uri, link, p, size, mtime))
        
        if files or dirs:
            files = u''.join(dirs) + u''.join(files)
        else:
            files = (u'<tr><td colspan="4" class="noborder">'
                     u'<div class="footer center">'
                     u'This directory is empty.</div></td></tr>')
        
        if Application.current_app and Application.current_app.debug:
            rtime = u'%0.3f ms' % (1000 * request.time)
        else:
            rtime = u''
        
        return DIRECTORY_PAGE % (uri, uri, go_up, files, request.host, rtime), \
            200, {
                'Content-Type':'text/html; charset=utf-8'
            }
    
###############################################################################
# Private Helper Functions
###############################################################################

def path(st):
    return st
path.regex = "(.+?)"

def _get_thing(thing):
    if thing in globals():
        return globals()[thing]
    elif type(__builtins__) is dict and thing in __builtins__:
        return __builtins__[thing]
    elif hasattr(__builtins__, thing):
        return getattr(__builtins__, thing)
    return None

_route_parser = re.compile(r"<([^>]+)>([^<]*)")
def _route_to_regex(route):
    """ Parse a Flask-style route and return a regular expression, as well as
        a tuple of things for conversion. """
    regex, values, names, namegen = "", [], [], ""
    if not route.startswith("^/"):
        if route.startswith("/"):
            route = "^%s$" % route
        else:
            route = "^/%s$" % route
    
    # Find up to the first < and add it to regex.
    ind = route.find('<')
    if ind is -1:
        return route, tuple(), tuple(), route[1:-1]
    elif ind > 0:
        regex += route[:ind]
        namegen += route[:ind]
        route = route[ind:]
    
    # If the parser doesn't match, return.
    if not _route_parser.match(route):
        return regex+route, tuple(), tuple(), (regex+route)[1:-1]
    
    for match in _route_parser.finditer(route):
        group = match.group(1)
        if ':' in group:
            type, var = group.split(':', 1)
            thing = _get_thing(type)
            if not thing:
                raise Exception, "Invalid type declaration, %s" % type
            if hasattr(thing, 'regex'):
                regex += thing.regex
            elif thing in REGEXES:
                regex += REGEXES[thing]
            else:
                regex += "([^/]+)"
            values.append(thing)
            names.append(var)
        else:
            regex += "([^/]+)"
            values.append(None)
            names.append(group)
        namegen += "%s" + match.group(2)
        regex += match.group(2)
    
    return regex, tuple(values), tuple(names), namegen[1:-1]

_abbreviations = (
    (1<<50L, u' PB'),
    (1<<40L, u' TB'),
    (1<<30L, u' GB'),
    (1<<20L, u' MB'),
    (1<<10L, u' KB'),
    (1, u' B')
)
def _human_readable_size(size, precision=2):
    """ Convert a size to a human readable filesize. """
    if size == 0:
        return u'0 B'
    
    for f,s in _abbreviations:
        if size >= f:
            break
    
    ip, dp = `size/float(f)`.split('.')
    if int(dp[:precision]):
        return  u'%s.%s%s' % (ip,dp[:precision],s)
    return u'%s%s' % (ip,s)

_encodings = ('utf-8','iso-8859-1','cp1252','latin1')
def _decode(text):
    for enc in _encodings:
        try:
            return text.decode(enc)
        except UnicodeDecodeError:
            continue
    else:
        return text.decode('utf-8','ignore')

def _date(dt):
    return dt.strftime("%a, %d %b %Y %H:%M:%S GMT")

def _parse_date(text):
    return datetime(*time.strptime(text, "%a, %d %b %Y %H:%M:%S GMT")[:6])

###############################################################################
# Public Helper Functions
###############################################################################

def abort(status=404, message=None, headers=None):
    """
    Raise an HTTPException to display an error page.
    """
    raise HTTPException(status, message, headers)

def all_or_404(*args):
    """
    If any of the provided arguments aren't truthy, raise a 404 exception.
    This is automatically called for you if you set auto404=True when using the
    route decorator.
    """
    all(args) or abort()

def error(message=None, status=None, headers=None, request=None, debug=None):
    """
    Return a very simple error page, defaulting to a 404 Not Found error if
    no status code is supplied. Usually, you'll want to call abort() in your
    code, rather than error, to streamline the process of abandoning your code.
    Usage:
        
        return error(404)
        return error("Some message.", 404)
        return error("Blah blah blah.", 403, {'Some-Header':'Fish'})
    """
    if request is None:
        request = Application.current_app.request
    
    if status is None:
        if type(message) is int:
            status = message
            message = None
        else:
            status = 404
    
    if not status in HTTP:
        status = 404
    title = HTTP[status]
    if not headers:
        headers = {}
    
    if message is None:
        if status in HTTP_MESSAGES:
            dict = request.__dict__.copy()
            dict['uri'] = _decode(urllib.unquote(dict['uri']))
            message = HTTP_MESSAGES[status] % dict
        else:
            message = u"An unspecified error has occured."
    
    haiku = u''
    if status in HAIKUS:
        haiku = u'<div class="haiku">%s</div>' % HAIKUS[status]
    
    if not message.startswith(u'<'):
        message = u'<p>%s</p>' % message
    
    if debug is None:
        debug = Application.current_app and Application.current_app.debug
    
    if debug:
        time = u'%0.3f ms' % (1000 * request.time)
    else:
        time = u''
    
    result = ERROR_PAGE % (status, title, status, title.replace(u' ',u'&nbsp;'),
        haiku, message, request.host, time)
    
    return result, status, headers

def json_response(object, status=200, headers=None):
    """
    Constructs a JSON response from a given object. You can also specify a
    HTTP status code and additional headers. Example:
        
        return json_response(["my","object","here"])
    
    Args:
        object: The object to return.
        status: The HTTP status code to send. Defaults to 200.
        headers: A dictionary of headers to send. Optional.
    """
    if not headers:
        headers = {}
    if not 'Content-Type' in headers:
        headers['Content-Type'] = 'application/json'
    
    return json.dumps(object), status, headers

def jsonify(*args, **kwargs):
    """
    Construct a JSON response using the provided arguments or keyword
    arguments. Somewhat less powerful than json_response, but providing a
    simple interface. Example:
        
        return jsonify(username="Stacy",
                       email="stacy@examples.com",
                       id=2)
    """
    if args:
        if kwargs:
            args = list(args) + [kwargs]
        kwargs = args
    return json.dumps(kwargs), 200, {'Content-Type':'application/json'}

def redirect(uri, status=302):
    """
    Construct a 302 Found response to instruct the client's browser to redirect
    its request to a different URL. Other codes may be returned by specifying a
    status.
    """
    url = uri
    if isinstance(url, unicode):
        url = uri.encode('utf-8')
    
    return error(
        'The document you have requested is located at <a href="%s">%s</a>.' % (
            uri, uri), status, {'Location':url})

def url_for(name, **values):
    """
    Generates a URL to the route with the given name. The name is relative to
    the module of the route function. Examples:
    
    View's Module | Target Endpoint | Target Function
    'test'        | 'index'         | 'index' function of 'test' module
    'test'        | '.who'          | First 'who' function of any module
    'test'        | 'admin.login'   | 'login' function of 'admin' module
    
    Provided values with unknown keys are added to the URL as query arugments.
    """
    app = Application.current_app
    request = app.request
    
    if name.startswith('.'):
        # Find it in the first possible place.
        name = name[1:]
        for n in app._names:
            module, nm = n.split('.',1)
            if nm == name:
                name = n
                break
    elif not '.' in name:
        # Find it in this module.
        name = "%s.%s" % (request.__viewmodule__, name)
    
    if not name in app._names:
        raise NameError("Cannot find route %r." % name)
    
    route = app._names[name]
    names, namegen = app._routes[route][-2:]
    
    out = []
    for n in names:
        out.append(str(values[n]))
        del values[n]
    out = tuple(out)
    
    if len(out) == 1:
        out = namegen % out[0]
    else:
        out = namegen % out
    out = urllib.quote(out)
    
    if '_external' in values:
        if values['_external']:
            out = '%s://%s%s' % (request.protocol, request.host, out)
        del values['_external']
    
    if values:
        out += '?%s' % urllib.urlencode(values)
    
    return out