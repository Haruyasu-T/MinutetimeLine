# サードパーティ ライセンス表記 (Third-Party Licenses)

MinutetimeLine 本体は [Apache License 2.0](LICENSE) で配布されます。

配布物（`MinutetimeLine.exe`）には、以下の第三者ライブラリが同梱されています。
各ライブラリは、それぞれのライセンスのもとで配布されており、その権利は各著作権者に帰属します。
ライセンス全文は `licenses/` フォルダに収録しています。

| ライブラリ | バージョン | ライセンス | 全文 |
|------------|-----------|-----------|------|
| customtkinter | 5.2.2 | MIT License | [licenses/customtkinter-LICENSE.txt](licenses/customtkinter-LICENSE.txt) |
| Pillow | 12.0.0 | HPND (MIT-CMU) | [licenses/Pillow-LICENSE.txt](licenses/Pillow-LICENSE.txt) |
| pystray | 0.19.5 | LGPL-3.0 | [licenses/pystray-LGPL-3.0.txt](licenses/pystray-LGPL-3.0.txt) ／ [licenses/pystray-GPL-3.0.txt](licenses/pystray-GPL-3.0.txt) |

## pystray (LGPL-3.0) について

`pystray` は GNU Lesser General Public License v3.0 のもとで配布されています。

- このアプリは pystray を **変更せずに利用**しています。
- pystray のソースコードは公式リポジトリから入手できます: https://github.com/moses-palmer/pystray
- LGPL-3.0 の条件に従い、利用者は pystray を同等機能の別バージョンに差し替えて
  利用することができます（本アプリは Python モジュールとして pystray を読み込んでいます）。
- ライセンス全文は `licenses/pystray-LGPL-3.0.txt`（LGPL）および
  `licenses/pystray-GPL-3.0.txt`（LGPL が参照する GPL 本文）に収録しています。

## その他

- **customtkinter** (MIT) — Copyright (c) 2023 Tom Schimansky
- **Pillow** (HPND/MIT-CMU) — Copyright (c) 1997-2011 by Secret Labs AB, 1995-2011 by Fredrik Lundh, 2010-2024 by Jeffrey A. Clark and contributors

`winsound`・`tkinter` 等は Python 標準ライブラリ（PSF License）であり、別途同梱はしていません。
