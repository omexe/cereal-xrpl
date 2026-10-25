"""The crawl gateway: a wallet may pay it only to read pages of a free site its sentence named (no network)."""
from urllib.parse import quote

from cereal import config
from cereal.routes import runs as runs_route
from cereal.service import gateway_pages, reads_site

NIKE = {"card": {"sites": [{"host": "www.nike.com", "kind": "free"}, {"host": "gatorade.com", "kind": "unreachable"}]}}


def gw(*pages: str, crawl: str = "abc") -> str:
    urls = "&".join(f"url={quote(p, safe='')}" for p in pages)
    return f"{config.CRAWL_GATEWAY_URL}/crawl/page?{urls}&crawl={crawl}"


def test_gateway_page_reads_the_target_only_from_gateway_urls():
    assert gateway_pages(gw("https://nike.com/", "https://nike.com/w/mens-shoes")) == ["https://nike.com/", "https://nike.com/w/mens-shoes"]
    assert gateway_pages("http://localhost:8000/swell/agenda") == []
    assert gateway_pages("http://evil.example/crawl/page?url=https%3A%2F%2Fnike.com%2F") == []
    assert gateway_pages(None) == []


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


def test_crawl_buys_every_page_in_one_gateway_payment_with_a_per_crawl_key(monkeypatch):
    monkeypatch.setattr("cereal.deployments.get", lambda dep_id: NIKE)
    called = []
    monkeypatch.setattr("cereal.runs.start", lambda *a, **k: called.append(k) or {"ok": True})
    runs_route.start_crawl("d_x", runs_route.CrawlRequest(pages=["https://nike.com/", "https://nike.com/w/x"], request_id="r1"))
    (kw,) = called
    assert kw["specs"] == [f"{gw('https://nike.com/', 'https://nike.com/w/x', crawl='r1')}@{config.CRAWL_PAGE_MAX}"]
    assert kw["keep_open"] is True
