###############################################################################
#
# Copyright 2009 Facebook (see NOTICE.txt)
# Copyright 2011-2012 Pants Developers (see AUTHORS.txt)
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
"""
The low-level channel class. Provides a non-blocking socket wrapper for
use as a base for higher-level classes.
"""

###############################################################################
# Imports
###############################################################################

import errno
import os
import socket
import sys
import time

from pants.engine import Engine
from pants.util.sendfile import sendfile

dns = None


###############################################################################
# Logging
###############################################################################

import logging
log = logging.getLogger("pants")


###############################################################################
# Constants
###############################################################################

SUPPORTED_FAMILIES = [socket.AF_INET]
try:
    SUPPORTED_FAMILIES.append(socket.AF_UNIX)
except AttributeError:
    # Unix sockets not supported.
    pass

HAS_IPV6 = False
if socket.has_ipv6:
    # IPv6 must be enabled on Windows XP before it can be used, but
    # socket.has_ipv6 will be True regardless.
    try:
        socket.socket(socket.AF_INET6)
    except socket.error:
        pass
    else:
        HAS_IPV6 = True
        SUPPORTED_FAMILIES.append(socket.AF_INET6)

SUPPORTED_FAMILIES = tuple(SUPPORTED_FAMILIES)
SUPPORTED_TYPES = (socket.SOCK_STREAM, socket.SOCK_DGRAM)

if sys.platform == "win32":
    FAMILY_ERROR = (10047, "WSAEAFNOSUPPORT")
    NAME_ERROR = (11001, "WSAHOST_NOT_FOUND")
else:
    FAMILY_ERROR = (97, "Address family not supported by protocol")
    NAME_ERROR = (-2, "Name or service not known")


###############################################################################
# Functions
###############################################################################

# os.strerror() is buggy on Windows, so we have to look up the error
# string manually.
if sys.platform == "win32":
    def strerror(err):
        if err in socket.errorTab:
            errstr = socket.errorTab[err]
        elif err in errno.errorcode:
            errstr = errno.errorcode[err]
        else:
            errstr = os.strerror(err)
            if errstr == "Unknown error":
                errstr += ": %d" % err
        return errstr
else:
    strerror = os.strerror


###############################################################################
# _Channel Class
###############################################################################

class _Channel(object):
    """
    A simple socket wrapper class.

    _Channel wraps most common socket methods to make them "safe", more
    consistent in their return values and easier to use in non-blocking
    code. This class is for internal use -- it does not function as-is
    and must be subclassed. Subclasses should override
    :meth:`~pants._channel._Channel._handle_read_event` and
    :meth:`~pants._channel._Channel._handle_write_event` to implement
    basic event-handling behaviour. Subclasses should also ensure that
    they call the relevant on_* event handler placeholders at the
    appropriate times.

    =================  ================================================
    Keyword Argument   Description
    =================  ================================================
    engine             *Optional.* The engine to which the channel
                       should be added. Defaults to the global engine.
    socket             *Optional.* A pre-existing socket to wrap.
                       Defaults to a newly-created socket.
    =================  ================================================
    """
    def __init__(self, **kwargs):
        self.engine = kwargs.get("engine", Engine.instance())

        # Socket
        self.family = None
        self.fileno = None
        self._socket = None
        self._closed = False
        sock = kwargs.get("socket", None)
        if sock:
            self._socket_set(sock)

        # I/O attributes
        self._recv_amount = 4096

        # Internal state
        self._events = Engine.ALL_EVENTS
        self._processing_events = False
        if self._socket:
            self.engine.add_channel(self)

    def __repr__(self):
        return "%s #%r (%s)" % (self.__class__.__name__, self.fileno,
                object.__repr__(self))

    ##### Control Methods #####################################################

    def close(self):
        """
        Close the channel.
        """
        if self._closed:
            return

        self.engine.remove_channel(self)
        self._socket_close()
        self._events = Engine.ALL_EVENTS
        self._processing_events = False

        self._safely_call(self.on_close)

    ##### Public Event Handlers ###############################################

    def on_read(self, data):
        """
        Placeholder. Called when data is read from the channel.

        =========  ============
        Argument   Description
        =========  ============
        data       A chunk of data received from the socket.
        =========  ============
        """
        pass

    def on_write(self):
        """
        Placeholder. Called after the channel has finished writing data.
        """
        pass

    def on_connect(self):
        """
        Placeholder. Called after the channel has connected to a remote
        socket.
        """
        pass

    def on_listen(self):
        """
        Placeholder. Called when the channel begins listening for new
        connections or packets.
        """
        pass

    def on_accept(self, sock, addr):
        """
        Placeholder. Called after the channel has accepted a new
        connection.

        =========  ============
        Argument   Description
        =========  ============
        sock       The newly connected socket object.
        addr       The new socket's address.
        =========  ============
        """
        pass

    def on_close(self):
        """
        Placeholder. Called after the channel has finished closing.
        """
        pass

    ##### Public Error Handlers ###############################################

    def on_connect_error(self, exception):
        """
        Placeholder. Called when the channel has failed to connect to a
        remote socket.

        By default, logs the exception and closes the channel.

        ==========  ============
        Argument    Description
        ==========  ============
        exception   The exception that was raised.
        ==========  ============
        """
        log.exception(exception)
        self.close()

    def on_overflow_error(self, exception):
        """
        Placeholder. Called when an internal buffer on the channel has
        exceeded its size limit.

        By default, logs the exception and closes the channel.

        ==========  ============
        Argument    Description
        ==========  ============
        exception   The exception that was raised.
        ==========  ============
        """
        log.exception(exception)
        self.close()

    def on_error(self, exception):
        """
        Placeholder. Generic error handler for exceptions raised on the
        channel. Called when an error occurs and no specific
        error-handling callback exists.

        By default, logs the exception and closes the channel.

        ==========  ============
        Argument    Description
        ==========  ============
        exception   The exception that was raised.
        ==========  ============
        """
        log.exception(exception)
        self.close()

    ##### Socket Method Wrappers ##############################################

    def _socket_set(self, sock):
        """
        Set the channel's current socket and update channel details.

        =========  ============
        Argument   Description
        =========  ============
        sock       A socket for this channel to wrap.
        =========  ============
        """
        if self._socket is not None:
            raise RuntimeError("Cannot replace existing socket.")
        if sock.family not in SUPPORTED_FAMILIES:
            raise ValueError("Unsupported socket family.")
        if sock.type not in SUPPORTED_TYPES:
            raise ValueError("Unsupported socket type.")

        sock.setblocking(False)
        self.family = sock.family
        self.fileno = sock.fileno()
        self._socket = sock

    def _socket_connect(self, addr):
        """
        Connect the socket to a remote socket at the given address.

        Returns True if the connection was completed immediately, False
        otherwise.

        =========  ============
        Argument   Description
        =========  ============
        addr       The remote address to connect to.
        =========  ============
        """
        try:
            result = self._socket.connect_ex(addr)
        except socket.error, err:
            result = err[0]

        if not result or result == errno.EISCONN:
            return True

        if result in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINPROGRESS, errno.EALREADY):
            self._start_waiting_for_write_event()
            return False

        raise socket.error(result, strerror(result))

    def _socket_bind(self, addr):
        """
        Bind the socket to the given address.

        =========  ============
        Argument   Description
        =========  ============
        addr       The local address to bind to.
        =========  ============
        """
        self._socket.bind(addr)

    def _socket_listen(self, backlog):
        """
        Begin listening for connections made to the socket.

        =========  ============
        Argument   Description
        =========  ============
        backlog    The size of the connection queue.
        =========  ============
        """
        if sys.platform == "win32" and backlog > socket.SOMAXCONN:
            log.warning("Setting backlog to SOMAXCONN on %r." % self)
            backlog = socket.SOMAXCONN

        self._socket.listen(backlog)

    def _socket_close(self):
        """
        Close the socket.
        """
        try:
            self._socket.close()
        except (AttributeError, socket.error):
            return
        finally:
            self.family = None
            self.fileno = None
            self._socket = None
            self._closed = True

    def _socket_accept(self):
        """
        Accept a new connection to the socket.

        Returns a 2-tuple containing the new socket and its remote
        address. The 2-tuple is (None, None) if no connection was
        accepted.
        """
        try:
            return self._socket.accept()
        except socket.error, err:
            if err[0] in (errno.EAGAIN, errno.EWOULDBLOCK):
                return None, None
            else:
                raise

    def _socket_recv(self):
        """
        Receive data from the socket.

        Returns a string of data read from the socket. The data is None if
        the socket has been closed.
        """
        try:
            data = self._socket.recv(self._recv_amount)
        except socket.error, err:
            if err[0] in (errno.EAGAIN, errno.EWOULDBLOCK):
                return ''
            elif err[0] == errno.ECONNRESET:
                return None
            else:
                raise

        if not data:
            return None
        else:
            return data

    def _socket_recvfrom(self):
        """
        Receive data from the socket.

        Returns a 2-tuple containing a string of data read from the socket
        and the address of the sender. The data is None if reading failed.
        The data and address are None if no data was received.
        """
        try:
            data, addr = self._socket.recvfrom(self._recv_amount)
        except socket.error, err:
            if err[0] in (errno.EAGAIN, errno.EWOULDBLOCK, errno.ECONNRESET):
                return '', None
            else:
                raise

        if not data:
            return None, None
        else:
            return data, addr

    def _socket_send(self, data):
        """
        Send data to the socket.

        Returns the number of bytes that were sent to the socket.

        =========  ============
        Argument   Description
        =========  ============
        data       The string of data to send.
        =========  ============
        """
        # TODO Find out if socket.send() can return 0 rather than raise
        # an exception if it needs a write event.
        try:
            return self._socket.send(data)
        except Exception, err:
            if err[0] in (errno.EAGAIN, errno.EWOULDBLOCK):
                self._start_waiting_for_write_event()
                return 0
            elif err[0] == errno.EPIPE:
                self.close()
                return 0
            else:
                raise

    def _socket_sendto(self, data, addr, flags=0):
        """
        Send data to a remote socket.

        Returns the number of bytes that were sent to the socket.

        =========  ============
        Argument   Description
        =========  ============
        data       The string of data to send.
        addr       The remote address to send to.
        flags      *Optional.* Flags to pass to the sendto call.
        =========  ============
        """
        try:
            return self._socket.sendto(data, flags, addr)
        except Exception, err:
            if err[0] in (errno.EAGAIN, errno.EWOULDBLOCK):
                self._start_waiting_for_write_event()
                return 0
            elif err[0] == errno.EPIPE:
                self.close()
                return 0
            else:
                raise

    def _socket_sendfile(self, sfile, offset, nbytes, fallback=False):
        """
        Send data from a file to a remote socket.

        Returns the number of bytes that were sent to the socket.

        =========  ====================================================
        Argument   Description
        =========  ====================================================
        sfile      The file to send.
        offset     The number of bytes to offset writing by.
        nbytes     The number of bytes of the file to write. If 0, all
                   bytes will be written.
        fallback   If True, the pure-Python sendfile function will be
                   used.
        =========  ====================================================
        """
        try:
            return sendfile(sfile, self, offset, nbytes, fallback)
        except Exception, err:
            if err[0] in (errno.EAGAIN, errno.EWOULDBLOCK):
                self._start_waiting_for_write_event()
                return 0
            elif err[0] == errno.EPIPE:
                self.close()
                return 0
            else:
                raise

    ##### Internal Methods ####################################################

    def _start_waiting_for_write_event(self):
        """
        Start waiting for a write event on the channel, update the
        engine if necessary.
        """
        if self._events != self._events | Engine.WRITE:
            self._events = self._events | Engine.WRITE
            if not self._processing_events:
                self.engine.modify_channel(self)

    def _stop_waiting_for_write_event(self):
        """
        Stop waiting for a write event on the channel, update the engine
        if necessary.
        """
        if self._events == self._events | Engine.WRITE:
            self._events = self._events & (self._events ^ Engine.WRITE)
            if not self._processing_events:
                self.engine.modify_channel(self)

    def _safely_call(self, thing_to_call, *args, **kwargs):
        """
        Safely execute a callable.

        The callable is wrapped in a try block and executed. If an
        exception is raised it is logged.

        If no exception is raised, returns the value returned by
        :func:`thing_to_call`.

        ==============  ============
        Argument        Description
        ==============  ============
        thing_to_call   The callable to execute.
        *args           The positional arguments to be passed to the callable.
        **kwargs        The keyword arguments to be passed to the callable.
        ==============  ============
        """
        try:
            return thing_to_call(*args, **kwargs)
        except Exception:
            log.exception("Exception raised in callback on %r." % self)

    def _get_socket_error(self):
        """
        Get the most recent error that occured on the socket.

        Returns a 2-tuple containing the error code and the error message.
        """
        err = self._socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        errstr = ""

        if err != 0:
            errstr = strerror(err)

        return err, errstr

    def _resolve_addr(self, addr, native_resolve, callback):
        """
        Resolve the given address into something that can be connected
        to immediately and determine the appropriate socket family.

        ===============  ==============================================
        Argument         Description
        ===============  ==============================================
        addr             The address to resolve.
        native_resolve   If True, use Python's builtin address
                         resolution. Otherwise, Pants' non-blocking
                         address resolution will be used.
        callback         A callable taking two mandatory arguments and
                         one optional argument. The arguments are: the
                         resolved address, the socket family and error
                         information, respectively.
        ===============  ==============================================
        """
        # This is here to prevent an import-loop. pants.util.dns depends
        # on pants._channel.
        global dns
        if dns is None:
            from pants.util import dns

        if isinstance(addr, str):
            # This is a unix socket!
            if not hasattr(socket, "AF_UNIX"):
                callback(None, None, FAMILY_ERROR)
                return
            callback(addr, socket.AF_UNIX)
            return

        if isinstance(addr, (int, long)):
            # INADDR_ANY-atize it!
            addr = ('', addr)

        if addr[0] in ('', '<broadcast>'):
            if HAS_IPV6:
                callback(addr, socket.AF_INET6)
            elif len(addr) == 4:
                callback(None, None, FAMILY_ERROR)
            else:
                callback(addr, socket.AF_INET)
            return

        # It must be a tuple or list. Or, at least, assume it is.
        # That means it's either an AF_INET or AF_INET6 address.
        got_family = None

        if HAS_IPV6:
            try:
                result = socket.inet_pton(socket.AF_INET6, addr[0])
            except socket.error:
                pass
            else:
                got_family = socket.AF_INET6

        if got_family is None and len(addr) == 2:
            try:
                result = socket.inet_pton(socket.AF_INET, addr[0])
            except socket.error:
                pass
            else:
                got_family = socket.AF_INET

        # Do it this way so any errors aren't gobbled up in those try
        # thingies.
        if got_family is not None:
            callback(addr, got_family)
            return

        if native_resolve:
            if len(addr) == 2:
                fam = socket.AF_INET
            else:
                if not HAS_IPV6:
                    callback(None, None, FAMILY_ERROR)
                    return

                fam = socket.AF_INET6

            try:
                info = socket.getaddrinfo(addr[0], addr[1], fam)[0]
            except socket.gaierror, err:
                callback(None, None, (err.errno, err.strerror))
                return

            callback(info[4], info[0])
            return

        # Resolve it with Pants.
        def dns_callback(status, cname, ttl, rdata):
            if status == dns.DNS_NAMEERROR:
                callback(None, None, NAME_ERROR)
                return

            if status != dns.DNS_OK or not rdata:
                self._resolve_addr(addr, True, callback)
                return

            for i in rdata:
                if ':' in i:
                    if not HAS_IPV6:
                        continue
                    callback((i,) + addr[1:], socket.AF_INET6)
                    return
                else:
                    callback((i,) + addr[1:], socket.AF_INET)
                    return
            else:
                callback(None, None, FAMILY_ERROR)

        if len(addr) == 4:
            if not HAS_IPV6:
                callback(None, None, FAMILY_ERROR)
                return
            qtype = dns.AAAA
        else:
            qtype = (dns.AAAA, dns.A)

        dns.query(addr[0], qtype, callback=dns_callback)

    ##### Internal Event Handler Methods ######################################

    def _handle_events(self, events):
        """
        Handle events raised on the channel.

        =========  ============
        Argument   Description
        =========  ============
        events     The events in the form of an integer.
        =========  ============
        """
        if self._closed:
            log.warning("Received events for closed %r." % self)
            return

        self._processing_events = True

        previous_events = self._events
        self._events = Engine.BASE_EVENTS

        if events & Engine.READ:
            self._handle_read_event()
            if self._closed:
                return

        if events & Engine.WRITE:
            self._handle_write_event()
            if self._closed:
                return

        if events & Engine.ERROR:
            self._handle_error_event()
            if self._closed:
                return

        if events & Engine.HANGUP:
            self._handle_hangup_event()
            if self._closed:
                return

        if self._events != previous_events:
            self.engine.modify_channel(self)

        self._processing_events = False

    def _handle_read_event(self):
        """
        Handle a read event raised on the channel.

        Not implemented in :class:`~pants._channel._Channel`.
        """
        raise NotImplementedError

    def _handle_write_event(self):
        """
        Handle a write event raised on the channel.

        Not implemented in :class:`~pants._channel._Channel`.
        """
        raise NotImplementedError

    def _handle_error_event(self):
        """
        Handle an error event raised on the channel.

        By default, logs the error and closes the channel.
        """
        err, errstr = self._get_socket_error()
        if err != 0:
            log.error("Error on %r: %s (%d)" % (self, errstr, err))
            self.close()

    def _handle_hangup_event(self):
        """
        Handle a hangup event raised on the channel.

        By default, logs the hangup and closes the channel.
        """
        log.debug("Hang up on %r." % self)
        self.close()
