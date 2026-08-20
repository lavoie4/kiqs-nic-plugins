import unittest
from chatwatcher_v2.features.played import Played

class TestPlayed(unittest.TestCase):

    def setUp(self):
        self.played = Played()

    def test_capture_now_playing(self):
        self.played.capture_now_playing("Artist - Song Title")
        self.assertIn("Artist - Song Title", self.played.now_playing)

    def test_log_played_message(self):
        self.played.capture_now_playing("Artist - Song Title")
        self.played.log_played_message()
        self.assertTrue(self.played.has_logged("Artist - Song Title"))

    def test_block_user(self):
        self.played.block_user("user123")
        self.assertIn("user123", self.played.blocked_users)

    def test_retention_management(self):
        self.played.capture_now_playing("Artist - Song Title")
        self.played.manage_retention()
        self.assertEqual(len(self.played.now_playing), 1)

if __name__ == '__main__':
    unittest.main()