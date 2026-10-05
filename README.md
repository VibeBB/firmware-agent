# firmware-agent

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/VibeBB/firmware-agent)

VibeBB firmware plugin for OpenHands (AgentCanvas). It designs and verifies
microcontroller firmware together with the sibling plugins
(`electrical-circuit-agent`, `mechanical-agent`, `wire-agent`,
`UX-creator-agent`, `bard-agent`, `document-agent`).

A firmware contract `<name>.fw.json` declares the MCU, pin map, peripherals
and power modes. Deterministic gates decide whether the design and the
code are acceptable:

| gate | checks |
| --- | --- |
| `fw.contract` | contract schema, MCU profile, circuit export readable |
| `fw.pin_functions` | pad exists, not reserved, routes the function and peripheral instance; strapping/JTAG pads acknowledged |
| `fw.netlist_match` | every pad is on the declared circuit net of the declared MCU; no active pad unassigned; voltage and supply net |
| `fw.power_modes` | duty cycle, wake sources, powered peripherals, average-current budget |
| `fw.pins_header` | generated pin header matches the contract |
| `fw.build` | make / CMake / PlatformIO build succeeds and produces the ELF |
| `fw.memory_budget` | flash and RAM from ELF segments within budget |
| `fw.static_analysis` | cppcheck with no blocking finding |
| `fw.sim.<id>` | QEMU run prints the expected UART lines (ARM core fidelity or Espressif ESP32/ESP32-S3) |

`firmware debug` attaches GDB to a QEMU run and records breakpoints,
backtraces, registers and expressions as advisory evidence.

## Layout

- `src/firmware/` — contract models, MCU profiles, gates, CLI, MCP server.
- `plugins/firmware/` — the OpenHands plugin: agents
  (`firmware-architect`, `firmware-developer`, `firmware-review`),
  commands (`doctor`, `design`, `gates`, `pinmap`, `simulate`, `debug`),
  skills, hooks, launcher, `.mcp.json`.
- `examples/smart-kettle/` — RP2040 bare-metal C, Make build, ARM QEMU
  (`mps2-an385`) logic simulation.
- `examples/desk-lamp-s3/` — ESP32-S3 ESP-IDF via PlatformIO, Espressif
  QEMU full-image simulation, circuit export from a KiCad netlist.
- `docker/firmware-tools.Dockerfile` — pinned toolchain image.
- `docs/` — ADRs.

## Quick start

```bash
uv sync --locked
uv run python -m firmware doctor
uv run python -m firmware check examples/smart-kettle/smart-kettle.fw.json
docker build -f docker/firmware-tools.Dockerfile -t firmware-tools:dev .
FIRMWARE_TOOLS_IMAGE=firmware-tools:dev \
  python3 plugins/firmware/scripts/firmware_launcher.py gates examples/desk-lamp-s3/desk-lamp.fw.json
```

CLI: `firmware {doctor,validate,check,gates,pins,pinmap,sim,debug,request,profile}`.
MCP tools: `firmware_doctor`, `firmware_validate`, `firmware_check`,
`firmware_gates`, `firmware_pins`, `firmware_pinmap_export`,
`firmware_sim`, `firmware_debug`, `firmware_request`, `firmware_profile`.

## Circuit cooperation

```bash
# circuit side
python -m circuit firmware-export --brief board.brief.json --netlist board.net --out circuit/
# firmware side
python -m firmware gates board.fw.json
# circuit side confirms the firmware pin map
python -m circuit firmware-check --brief board.brief.json --netlist board.net \
  --pinmap fw-reports/board.fw-pinmap.json
```

## Development

```bash
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest
uv run python scripts/check_plugin_load.py
uv run python scripts/verify_docs.py
```

## License

BSD-3-Clause. Third-party tools are listed in `THIRD_PARTY_NOTICES.md`.

## 日本語

OpenHands（AgentCanvas）向けの VibeBB ファームウェアプラグイン。姉妹プラグイン
（`electrical-circuit-agent`、`mechanical-agent`、`wire-agent`、
`UX-creator-agent`、`bard-agent`、`document-agent`）と連携して、
マイコンのファームウェアを設計・検証します。

ファームウェアコントラクト `<name>.fw.json` で MCU、ピンマップ、
ペリフェラル、パワーモードを宣言します。決定論的なゲートが設計と
コードの合否を判定します:

| ゲート | 検査内容 |
| --- | --- |
| `fw.contract` | コントラクトのスキーマ、MCU プロファイル、回路エクスポートの読み取り可否 |
| `fw.pin_functions` | パッドの存在・非予約、機能とペリフェラルインスタンスへの割当、ストラッピング/JTAG パッドの確認 |
| `fw.netlist_match` | 全パッドが宣言 MCU の宣言回路ネット上にあること、アクティブパッドの未割当なし、電圧と電源ネット |
| `fw.power_modes` | デューティサイクル、起床源、給電ペリフェラル、平均電流予算 |
| `fw.pins_header` | 生成されたピンヘッダがコントラクトと一致 |
| `fw.build` | make / CMake / PlatformIO ビルドが成功し ELF を生成 |
| `fw.memory_budget` | ELF セグメント由来のフラッシュ/RAM が予算内 |
| `fw.static_analysis` | cppcheck でブロッキング指摘がないこと |
| `fw.sim.<id>` | QEMU 実行が期待された UART 行を出力（ARM コア忠実度または Espressif ESP32/ESP32-S3） |

`firmware debug` は QEMU 実行に GDB をアタッチし、ブレークポイント、
バックトレース、レジスタ、式を助言的証拠として記録します。

### 構成

- `src/firmware/` — コントラクトモデル、MCU プロファイル、ゲート、CLI、MCP サーバー。
- `plugins/firmware/` — OpenHands プラグイン: エージェント
  （`firmware-architect`、`firmware-developer`、`firmware-review`）、
  コマンド（`doctor`、`design`、`gates`、`pinmap`、`simulate`、`debug`）、
  スキル、フック、ランチャー、`.mcp.json`。
- `examples/smart-kettle/` — RP2040 ベアメタル C、Make ビルド、ARM QEMU
  （`mps2-an385`）ロジックシミュレーション。
- `examples/desk-lamp-s3/` — PlatformIO 経由の ESP32-S3 ESP-IDF、Espressif
  QEMU フルイメージシミュレーション、KiCad ネットリスト由来の回路エクスポート。
- `docker/firmware-tools.Dockerfile` — ピン固定済みツールチェーンイメージ。
- `docs/` — ADR。

### クイックスタート

```bash
uv sync --locked
uv run python -m firmware doctor
uv run python -m firmware check examples/smart-kettle/smart-kettle.fw.json
docker build -f docker/firmware-tools.Dockerfile -t firmware-tools:dev .
FIRMWARE_TOOLS_IMAGE=firmware-tools:dev \
  python3 plugins/firmware/scripts/firmware_launcher.py gates examples/desk-lamp-s3/desk-lamp.fw.json
```

CLI: `firmware {doctor,validate,check,gates,pins,pinmap,sim,debug,request,profile}`。
MCP ツール: `firmware_doctor`、`firmware_validate`、`firmware_check`、
`firmware_gates`、`firmware_pins`、`firmware_pinmap_export`、
`firmware_sim`、`firmware_debug`、`firmware_request`、`firmware_profile`。

### 回路側との連携

```bash
# 回路側
python -m circuit firmware-export --brief board.brief.json --netlist board.net --out circuit/
# ファームウェア側
python -m firmware gates board.fw.json
# 回路側がファームウェアのピンマップを確認
python -m circuit firmware-check --brief board.brief.json --netlist board.net \
  --pinmap fw-reports/board.fw-pinmap.json
```

### 開発

```bash
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pytest
uv run python scripts/check_plugin_load.py
uv run python scripts/verify_docs.py
```

### ライセンス

BSD-3-Clause。第三者ツールは `THIRD_PARTY_NOTICES.md` に一覧があります。
