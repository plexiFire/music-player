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
