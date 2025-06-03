import asyncio
import hashlib
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from decouple import config
from fastmcp import FastMCP
from lxml import etree

# ロギングの設定
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

mcp = FastMCP("はてなブログ用MCPサーバー")

HATENA_ID = config("HATENA_ID")
HATENA_BLOG_ID = config("HATENA_BLOG_ID")
HATENA_API_KEY = config("HATENA_API_KEY")

# キャッシュ設定
CACHE_DIR = Path.home() / ".cache" / "hatena-blog-mcp"
CACHE_EXPIRY_HOURS = 24 * 365  # キャッシュの有効期限（1年）


def get_auth():
    """認証情報を返す"""
    logger.debug(f"認証情報を取得: HATENA_ID={HATENA_ID}")
    return (HATENA_ID, HATENA_API_KEY)


def get_collection_uri():
    """コレクションURIを生成"""
    return f"https://blog.hatena.ne.jp/{HATENA_ID}/{HATENA_BLOG_ID}/atom/entry"


def get_entry_uri(entry_id: str):
    """エントリーURIを生成"""
    return (
        f"https://blog.hatena.ne.jp/{HATENA_ID}/{HATENA_BLOG_ID}/atom/entry/{entry_id}"
    )


def get_cache_path(key: str) -> Path:
    """キャッシュファイルのパスを生成"""
    # キーをハッシュ化してファイル名にする
    hashed = hashlib.md5(key.encode()).hexdigest()
    return CACHE_DIR / f"{hashed}.json"


def load_cache(key: str) -> Optional[Dict[str, Any]]:
    """キャッシュを読み込む"""
    cache_path = get_cache_path(key)
    logger.debug(f"キャッシュ読み込み: key={key}, path={cache_path}")
    if not cache_path.exists():
        logger.debug(f"キャッシュが存在しません: {cache_path}")
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)

        # キャッシュの有効期限をチェック
        cached_at = datetime.fromisoformat(cache_data["cached_at"])
        if datetime.now() - cached_at > timedelta(hours=CACHE_EXPIRY_HOURS):
            logger.debug(f"キャッシュ期限切れ: {cache_path}")
            cache_path.unlink()  # 期限切れキャッシュを削除
            return None

        logger.debug(f"キャッシュヒット: {key}")
        return cache_data["data"]
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        # 不正なキャッシュファイルは削除
        logger.warning(f"不正なキャッシュファイル: {cache_path}, エラー: {e}")
        cache_path.unlink()
        return None


def save_cache(key: str, data: Dict[str, Any]):
    """データをキャッシュに保存"""
    logger.debug(f"キャッシュ保存: key={key}")
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path = get_cache_path(key)

    cache_data = {"cached_at": datetime.now().isoformat(), "data": data}

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)
    logger.debug(f"キャッシュ保存完了: {cache_path}")


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
    logger.info(f"list_entries 呼び出し: page_url={page_url}, max_results={max_results}")
    if not all([HATENA_ID, HATENA_BLOG_ID, HATENA_API_KEY]):
        logger.error("環境変数が設定されていません")
        return {
            "error": "環境変数 HATENA_ID, HATENA_BLOG_ID, HATENA_API_KEY を設定してください"
        }

    url = page_url or get_collection_uri()
    logger.debug(f"API URL: {url}")

    response = requests.get(url, auth=get_auth())
    logger.debug(f"API レスポンス: status_code={response.status_code}")

    if response.status_code != 200:
        logger.error(f"APIエラー: {response.status_code}")
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

    logger.info(f"list_entries 完了: {len(entries)}件の記事を取得")
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
    logger.info(f"get_entry 呼び出し: entry_id={entry_id}")
    # キャッシュをチェック
    cache_key = f"entry_{entry_id}"
    cached = load_cache(cache_key)
    if cached:
        logger.info(f"get_entry 完了: キャッシュから取得")
        return cached

    # キャッシュがない場合はエラー
    logger.warning(f"get_entry: キャッシュに記事が存在しません entry_id={entry_id}")
    return {"error": "記事が見つかりません。キャッシュを更新してください。"}


@mcp.tool()
async def search_entries(keyword: str, max_results: int = 10) -> Dict[str, Any]:
    """
    キーワードで記事を検索

    Args:
        keyword: 検索キーワード
        max_results: 取得する最大記事数

    Returns:
        検索結果の記事一覧
    """
    logger.info(f"search_entries 呼び出し: keyword={keyword}, max_results={max_results}")
    if not CACHE_DIR.exists():
        logger.error("キャッシュディレクトリが存在しません")
        return {
            "error": "キャッシュが存在しません。サーバー側でキャッシュを更新してください。"
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

        except Exception as e:
            logger.warning(f"キャッシュファイル読み込みエラー: {cache_file}, エラー: {e}")
            continue

    logger.info(f"search_entries 完了: {len(matched_entries[:max_results])}件の記事がマッチ")
    return {
        "entries": matched_entries[:max_results],
        "count": len(matched_entries[:max_results]),
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


async def fetch_entry_from_api(entry_id: str) -> Dict[str, Any]:
    """
    APIから記事を取得（内部使用）
    """
    logger.debug(f"fetch_entry_from_api: entry_id={entry_id}")
    if not all([HATENA_ID, HATENA_BLOG_ID, HATENA_API_KEY]):
        return {"error": "環境変数を設定してください"}

    url = get_entry_uri(entry_id)
    logger.debug(f"API URL: {url}")
    response = requests.get(url, auth=get_auth())
    logger.debug(f"API レスポンス: status_code={response.status_code}")

    if response.status_code != 200:
        logger.error(f"APIエラー: {response.status_code}")
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


async def sync_all_entries_to_cache() -> Dict[str, Any]:
    """
    全ての記事をキャッシュに同期

    Returns:
        同期結果
    """
    logger.info("キャッシュ同期を開始")
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
            # タグ形式のIDから数字のエントリーIDを抽出
            # 例: "tag:blog.hatena.ne.jp,2013:blog-mtb_beta-10328749687202087533-6802418398316299513" -> "6802418398316299513"
            entry_id = entry["id"].split("-")[-1]
            try:
                # APIから取得してキャッシュに保存
                entry_detail = await fetch_entry_from_api(entry_id)
                if "error" not in entry_detail:
                    save_cache(f"entry_{entry_id}", entry_detail)
                    synced_count += 1
                else:
                    error_count += 1
            except Exception as e:
                logger.error(f"エントリ同期エラー: entry_id={entry_id}, エラー: {e}")
                error_count += 1

        next_url = result.get("next_page_url")
        if not next_url:
            break

    logger.info(f"キャッシュ同期完了: 同期={synced_count}件, エラー={error_count}件")
    return {
        "synced": synced_count,
        "errors": error_count,
        "message": f"{synced_count}件の記事をキャッシュに同期しました",
    }


async def update_cache():
    """キャッシュを更新"""
    print("キャッシュを更新しています...")
    result = await sync_all_entries_to_cache()
    if "error" in result:
        print(f"エラー: {result['error']}")
        return False
    print(f"キャッシュ更新完了: {result['synced']}件の記事を同期しました")
    if result["errors"] > 0:
        print(f"警告: {result['errors']}件のエラーが発生しました")
    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="はてなブログMCPServer")
    parser.add_argument("--update-cache", action="store_true", help="キャッシュを更新")
    parser.add_argument("--clear-cache", action="store_true", help="キャッシュをクリア")

    args = parser.parse_args()

    if args.update_cache:
        # キャッシュ更新モード
        asyncio.run(update_cache())
    elif args.clear_cache:
        # キャッシュクリアモード
        if clear_cache():
            print("キャッシュをクリアしました")
        else:
            print("キャッシュディレクトリが存在しません")
    else:
        # サーバー起動モード
        # キャッシュが存在しない場合は自動で更新
        if not CACHE_DIR.exists() or not any(CACHE_DIR.glob("*.json")):
            logger.info("初回起動のため、キャッシュを更新します")
            print("初回起動のため、キャッシュを更新します...")
            if asyncio.run(update_cache()):
                logger.info("サーバーを起動します")
                print("サーバーを起動します...")
                mcp.run()
            else:
                logger.error("キャッシュの更新に失敗しました")
                print("キャッシュの更新に失敗しました")
                sys.exit(1)
        else:
            # サーバーを起動
            logger.info("サーバーを起動します")
            mcp.run()
