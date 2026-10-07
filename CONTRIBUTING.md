# Contributing / 参与贡献

Use Python 3.12 and install both hash-locked requirements files. Keep the scalar
engine as the single computation source. The web UI consumes its explicit JSON
protocol; it must not evaluate formulas or reinterpret Pint display-unit text.

使用 Python 3.12 和两份哈希锁文件。计算只能来自现有 Python 引擎；前端读取显式
JSON 映射，不能执行公式或把显示用单位字符串当作输入语法重新解析。

## Changes

Add a failing behavior test first, implement the smallest change, then run:

```text
python -m unittest discover -s tests -v
python -m pip check
```

Server tests bind real random loopback ports. CLI tests use their own temporary
files and verify source protection, including hardlinks and available symlinks.
The Windows cancellation test sends Ctrl+Break only to its newly created process
group. Tests close their owned connections, threads and child processes.

Before changing web behavior, exercise real browser edits, current/old result
states, keyboard controls, imports, downloads, 390px layout and delayed responses.
The included CI runs Python tests; the recorded browser acceptance is a separate
local check. Never include session headers, private experiments or local paths in
screenshots and reports.

## New templates

A template contains `normal.json`, `dimension.json`, `scale.json`, and
`expected.json` under `src/unit_trace/templates/<id>/`. Add its ID to the fixed
template catalog and update the UI title and both READMEs.

1. Describe the physical assumptions and write the normal result by hand.
2. Put one incompatible operation in the dimension variant; record its exact
   node ID, half-open source span and blocked successors by hand.
3. Change only one input unit in the scale variant, keeping its number. Record
   the scale result by hand. The original templates contain no preset ranges.
4. Extend the real template tests. Use `math.isclose(rel_tol=1e-12,
   abs_tol=1e-15)` for numeric expectations and exact assertions for dimensions,
   root IDs, spans, blocked IDs and conversion factors.
5. Add a user range around the normal result in the test and verify the scale
   variant warns. Do not generate expected values from the engine under test.

新增模板必须手算正常值、错误字符区间、被阻塞节点和尺度变体结果；不能用被测引擎
生成期望。说明简化假设，保留无预设范围的原模板，再由测试加入用户范围。

## Scope and attribution

Keep the schema, AST, unit and numeric bounds explicit. A new unit or engine
behavior can affect the reproducibility profile and requires matching protocol
documentation and tests. Preserve original author attribution and dependency
licenses. Use synthetic public fixtures and inspect changes for secrets before
sharing. Original contributions use the repository's MIT license.
