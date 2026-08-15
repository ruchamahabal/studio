"""SSRF guard for model-authored URLs (image markers, probes)."""

import ipaddress
import socket
from urllib.parse import urlparse

import frappe
from frappe import _


def assert_not_private_url(url: str) -> list[str]:
	"""Raise PermissionError if the URL resolves to a private/internal IP.
	Returns the addresses it validated so a caller can PIN its connection to one —
	a second DNS resolution at connect time can answer differently (DNS rebinding)."""
	parsed = urlparse(url)
	if parsed.scheme not in ("http", "https"):
		frappe.throw(_("Only HTTP/HTTPS URLs are allowed for external images."), frappe.PermissionError)
	hostname = parsed.hostname
	if not hostname:
		frappe.throw(_("Invalid URL: missing hostname."), frappe.ValidationError)
	try:
		addr_infos = socket.getaddrinfo(hostname, None)
	except socket.gaierror:
		frappe.throw(_("Could not resolve hostname: {0}").format(hostname), frappe.ValidationError)
	ips = []
	for addr_info in addr_infos:
		ip = ipaddress.ip_address(addr_info[4][0])
		if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
			frappe.throw(
				_("Requests to private or internal addresses are not allowed."), frappe.PermissionError
			)
		ips.append(str(ip))
	return ips
