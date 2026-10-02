import tempfile
from pathlib import Path

from django.test import TestCase, override_settings


class FrontendServingTests(TestCase):
    def test_web_page_is_served_for_non_api_urls(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'index.html').write_text('<div id="root">react app</div>')

            with override_settings(FRONTEND_DIST=Path(folder)):
                for url in ['/', '/login', '/register', '/reset-password/abc/def']:
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200, url)
                    self.assertContains(response, 'react app')

    def test_unknown_api_url_is_not_answered_with_the_web_page(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'index.html').write_text('<div id="root">react app</div>')

            with override_settings(FRONTEND_DIST=Path(folder)):
                response = self.client.get('/api/does-not-exist/')

            self.assertEqual(response.status_code, 404)
            self.assertNotContains(response, 'react app', status_code=404)

    def test_missing_build_gives_a_helpful_message(self):
        with tempfile.TemporaryDirectory() as folder:
            with override_settings(FRONTEND_DIST=Path(folder)):
                response = self.client.get('/login')

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Web page files not found', status_code=404)
