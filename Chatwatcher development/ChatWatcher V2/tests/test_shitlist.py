import unittest
from chatwatcher_v2.features.shitlist import Shitlist

class TestShitlist(unittest.TestCase):

    def setUp(self):
        self.shitlist = Shitlist()

    def test_add_to_shitlist(self):
        self.shitlist.add("bad_user")
        self.assertIn("bad_user", self.shitlist.banned_users)

    def test_remove_from_shitlist(self):
        self.shitlist.add("bad_user")
        self.shitlist.remove("bad_user")
        self.assertNotIn("bad_user", self.shitlist.banned_users)

    def test_is_user_banned(self):
        self.shitlist.add("bad_user")
        self.assertTrue(self.shitlist.is_banned("bad_user"))
        self.assertFalse(self.shitlist.is_banned("good_user"))

    def test_ignore_ip(self):
        self.shitlist.ignore_ip("192.168.1.1")
        self.assertIn("192.168.1.1", self.shitlist.ignored_ips)

    def test_unignore_ip(self):
        self.shitlist.ignore_ip("192.168.1.1")
        self.shitlist.unignore_ip("192.168.1.1")
        self.assertNotIn("192.168.1.1", self.shitlist.ignored_ips)

if __name__ == '__main__':
    unittest.main()