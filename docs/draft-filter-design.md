# 下書きフィルタリング機能 設計文書

## 概要

本文書は、はてなブログMCPサーバーに追加された下書き記事フィルタリング機能の設計について説明します。

## 背景

従来の実装では、記事一覧や検索結果に下書き記事が含まれていました。しかし、多くのユースケースでは公開済みの記事のみを取得したいため、下書き記事を除外するオプションが必要でした。

## 設計方針

1. **後方互換性の維持**: 既存のAPIに影響を与えないよう、新しいパラメータはオプショナルとする
2. **デフォルトの動作**: デフォルトでは下書き記事を除外する（`include_drafts=False`）
3. **一貫性**: すべての記事取得系APIに統一的なインターフェースを提供

## 実装詳細

### 影響を受けるAPI

以下の3つのAPIに`include_drafts`パラメータを追加：

1. `list_entries`: 記事一覧取得API
2. `search_entries`: キーワード検索API
3. `get_entries_by_category`: カテゴリ別記事取得API

### パラメータ仕様

```python
include_drafts: bool = False
```

- **型**: bool
- **デフォルト値**: False（下書きを除外）
- **説明**: Trueを指定した場合、下書き記事も結果に含める

### フィルタリングの実装

#### 1. list_entries関数

```python
# エントリーIDを取得してキャッシュを確認
entry_id = entry.find("atom:id", ns).text.split("/")[-1]
cache_key = f"entry_{entry_id}"
cached = load_cache(cache_key)

# キャッシュに記事がある場合は下書きかどうかを確認
if cached and cached.get("draft", False):
    continue
```

はてなブログAPIから取得した記事一覧に対して、各記事のキャッシュを確認し、下書きフラグが立っている記事をスキップします。

#### 2. search_entries関数

```python
# 下書きをフィルタリング
if not include_drafts and cached.get("draft", False):
    continue
```

キャッシュから記事を検索する際に、下書きフラグをチェックしてフィルタリングします。

#### 3. get_entries_by_category関数

```python
result = await list_entries(
    page_url=next_url, 
    max_results=50, 
    include_drafts=include_drafts
)
```

内部的に`list_entries`を呼び出しているため、`include_drafts`パラメータを伝播させることでフィルタリングを実現します。

### キャッシュの活用

下書き情報は`fetch_entry_from_api`関数でAPIから取得し、キャッシュに保存されます：

```python
"draft": root.find("hatena:draft", ns).text == "yes"
if root.find("hatena:draft", ns) is not None
else False,
```

これにより、APIへのアクセスを最小限に抑えつつ、高速な下書きフィルタリングが可能となります。

## 使用例

### 公開記事のみを取得（デフォルト）

```python
# 下書きを除外した記事一覧を取得
result = await list_entries(max_results=20)

# 下書きを除外してキーワード検索
result = await search_entries(keyword="Python")

# 下書きを除外してカテゴリ別記事を取得
result = await get_entries_by_category(category="技術")
```

### 下書きを含めて取得

```python
# 下書きを含む全記事一覧を取得
result = await list_entries(max_results=20, include_drafts=True)

# 下書きを含めてキーワード検索
result = await search_entries(keyword="Python", include_drafts=True)

# 下書きを含めてカテゴリ別記事を取得
result = await get_entries_by_category(category="技術", include_drafts=True)
```

## 今後の拡張可能性

1. **フィルタリング条件の追加**: 日付範囲、更新日時などでのフィルタリング
2. **パフォーマンスの最適化**: 下書き記事が多い場合のページネーション改善
3. **キャッシュ戦略の改善**: 下書き/公開ステータスの変更を効率的に反映

## まとめ

本機能により、はてなブログMCPサーバーのユーザーは、用途に応じて下書き記事を含めるか除外するかを柔軟に選択できるようになりました。デフォルトで下書きを除外することで、多くのユースケースで期待される動作を提供しつつ、必要に応じて下書きも取得できる柔軟性を維持しています。