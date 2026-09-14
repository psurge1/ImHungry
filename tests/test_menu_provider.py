import pytest

from imhungry.errors import AppError
from imhungry.providers import WebMenuProvider


class Headers:
    def get_content_charset(self):
        return "utf-8"


class Response:
    headers = Headers()

    def __init__(self, html, url):
        self.html, self.url = html.encode(), url

    def read(self, limit):
        return self.html

    def geturl(self):
        return self.url


def test_menu_provider_tries_public_source_and_parses_macros():
    calls = []
    html = "<h1>Torchey's Tacos</h1><div>Chicken Taco</div><div>Calories 520 Protein 28g Carbs 42g Fat 18g</div>"
    def opener(request, timeout):
        calls.append(request.full_url)
        if "menumacros.com" in request.full_url:
            return Response(html, request.full_url)
        raise OSError("offline")
    provider = WebMenuProvider(opener=opener)
    items = provider.menu("Torchy's Tacos", "US", "Chicken")
    assert calls[0] == "https://menumacros.com/torchys_tacos_us"
    assert items[0]["food"]["display_name"] == "Chicken Taco"
    assert items[0]["nutrition"]["protein_g"] == 28
    assert items[0]["source"]["provider"] == "menumacros"
    assert items[0]["estimate"]["assumptions"]


def test_macros_menu_proxy_requires_https_and_encodes_official_url():
    calls = []
    html = "Chicken Bowl Calories 600 Protein 40g Carbs 60g Fat 16g"
    def opener(request, timeout):
        calls.append(request.full_url)
        return Response(html, request.full_url)
    provider = WebMenuProvider(opener=opener)
    provider.menu("Chuy's", menu_url="https://www.chuys.com/menu")
    assert calls == ["https://macros.menu/https%3A%2F%2Fwww.chuys.com%2Fmenu"]
    with pytest.raises(AppError):
        provider.menu("Chuy's", menu_url="http://example.com/menu")


def test_no_result_is_a_provider_error_for_service_fallback():
    provider = WebMenuProvider(opener=lambda request, timeout: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(AppError, match="No documented"):
        provider.menu("Unknown restaurant")
