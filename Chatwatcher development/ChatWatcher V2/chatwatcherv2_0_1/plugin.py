"""Compatibility import for the Nicotine+ plugin entry point.

Nicotine+ loads ``__init__.py`` from the plugin folder. The authoritative
implementation lives there, matching the working example plugins in this
workspace.
"""

from . import Plugin

ChatWatcherPlugin = Plugin

__all__ = ["Plugin", "ChatWatcherPlugin"]
