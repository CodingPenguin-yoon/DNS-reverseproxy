from __future__ import annotations

import unittest
from types import SimpleNamespace

from edge_controller.services.caddy_renderer import render_routes_caddyfile


class CaddyRendererTest(unittest.TestCase):
    def test_renders_http_route_without_scheme_in_upstream(self) -> None:
        config = render_routes_caddyfile(
            [
                SimpleNamespace(
                    domain="heimdall.home.arpa",
                    target_scheme="http",
                    target_host="192.168.2.117",
                    target_port=8080,
                    tls_insecure_skip_verify=False,
                    enabled=True,
                )
            ]
        )

        self.assertIn("http://heimdall.home.arpa {", config)
        self.assertIn("\treverse_proxy 192.168.2.117:8080", config)

    def test_renders_https_route_with_skip_verify_transport(self) -> None:
        config = render_routes_caddyfile(
            [
                SimpleNamespace(
                    domain="proxmox.home.arpa",
                    target_scheme="https",
                    target_host="192.168.2.100",
                    target_port=8006,
                    tls_insecure_skip_verify=True,
                    enabled=True,
                )
            ]
        )

        self.assertIn("reverse_proxy https://192.168.2.100:8006 {", config)
        self.assertIn("tls_insecure_skip_verify", config)

    def test_omits_disabled_routes(self) -> None:
        config = render_routes_caddyfile(
            [
                SimpleNamespace(
                    domain="off.home.arpa",
                    target_scheme="http",
                    target_host="192.168.2.120",
                    target_port=8080,
                    tls_insecure_skip_verify=False,
                    enabled=False,
                )
            ]
        )

        self.assertNotIn("off.home.arpa", config)


if __name__ == "__main__":
    unittest.main()
