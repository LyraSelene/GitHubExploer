"""Prevent pywebview from recursively exposing native windows and services."""
import unittest
from unittest.mock import Mock

from desktop import DesktopAPI, CompanionBridge


class BridgeTests(unittest.TestCase):
    def test_public_bridge_attributes_are_methods_only(self):
        bridge = Mock()
        for api in (DesktopAPI(bridge), CompanionBridge(bridge)):
            for name in dir(api):
                if not name.startswith('_'):
                    self.assertTrue(callable(getattr(api, name)), name)
        self.assertEqual([n for n in dir(CompanionBridge(bridge)) if not n.startswith('_')], ['open_workspace'])

    def test_flat_bridge_preserves_arguments(self):
        bridge = Mock()
        DesktopAPI(bridge).import_materials(True, '队列', '练习')
        bridge.import_materials.assert_called_once_with(True, '队列', '练习')
        CompanionBridge(bridge).open_workspace('tasks')
        bridge.open_workspace.assert_called_once_with('tasks')


if __name__ == '__main__':
    unittest.main()
