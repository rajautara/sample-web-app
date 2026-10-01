"""Portable unit tests: Windows/AD calls are mocked, not live integration tests."""
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace
import os
import sys
import unittest
from unittest.mock import Mock, patch


class WindowsProfileTests(unittest.TestCase):
    def setUp(self):
        flask = ModuleType("flask")
        flask.g = SimpleNamespace()
        flask.abort = Mock(side_effect=RuntimeError("Unauthorized"))
        flask.request = SimpleNamespace(headers={})
        self.flask = flask
        self.modules = patch.dict(sys.modules, {"flask": flask})
        self.modules.start()
        spec = importlib.util.spec_from_file_location(
            "profile_winauth", Path(__file__).with_name("winauth.py"))
        self.auth = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.auth)

        self.com = ModuleType("pythoncom")
        self.com.CoInitialize = Mock()
        self.com.CoUninitialize = Mock()
        self.com.com_error = type("ComError", (Exception,), {})
        self.translator = Mock()
        self.translator.Get.return_value = "CN=Person,DC=example,DC=com"
        self.account = Mock()
        self.client = ModuleType("win32com.client")
        self.client.Dispatch = Mock(return_value=self.translator)
        self.client.GetObject = Mock(return_value=self.account)
        win32com = ModuleType("win32com")
        win32com.client = self.client
        self.windows = patch.dict(sys.modules, {
            "pythoncom": self.com, "win32com": win32com,
            "win32com.client": self.client,
        })
        self.windows.start()

    def tearDown(self):
        self.windows.stop()
        self.modules.stop()

    def test_profile_and_cache_use_authenticated_account(self):
        self.account.Get.side_effect = lambda key: {
            "displayName": " Full Name ", "mail": " person@example.com "}[key]
        self.assertEqual(self.auth._read_ad_profile("EXAMPLE\\person", 1),
                         ("Full Name", "person@example.com"))
        self.translator.Set.assert_called_once_with(3, "EXAMPLE\\person")
        self.client.GetObject.assert_called_once_with(
            "LDAP://CN=Person,DC=example,DC=com")
        self.auth._read_ad_profile("EXAMPLE\\person", 1)
        self.com.CoInitialize.assert_called_once()
        self.com.CoUninitialize.assert_called_once()
        self.auth._read_ad_profile("EXAMPLE\\person", 2)
        self.assertEqual(self.com.CoInitialize.call_count, 2)

    def test_missing_mail_preserves_name(self):
        def get_attribute(key):
            if key == "mail":
                raise self.com.com_error("attribute absent")
            return "Full Name"
        self.account.Get.side_effect = get_attribute
        self.assertEqual(self.auth._read_ad_profile("EXAMPLE\\person", 1),
                         ("Full Name", None))
        self.com.CoUninitialize.assert_called_once()

    def test_ad_failure_does_not_break_authenticated_login(self):
        self.auth.RUNNING_UNDER_IIS = True
        self.auth._read_iis_token = Mock(return_value=("EXAMPLE\\person", True))
        self.translator.Init.side_effect = self.com.com_error("AD unreachable")
        app = SimpleNamespace(config={}, before_request=lambda fn: fn)
        app.before_request = lambda fn: setattr(app, "load_user", fn)
        self.auth.init_app(app)
        with self.assertLogs(self.auth.logger, level="WARNING"), patch.dict(
            os.environ, {"DEV_DISPLAY_NAME": "Spoof", "DEV_EMAIL": "spoof@example.com"}
        ):
            app.load_user()
        self.assertEqual(self.flask.g.user, "EXAMPLE\\person")
        self.assertEqual(self.flask.g.domain, "EXAMPLE")
        self.assertEqual(self.flask.g.display_name, "person")
        self.assertIsNone(self.flask.g.email)
        self.assertTrue(self.flask.g.is_admin)
        self.com.CoUninitialize.assert_called_once()

    def test_dev_profile(self):
        self.auth.RUNNING_UNDER_IIS = False
        app = SimpleNamespace(config={})
        app.before_request = lambda fn: setattr(app, "load_user", fn)
        self.auth.init_app(app)
        with patch.dict(os.environ, {
            "DEV_USER": "EXAMPLE\\person", "DEV_DISPLAY_NAME": "Full Name",
            "DEV_EMAIL": "person@example.com", "DEV_ADMIN": "0",
        }):
            app.load_user()
        self.assertEqual(self.flask.g.display_name, "Full Name")
        self.assertEqual(self.flask.g.email, "person@example.com")
        self.client.Dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
