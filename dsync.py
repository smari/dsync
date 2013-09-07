# coding: utf-8
#
#	DSync - Differential Synchronization
#
__AUTHOR__ = "Smári McCarthy <smarimccarthy@thoughtworks.com>"

import os
import socket
import SocketServer
from SimpleXMLRPCServer import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler
from hashlib import sha1
import diff_match_patch as dmp_module
import threading
import json
import time, datetime
import stat

DEFAULT_PORT = 33411


class DSyncPeer:
	def __init__(self, dsync):
		self.shadow = {"text": "", "localv": 0, "remotev": 0}
		self.backup = {"text": "", "localv": 0}
		self.dsync = dsync

	def message_receive(self, message):
		print "Received message! %s" % message
		self.dsync.message_parse(message, self)

	def message_send(self, message):
		# Send the message to the peer
		pass


class DSync:
	def __init__(self):
		self.dmp = dmp_module.diff_match_patch()
		self.localtext = ""
		self.peers = []

	def peer_add(self, peer):
		assert(isinstance(peer, DSyncPeer))
		self.peers.append(peer)

	def peer_remove(self, peer):
		self.peers.remove(peer)

	def set_text(self, text):
		if self.localtext == text:
			return

		print "Detected change!!"
		self.localtext = text

		# Every time we apply a change, we must send them out to all peers:
		for peer in self.peers:
			self.message_send(peer)

	def get_text(self):
		return self.localtext

	def message_parse(self, msg, peer):
		if msg["lastv"] != peer.shadow["localv"]:
			# Recover
			pass

		# TODO: Make sure edits are in sequential order
		for edit in msg["edits"]:
			if not self.patch_shadow(peer, edit):
				# Hard patching failed, roll back hard.
				peer.shadow["text"] = peer.backup["text"]
				peer.shadow["localv"] = peer.backup["localv"]
			else:
				peer.shadow["remotev"] = edit["v"]

		self.patch_localtext(edit)
		# Check conflicts. If none, we're good.

	def message_construct(self, peer):
		delta = self.diff_local(peer)
		msg = {"edits": [{"diff": delta, "v": peer.shadow["localv"]}], "lastv": peer.shadow["remotev"] }
		self.update_shadow(peer)
		return msg

	def message_send(self, peer):
		msg = self.message_construct(peer)
		peer.message_send(msg)

	def update_shadow(self, peer):
		peer.shadow["text"] = self.localtext
		peer.shadow["localv"] += 1

	def patch_localtext(self, patches):
		patchset = self.dmp.patch_fromText(patches["diff"])
		res, retval = self.dmp.patch_apply(patchset, self.localtext)
		if all(retval) == True:
			print "Patched..."
			self.localtext = res
			print "localtext = '%s'" % self.localtext
			return False
		else:
			return False

	def patch_shadow(self, peer, patches):
		patchset = self.dmp.patch_fromText(patches["diff"])
		res, retval = self.dmp.patch_apply(patchset, peer.shadow["text"])
		peer.shadow["text"] = res
		return True

	def diff_local(self, peer):
		p = self.dmp.patch_make(peer.shadow["text"], self.localtext)
		return self.dmp.patch_toText(p)

	def restore_backup(self, peer):
		peer.shadow["text"] = peer.backup["text"]
		peer.shadow["localv"] = peer.backup["localv"]

	def save_backup(self, peer):
		peer.backup["text"] = peer.shadow["text"]
		peer.backup["localv"] = peer.shadow["localv"]


class HttpRequestHandler(SimpleXMLRPCRequestHandler):

	def http_host(self):
		return self.headers.get('host', 'localhost').rsplit(':', 1)[0]

	def server_url(self):
		return '%s://%s' % (self.headers.get('x-forwarded-proto', 'http'),
		                    self.headers.get('host', 'localhost'))

	def send_http_response(self, code, msg):
		self.wfile.write('HTTP/1.1 %s %s\r\n' % (code, msg))

class HttpWorker(threading.Thread):
	def __init__(self, session, sspec):
		threading.Thread.__init__(self)
		self.httpd = HttpServer(session, sspec, HttpRequestHandler)
		self.session = session

	def run(self):
		self.httpd.serve_forever()

	def quit(self):
		if self.httpd: self.httpd.shutdown()
		self.httpd = None

class HttpServer(SocketServer.ThreadingMixIn, SimpleXMLRPCServer):
	def __init__(self, session, sspec, handler):
		SimpleXMLRPCServer.__init__(self, sspec, handler)
		self.session = session
		self.sessions = {}
		self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		self.sspec = (sspec[0] or 'localhost', self.socket.getsockname()[1])
		# FIXME: This could be more securely random
		self.secret = '-'.join([str(x) for x in [self.socket, self.sspec,
		                                         time.time(), self.session]])

	def finish_request(self, request, client_address):
		try:
			SimpleXMLRPCServer.finish_request(self, request, client_address)
		except socket.error, e:
			pass

class DSyncHTTPClient(DSyncPeer):
	"""A HTTP client!"""
	pass

class DSyncHTTPServer(DSyncPeer, HttpServer):
	"""Run a HTTP Server and process requests in both directions."""
	pass

class DSyncFilePeerWorker(threading.Thread):
	def __init__(self, peer):
		threading.Thread.__init__(self)
		self.peer = peer
		self.on = True

	def run(self):
		lastmodified = os.stat(self.peer.instream).st_mtime - 1
		while True:
			if os.stat(self.peer.instream).st_mtime > lastmodified:
				fh = open(self.peer.instream)
				buf = fh.read()
				if buf == "" or buf == "\n":
					fh.close()
					continue
				buf = json.loads(buf)
				fh.close()
				self.peer.message_receive(buf)
				fh = open(self.peer.instream, "w")
				fh.write("")
				fh.close()

			time.sleep(0.2)

	def quit(self):
		self.on = False


class DSyncFilePeer(DSyncPeer):
	"""Monitor an input stream file and contribute updates to an output stream file."""
	def __init__(self, dsync, instream, outstream):
		DSyncPeer.__init__(self, dsync)
		self.instream = instream
		self.outstream = outstream

	def monitor(self):
		self.worker = DSyncFilePeerWorker(self)
		self.worker.start()

	def quit(self):
		self.worker.quit()

	def message_send(self, message):
		print "%s: Sending message %s" % (self.dsync.name, message)
		fh = open(self.outstream, "w")
		fh.write(json.dumps(message))
		fh.close()


class DSyncFileClientWorker(threading.Thread):
	def __init__(self, client):
		threading.Thread.__init__(self)
		self.client = client
		self.on = True

	def run(self):
		lastmodified = os.stat(self.client.filename).st_mtime - 1
		while self.on:
			if os.stat(self.client.filename).st_mtime > lastmodified:
				buf = open(self.client.filename).read()
				self.client.set_text(buf)
				lastmodified = os.stat(self.client.filename).st_mtime

			if buf != self.client.localtext:
				print "%s: Writing out to '%s'" % (self.client.name, self.client.filename)
				fh = open(self.client.filename, "w")
				fh.write(buf)
				fh.close()

			time.sleep(0.2)

	def quit(self):
		self.on = False


class DSyncFileClient(DSync):
	"""Monitor a file and continuously update it over a DSync channel"""
	def __init__(self, name):
		DSync.__init__(self)
		self.name = name

	def monitor(self, filename):
		self.filename = filename
		self.worker = DSyncFileClientWorker(self)
		self.worker.start()

	def stop(self):
		self.worker.quit()


class DSyncSocketServer(DSyncPeer):
	pass


if __name__ == "__main__":
	d1 = DSyncFileClient("D1")
	d2 = DSyncFileClient("D2")

	d1.monitor("d1.foo")
	d2.monitor("d2.bar")

	p1 = DSyncFilePeer(d1, "foo.in", "foo.out")
	d1.peer_add(p1)
	p1.monitor()

	p2 = DSyncFilePeer(d2, "foo.out", "foo.in")
	d2.peer_add(p2)
	p2.monitor()

	while True:
		print "P1: %s =====" % d1.get_text()
		print "P2: %s =====" % d2.get_text()
		time.sleep(1)