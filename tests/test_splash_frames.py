"""The splash plays the animation, not whatever order the gif was exported in.

The supplied artwork holds the *finished* logo for 2.24 s, then blanks, then
animates in. Played from frame 0 that shows the punchline first and the
build-up second, which is exactly what it did on screen.
"""

from PIL import Image

from stfu.splashui import _Frame, _trim_to_the_animation

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


def frame(ink_fraction: float, duration_ms: int = 40) -> _Frame:
    """A frame with roughly `ink_fraction` of its pixels drawn on."""
    image = Image.new("RGB", (48, 48), WHITE)
    rows = int(48 * ink_fraction)
    for y in range(rows):
        for x in range(48):
            image.putpixel((x, y), BLACK)
    return _Frame(image, duration_ms)


def test_it_starts_at_the_emptiest_frame():
    # finished logo held, then blank, then a build-up: the supplied gif's shape
    frames = [frame(0.5)] * 5 + [frame(0.0)] + [frame(0.2), frame(0.4), frame(0.5)]
    trimmed = _trim_to_the_animation(frames)
    assert trimmed[0].image.getpixel((0, 0)) == WHITE


def test_it_ends_on_the_finished_mark():
    frames = [frame(0.5)] * 5 + [frame(0.0)] + [frame(0.2), frame(0.4), frame(0.5)]
    trimmed = _trim_to_the_animation(frames)
    assert trimmed[-1].image.getpixel((0, 0)) == BLACK


def test_it_drops_the_long_static_hold():
    frames = [frame(0.5)] * 50 + [frame(0.0)] + [frame(0.2), frame(0.4), frame(0.5)]
    trimmed = _trim_to_the_animation(frames)
    assert len(trimmed) < len(frames)


def test_it_keeps_a_short_hold_on_the_final_mark():
    frames = [frame(0.5)] * 50 + [frame(0.0)] + [frame(0.2), frame(0.4)] + [frame(0.5)] * 30
    trimmed = _trim_to_the_animation(frames)
    held = sum(1 for f in trimmed if f.image.getpixel((0, 0)) == BLACK)
    # A hold, but not all thirty frames of it.
    assert 1 <= held <= 15


def test_an_already_correct_gif_is_left_alone():
    frames = [frame(0.0), frame(0.2), frame(0.4), frame(0.6)]
    trimmed = _trim_to_the_animation(frames)
    assert len(trimmed) == len(frames)
    assert trimmed[0].image.getpixel((0, 0)) == WHITE


def test_a_very_short_gif_is_returned_untouched():
    frames = [frame(0.3), frame(0.6)]
    assert _trim_to_the_animation(frames) is frames


def test_a_single_frame_gif_survives():
    frames = [frame(0.3)]
    assert len(_trim_to_the_animation(frames)) == 1


def test_the_real_artwork_starts_blank_and_ends_drawn():
    from stfu.assets import assets_dir
    from stfu.splashui import _ink, _load_gif_frames

    path = assets_dir() / "brand" / "logo.gif"
    if not path.is_file():  # pragma: no cover - the asset ships with the app
        return
    frames = _load_gif_frames(path)
    assert _ink(frames[0].image) < 0.01, "the splash must open on the animation"
    assert _ink(frames[-1].image) > 0.02, "and close on the finished mark"
    total_s = sum(f.duration_ms for f in frames) / 1000
    assert total_s < 2.5, "the dead hold at the front must not be replayed"
