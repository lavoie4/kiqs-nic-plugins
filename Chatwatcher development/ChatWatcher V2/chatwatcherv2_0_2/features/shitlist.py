"""Initial Shitlist state container."""


class ShitlistFeature:
    def __init__(self, config):
        self.config = config
        self.banned_keywords = set(config.get_setting("shitlist", "keywords", []))
        self.ignored_ips = set()
        self.log = []

    def add_banned_keyword(self, keyword):
        keyword = keyword.strip()
        if keyword:
            self.banned_keywords.add(keyword)

    def remove_banned_keyword(self, keyword):
        self.banned_keywords.discard(keyword)

    def process_message(self, message):
        if not self.config.get_setting("shitlist", "enabled", False):
            return []
        text = message.casefold()
        return [keyword for keyword in self.banned_keywords if keyword.casefold() in text]

    def ignore_ip(self, ip):
        self.ignored_ips.add(ip)

    def unignore_ip(self, ip):
        self.ignored_ips.discard(ip)

    def is_keyword_banned(self, keyword):
        return keyword in self.banned_keywords

    def is_ip_ignored(self, ip):
        return ip in self.ignored_ips

    def get_log(self):
        return self.log


# Compatibility with the original scaffold name.
Shitlist = ShitlistFeature
