
import os
import socket
import SocketServer
from SimpleXMLRPCServer import SimpleXMLRPCServer, SimpleXMLRPCRequestHandler
from hashlib import sha1
import diff_match_patch as dmp_module
import threading

DEFAULT_PORT = 33411


class DSync:
	def __init__(self):
		self.dmp = dmp_module.diff_match_patch()
		self.localtext = ""
		self.shadow = {text: "", localv: 0, remotev: 0}
		self.backup = {text: "", localv: 0}

	def set_text(self, text):
		self.localtext = text
		# Every time we apply a change, we must send them out:
		self.message_send()	

	def get_text(self):
		return self.localtext

	def message_parse(self, msg):
		if msg["lastv"] != shadow["localv"]:
			# Recover
			pass

		# TODO: Make sure edits are in sequential order
		for edit in msg["edits"]:
			if not self.patch_shadow(edit):
				# Hard patching failed, roll back hard.
				shadow["text"] = backup["text"]
				shadow["localv"] = backup["localv"]
			else:
				shadow["remotev"] = edit["v"]

		self.patch_localtext(edit)
		# Check conflicts. If none, we're good.

	def message_construct(self):
		delta = self.diff_local()
		msg = {"edits": [{diff: delta, v: shadow["localv"]}]}
		self.update_shadow()
		return msg


	def update_shadow(self):
		self.shadow["text"] = self.localtext
		self.shadow["localv"] += 1

	def patch_localtext(self, patches):
		res, retval = self.dmp.patch_apply(patches, self.localtext)
		if all(retval) == True:
			self.localtext = res
			return False
		else:
			return False

	def patch_shadow(self, patches):
		res, retval = self.dmp.patch_apply(patches, self.shadow["text"])
		self.shadow["text"] = res
		return True

	def diff_local(self):
		return self.dmp.patch_make(self.shadow["text"], self.localtext)

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
	dmp = dmp_module.diff_match_patch()
	patches = dmp.patch_make("The man on the dancing boat went awol", "The man on the fishing boat went swimming")
	print dmp.patch_toText(patches)
	print dmp.patch_apply(patches, "The man on the dancing boat went awol")
