class KeywordsFeature:
    def __init__(self, config):
        self.config = config
        self.keywords = []
        self.message_log = []

    def add_keyword(self, keyword):
        if keyword not in self.keywords:
            self.keywords.append(keyword)

    def remove_keyword(self, keyword):
        if keyword in self.keywords:
            self.keywords.remove(keyword)

    def log_message(self, message):
        self.message_log.append(message)
        self.check_keywords(message)

    def check_keywords(self, message):
        text = message if self.config.get_setting("keywords", "case_sensitive", False) else message.casefold()
        for keyword in self.keywords:
            candidate = keyword if self.config.get_setting("keywords", "case_sensitive", False) else keyword.casefold()
            if candidate in text:
                self.handle_keyword_match(message, keyword)

    def handle_keyword_match(self, message, keyword):
        # Logic to handle the matched keyword in the message
        print(f"Keyword '{keyword}' found in message: {message}")

    def get_logged_messages(self):
        return self.message_log

    def get_keywords(self):
        return self.keywords