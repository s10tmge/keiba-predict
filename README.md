# keiba-predict

競馬予想・バックテストシステム（個人学習・エンタメ目的）

## 概要

netkeibaから過去レースデータを収集し、予測スコアをもとに毎週3レースを厳選して楽しむための支援ツールです。

## セットアップ

```bash
pip install -r requirements.txt
```

## 使い方

### DBの初期化

```bash
python main.py init-db
```

### データ収集（特定日）

```bash
python main.py scrape --date 2024-01-01
```

### データ収集（月単位）

```bash
python main.py scrape --year 2024 --month 1
```

## プロジェクト構成

```
keiba-predict/
├── REQUIREMENTS.md     # 要件定義書
├── README.md
├── requirements.txt
├── config.py           # 設定定数
├── db/
│   ├── __init__.py
│   └── schema.py       # SQLiteスキーマ定義・初期化
├── scraper/
│   ├── __init__.py
│   ├── base.py         # ベーススクレイパー（スリープ・リトライ）
│   ├── race_list.py    # レース一覧スクレイパー
│   └── race_detail.py  # レース詳細スクレイパー
└── main.py             # CLIエントリーポイント
```

## 注意事項

- スクレイピングはrobots.txtおよびnetkeibaの利用規約を遵守してください
- ログイン不要で閲覧できるページのみを対象としています
- 本ツールは個人の趣味・学習目的です
