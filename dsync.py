
import os
import socket
import SocketServer
from SimpleXMLRPCServer import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler
from hashlib import sha1
import diff_match_patch as dmp_module
import threading
import json

DEFAULT_PORT = 33411


class DSync:
	def __init__(self):
		self.dmp = dmp_module.diff_match_patch()
		self.localtext = ""
		self.shadow = {"text": "", "localv": 0, "remotev": 0}
		self.backup = {"text": "", "localv": 0}

	def set_text(self, text):
		self.localtext = text
		# Every time we apply a change, we must send them out:
		return self.message_construct()

	def get_text(self):
		return self.localtext

	def message_parse(self, msg):
		if msg["lastv"] != self.shadow["localv"]:
			# Recover
			pass

		# TODO: Make sure edits are in sequential order
		for edit in msg["edits"]:
			if not self.patch_shadow(edit):
				# Hard patching failed, roll back hard.
				self.shadow["text"] = self.backup["text"]
				self.shadow["localv"] = self.backup["localv"]
			else:
				self.shadow["remotev"] = edit["v"]

		self.patch_localtext(edit)
		# Check conflicts. If none, we're good.

	def message_construct(self):
		delta = self.diff_local()
		msg = {"edits": [{"diff": delta, "v": self.shadow["localv"]}], "lastv": self.shadow["remotev"] }
		self.update_shadow()
		return msg

	def update_shadow(self):
		self.shadow["text"] = self.localtext
		self.shadow["localv"] += 1

	def patch_localtext(self, patches):
		patchset = self.dmp.patch_fromText(patches["diff"])
		res, retval = self.dmp.patch_apply(patchset, self.localtext)
		if all(retval) == True:
			self.localtext = res
			return False
		else:
			return False

	def patch_shadow(self, patches):
		patchset = self.dmp.patch_fromText(patches["diff"])
		res, retval = self.dmp.patch_apply(patchset, self.shadow["text"])
		self.shadow["text"] = res
		return True

	def diff_local(self):
		p = self.dmp.patch_make(self.shadow["text"], self.localtext)
		return self.dmp.patch_toText(p)

	def restore_backup(self):
		self.shadow["text"] = self.backup["text"]
		self.shadow["localv"] = self.backup["localv"]

	def save_backup(self):
		self.backup["text"] = self.shadow["text"]
		self.backup["localv"] = self.shadow["localv"]


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


class DSyncPeer:
	pass


class DSyncHTTPServer(DSyncPeer, HttpServer):
	"""Run a HTTP Server and process requests in both directions."""
	pass


class DSyncFileMon(DSyncPeer):
	"""Monitor a file and continuously update it over a DSync channel"""
	pass


class DSyncSocketServer(DSyncPeer):
	"""Monitor a file and continuously update it over a DSync channel"""
	pass


class DSyncPeerManager:
	def __init__(self, document):
		assert(isinstance(document, DSync))

		self.document = document
		self.peers = []

	def addPeer(self, connection):
		assert(isinstance(connection, DSyncPeer))
		pass

	def removePeer(self, connection):
		pass

	def cycle(self):
		# Collect messages and send them out to each peer in turn
		# Is doing a peer-based round robin acceptable, or do we
		# want to do some locking and threading?
		pass


if __name__ == "__main__":
	d1 = DSync()
	d2 = DSync()
	d2.message_parse(d1.set_text("Cat"))
	d2.message_parse(d1.set_text("Cat!"))
	d2.message_parse(d1.set_text("Hat"))
	print "D2 [Hat   ]: ", d2.get_text()
	print "D1 [Hat   ]: ", d1.get_text()
	d1.message_parse(d2.set_text("Hatter"))
	print "D2 [Hatter]: ", d2.get_text()
	print "D1 [Hatter]: ", d1.get_text()
	d2.message_parse(d1.set_text("Arbitrary"))
	print "D2 [Arbitr]: ", d2.get_text()
	print "D1 [Arbitr]: ", d1.get_text()
	print "--- Intentionally doing things out of sequence: ---"
	r1 = d1.set_text("Monster")
	r2 = d2.set_text("Arbitrary foo")
	d2.message_parse(r1)
	d1.message_parse(r2)
	print "D2 [BREAK ]: ", d2.get_text()
	print "D1 [BREAK ]: ", d1.get_text()
	print "D1 shadow: %d/%d: '%s'" % (d1.shadow["localv"], d1.shadow["remotev"], d1.shadow["text"])
	print "D2 shadow: %d/%d: '%s'" % (d2.shadow["localv"], d2.shadow["remotev"], d2.shadow["text"])
	print "D1 backup: %d: '%s'" % (d1.backup["localv"], d1.backup["text"])
	print "D2 backup: %d: '%s'" % (d2.backup["localv"], d2.backup["text"])
	print "--- Intentionally doing things that are unacceptable: ---"
	r1 = d1.set_text("Monster foo madness")
	r2 = d1.set_text("Monster fudge madness")
	d2.message_parse(r2)
	d2.message_parse(r1)
	print "D2 [BREAK ]: ", d2.get_text()
	print "D2 shadow: %d/%d: '%s'" % (d2.shadow["localv"], d2.shadow["remotev"], d2.shadow["text"])
	print "D2 backup: %d: '%s'" % (d2.backup["localv"], d2.backup["text"])
