import pytest
from engine.sources import ytdlp


def test_authorization_gate():
    assert ytdlp.authorization({"license": "Creative Commons Attribution license (reuse allowed)"}) == "creative-commons"
    assert ytdlp.authorization({"license": ""}, attested=True) == "user-attested"
    with pytest.raises(ytdlp.NotAuthorized):
        ytdlp.authorization({"title": "x", "license": ""})
