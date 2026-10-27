# 本机环境安装说明（macOS）

这份文档记录仓库在本机跑起来所需的工具链和验证结果。**只记录安装方式，不包含任何密钥。**

## 机器

- macOS 27.2 (Apple Silicon, arm64)，Xcode 已装（`/Applications/Xcode.app`）
- Shell：zsh

## 安装清单

| 组件 | 版本 | 位置 |
| --- | --- | --- |
| Homebrew | 7.0.11 | `/opt/homebrew` |
| iverilog / vvp | Icarus Verilog 13.0 | `/opt/homebrew/bin`（`brew install icarus-verilog`） |
| yosys | 0.70 | `/opt/homebrew/bin`（`brew install yosys`） |
| CUDD | 3.0.0 | `~/.local`（源码编译，`~/cudd`） |
| OpenSTA `sta` | 3.1.0 | `~/.local/bin/sta`（源码编译，`~/OpenSTA`） |
| Python | 3.11.5 | 项目内 `.venv`（由 anaconda3 的 python3 创建） |
| Python 依赖 | — | `openai` / `httpx[socks]` / `verilog-pad-analyzer==0.0.7` |

`sta` 的依赖（bison / cmake / eigen / flex / swig / tcl-tk@8）全部来自 Homebrew；CUDD 用
[cuddorg/cudd](https://github.com/cuddorg/cudd) 3.0.0 源码 `./configure --prefix="$HOME/.local"` 安装。

## 一次性安装步骤

```sh
# 1) 仿真 / 综合工具
brew install icarus-verilog yosys

# 2) CUDD 3.0.0（OpenSTA 的 BDD 依赖）
git clone https://github.com/cuddorg/cudd.git ~/cudd && cd ~/cudd && git checkout 3.0.0
touch aclocal.m4 configure config.h.in Makefile.in   # 修 Git 检出后的时间戳问题
./configure --prefix="$HOME/.local" && make -j"$(sysctl -n hw.ncpu)" && make install

# 3) OpenSTA
brew install bison cmake eigen flex swig tcl-tk@8
git clone https://github.com/parallaxsw/OpenSTA.git ~/OpenSTA && cd ~/OpenSTA
mkdir -p build && cd build
cmake -DCMAKE_BUILD_TYPE=Release \
  -DCUDD_DIR="$HOME/.local" \
  -DTCL_LIBRARY="$(brew --prefix tcl-tk@8)/lib/libtcl8.6.dylib" \
  -DCMAKE_INSTALL_PREFIX="$HOME/.local" \
  -DCMAKE_PREFIX_PATH="$(brew --prefix)" ..
make -j"$(sysctl -n hw.ncpu)" && make install

# 4) Python 环境（在仓库根目录）
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

# 5) 让工作台优先在项目内找到 sta
mkdir -p .tools && ln -sfn "$HOME/.local" .tools/opensta
```

`~/.zprofile` 里加了 `eval "$(/opt/homebrew/bin/brew shellenv)"`，`~/.zshrc` 里已有
`export PATH="$HOME/.local/bin:$PATH"`，所以新开终端四个工具都可用：

```sh
command -v iverilog vvp yosys sta
# /opt/homebrew/bin/iverilog
# /opt/homebrew/bin/vvp
# /opt/homebrew/bin/yosys
# /Users/<user>/.local/bin/sta
```

## 启动工作台

```sh
cd THU_AI_EDA_2026
make web          # 监听 http://127.0.0.1:8000
```

页面右上角 **API KEY** 输入框粘贴 DeepSeek Key 并保存（写入 `.api_key`，权限 600），
或启动前 `export DEEPSEEK_API_KEY='sk-...'`。

## 验证结果（实测）

用项目自己的 `ai_eda.rtl.metrics.synthesize_metrics` 跑通完整链路
（iverilog 仿真出 VCD → yosys 映射 gscl45nm → OpenSTA 读 VCD 估算功耗）：

- 面积 35.1975（gscl45nm 单位）
- 功耗：internal 11.2 µW + switching 0.35 µW + leakage 0.33 µW，合计约 11.9 µW
- `make web` 启动后 `GET /` 返回 200

## 不纳入仓库的内容

`.gitignore` 已排除，属于本机产物：

- `.venv/` 虚拟环境（约 65 MB）
- `.tools/` 指向 `~/.local` 的软链
- `runs/` 实验记录、`*.vcd` / `*.vvp` 等仿真产物
- `.api_key` 本地 Key（**绝不要提交**）

## 备注

- 拉 brew / pip / GitHub 需要代理（本机用 Clash Verge，`127.0.0.1:7897`）。
- 上游仓库：<https://github.com/K1ssMe520/THU_AI_EDA_2026>（本仓库是它的副本，保留了原始提交历史）。
