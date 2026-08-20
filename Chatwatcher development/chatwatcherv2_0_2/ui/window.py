from gi.repository import Gtk

class ChatWatcherWindow(Gtk.Window):
    def __init__(self, plugin):
        super().__init__(title="ChatWatcher V2")
        self.plugin = plugin
        self.set_default_size(800, 600)

        # Create a notebook for tabs
        self.notebook = Gtk.Notebook()
        self.add(self.notebook)

        # Create tabs for Played, Keywords, and Shitlist
        self.create_played_tab()
        self.create_keywords_tab()
        self.create_shitlist_tab()

        self.show_all()

    def create_played_tab(self):
        played_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        played_label = Gtk.Label(label="Played Feature")
        played_box.pack_start(played_label, True, True, 0)
        # Additional UI components for Played feature can be added here
        self.notebook.append_page(played_box, Gtk.Label(label="Played"))

    def create_keywords_tab(self):
        keywords_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        keywords_label = Gtk.Label(label="Keywords Feature")
        keywords_box.pack_start(keywords_label, True, True, 0)
        # Additional UI components for Keywords feature can be added here
        self.notebook.append_page(keywords_box, Gtk.Label(label="Keywords"))

    def create_shitlist_tab(self):
        shitlist_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        shitlist_label = Gtk.Label(label="Shitlist Feature")
        shitlist_box.pack_start(shitlist_label, True, True, 0)
        # Additional UI components for Shitlist feature can be added here
        self.notebook.append_page(shitlist_box, Gtk.Label(label="Shitlist"))

def main():
    from ..plugin import Plugin

    win = ChatWatcherWindow(Plugin())
    win.connect("destroy", Gtk.main_quit)
    Gtk.main()

if __name__ == "__main__":
    main()