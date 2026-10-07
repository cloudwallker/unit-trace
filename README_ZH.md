# UnitTrace

### 在标量公式中追踪单位的本地工作台

**检查单位、追踪依赖，找到第一步不兼容的运算。将实验保存为可复算的 JSON，或用离线 SVG、HTML 分享依赖图与计算解释。**

[English](README.md) | 中文

[本地启动](#本地启动) · [试一个实验](#用流量模板走一遍) · [命令行](#命令行) · [协议与限额](docs/schema.md)

![实际流量模板：面积节点量纲错误及下游阻塞](docs/demo.png)

真实 Flow 演示定位 `width**2 + height` 的不兼容加法，并把下游流量节点标为 blocked。

## 功能

- 沿依赖图追踪公式，查看运算字符区间、数值代入、量纲和换算因子。
- 编辑变量、公式和预期范围，明确选择物理量换算或输入单位重解释。
- 探索八个实验，每个都有正常、量纲错误和尺度变化三种变体。
- 使用 Python/Pint 引擎重算已保存工程，导出 JSON、SVG 或离线 HTML。

## 本地启动

使用 **Python 3.12**。已完成本地验证的环境为 Windows、Python 3.12.14、Pint 0.25.2。

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install --require-hashes -r requirements.lock
.venv\Scripts\python -m pip install --require-hashes -r requirements-build.lock
.venv\Scripts\python -m pip install --no-deps --no-build-isolation .
.venv\Scripts\unit-trace serve --open
```

命令会打印随机端口的 `127.0.0.1` 地址。编辑期间保留服务进程，Ctrl+C 关闭会话。安装后可从源码目录之外使用命令。静态资源全部来自本地，计算交给唯一的 Python/Pint 引擎，运行时无需账户或联网服务。

## 用流量模板走一遍

1. 选择 **Flow**，点击 **Dimension error**、**Run calculation**。面积节点定位 `width**2 + height` 的加法错误，下游 flow 标为 blocked。
2. 把面积公式改为 `width * height` 后重算：面积为 6 cm²，流量为 0.0003 m³/s。
3. 将面积输出单位 `cm**2` 改为 `m**2`：面积为 0.0006 m²，转换因子为 0.0001，流量保持不变。
4. 保留 speed 的数值 50，把其输入单位从 `cm/s` 改为 `m/s`：流量变为 0.03 m³/s。直接改输入单位会重新解释物理量；要保持原物理量，请使用 **Convert** 同时换算数值和单位。
5. 勾选节点的范围检查，填写自己的预期上下限和单位。范围警告保留有效量及下游计算；范围换算无法完成时会明确说明“无法检查”。

任何修改立即把旧报告标为待计算，并禁用导出。迟到的计算或换算响应不会覆盖新编辑。点击图节点，或用 Tab/Enter 操作拓扑列表，可查看符号表达式、数值代入、当前量与量纲、转换因子及各步字符区间。

## 八个实验模板

每个模板提供正常、量纲错误和同量纲尺度变化三种变体，界面列出具体修改字段；**Restore normal** 恢复原模板。模板不会预设范围。

| ID | 正常结果 | 简化假设 |
| --- | --- | --- |
| `flow` 流量 | 0.0003 m³/s | 矩形截面、均匀流速 |
| `density` 密度 | 2500 kg/m³ | 均质样品 |
| `spring` 弹簧 | 98 N/m | 线性、静态响应 |
| `electric` 电功率 | 24 W | 理想欧姆元件 |
| `energy` 动能 | 9 J | 经典平动 |
| `diffusion` 扩散估计 | 5×10⁻⁷ m²/s | 一维均方位移关系 |
| `concentration` 浓度 | 200 mg/L | 均匀混合、取样体积可加 |
| `pendulum` 单摆反推 | 9.869604401089358 m/s² | 理想小角度单摆 |

解读结果时使用上表中的简化假设。量纲检查验证运算是否兼容，物理模型的有效性需要领域判断；自行设置预期范围可以标记同量纲尺度变化。

## 命令行

```powershell
unit-trace --version
unit-trace demo flow --variant dimension --json experiment.json
unit-trace evaluate experiment.json --json result.json --svg graph.svg --html report.html
unit-trace serve --port 0
```

`demo` 输出 Project，`evaluate` 始终重新计算。已有输出需要 `--overwrite`；该选项仍不能覆盖输入及其硬链接、符号链接别名，不同输出也不能使用同一个文件。退出码：**0** 无问题，**1** 有错误或 blocked，**2** 仅警告，**3** 输入无效、限额、I/O 或取消；优先级为 3 > 1 > 2 > 0。

导入 Bundle 时，若支持的 schema/profile 相同但引擎版本或单位定义哈希不同，CLI 默认报告 `engine_mismatch` 并退出 3。显式使用 `unit-trace evaluate saved.json --recompute` 可选择按当前引擎重算。它不会信任旧报告，也不会绕过未知 schema/profile 或输入限额。浏览器会展示新旧 profile，等待点击 **Recompute with current engine**。

## 公式、单位与限额

公式引用节点 ID，支持十进制常数、括号、正负号、`+ - * /`，以及 −12 到 12 的整数字面量幂 `**`。乘方使用 `**`，π 等常数作为单位为 `1` 的普通输入。调用、属性、下标、函数及可执行表达式不在支持范围。

单位区分大小写，通过 `* / **` 和括号组合，例如 `cm**2`、`kg/m**3`、`m**2/s`。白名单如下：

```text
1 m cm mm um nm km s ms us min h kg g mg L mL mol mmol
A mA V mV ohm kohm N Pa kPa MPa J kJ W mW Hz rad
```

使用 ASCII 写法 `um`、`cm**2`。温度及温差、context、数组、不确定度和自定义单位不属于此 profile。输入保留十进制文本，计算使用有限 binary64；每步非零绝对值限于 1e−100 至 1e100。最多 80 个变量、20 条公式；Project 上限 128 KiB，HTTP 请求体 256 KiB，本地 JSON Bundle 8 MiB。详见[完整协议](docs/schema.md)。

## 保存与分享

- **JSON** 包含输入、实际引擎 profile 和报告快照。导入只提取 Project 后重算，不把旧数量当计算输入。
- **SVG** 是可独立打开的图快照。
- **HTML** 是离线报告，可展开节点解释，不发网络请求；继续编辑和重算时，把对应 JSON 导入正在运行的服务或 CLI。

导出包含用户录入的实验内容，不含会话 token、本机路径或服务日志。服务仅绑定 loopback，校验 Host/Origin/会话头，最多四个活跃 worker，没有服务器文件 API。[实际 profile](docs/profile.json) 记录 Python、Pint、依赖、白名单版本和随包单位定义哈希。

## 开发与许可

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python -m pip check
.venv\Scripts\python -m pip wheel --no-deps --no-build-isolation . -w dist
```

新增模板与手写期望见 [CONTRIBUTING](CONTRIBUTING.md)。随仓库提供的 CI 配置在 Windows 上运行 Python 检查；本地验收已通过 75 项测试，并实际操作浏览器编辑、导入、导出、键盘控件和 390px 布局。原创代码和模板采用 [MIT](LICENSE)，依赖许可和署名保留在 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)。
