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
    pic = Image.open(vinyl.make_disc(str(tmp_path / "pic.png"), 240, "picture", art=str(tmp_path / "art.png")))
    r, g, b, _ = pic.getpixel((120, 40))
    assert r > g + 40 and r > b + 40                           # the cover's red shows on the disc


def test_unknown_disc_style_and_missing_art_are_refused(tmp_path):
    import pytest
    from engine.look import vinyl
    with pytest.raises(ValueError):
        vinyl.make_disc(str(tmp_path / "x.png"), 100, "banana")
    with pytest.raises(ValueError):
        vinyl.make_disc(str(tmp_path / "x.png"), 100, "picture")
