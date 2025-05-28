from fastmcp import FastMCP
from decouple import config
import requests
import base64
from lxml import etree
from typing import Dict, Any, List, Optional


mcp = FastMCP("はてなブログ用MCPサーバー")

HATENA_ID = config("HATENA_ID")
HATENA_BLOG_ID = config("HATENA_BLOG_ID")
HATENA_API_KEY = config("HATENA_API_KEY")


def get_auth_header():
    """Basic認証ヘッダーを生成"""
    credentials = f"{HATENA_ID}:{HATENA_API_KEY}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return {"Authorization": f"Basic {encoded}"}


def get_collection_uri():
    """コレクションURIを生成"""
    return f"https://blog.hatena.ne.jp/{HATENA_ID}/{HATENA_BLOG_ID}/atom/entry"


@mcp.tool()
async def list_entries(
    page_url: Optional[str] = None, max_results: int = 10
) -> Dict[str, Any]:
    """
    ブログ記事一覧を取得

    Args:
        page_url: ページネーション用URL（省略時は最新記事から）
        max_results: 取得する最大記事数

    Returns:
        記事一覧と次ページURL
    """
    if not all([HATENA_ID, HATENA_BLOG_ID, HATENA_API_KEY]):
        return {
            "error": "環境変数 HATENA_ID, HATENA_BLOG_ID, HATENA_API_KEY を設定してください"
        }

    url = page_url or get_collection_uri()

    response = requests.get(url, headers=get_auth_header())

    if response.status_code != 200:
        return {"error": f"Failed to fetch entries: {response.status_code}"}

    # XMLをパース
    root = etree.fromstring(response.content)
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    entries = []
    for entry in root.xpath("//atom:entry", namespaces=ns)[:max_results]:
        entry_data = {
            "id": entry.find("atom:id", ns).text,
            "title": entry.find("atom:title", ns).text,
            "link": entry.find("atom:link[@rel='alternate']", ns).get("href"),
            "published": entry.find("atom:published", ns).text,
            "updated": entry.find("atom:updated", ns).text,
            "categories": [
                cat.get("term") for cat in entry.findall("atom:category", ns)
            ],
        }
        entries.append(entry_data)

    # 次ページのリンクを取得
    next_link = root.find("atom:link[@rel='next']", ns)
    next_page_url = next_link.get("href") if next_link is not None else None

    return {"entries": entries, "next_page_url": next_page_url, "count": len(entries)}


@mcp.tool()
async def get_entry(entry_id: str) -> Dict[str, Any]:
    """
    特定の記事を取得

    Args:
        entry_id: 記事ID（記事一覧で取得したID）

    Returns:
        記事の詳細情報
    """
    if not all([HATENA_ID, HATENA_BLOG_ID, HATENA_API_KEY]):
        return {"error": "環境変数を設定してください"}

    url = f"https://blog.hatena.ne.jp/{HATENA_ID}/{HATENA_BLOG_ID}/atom/entry/{entry_id}"

    response = requests.get(url, headers=get_auth_header())

    if response.status_code != 200:
        return {"error": f"Failed to fetch entry: {response.status_code}"}

    root = etree.fromstring(response.content)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "hatena": "http://www.hatena.ne.jp/info/xmlns#",
    }

    return {
        "id": root.find("atom:id", ns).text,
        "title": root.find("atom:title", ns).text,
        "content": root.find("atom:content", ns).text,
        "content_type": root.find("atom:content", ns).get("type", "text"),
        "published": root.find("atom:published", ns).text,
        "updated": root.find("atom:updated", ns).text,
        "categories": [cat.get("term") for cat in root.findall("atom:category", ns)],
        "draft": root.find("hatena:draft", ns).text == "yes"
        if root.find("hatena:draft", ns) is not None
        else False,
    }


@mcp.tool()
async def search_entries(
    keyword: str, max_results: int = 10, search_in_content: bool = True
) -> Dict[str, Any]:
    """
    キーワードで記事を検索

    Args:
        keyword: 検索キーワード
        max_results: 取得する最大記事数
        search_in_content: 本文も検索対象にするか（Trueの場合、処理が重くなる可能性あり）

    Returns:
        検索結果の記事一覧
    """
    if not all([HATENA_ID, HATENA_BLOG_ID, HATENA_API_KEY]):
        return {"error": "環境変数を設定してください"}

    all_entries = []
    next_url = None
    keyword_lower = keyword.lower()

    # ページネーションを使って全記事を検索
    while len(all_entries) < max_results * 3:  # 検索のため多めに取得
        result = await list_entries(page_url=next_url, max_results=50)
        if "error" in result:
            return result

        for entry in result["entries"]:
            # タイトルで検索
            if keyword_lower in entry["title"].lower():
                all_entries.append(entry)
                continue

            # カテゴリで検索
            if any(keyword_lower in cat.lower() for cat in entry["categories"]):
                all_entries.append(entry)
                continue

            # 本文も検索対象にする場合
            if search_in_content:
                entry_detail = await get_entry(entry["id"].split("/")[-1])
                if "content" in entry_detail and keyword_lower in entry_detail["content"].lower():
                    all_entries.append(entry)

            if len(all_entries) >= max_results:
                break

        next_url = result.get("next_page_url")
        if not next_url or len(all_entries) >= max_results:
            break

    return {
        "entries": all_entries[:max_results],
        "count": len(all_entries[:max_results]),
        "keyword": keyword
    }


@mcp.tool()
async def get_categories() -> Dict[str, Any]:
    """
    カテゴリ一覧を取得

    Returns:
        カテゴリ一覧と各カテゴリの記事数
    """
    if not all([HATENA_ID, HATENA_BLOG_ID, HATENA_API_KEY]):
        return {"error": "環境変数を設定してください"}

    category_count = {}
    next_url = None

    # 全記事を取得してカテゴリを集計
    while True:
        result = await list_entries(page_url=next_url, max_results=50)
        if "error" in result:
            return result

        for entry in result["entries"]:
            for category in entry["categories"]:
                category_count[category] = category_count.get(category, 0) + 1

        next_url = result.get("next_page_url")
        if not next_url:
            break

    # カテゴリを記事数でソート
    sorted_categories = sorted(
        category_count.items(), key=lambda x: x[1], reverse=True
    )

    return {
        "categories": [
            {"name": cat, "count": count} for cat, count in sorted_categories
        ],
        "total": len(sorted_categories)
    }


@mcp.tool()
async def get_entries_by_category(
    category: str, max_results: int = 10
) -> Dict[str, Any]:
    """
    特定のカテゴリに属する記事一覧を取得

    Args:
        category: カテゴリ名
        max_results: 取得する最大記事数

    Returns:
        指定カテゴリの記事一覧
    """
    if not all([HATENA_ID, HATENA_BLOG_ID, HATENA_API_KEY]):
        return {"error": "環境変数を設定してください"}

    category_entries = []
    next_url = None

    # ページネーションを使って記事を検索
    while len(category_entries) < max_results:
        result = await list_entries(page_url=next_url, max_results=50)
        if "error" in result:
            return result

        for entry in result["entries"]:
            if category in entry["categories"]:
                category_entries.append(entry)
                if len(category_entries) >= max_results:
                    break

        next_url = result.get("next_page_url")
        if not next_url:
            break

    return {
        "entries": category_entries[:max_results],
        "count": len(category_entries[:max_results]),
        "category": category
    }


if __name__ == "__main__":
    # サーバーを起動
    mcp.run()