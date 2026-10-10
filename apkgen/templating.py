"""Template files shipped inside kind packages, filled with string.Template.

Templates use ``${name}`` placeholders. Substitution is strict: a missing value raises
KeyError instead of leaving a placeholder behind. Files are read verbatim (no strip or
dedent) because line positions end up in the compiled APK.
"""
from importlib import resources
from string import Template


def load(package, name):
    return resources.files(package).joinpath(name).read_text(encoding="utf-8")


def render(package, name, /, **values):
    return Template(load(package, name)).substitute(values)


def xml_escape(text):
    """Escape text for an XML attribute value (e.g. android:label="...")."""
    text = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&apos;"))
    # A leading @ or ? would be read as a resource reference.
    return "\\" + text if text[:1] in ("@", "?") else text


def aapt_string(text):
    """Escape text for the body of a <string> resource in res/values/*.xml."""
    text = text.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return "\\" + text if text[:1] in ("@", "?") else text
