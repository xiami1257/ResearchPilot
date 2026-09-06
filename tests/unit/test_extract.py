"""正文提取纯函数测试(不联网;trafilatura 本地解析)。"""

from researchpilot.search.extract import extract_text

HTML = """<!DOCTYPE html>
<html><head><title>T</title></head>
<body>
  <nav><a href="/x">导航链接不该进正文</a></nav>
  <main>
    <h1>研究标题</h1>
    <p>这是第一段真正的内容,包含<strong>加粗</strong>与
       <a href="/y">页内链接</a>。</p>
    <p>第二段内容。</p>
  </main>
  <footer>版权信息</footer>
</body></html>"""


def test_extract_keeps_main_text():
    """提取结果必须保留正文主体(标题 + 段落)。

    注意:不断言"导航被剔除"——玩具 HTML 上 trafilatura 未必能识别
    nav 语义(真实站点亦然),正文含导航文本时,去噪由 Researcher
    的 prompt 消化,这里只保证主体内容不丢。
    """
    text = extract_text(HTML)
    assert text is not None
    assert "研究标题" in text
    assert "第一段真正的内容" in text


def test_extract_empty_or_garbage_returns_none():
    assert extract_text("") is None
    assert extract_text("<html></html>") is None
    assert extract_text("not html at all") is None
