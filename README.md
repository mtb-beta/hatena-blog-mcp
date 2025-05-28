# はてなブログ MCP サーバー

はてなブログの記事を取得・検索するためのMCP（Model Context Protocol）サーバーです。

## 機能

- 📝 記事一覧の取得
- 🔍 キーワードによる記事検索
- 🏷️ カテゴリ管理（一覧取得、カテゴリ別記事取得）
- 💾 キャッシュ機能による高速検索

## セットアップ

### 1. 依存関係のインストール

```bash
uv sync
```

### 2. 環境変数の設定

`.env`ファイルを作成し、以下の環境変数を設定してください：

```env
HATENA_ID=あなたのはてなID
HATENA_BLOG_ID=あなたのブログID
HATENA_API_KEY=あなたのAPIキー
```

APIキーは[はてなブログの設定ページ](https://blog.hatena.ne.jp/)から取得できます。

### 3. サーバーの起動

```bash
uv run python server.py
```

## 利用可能なツール

### `list_entries`
ブログ記事の一覧を取得します。

**パラメータ:**
- `page_url` (optional): ページネーション用URL
- `max_results` (optional): 取得する最大記事数（デフォルト: 10）

### `get_entry`
特定の記事の詳細を取得します。

**パラメータ:**
- `entry_id`: 記事ID
- `use_cache` (optional): キャッシュを使用するか（デフォルト: True）

### `search_entries`
記事をキーワードで検索します。キャッシュが存在する場合はキャッシュから高速検索します。

**パラメータ:**
- `keyword`: 検索キーワード
- `max_results` (optional): 取得する最大記事数（デフォルト: 10）
- `use_cache` (optional): キャッシュを使用するか（デフォルト: True）

### `get_categories`
全てのカテゴリと記事数を取得します。

### `get_entries_by_category`
特定のカテゴリに属する記事を取得します。

**パラメータ:**
- `category`: カテゴリ名
- `max_results` (optional): 取得する最大記事数（デフォルト: 10）

### `sync_all_entries_to_cache`
全ての記事をキャッシュに同期します。高速検索を使用する前に実行してください。

### `clear_blog_cache`
キャッシュをクリアします。

## キャッシュについて

- キャッシュは`blog_cache/`ディレクトリに保存されます
- キャッシュの有効期限は1年間です
- `sync_all_entries_to_cache`を実行することで、全記事をローカルにキャッシュできます
- `search_entries`はキャッシュが存在する場合、自動的にキャッシュから高速検索します

## ライセンス

MIT License
