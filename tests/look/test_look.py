from engine.look import background as b


def test_background_style_is_deterministic_and_varies():
    from engine.look import background as b
    assert b.style_from_seed("Late Night") == b.style_from_seed("Late Night")
    looks = {str(b.style_from_seed(f"Playlist {i}")) for i in range(12)}
    assert len(looks) >= 10


def test_cover_background_is_blurred_and_oversized(tmp_path):
    from PIL import Image
    from engine.look import coverbg
    im = Image.new("RGB", (200, 200), "white")
    im.paste((255, 0, 0), (0, 0, 100, 200)); im.save(tmp_path / "c.png")
    out = Image.open(coverbg.make(str(tmp_path / "c.png"), str(tmp_path / "bg.png"), (1280, 720)))
    assert out.size == (1536, 864)                       # 1.2x so the render can drift
    a, b = out.getpixel((10, 400)), out.getpixel((1500, 400))
    assert a[0] > a[2] and b[0] > 0 and out.getpixel((768, 432))[1] > 0   # colours survive, edge is soft


def test_every_disc_style_draws_a_round_transparent_cornered_disc(tmp_path):
    from PIL import Image
    from engine.look import vinyl
    Image.new("RGB", (200, 200), (180, 60, 60)).save(tmp_path / "art.png")
    for st in vinyl.STYLES:
        im = Image.open(vinyl.make_disc(str(tmp_path / f"{st}.png"), 240, st, art=str(tmp_path / "art.png"), stars=3))
        assert im.size == (240, 240) and im.mode == "RGBA", st
        assert im.getpixel((2, 2))[3] == 0 and im.getpixel((120, 20))[3] > 200, st     # corners clear, disc solid
    cd = Image.open(vinyl.make_disc(str(tmp_path / "cd2.png"), 240, "cd"))
    assert cd.getpixel((120, 120))[3] == 0                      # a CD's centre hole is see-through
    pic = Image.open(vinyl.make_disc(str(tmp_path / "pic.png"), 240, "art", art=str(tmp_path / "art.png")))
    r, g, b, _ = pic.getpixel((120, 95))
    assert r > g + 40 and r > b + 40                           # the cover's red shows on the label
    assert max(pic.getpixel((120, 12))[:3]) < 80               # the rest of the disc stays dark


def test_unknown_disc_style_and_missing_art_are_refused(tmp_path):
    import pytest
    from engine.look import vinyl
    with pytest.raises(ValueError):
        vinyl.make_disc(str(tmp_path / "x.png"), 100, "banana")
    with pytest.raises(ValueError):
        vinyl.make_disc(str(tmp_path / "x.png"), 100, "art")


def test_every_disc_is_dark_and_solid_background_is_dark(tmp_path):
    import numpy as np
    from PIL import Image
    from engine.look import background, vinyl
    Image.new("RGB", (200, 200), (180, 60, 60)).save(tmp_path / "art.png")
    for st in vinyl.STYLES:
        a = np.asarray(Image.open(vinyl.make_disc(str(tmp_path / f"{st}.png"), 240, st, art=str(tmp_path / "art.png"))).convert("RGBA"), float)
        ring = a[..., 3] > 200
        yy, xx = np.mgrid[0:240, 0:240]
        outer = ring & (np.hypot(xx - 120, yy - 120) > 0.5 * 120)       # the playing surface, not the label
        assert a[..., :3][outer].mean() < 70, st
    for c in background.SOLID:
        im = np.asarray(Image.open(background.make_solid(str(tmp_path / f"{c}.png"), (320, 180), c)), float)
        assert im.mean() < 90, c


def test_sky_background_is_dark_loops_and_twinkles(tmp_path):
    import numpy as np
    from engine.look import background
    for name in background.SKY:
        a = background.sky_frame(320, 180, 0.2, name)
        assert a.mean() < 60, name
    f0, f1 = background.sky_frame(320, 180, 0.0, "night"), background.sky_frame(320, 180, 0.999, "night")
    mid = background.sky_frame(320, 180, 0.37, "night")
    assert np.abs(f0.astype(int) - f1.astype(int)).mean() < 1.0          # last frame flows into the first: seamless loop
    assert np.abs(f0.astype(int) - mid.astype(int)).max() > 40            # some stars changed brightness: they twinkle


def test_watermark_is_drawn_with_the_channel_name(tmp_path):
    from PIL import Image
    from engine.look import watermark
    im = Image.open(watermark.make("Senora", str(tmp_path / "w.png"), 1080))
    assert im.mode == "RGBA" and im.getbbox() is not None and im.size[0] > 60
