"""Normal test apps: one empty activity and a coloured icon showing the app number.

The templates reproduce the original generator's output exactly (line positions are
compiled into the APK), so do not reformat them. With --legacy-icons the whole APK matches
the original; by default the 512 px icon goes to drawable-xxxhdpi instead of drawable/.
"""
from dataclasses import dataclass

from ... import icons, templating
from ...apk import ApkSpec

HELP = "numbered test apps (com.test.app.app<N>)"
PACKAGE_PREFIX = "com.test.app.app"


@dataclass(frozen=True)
class Options:
    legacy_icons: bool = False


def add_arguments(parser):
    parser.add_argument("--legacy-icons", action="store_true",
                        help="put the 512 px icon in res/drawable/ like the original generator "
                             "(Android then decodes it ~4x larger); default: res/drawable-xxxhdpi/")


def options_from_args(args):
    return Options(legacy_icons=args.legacy_icons)


def make_spec(i, opts, tc, prepared=None):
    package = f"{PACKAGE_PREFIX}{i}"
    label = f"Test App {i}"
    return ApkSpec(
        package=package,
        manifest=templating.render(__name__, "AndroidManifest.xml.tmpl",
                                   package=package, label=templating.xml_escape(label)),
        resources={
            "values/strings.xml": templating.render(__name__, "strings.xml.tmpl",
                                                    label=templating.aapt_string(label)),
            icons.drawable_path("ic_launcher", opts.legacy_icons): icons.render_number_icon(i, tc.font),
        },
        java_sources={
            package.replace(".", "/") + "/MainActivity.java":
                templating.render(__name__, "MainActivity.java.tmpl", package=package),
        },
        launch=("-n", f"{package}/.MainActivity"),
    )
