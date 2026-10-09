"""Regression: production must serve the versioned CSS/JS used by Django admin."""
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.management import call_command
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from whitenoise.middleware import WhiteNoiseMiddleware


class AdminStaticFilesTests(TestCase):
    def test_collected_admin_assets_are_versioned_and_served_without_debug(self):
        assets = {
            "admin/css/base.css": "text/css",
            "admin/css/login.css": "text/css",
            "admin/css/responsive.css": "text/css",
            "admin/css/dark_mode.css": "text/css",
            "admin/css/nav_sidebar.css": "text/css",
            "admin/js/theme.js": "javascript",
            "admin/js/nav_sidebar.js": "javascript",
        }
        with tempfile.TemporaryDirectory() as root:
            with override_settings(
                DEBUG=False, STATIC_ROOT=root, WHITENOISE_USE_FINDERS=False
            ):
                call_command("collectstatic", interactive=False, verbosity=0)
                self.assertTrue((Path(root) / "staticfiles.json").is_file())
                app = WhiteNoiseMiddleware(lambda request: HttpResponse(status=404))
                for asset, content_type in assets.items():
                    with self.subTest(asset=asset):
                        url = staticfiles_storage.url(asset)
                        self.assertNotEqual(url, settings.STATIC_URL + asset)
                        response = app(RequestFactory().get(url))
                        self.assertEqual(response.status_code, 200)
                        self.assertIn(content_type, response["Content-Type"])
                        self.assertIn("immutable", response["Cache-Control"])
                        response.close()
