import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_AUDIO_BACKEND','pulseaudio')
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QApplication, QLineEdit
from ui import MainWindow, SetupOverlay
from memory import config_manager


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.settings=patch('ui._read_full_config',return_value={})
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.window=MainWindow('ultron_avatar.png')
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_setup_fits_both_window_sizes(self):
        for width,height in ((1280,820),(1100,720)):
            with self.subTest(size=(width,height)):
                self.window.resize(width,height)
                self.app.processEvents()
                overlay=self.window._overlay
                self.assertIsNotNone(overlay)
                self.assertTrue(overlay.isVisible())
                self.assertTrue(self.window.rect().contains(overlay.geometry()))
                self.assertTrue(overlay.rect().contains(overlay._submit_btn.mapTo(overlay,overlay._submit_btn.rect().bottomRight())))
                self.assertGreater(self.window._input.width(),100)

    def test_unconfigured_composer_keeps_draft_and_shows_setup(self):
        self.window._dismiss_connection_setup()
        self.window._input.setText('Please keep this message')
        self.window._send()
        self.assertEqual(self.window._input.text(),'Please keep this message')
        self.assertIsNotNone(self.window._overlay)

    def test_rejected_busy_send_keeps_draft(self):
        self.window._ready=True
        self.window.on_text_command=Mock(return_value=False)
        self.window._input.setText('Draft')
        self.window._send()
        self.assertEqual(self.window._input.text(),'Draft')

    def test_accepted_send_clears_input_once(self):
        self.window._ready=True
        self.window.on_text_command=Mock(return_value=True)
        self.window._input.setText('Hello')
        self.window._send()
        self.assertEqual(self.window._input.text(),'')
        self.window.on_text_command.assert_called_once_with('Hello')

    def test_missing_key_and_empty_model_have_visible_validation(self):
        overlay=self.window._overlay
        done=Mock()
        overlay.done.connect(done)
        overlay._submit()
        self.assertIn('API key',overlay._status.text())
        overlay._key_input.setText('fake-key')
        overlay._model_combo.setCurrentText('')
        overlay._submit()
        self.assertIn('model ID',overlay._status.text())
        done.assert_not_called()

    def test_provider_switch_clears_unsaved_key_and_resets_url(self):
        overlay=self.window._overlay
        overlay._key_input.setText('fake-unsaved-key')
        overlay._provider_combo.setCurrentIndex(overlay._provider_combo.findData('nvidia_nim'))
        self.assertEqual(overlay._key_input.text(),'')
        self.assertEqual(overlay._url_input.text(),'https://integrate.api.nvidia.com/v1')
        overlay._provider_combo.setCurrentIndex(overlay._provider_combo.findData('gemini'))
        self.assertNotIn('nvidia',overlay._url_input.text())

    def test_stale_connection_result_is_not_marked_verified(self):
        overlay=self.window._overlay
        generation=overlay._generation
        overlay._model_combo.setCurrentText('changed-model')
        overlay._finish_test(generation,None,True,'Verified')
        self.assertIn('Settings changed',overlay._status.text())
        self.assertTrue(overlay._test_btn.isEnabled())

    def test_key_visibility_is_explicit_and_resets_on_provider_switch(self):
        overlay=self.window._overlay
        self.assertEqual(overlay._key_input.echoMode(),QLineEdit.EchoMode.Password)
        overlay._show_key.setChecked(True)
        self.assertEqual(overlay._key_input.echoMode(),QLineEdit.EchoMode.Normal)
        overlay._provider_combo.setCurrentIndex(overlay._provider_combo.findData('gpt'))
        self.assertEqual(overlay._key_input.echoMode(),QLineEdit.EchoMode.Password)

    def test_cancel_never_writes_preferences(self):
        overlay=self.window._overlay
        overlay._key_input.setText('fake-key')
        with patch.object(config_manager,'save_config') as save:
            overlay._cancel_btn.click()
            self.assertIsNone(self.window._overlay)
            save.assert_not_called()

    def test_failed_save_keeps_setup_open_then_success_persists(self):
        overlay=self.window._overlay
        overlay._provider_combo.setCurrentIndex(overlay._provider_combo.findData('ollama'))
        with patch.object(config_manager,'save_config',side_effect=OSError('disk unavailable')):
            overlay._submit()
        self.assertIs(self.window._overlay,overlay)
        self.assertIn('Could not save',overlay._status.text())
        with patch.object(config_manager,'save_config') as save:
            overlay._submit()
        self.assertIsNone(self.window._overlay)
        self.assertTrue(self.window._ready)
        self.assertEqual(save.call_args.args[0]['ai_provider'],'ollama')

    def test_missing_microphone_has_truthful_button_status(self):
        self.window._microphone_available(False)
        self.assertTrue(self.window._muted)
        self.assertFalse(self.window._mute_btn.isEnabled())
        self.assertIn('TEXT MODE',self.window._mute_btn.text())

    def test_atomic_settings_write_uses_only_target_and_no_temp_left(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'api_keys.json'
            with patch.object(config_manager,'CONFIG_FILE',target):
                config_manager.save_config({'ai_provider':'ollama'})
            self.assertIn('ollama',target.read_text())
            self.assertEqual(list(Path(directory).iterdir()),[target])
