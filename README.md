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

### 3. キャッシュの管理

```bash
# キャッシュを更新（全記事をローカルに保存）
uv run python server.py --update-cache

# キャッシュをクリア
uv run python server.py --clear-cache
```

### 4. サーバーの起動

```bash
uv run python server.py
```

※ 初回起動時またはキャッシュが存在しない場合は、自動的にキャッシュを更新します。

## 利用可能なツール

### `list_entries`
ブログ記事の一覧を取得します。

**パラメータ:**
- `page_url` (optional): ページネーション用URL
- `max_results` (optional): 取得する最大記事数（デフォルト: 10）

### `get_entry`
特定の記事の詳細を取得します。キャッシュから取得します。

**パラメータ:**
- `entry_id`: 記事ID

### `search_entries`
記事をキーワードで検索します。キャッシュから高速検索します。

**パラメータ:**
- `keyword`: 検索キーワード
- `max_results` (optional): 取得する最大記事数（デフォルト: 10）

### `get_categories`
全てのカテゴリと記事数を取得します。

### `get_entries_by_category`
特定のカテゴリに属する記事を取得します。

**パラメータ:**
- `category`: カテゴリ名
- `max_results` (optional): 取得する最大記事数（デフォルト: 10）


## キャッシュについて

- キャッシュは`blog_cache/`ディレクトリに保存されます
- キャッシュの有効期限は1年間です
- サーバー起動時にキャッシュがない場合は自動で更新されます
- `--update-cache`オプションでキャッシュを手動更新できます
- 全ての記事検索と取得はキャッシュから高速に行われます

## ライセンス

MIT License
