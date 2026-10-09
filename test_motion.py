import tempfile
import unittest
from pathlib import Path

from core import Store, UserError
from desktop import Service
from motion import DEFAULT, MODES, load_preferences, validate_preferences


class MotionTests(unittest.TestCase):
    def test_scene_upgrade_runs_once_and_preserves_custom_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            store.set('wallpaper_motion', {'mode':'still', 'paused':True, 'intensity':0,
                'entry':'outline', 'entry_enabled':False, 'prompt':'我的自定义提示词'})
            store.set('character_selected','previous-media')
            upgraded = load_preferences(store)
            self.assertEqual(upgraded['mode'],'living')
            self.assertEqual(upgraded['entry'],'portrait')
            self.assertFalse(upgraded['paused'])
            self.assertGreater(upgraded['intensity'],0)
            self.assertEqual(upgraded['prompt'],'我的自定义提示词')
            self.assertFalse(upgraded['entry_enabled'])
            self.assertEqual(store.get('character_selected'),'original')
            store.set('wallpaper_motion',{**upgraded,'mode':'still','paused':True})
            self.assertTrue(load_preferences(store)['paused'])
            self.assertEqual(load_preferences(store)['mode'],'still')

    def test_modes_and_prompt_survive_restart_without_changing_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            store.set('profile', {'近期目标': 'AI Infra'})
            service = Service(store)
            service.bootstrap()
            for mode in MODES:
                service.dispatch('motion', {**DEFAULT, 'mode': mode, 'intensity': 80,
                    'paused': True, 'cycle': True, 'entry': 'mist', 'prompt': '自定义入场提示词'})
                reboot = Service(Store(Path(directory))).bootstrap()
                self.assertEqual(reboot['motion']['mode'], mode)
                self.assertEqual(reboot['motion']['prompt'], '自定义入场提示词')
                self.assertTrue(reboot['motion']['paused'])
                self.assertEqual(reboot['profile'], {'近期目标': 'AI Infra'})
                self.assertEqual(reboot['reports'], [])

    def test_invalid_preferences_do_not_overwrite_saved_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(Store(Path(directory)))
            service.bootstrap()
            service.dispatch('motion', {'mode': 'ripple'})
            for invalid in [{'mode': []}, {'entry': 'unknown'}, {'intensity': True},
                            {'intensity': -1}, {'intensity': 101}, {'intensity': 2.5},
                            {'paused': 1}, {'cycle': 'true'}, {'entry_enabled': None},
                            {'auto_actions': 'true'},
                            {'prompt': 'x' * 12001}, {'prompt': []}]:
                with self.subTest(invalid=invalid):
                    with self.assertRaises(UserError): service.dispatch('motion', invalid)
                    self.assertEqual(service.bootstrap()['motion']['mode'], 'ripple')
            self.assertNotIn('unknown', validate_preferences({'unknown': 'ignored'}))
            self.assertEqual(validate_preferences({'intensity': 0})['intensity'], 0)

    def test_automatic_actions_preference_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            service = Service(Store(Path(directory)))
            service.bootstrap()
            service.dispatch('motion', {**DEFAULT, 'auto_actions':False})
            self.assertFalse(Service(Store(Path(directory))).bootstrap()['motion']['auto_actions'])

    def test_tail_settings_survive_restart_and_validate(self):
        with tempfile.TemporaryDirectory() as directory:
            service=Service(Store(Path(directory)));service.bootstrap()
            service.dispatch('motion',{**DEFAULT,'tail_amplitude':42,'tail_duration':6})
            restored=Service(Store(Path(directory)));self.addCleanup(service.close);self.addCleanup(restored.close)
            self.assertEqual(restored.bootstrap()['motion']['tail_amplitude'],42)
            self.assertEqual(restored.bootstrap()['motion']['tail_duration'],6)
            for bad in [{'tail_amplitude':101},{'tail_amplitude':True},{'tail_duration':3.9},{'tail_duration':6.1},{'tail_duration':float('nan')}]:
                with self.assertRaises(UserError):service.dispatch('motion',bad)

    def test_corrupt_or_missing_preferences_fall_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            self.assertEqual(load_preferences(store), DEFAULT)
            for broken in ['bad', {'mode': {}}, {'intensity': 900}]:
                store.set('wallpaper_motion', broken)
                self.assertEqual(load_preferences(store), DEFAULT)

    def test_water_settings_restart_and_invalid_ranges(self):
        with tempfile.TemporaryDirectory() as directory:
            service=Service(Store(Path(directory)));self.addCleanup(service.close);service.bootstrap()
            prefs={**DEFAULT,'water_preset':'lively','water_wait_min':12,'water_wait_max':30,'water_brush':False,'water_drift':False}
            service.dispatch('motion',prefs)
            restored=Service(Store(Path(directory)));self.addCleanup(restored.close)
            self.assertEqual(restored.bootstrap()['motion'],prefs)
            for bad in [{'water_preset':'fast'},{'water_wait_min':7},{'water_wait_max':181},{'water_wait_min':60,'water_wait_max':20},{'water_fin':1}]:
                with self.assertRaises(UserError):service.dispatch('motion',bad)
            self.assertEqual(restored.bootstrap()['motion'],prefs)


if __name__ == '__main__': unittest.main()
