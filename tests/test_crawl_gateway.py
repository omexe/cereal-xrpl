"""The crawl gateway: a wallet may pay it only to read pages of a free site its sentence named (no network)."""
from urllib.parse import quote

from cereal import config
from cereal.routes import runs as runs_route
from cereal.service import gateway_page, reads_site

NIKE = {"card": {"sites": [{"host": "www.nike.com", "kind": "free"}, {"host": "gatorade.com", "kind": "unreachable"}]}}


def gw(page: str, crawl: str = "abc") -> str:
    return f"{config.CRAWL_GATEWAY_URL}/crawl/page?url={quote(page, safe='')}&crawl={crawl}"


def test_gateway_page_reads_the_target_only_from_gateway_urls():
    assert gateway_page(gw("https://nike.com/w/mens-shoes")) == "https://nike.com/w/mens-shoes"
    assert gateway_page("http://localhost:8000/swell/agenda") is None
    assert gateway_page("http://evil.example/crawl/page?url=https%3A%2F%2Fnike.com%2F") is None
    assert gateway_page(None) is None


def test_reads_site_matches_named_free_sites_with_or_without_www():
    assert reads_site(NIKE, "https://nike.com/search?q=shoes")
    assert reads_site(NIKE, "https://www.nike.com/")
    assert not reads_site(NIKE, "https://adidas.com/")
    assert not reads_site(NIKE, "https://gatorade.com/")  # named, but not a free site
    assert not reads_site({"card": {}}, "https://nike.com/")
    assert not reads_site(NIKE, None)


def test_crawl_refuses_pages_of_sites_the_wallet_did_not_name(monkeypatch):
    monkeypatch.setattr("cereal.deployments.get", lambda dep_id: NIKE)
    called = []
    monkeypatch.setattr("cereal.runs.start", lambda *a, **k: called.append(k) or {"ok": True})
    out = runs_route.start_crawl("d_x", runs_route.CrawlRequest(pages=["https://nike.com/", "https://adidas.com/"]))
    assert out["refused"] == "site_not_in_wallet" and out["pages"] == ["https://adidas.com/"] and not called


def test_crawl_buys_each_page_from_the_gateway_with_a_per_crawl_key(monkeypatch):
    monkeypatch.setattr("cereal.deployments.get", lambda dep_id: NIKE)
    called = []
    monkeypatch.setattr("cereal.runs.start", lambda *a, **k: called.append(k) or {"ok": True})
    runs_route.start_crawl("d_x", runs_route.CrawlRequest(pages=["https://nike.com/"], request_id="r1"))
    (kw,) = called
    assert kw["specs"] == [f"{gw('https://nike.com/', 'r1')}@{config.CRAWL_PAGE_MAX}"] and kw["keep_open"] is True
