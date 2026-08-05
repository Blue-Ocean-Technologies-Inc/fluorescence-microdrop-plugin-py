"""Theme-aware styling for this plugin's panes and windows.

The app's colour scheme can change while it runs (the OS toggling dark
mode), so styling is applied once up front and again on every change —
the pattern the device viewer and the magnet plugin already use, kept
here in one place because this plugin has several panes plus a popup
window that all need it.
"""
from pyface.qt.QtCore import Qt
from pyface.qt.QtWidgets import QApplication

from microdrop_style.button_styles import get_tooltip_style
from microdrop_style.general_style import get_general_style
from microdrop_style.helpers import QT_THEME_NAMES, is_dark_mode
from microdrop_style.label_style import get_label_style


def current_theme():
    """'dark' or 'light' for the app's colour scheme right now."""
    return "dark" if is_dark_mode() else "light"


def theme_stylesheet(theme=None):
    """The plugin's stylesheet for a theme. Order matters slightly:
    generic rules first, specific widgets last."""
    theme = theme or current_theme()
    return "\n".join((get_general_style(theme), get_label_style(theme),
                      get_tooltip_style(theme)))


def follow_app_theme(widget, also=None):
    """Style ``widget`` for the current theme and keep it in step with
    later changes. ``also`` is called with the theme name ('dark' /
    'light') on each restyle, for anything that is not a stylesheet —
    a matplotlib figure, say.

    Returns the connected slot: hold on to it and pass it to
    :func:`unfollow_app_theme` when the widget goes away, or the signal
    will keep calling into a deleted window.
    """
    def restyle(scheme=None):
        theme = (QT_THEME_NAMES.get(scheme) if scheme is not None
                 else None) or current_theme()
        try:
            widget.setStyleSheet(theme_stylesheet(theme))
        except RuntimeError:
            return          # the widget went away before we did
        if also is not None:
            also(theme)

    restyle()
    QApplication.styleHints().colorSchemeChanged.connect(restyle)
    return restyle


def unfollow_app_theme(slot):
    """Stop restyling on theme changes. Safe to call with None, or
    twice."""
    if slot is None:
        return
    try:
        QApplication.styleHints().colorSchemeChanged.disconnect(slot)
    except (RuntimeError, TypeError):
        pass                # never connected, or already disconnected


#: Figure colours per theme, for the matplotlib canvas — which is a
#: widget-sized rectangle of its own and cannot take a stylesheet.
FIGURE_COLORS = {
    "light": {"background": "#ffffff", "foreground": "#000000",
              "grid": "#b0b0b0"},
    "dark": {"background": "#1e1e1e", "foreground": "#e0e0e0",
             "grid": "#555555"},
}


def style_figure(figure, theme=None):
    """Paint a matplotlib figure in the app's theme: backgrounds, and
    every piece of text and every line that has to read against them."""
    colors = FIGURE_COLORS[theme or current_theme()]
    figure.patch.set_facecolor(colors["background"])
    for axes in figure.get_axes():
        axes.set_facecolor(colors["background"])
        for spine in axes.spines.values():
            spine.set_color(colors["foreground"])
        axes.tick_params(colors=colors["foreground"])
        axes.xaxis.label.set_color(colors["foreground"])
        axes.yaxis.label.set_color(colors["foreground"])
        axes.title.set_color(colors["foreground"])
        axes.grid(True, alpha=0.3, color=colors["grid"])
        legend = axes.get_legend()
        if legend is not None:
            legend.get_frame().set_facecolor(colors["background"])
            legend.get_frame().set_edgecolor(colors["foreground"])
            for text in legend.get_texts():
                text.set_color(colors["foreground"])
