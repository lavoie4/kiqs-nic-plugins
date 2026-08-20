import unittest
from chatwatcher_v2.features.keywords import Keywords

class TestKeywords(unittest.TestCase):

    def setUp(self):
        self.keywords = Keywords()
        self.keywords.add_keyword("test")
        self.keywords.add_keyword("example")

    def test_add_keyword(self):
        self.keywords.add_keyword("new_keyword")
        self.assertIn("new_keyword", self.keywords.keywords)

    def test_remove_keyword(self):
        self.keywords.remove_keyword("test")
        self.assertNotIn("test", self.keywords.keywords)

    def test_capture_message_with_keyword(self):
        message = "This is a test message."
        self.assertTrue(self.keywords.capture_message(message))

    def test_capture_message_without_keyword(self):
        message = "This is a message."
        self.assertFalse(self.keywords.capture_message(message))

    def test_log_profile_view(self):
        self.keywords.log_profile_view("user123")
        self.assertIn("user123", self.keywords.profile_views)

    def test_log_download(self):
        self.keywords.log_download("file.txt")
        self.assertIn("file.txt", self.keywords.downloads)

if __name__ == '__main__':
    unittest.main()