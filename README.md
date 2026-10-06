# firmware-agent

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/VibeBB/firmware-agent)

Design a real hardware product with AI — this is the firmware sister of
the VibeBB plugin family for AgentCanvas / OpenHands
(https://vibebb.org/).

## What firmware-agent does for you

It decides which pin on the chip does what (LEDs, sensors, buzzers, USB),
checks that your firmware builds, fits in the chip's memory, and behaves
correctly inside a simulator — and that the chosen pins actually match
the circuit board the circuit plugin designed.

## What you give it, what you get back

You give it a product idea (or a request from the UX-creator plugin),
the circuit plugin's `*.firmware.json`, and optionally photos or
datasheets of your board. You get back:

- `*.fw.json` — the firmware contract: MCU, pin map, peripherals, power modes
- a generated pin header (`fw_pins.h`) your code includes
- a generated sound-cue header (`fw_cues.h`) that plays the bard plugin's
  product cues on a buzzer pin, checked against the buzzer's frequency band
- a pin map PNG of the chip and a gate report (JSON/Markdown/PNG)
- a QEMU simulation transcript and timeline PNG
- a record of every decision, stage impression and image review
- answers to UX-creator requests (`liaison/*.ux-response.json`)

## How it works with sister plugins

The VibeBB sisters (github.com/VibeBB/…) exchange JSON files, never
code. UX-creator directs firmware through liaison requests; the
electrical-circuit plugin provides `*.firmware.json` and checks the pin
map firmware exports back; firmware files change requests to circuit,
mechanical, wire, UX, bard, doc, prodeng, sim, fpga or dashboard sisters
when something outside its scope must move — it never edits a sister's
files. See https://vibebb.org/.

## Getting started

Requires Docker (all tools run inside a pinned `firmware-tools` image).
Install the plugin from this repo's `plugins/firmware` directory into
AgentCanvas / OpenHands, then ask, for example:

> "Design the firmware pin map for my smart kettle on an RP2040 — heater
> on a PWM pin, temperature sensor on I2C, one button."

Useful prompts: `/firmware:doctor` checks the toolchain,
`/firmware:design` starts a contract, `/firmware:gates` runs every check.

## Safety and limits

- Docker-only: no pinned tools image, no run — never falls back to your
  host.
- The tool container has no network access.
- Gates are deterministic and fail closed; vision reviews are advisory.
- The simulator is not real hardware — it checks printed behaviour, not
  electricity, RF or timing.
- Nothing is flashed to a device; a human signs off on real hardware.

## For engineers

Module map, gate semantics, JSON contracts, MCP tools, hooks and the
record protocol live in [docs/README.md](docs/README.md).

License: BSD-3-Clause, © VibeBB (see `LICENSE`; third-party tools in
`THIRD_PARTY_NOTICES.md`).

## 日本語

AI で実際のハードウェア製品を設計する — AgentCanvas / OpenHands 向け
VibeBB プラグインファミリーの firmware 姉妹プラグインです
（https://vibebb.org/）。

### firmware-agent ができること

チップのどのピンが何を担うか（LED、センサー、ブザー、USB など）を決め、
ファームウェアがビルドできるか、チップのメモリに収まるか、
シミュレータ内で正しく動くか、そして選んだピンが回路プラグインの
設計した基板と一致するかを検証します。

### 入力と出力

製品のアイデア（または UX-creator プラグインからの依頼）、回路
プラグインの `*.firmware.json`、必要なら基板の写真やデータシートを
渡します。返ってくるもの:

- `*.fw.json` — MCU、ピンマップ、ペリフェラル、電源モードを定義した
  ファームウェア契約
- コードがインクルードする生成済みピンヘッダ `fw_pins.h`
- bardプラグインの製品の効果音（cue）をブザーで鳴らすための生成済みヘッダ `fw_cues.h`（ブザーが鳴らせる周波数の範囲に収まるかを確認済み）
- チップのピンマップ PNG とゲートレポート（JSON/Markdown/PNG）
- QEMU シミュレーションのログとタイムライン PNG
- すべての決定・ステージ感想・画像レビューの記録
- UX-creator 依頼への回答（`liaison/*.ux-response.json`）

### 姉妹プラグインとの連携

VibeBB 姉妹（github.com/VibeBB/…）はコードではなく JSON ファイルで
連携します。UX-creator は liaison 依頼で firmware を指揮し、
electrical-circuit プラグインは `*.firmware.json` を渡して
firmware のピンマップを検査します。firmware は自分の範囲外の変更を
circuit・mechanical・wire・UX・bard・doc・prodeng・sim・fpga・
dashboard の各姉妹へ変更依頼として出し、姉妹のファイルは絶対に
編集しません。https://vibebb.org/ を参照。

### はじめ方

Docker が必須です（すべてのツールはピン留めされた
`firmware-tools` イメージ内で実行されます）。このリポジトリの
`plugins/firmware` ディレクトリから AgentCanvas / OpenHands に
プラグインをインストールし、例えば:

> 「RP2040 のスマートケトル用ファームウェアのピンマップを設計して
> — ヒーターは PWM ピン、温度センサーは I2C、ボタンは1つ。」

便利なコマンド: `/firmware:doctor` はツールチェーン診断、
`/firmware:design` は契約の作成開始、`/firmware:gates` は全検査。

### 安全性と限界

- Docker 専用: ツールイメージが無ければ実行せず、ホストには逃げません。
- ツールコンテナはネットワークなしで動きます。
- ゲートは決定論的でフェイルクローズ。画像レビューは助言のみ。
- シミュレータは実機ではありません — 電気特性・RF・タイミングは見ません。
- 実機への書き込みは行いません。最終判断は人間が行います。

### エンジニア向け

モジュール構成、ゲート仕様、JSON 契約、MCP ツール、フック、
レコードプロトコルは [docs/README.md](docs/README.md) にあります。

ライセンス: BSD-3-Clause、© VibeBB（`LICENSE` 参照。サードパーティ
ツールは `THIRD_PARTY_NOTICES.md`）。
