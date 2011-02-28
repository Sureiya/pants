###############################################################################
#
# Copyright 2011 Chris Davis
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

import errno
import os
import socket

from pants.engine import Engine


###############################################################################
# Logging
###############################################################################

import logging
log = logging.getLogger("pants")


###############################################################################
# Channel Class
###############################################################################

class Channel(object):
    """
    A raw socket wrapper object.
    
    This class wraps a raw socket object and provides a basic API to
    make socket programming significantly simpler. It handles read,
    write and exception events, has a level of inbuilt error handling
    and calls placeholder methods when certain events occur. The Channel
    class can be subclassed directly, but it is recommended that the
    Server, Connection and Client classes be used to develop networking
    code as they provide slightly less generic APIs.
    """
    def __init__(self, socket=None):
        """
        Initialises the channel object.
        
        Args:
            socket: A pre-existing socket that this channel should wrap.
                Optional.
        """
        # Socket
        self._socket = socket or self._socket_create()
        self._socket.setblocking(False)
        self.fileno = self._socket.fileno()
        self.remote_addr = (None, None)
        self.local_addr = (None, None)
        
        # Internal state
        self._connected = False
        self._connecting = False
        self._listening = False
        self._closing = False
        
        # Input
        self.read_delimiter = None # String, integer or None.
        self._read_amount = 4096
        self._read_buffer = ""
        
        # Output
        self._write_buffer = ""
        self._secondary_write_buffer = ""
        self._write_file = None
        self._write_file_left = None
        self._write_file_chunk = 65536
        
        # Initialisation
        self._events = Engine.ERROR
        if self.readable():
            self._events |= Engine.READ
        if self.writable():
            self._events |= Engine.WRITE
        Engine.instance().add_channel(self)
    
    ##### General Methods #####################################################
    
    def active(self):
        """
        Check if the channel is currently active.
        
        Returns:
            True or False
        """
        return self._socket and (self._connected or self._listening or self._connecting)
    
    def readable(self):
        """
        Check if the channel is currently readable.
        
        Returns:
            True or False
        """
        return not self._closing
    
    def writable(self):
        """
        Check if the channel is currently writable.
        
        Returns:
            True or False
        """
        return len(self._write_buffer) > 0 or self._write_file
    
    def connect(self, host, port):
        """
        Connects to the given host and port.
        
        Args:
            host: The hostname to connect to.
            port: The port to connect to.
        
        Returns:
            The Channel object.
        """
        if self.active():
            log.warning("Channel.connect() called on active channel %d." % self.fileno)
            return
        
        self._socket_connect(host, port)
        
        return self
    
    def listen(self, port=8080, host='', backlog=1024):
        """
        Begins listening on the given host and port.
        
        Args:
            port: The port to listen on. Defaults to 8080.
            host: The hostname to listen on. Defaults to ''.
            backlog: The maximum number of queued connections. Defaults
                to 1024.
        
        Returns:
            The Channel object.
        """
        if self.active():
            log.warning("Channel.listen() called on active channel %d." % self.fileno)
            return
        
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket_bind(host, port)
        self._socket_listen(backlog)
        self._update_addr()
        
        return self
    
    def close(self):
        """
        Close the socket.
        
        Currently pending data will be sent, any further data will not
        be sent.
        """
        if not self.active():
            return
        
        if self.writable():
            self._closing = True
        else:
            self.close_immediately()
    
    def close_immediately(self):
        """
        Close the socket immediately.
        
        Any pending data will not be sent.
        """
        if not self.active():
            return
        
        if self._write_file:
            self._write_file.close()
            self._write_file = None
            self._write_file_left = None
        
        Engine.instance().remove_channel(self)
        self._socket_close()
        self._update_addr()
        self._safely_call(self.handle_close)
    
    ##### I/O Methods #########################################################
    
    def send(self, data):
        """
        Overridable wrapper for Channel.write()
        
        Args:
            data: The data to be sent.
        """
        self.write(data)
    
    def write(self, data):
        """
        Writes data to the socket.
        
        Args:
            data: The data to be sent.
        """
        if not self.active():
            raise IOError("Attempted to write to closed channel %d." % self.fileno)
        if self._closing:
            log.warning("Attempted to write to closing channel %d." % self.fileno)
            return
        
        if not self._write_file:
            self._write_buffer += data
        else:
            self._secondary_write_buffer += data
        self._add_event(Engine.WRITE)
    
    def send_file(self, file, length=None):
        self.write_file(file, length)
    
    def write_file(self, file, length=None):
        if not self.active():
            raise IOError("Attempted to write to closed channel %d." % self.fileno)
        if self._closing:
            log.warning("Attempted to write to closing channel %d." % self.fileno)
            return
        if self._write_file:
            raise IOError("Channel %d is already writing a file." % self.fileno)
        
        self._write_file = file
        self._write_file_left = length
        self._add_event(Engine.WRITE)
    
    ##### Public Event Handlers ###############################################
    
    def handle_read(self, data):
        """
        Placeholder. Called when the channel is ready to receive data.
        
        Args:
            data: The chunk of received data.
        """
        pass
    
    def handle_write(self):
        """
        Placeholder. Called after the channel has written data.
        """
        pass
    
    def handle_write_file(self):
        """
        Placeholder. Called after the channel has written a file.
        """
        pass
    
    def handle_accept(self, socket, addr):
        """
        Placeholder. Called when a new connection has been made to the
        channel.
        
        Args:
            socket: The newly-connected socket object.
            addr: The socket's address.
        """
        pass
    
    def handle_connect(self):
        """
        Placeholder. Called after the channel has connected to a remote
        host.
        """
        pass
    
    def handle_close(self):
        """
        Placeholder. Called when the channel is about to close.
        """
        pass
    
    ##### Private Methods #####################################################
    
    def _add_event(self, event):
        if not self._events & event:
            self._events |= event
            Engine.instance().modify_channel(self)
    
    def _safely_call(self, callable, *args, **kwargs):
        """
        Args:
            callable: The callable to execute.
            *args: Positional arguments to pass to the callable.
            **kwargs: Keyword arguments to pass to the callable.
        """
        try:
            callable(*args, **kwargs)
        except Exception:
            log.exception("Exception raised on channel %d." % self.fileno)
            self.close_immediately()
    
    def _update_addr(self):
        if self._connected:
            self.remote_addr = self._socket.getpeername()
            self.local_addr = self._socket.getsockname()
        elif self._listening:  
            self.remote_addr = (None, None)
            self.local_addr = self._socket.getsockname()
        else:
            self.remote_addr = (None, None)
            self.local_addr = (None, None)
    
    ##### Socket Method Wrappers ##############################################
    
    def _socket_create(self, family=socket.AF_INET, type=socket.SOCK_STREAM):
        """
        Wrapper for socket.socket().
        
        Args:
            family: The address family. Defaults to AF_INET.
            type: The socket type. Defaults to SOCK_STREAM.
        
        Returns:
            A new socket object.
        """
        return socket.socket(family, type)
    
    def _socket_connect(self, host, port):
        """
        Wrapper for self._socket.connect().
        
        Args:
            host: The hostname to connect to.
            port: The port to connect to.
        """
        if self._connected:
            return
        elif not self._connecting:
            self._connected = False
            self._connecting = True
        
        try:
            result = self._socket.connect_ex((host, port))
        except socket.error, err:
            result = err[0]
        
        if result and result != errno.EISCONN:
            if result in (errno.EWOULDBLOCK, errno.EINPROGRESS,errno.EALREADY):
                self._add_event(Engine.READ)
                self._add_event(Engine.WRITE)
                return
            
            elif result == errno.EAGAIN:
                # EAGAIN: Try again. TODO: Something.
                return
            
            else:
                errstr = "Unknown error %d" % result
                try:
                    errstr = os.strerror(result)
                except (NameError, OverflowError, ValueError):
                    if result in errno.errorcode:
                        errstr = errno.errorcode[result]
                
                raise socket.error(result, errstr)
        
        self._handle_connect_event()
    
    def _socket_bind(self, host, port):
        """
        Wrapper for self._socket.bind().
        
        Args:
            host: The hostname to bind to.
            port: The port to bind to.
        """
        self._socket.bind((host, port))
    
    def _socket_listen(self, backlog=5):
        """
        Wrapper for self._socket.listen().
        
        Args:
            backlog: The maximum number of queued connections. Defaults
                to 5.
        """
        self._listening = True
        
        if os.name == "nt" and backlog > 5:
            backlog = 5
        
        self._socket.listen(backlog)
    
    def _socket_close(self):
        """
        Wrapper for self._socket.close().
        """
        self._connected = False
        self._listening = False
        
        try:
            self._socket.close()
        except AttributeError:
            # self._socket is None - closed already.
            return
        except socket.error, err:
            if err[0] in (errno.EBADF, errno.ENOTCONN):
                # EBADF: Bad file number.
                # ENOTCONN: Transport endpoint is not connected.
                return
            else:
                raise
        finally:
            self._socket = None
    
    def _socket_accept(self):
        """
        Wrapper for self._socket.accept().
        
        Returns:
            A 2-tuple (sock, addr). sock is None if an exception was
            raised by self._socket.accept().
        """
        try:
            return self._socket.accept()
        except socket.error, err:
            if err[0] in (errno.EAGAIN, errno.EWOULDBLOCK):
                # EAGAIN: Try again.
                # EWOULDBLOCK: Operation would block.
                return None, () # sock, addr
            else:
                raise
    
    def _socket_send(self, data):
        """
        Wrapper for self._socket.send().
        
        Args:
            data: The data to be sent.
        
        Returns:
            The number of bytes sent.
        """
        try:
            return self._socket.send(data)
        except socket.error, err:
            if err[0] in (errno.EAGAIN, errno.EWOULDBLOCK):
                # EAGAIN: Try again.
                # EWOULDBLOCK: Operation would block.
                return 0
            elif err[0] in (errno.ECONNABORTED, errno.ECONNRESET,
                            errno.ENOTCONN, errno.ESHUTDOWN):
                # ECONNABORTED: Software caused connection abort.
                # ECONNRESET: Connection reset by peer.
                # ENOTCONN: Transport endpoint is not connected.
                # ESHUTDOWN: Cannot send after transport endpoint shutdown.
                self.close_immediately()
                return 0
            else:
                raise
    
    def _socket_recv(self):
        """
        Wrapper for self._socket.recv().
        
        Returns:
            The data received.
        """
        try:
            data = self._socket.recv(self._read_amount)
        except socket.error, err:
            if err[0] in (errno.EAGAIN, errno.EWOULDBLOCK):
                # EAGAIN: Try again.
                # EWOULDBLOCK: Operation would block.
                return ''
            elif err[0] in (errno.ECONNABORTED, errno.ECONNRESET,
                            errno.ENOTCONN, errno.ESHUTDOWN,):
                # ECONNABORTED: Software caused connection abort.
                # ECONNRESET: Connection reset by peer.
                # ENOTCONN: Transport endpoint is not connected.
                # ESHUTDOWN: Cannot send after transport endpoint shutdown.
                self.close_immediately()
                return ''
            else:
                raise
        
        if not data:
            # A closed connection is signalled by a read condition
            # and having recv() return an empty string.
            self.close_immediately()
            return ''
        else:
            return data
    
    ##### Private Event Handlers ##############################################
    
    def _handle_events(self, events):
        """
        Args:
            events: The events raised on the channel.
        """
        if not self.active():
            log.warning("Received events for closed channel %d." % self.fileno)
            return
        
        # Read event.
        if events & Engine.READ:
            if self._listening:
                self._handle_accept_event()
            elif not self._connected:
                self._handle_connect_event()
            else:
                self._handle_read_event()
            if not self.active():
                return
        
        # Write event.
        if events & Engine.WRITE:
            if not self._connected:
                self._handle_connect_event()
            else:
                self._handle_write_event()
            if not self.active():
                return
        
        # Error event.
        if events & Engine.ERROR:
            self.close_immediately()
            return
        
        # Update events.
        events = Engine.ERROR
        if self.readable():
            events |= Engine.READ
        if self.writable():
            events |= Engine.WRITE
        elif self._closing:
            # Done writing, so close.
            self.close_immediately()
            return
        
        if events != self._events:
            self._events = events
            Engine.instance().modify_channel(self)
    
    def _handle_accept_event(self):
        while True:
            sock, addr = self._socket_accept()
            
            if sock is None:
                return
            
            self._safely_call(self.handle_accept, sock, addr)
    
    def _handle_connect_event(self):
        self._update_addr()
        self._connected = True
        self._connecting = False
        self._safely_call(self.handle_connect)
    
    def _handle_read_event(self):
        # Receive incoming data.
        while True:
            data = self._socket_recv()
            if not data:
                break
            self._read_buffer += data
        
        # Handle incoming data.
        while self._read_buffer:
            delimiter = self.read_delimiter
            
            if delimiter is None:
                data = self._read_buffer
                self._read_buffer = ""
                self._safely_call(self.handle_read, data)
                
            elif isinstance(delimiter, (int, long)):
                if len(self._read_buffer) < delimiter:
                    break
                
                data = self._read_buffer[:delimiter]
                self._read_buffer = self._read_buffer[delimiter:]
                self._safely_call(self.handle_read, data)
                
            elif isinstance(delimiter, basestring):
                mark = self._read_buffer.find(delimiter)
                if mark == -1:
                    break
                
                data = self._read_buffer[:mark]
                self._read_buffer = self._read_buffer[mark+len(delimiter):]
                self._safely_call(self.handle_read, data)
            
            else:
                log.warning("Invalid read_delimiter on channel %d." % self.fileno)
                break
            
            if not self.active():
                break
    
    def _handle_write_event(self):
        if self._listening:
            log.warning("Received write event for listening channel %d." % self.fileno)
            return
        
        if not self._connected:
            # socket.connect() has completed, returning either 0 or an errno.
            err = self._socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if err == 0:
                self._safely_call(self._handle_connect_event())
            else:
                errstr = "Unknown error %d" % err
                try:
                    errstr = os.strerror(err)
                except (NameError, OverflowError, ValueError):
                    if err in errno.errorcode:
                        errstr = errno.errorcode[err]
                
                raise socket.error(err, errstr)
            
            # Write events are raised on clients when they initially
            # connect. In these circumstances, we may not need to write
            # any data, so we check.
            if not self.writable():
                return
        
        if not self._write_buffer and self._write_file:
            self._handle_write_file()
        else:
            self._handle_write_buffer()
    
    def _handle_write_buffer(self):
        # We only get to this stage if there's no file to be written.
        if self._secondary_write_buffer:
            self._write_buffer += self._secondary_write_buffer
            self._secondary_write_buffer = ""
        
        # Empty as much of the write buffer as possible.
        while self._write_buffer:
            sent = self._socket_send(self._write_buffer)
            if sent == 0:
                break
            self._write_buffer = self._write_buffer[sent:]
        
        self._safely_call(self.handle_write)
    
    def _handle_write_file(self):
        # Find how much needs to be written.
        if self._write_file_left:
            to_write = min(self._write_file_left, self._write_file_chunk)
            limited = True
        else:
            to_write = self._write_file_chunk
            limited = False
        
        # Read in data from the file.
        out = self._write_file.read(to_write)
        if len(out) < to_write:
            to_write = len(out)
            limited = True
        if to_write != 0:
            done = False
        else:
            done = True
        
        # If there's data to be written, write it.
        if not done:
            written = 0
            while out:
                sent = self._socket_send(out)
                if sent == 0:
                    break
                out = out[sent:]
                written += sent
            
            # File doesn't exist any more? _socket_send closed the channel.
            if not self._write_file:
                return
            
            # Written all we need to? We're done.
            if self._write_file_left:
                self._write_file_left -= written
                if self._write_file_left <= 0:
                    done = True
            
            # Written less than we need to? Back up.
            if written < to_write:
                self._write_file.seek(written - to_write, 1)
                if not limited:
                    self._write_file_chunk = written
        
        # We're done. Close the file and call the callback.
        if done:
            self._write_file.close()
            self._write_file = None
            self._safely_call(self.handle_write_file)
