"""DDG 结果页解析测试(纯函数,无网络)。"""
from researchpilot.search.providers import _parse_ddg_html

PAGE = """<html><body>
<div class="result results_links">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">Title A</a>
  <a class="result__snippet">Snippet for A.</a>
</div>
<div class="result results_links">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fb">Title B</a>
  <a class="result__snippet">Snippet for B.</a>
</div>
</body></html>"""


def test_parse_basic_results():
    results = _parse_ddg_html(PAGE)
    assert len(results) == 2
    assert results[0].url == "https://example.com/a"  # uddg 参数被还原
    assert results[0].title == "Title A"
    assert results[0].snippet == "Snippet for A."
    assert results[1].url == "https://example.com/b"


def test_parse_empty_page():
    assert _parse_ddg_html("<html><body>no results</body></html>") == []


def test_parse_plain_https_href():
    """非 uddg 链接(直接 https://)也应支持。"""
    page = '<a class="result__a" href="https://plain.io/x">Plain</a>'
    results = _parse_ddg_html(page)
    assert results[0].url == "https://plain.io/x"
    assert results[0].title == "Plain"


def test_parse_malformed_html_does_not_crash():
    # 截断/畸形 HTML 不能抛异常
    assert _parse_ddg_html("<a class=result__a href=") == []
