import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from decouple import config
from fastmcp import FastMCP
from lxml import etree

mcp = FastMCP("はてなブログ用MCPサーバー")

HATENA_ID = config("HATENA_ID")
HATENA_BLOG_ID = config("HATENA_BLOG_ID")
HATENA_API_KEY = config("HATENA_API_KEY")

# キャッシュ設定
CACHE_DIR = Path("blog_cache")
CACHE_EXPIRY_HOURS = 24 * 365  # キャッシュの有効期限（1年）


def get_auth():
    """認証情報を返す"""
    return (HATENA_ID, HATENA_API_KEY)


def get_collection_uri():
    """コレクションURIを生成"""
    return f"https://blog.hatena.ne.jp/{HATENA_ID}/{HATENA_BLOG_ID}/atom/entry"


def get_cache_path(key: str) -> Path:
    """キャッシュファイルのパスを生成"""
    # キーをハッシュ化してファイル名にする
    hashed = hashlib.md5(key.encode()).hexdigest()
    return CACHE_DIR / f"{hashed}.json"


def load_cache(key: str) -> Optional[Dict[str, Any]]:
    """キャッシュを読み込む"""
    cache_path = get_cache_path(key)
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)

        # キャッシュの有効期限をチェック
        cached_at = datetime.fromisoformat(cache_data["cached_at"])
        if datetime.now() - cached_at > timedelta(hours=CACHE_EXPIRY_HOURS):
            cache_path.unlink()  # 期限切れキャッシュを削除
            return None

        return cache_data["data"]
    except (json.JSONDecodeError, KeyError, ValueError):
        # 不正なキャッシュファイルは削除
        cache_path.unlink()
        return None


def save_cache(key: str, data: Dict[str, Any]):
    """データをキャッシュに保存"""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path = get_cache_path(key)

    cache_data = {"cached_at": datetime.now().isoformat(), "data": data}

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)


def clear_cache():
    """全てのキャッシュをクリア"""
    if CACHE_DIR.exists():
        for cache_file in CACHE_DIR.glob("*.json"):
            cache_file.unlink()
        return True
    return False


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

    response = requests.get(url, auth=get_auth())

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
async def get_entry(entry_id: str, use_cache: bool = True) -> Dict[str, Any]:
    """
    特定の記事を取得

    Args:
        entry_id: 記事ID（記事一覧で取得したID）
        use_cache: キャッシュを使用するか（デフォルト: True）

    Returns:
        記事の詳細情報
    """
    if not all([HATENA_ID, HATENA_BLOG_ID, HATENA_API_KEY]):
        return {"error": "環境変数を設定してください"}

    # キャッシュをチェック
    cache_key = f"entry_{entry_id}"
    if use_cache:
        cached = load_cache(cache_key)
        if cached:
            return {**cached, "from_cache": True}

    url = (
        f"https://blog.hatena.ne.jp/{HATENA_ID}/{HATENA_BLOG_ID}/atom/entry/{entry_id}"
    )

    response = requests.get(url, auth=get_auth())

    if response.status_code != 200:
        return {"error": f"Failed to fetch entry: {response.status_code}"}

    root = etree.fromstring(response.content)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "hatena": "http://www.hatena.ne.jp/info/xmlns#",
    }

    result = {
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

    # キャッシュに保存
    if use_cache:
        save_cache(cache_key, result)

    return result


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
                if (
                    "content" in entry_detail
                    and keyword_lower in entry_detail["content"].lower()
                ):
                    all_entries.append(entry)

            if len(all_entries) >= max_results:
                break

        next_url = result.get("next_page_url")
        if not next_url or len(all_entries) >= max_results:
            break

    return {
        "entries": all_entries[:max_results],
        "count": len(all_entries[:max_results]),
        "keyword": keyword,
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
    sorted_categories = sorted(category_count.items(), key=lambda x: x[1], reverse=True)

    return {
        "categories": [
            {"name": cat, "count": count} for cat, count in sorted_categories
        ],
        "total": len(sorted_categories),
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
        "category": category,
    }


@mcp.tool()
async def sync_all_entries_to_cache() -> Dict[str, Any]:
    """
    全ての記事をキャッシュに同期

    Returns:
        同期結果
    """
    if not all([HATENA_ID, HATENA_BLOG_ID, HATENA_API_KEY]):
        return {"error": "環境変数を設定してください"}

    synced_count = 0
    error_count = 0
    next_url = None

    # 全記事を取得してキャッシュに保存
    while True:
        result = await list_entries(page_url=next_url, max_results=50)
        if "error" in result:
            return result

        for entry in result["entries"]:
            entry_id = entry["id"].split("/")[-1]
            try:
                # キャッシュを強制的に更新
                await get_entry(entry_id, use_cache=False)
                synced_count += 1
            except Exception:
                error_count += 1

        next_url = result.get("next_page_url")
        if not next_url:
            break

    return {
        "synced": synced_count,
        "errors": error_count,
        "message": f"{synced_count}件の記事をキャッシュに同期しました",
    }


@mcp.tool()
async def search_entries_cached(keyword: str, max_results: int = 10) -> Dict[str, Any]:
    """
    キャッシュから高速に記事を検索

    Args:
        keyword: 検索キーワード
        max_results: 取得する最大記事数

    Returns:
        検索結果の記事一覧
    """
    if not CACHE_DIR.exists():
        return {
            "error": "キャッシュが存在しません。先に sync_all_entries_to_cache を実行してください"
        }

    keyword_lower = keyword.lower()
    matched_entries = []

    # キャッシュディレクトリ内の全ファイルを検索
    for cache_file in CACHE_DIR.glob("*.json"):
        try:
            cached = load_cache(cache_file.stem)
            if not cached:
                continue

            # タイトルで検索
            if keyword_lower in cached.get("title", "").lower():
                matched_entries.append(cached)
                continue

            # カテゴリで検索
            if any(
                keyword_lower in cat.lower() for cat in cached.get("categories", [])
            ):
                matched_entries.append(cached)
                continue

            # 本文で検索
            if keyword_lower in cached.get("content", "").lower():
                matched_entries.append(cached)

            if len(matched_entries) >= max_results:
                break

        except Exception:
            continue

    return {
        "entries": matched_entries[:max_results],
        "count": len(matched_entries[:max_results]),
        "keyword": keyword,
        "from_cache": True,
    }


@mcp.tool()
async def clear_blog_cache() -> Dict[str, Any]:
    """
    ブログのキャッシュをクリア

    Returns:
        クリア結果
    """
    if clear_cache():
        return {"message": "キャッシュをクリアしました"}
    else:
        return {"message": "キャッシュディレクトリが存在しません"}


if __name__ == "__main__":
    # サーバーを起動
    mcp.run()
