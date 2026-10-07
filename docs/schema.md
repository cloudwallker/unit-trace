# Scalar protocol / 标量协议

This core uses schema version 1 and profile `unit-trace-scalar-v1`.
本核心使用 schemaVersion 1 和固定标量 profile，所有输入均视为不可信数据。

```json
{
  "schemaVersion": 1,
  "profile": "unit-trace-scalar-v1",
  "title": "Flow experiment",
  "variables": [
    {"id": "width", "label": "Width", "value": "2", "unit": "cm"},
    {"id": "height", "label": "Height", "value": "3", "unit": "cm"}
  ],
  "formulas": [
    {"id": "area", "label": "Area", "expression": "width*height", "outputUnit": "cm**2",
     "expected": {"min": "5", "max": "7", "unit": "cm**2"}}
  ]
}
```

`Project`, `Variable`, `Formula` and `ExpectedRange` are immutable dataclasses;
their `to_json()` methods use explicit public field names and omit absent optional
fields. Python fields use snake_case (`schema_version`, `output_unit`,
`node_id`, `related_ids`, `definition_hashes`); JSON uses the camelCase names
shown in the protocol. Collections are tuples internally and JSON arrays publicly.
Projects contain no Pint objects. The original decimal `value`, `min` and `max`
strings are preserved.

`parse_project(object) -> Project` checks the object shape, field presence,
unknown fields, text, numeric values and sizes. It checks the *text bounds* of
expressions and units; expression semantics/references are checked by
`parse_formula`/`build_graph`, and unit semantics by `resolve_unit`. Callers must
perform these semantic checks before interpreting the parsed project.

`ProjectValidationError.issues` is a tuple of `Issue`. Each issue maps to
`{id,code,field,message,relatedIds,nodeId?,span?}`. `Span` is `{start,end}` with
zero-based ASCII source offsets and an exclusive end. Messages never quote the
input or expose dependency exceptions. `CalculationError.issue` is the shared
single-operation error interface for the subsequent scalar evaluator.

## JSON and field limits

- Strict UTF-8; duplicate keys, NUL, unpaired surrogates, NaN and Infinity are
  rejected. String-aware nesting inspection precedes JSON decoding, with at most
  16 container levels. Escaped braces and brackets in strings do not count.
- `load_json(bytes, max_bytes=8388608)` enforces the local bundle limit of 8 MiB.
  A future HTTP caller must first enforce its own 256 KiB request cap and pass
  `max_bytes=262144`. `parse_project` independently enforces a compact UTF-8 JSON
  project cap of 128 KiB; it does not impose that cap on an entire report bundle.
- At most 80 variables and 20 formulas; therefore at most 100 graph nodes.
  `title` has at most 120 Unicode characters, `label` at most 80. They are plain
  text. Unknown fields and explicit null for optional fields are rejected.
- IDs match `[A-Za-z][A-Za-z0-9_]{0,31}` and cannot be Python keywords. Variables
  and formulas share one unique namespace; graph construction detects duplicates.
- NumberText is a decimal string of 1–32 characters:
  `[+-]?(digits(.digits?)?|.digits)([eE][+-]?digits)?`. Every nonzero binary64 value
  must have absolute magnitude between `1e-100` and `1e100`, inclusive. Zero is
  allowed; a lexically nonzero value that underflows to zero is rejected. Range
  endpoints obey the same limits and minimum must not exceed maximum.

## Formula grammar and graph

`parse_formula(str) -> ParsedFormula` returns the original `expression`, an
`ast.Expression` tree, and unique `refs` in source occurrence order. Each source
node has original `col_offset`/`end_col_offset`, including leading whitespace.
Numeric constants are validated then stored as floats; exponent syntax has
already been checked against the original integer literal.

Expressions are ASCII, single line, at most 512 characters, 128 AST nodes
(including operator/context nodes), 24 AST levels and 24 characters per numeric
token. Only decimal real constants, references, parentheses, unary `+`/`-`,
binary `+`/`-`/`*`/`/` and `**` are supported. Exponents are optionally signed
integer literals from -12 through 12. Nested powers, comments, calls, attributes,
subscripts, containers, comprehensions, bool/null/string/complex constants,
comparison, boolean/bitwise operators, assignment, modulo and floor division are
rejected. `^` prompts use of `**`. Parsing never evaluates or compiles a user's
AST into executable code. Domain errors such as `0**0` belong to evaluation.

`build_graph(Project) -> Graph` resolves all references after collecting the
namespace, allowing forward references. Duplicate IDs, missing references,
self references and cycles reject the graph. Missing references include source
spans and named IDs; cycles include a closed path such as `a,b,a`. Syntax errors
are relocated to `formulas[i].expression` with the formula node ID.
`order` uses stable Kahn topological sorting with original variable/formula
position as the ready-node priority. `edges` are `(source,target)` pairs in
formula/source-reference order. `dependants` contains every ID, including leaves,
and its direct successors in formula order. Empty projects return an empty graph.

## Unit grammar and Pint provenance

`make_registry() -> pint.UnitRegistry` creates an independent registry with
Pint 0.25.2's bundled definitions. `resolve_unit(str, registry) -> pint.Unit`
expects this factory's registry and never sends user text to Pint's parser.
Only fixed symbol mappings are prebuilt into Unit objects. The independent
recursive parser combines these objects using multiplication, division and powers.

UnitText has at most 64 ASCII characters, 32 tokens and 8 parenthesis levels.
Its grammar allows whitelist symbols, `1`, parentheses, `*`, `/`, and optionally
signed integer `**` exponents -12..12. Nested powers are rejected, including
parenthesized nesting. Every atom and intermediate combination is checked for
dimensionality powers with absolute value at most 24. Thus cancellation cannot
hide an oversized intermediate dimension. The scalar evaluator must also check
this bound after every formula operation.

The case-sensitive whitelist is:
`1,m,cm,mm,um,nm,km,s,ms,us,min,h,kg,g,mg,L,mL,mol,mmol,A,mA,V,mV,ohm,kohm,N,Pa,kPa,MPa,J,kJ,W,mW,Hz,rad`.
Temperature/temperature differences, contexts, offset conversion, arrays,
uncertainties, functions, definitions, plugins and environment-loaded units are
outside this profile. Non-ASCII `cm²`/`μm` must be replaced explicitly with
`cm**2`/`um`; no input rewriting occurs.

Registry constructor options are explicit: `filename=''`, `cache_folder=None`,
`on_redefinition='raise'`, `autoconvert_offset_to_baseunit=False`,
`autoconvert_to_preferred=False`, `auto_reduce_dimensions=False`,
`force_ndarray=False`, `force_ndarray_like=False`, `case_sensitive=True`.
Pint 0.25.2's `PlainRegistry._after_init` resolves the empty filename to its own
`default_en.txt`, whose only imported resource is sibling `constants_en.txt`.
`cache_folder=None` keeps `_diskcache=None`; no environment-selected definition
file or user directory is read. Bundled contexts are not activated or exposed by
the input grammar. Caller-provided registries are not a supported unit source.

`get_profile() -> Profile` reads actual Python/Pint/runtime dependency versions
and SHA256 of `pint/default_en.txt` and `pint/constants_en.txt` via package
resources. Only logical resource names appear in JSON, never installation paths.
Build tools are independently pinned in `requirements-build.lock` and are not
runtime requirements of the public engine profile. This task verified Python
3.12.14 on Windows with Pint 0.25.2; it does not claim other platforms were tested.

## Scalar evaluation and trace reports

`evaluate_project(project: Project, previous: Project | None = None) ->
EvaluationReport` consumes the same validated Project, formula AST and unit
grammar. `models.py` is the sole owner of QuantityView, Conversion,
OperationTrace, NodeResult, EvaluationReport, ChangeSet and LoadedProject.
All report JSON comes from explicit `.to_json()` mappings. QuantityView has
`value` (finite JSON number), `roundtrip` (17 significant digits), `unit` and
`dimensionality` (Pint display text). Display text is not accepted UnitText:
when applying an input conversion, retain the requested whitelist `toUnit`.

Traces are left-to-right postorder, with the original expression's half-open
ASCII span, operator, symbolic substring, numeric/unit substitution, original
operands, result or null, actual successful conversions, and issueId or null.
Addition/subtraction compare dimensions even for zero, explicitly convert the
right operand to the left unit and record the independent multiplicative factor.
Unary operators are `u+`/`u-`. Output conversion follows all expression traces,
in the node's `conversions` list. Each operation and conversion checks finite
binary64 magnitude, nonzero bounds 1e-100..1e100, nonzero underflow and dimension
powers at most 24. Zero to zero power is domain_error; zero to negative power
or division by zero is division_by_zero.

A failed operation retains its available operands and any successful conversion,
with result null. Evaluation stops that expression and continues independent
branches. `rootErrors` contains direct issues in stable topological order;
`firstError` is the first or null. An error node has its own issue ID in
`rootErrorIds`; blocked nodes have no quantity or direct error and only the
true upstream root IDs, in global root order. Output-unit incompatibility is
conversion_mismatch and blocks successors. Unsupported unit syntax is a
structural ProjectValidationError with a node/field location.

User ranges are inclusive binary64 comparisons with no hidden tolerance.
range_outside and range_unit_mismatch are warnings and preserve real quantities
and successor evaluation. If an otherwise compatible expected-unit conversion
exceeds numeric/factor bounds or underflows a nonzero value, numeric_limit is a
warning located at `expected`: the range could not be checked. It is neither
an accepted range nor a fabricated range_outside. No unsuccessful conversion
is recorded. Input/output/addition/subtraction numeric conversion failure
remains a calculation error. Without a user range, same-dimension scale changes
have no automatic warning.

`convert_input(value, from_unit, to_unit) -> QuantityView` returns the equivalent
quantity. `units.conversion_factor(from_unit, to_unit) -> float` uses a unit-valued
1 conversion, so zero inputs still yield a real factor; factors must themselves
be finite, nonzero and within scalar bounds. CalculationError.issue is the
single-operation failure interface; invalid NumberText/UnitText remain structural.

## Dependency changes and canonical bundle JSON

`compare_projects(current, previous) -> ChangeSet` compares value/unit for
variables and expression/outputUnit for formulas, plus additions, removals and
kind changes. Metadata/range changes cause fresh evaluation without numeric
path highlights. changedIds lists current direct changes in input order followed
by removed IDs in previous input order. affectedIds traverses the union of both
valid DAGs and lists only existing current IDs in current input order. removedIds
is separate. With no previous Project, all three lists are empty.

`canonical_project_bytes(Project)` serializes `.to_json()` as UTF-8 with
`sort_keys=True`, `ensure_ascii=False`, compact separators `(',', ':')` and
`allow_nan=False`; array order and NumberText are preserved, optional absent
fields stay absent. `project_hash(Project)` is lowercase SHA256 of these bytes.
The following exact ASCII test vector has no trailing newline:

```json
{"formulas":[],"profile":"unit-trace-scalar-v1","schemaVersion":1,"title":"Synthetic experiment","variables":[]}
```

`serialize_bundle(project, report) -> bytes` emits only
`{schemaVersion:1,project,report}`, rejects stale hashes/profile and enforces
8 MiB. `parse_bundle(object) -> LoadedProject` accepts this bundle or a standalone
Project, independently enforces 8 MiB/16 JSON levels and Project's 128 KiB limit,
and discards all snapshot computation data. source_profile contains only the
validated profile, or None for a standalone Project. Unknown schema/profile is
rejected; changes in Python/Pint/dependency/whitelist versions or definition
hashes set requires_recompute_confirmation=True. A caller must show
engine_mismatch and obtain the product user's explicit recomputation choice.
Every accepted import is recomputed from `loaded.project`; snapshot values,
errors and projectHash never become evaluation inputs.

## Local service and browser state

The service binds only `127.0.0.1` on an explicit or random port. Its fixed static
paths are `/`, `/app.js`, `/graph.js`, `/style.css`; there is no filesystem API.
The entry HTML provides a memory-only session token through a meta element.
API callers send `X-Unit-Trace-Session`; Host must match the exact loopback
address and port. POST also requires matching Origin. An existing GET Origin
must match, and `Sec-Fetch-Site: cross-site` is rejected.

| Method / path | Request | Response |
| --- | --- | --- |
| GET `/api/profile` | Session header | Current Profile |
| GET `/api/templates` | Session header | `{templates:[{id,variants:{normal,dimension,scale}}]}` |
| POST `/api/evaluate` | `{project,previousProject?,revision}` | `{revision,report}` |
| POST `/api/convert` | `{value,fromUnit,toUnit}` | `{quantity,conversion}` |
| POST `/api/export` | `{project,format:"json"\|"svg"\|"html"}` | Freshly evaluated artifact bytes |

Revisions are integers 0..2147483647. The server recomputes every export from
Project and uses fixed filenames `unit-trace.json`, `unit-trace.svg`, and
`unit-trace.html`. It never accepts a client-provided report as an export input.
Malformed JSON/protocol is 400, invalid origin/session 403, unknown route 404,
oversized body 413, unsupported content type 415, structural project/request
failure 422, and busy admission 503. Valid calculations containing error/blocked
nodes are 200. Errors are `{errors:Issue[]}`, without request data or tracebacks.

JSON requests require Content-Length and application/json. Duplicate critical
headers, transfer encodings and compression are rejected. Each accepted
connection has an absolute five-second deadline, including incomplete headers;
there are at most four active workers. `close()` owns all connections and the
executor, interrupts slow reads, stops acceptance, joins workers and clears the
session. `shutdown()` is coordinated outside the serving thread. Closing before
serving and repeated closes are supported. CLI cancellation uses exit 3.

Browser state is `{project,lastReport,pendingRevision,lastEvaluatedHash,
lastEvaluatedProject,dirty}`. Every edit/import/template restoration/applied
conversion increments the revision and immediately makes prior results old.
Each evaluation captures an immutable Project and the last accepted Project as
its previous baseline. It commits report, input baseline and hash atomically
only if the response revision, current Project, and canonical SHA256 still match.
Structurally valid error/blocked/warning results can become baselines; 422,
network errors and stale responses cannot. An in-flight conversion captures
target ID, revision, value, source unit and requested destination unit; it writes
both value and the requested UnitText only while that capture is current.

Local browser JSON import uses strict UTF-8, duplicate-key detection, maximum
depth 16 and an 8 MiB limit before extracting the Project. Profile differences
require the explicit current-engine choice. CLI exposes that choice as
`evaluate --recompute`; unknown schema/Project profile and all bounds still
apply. Saved report values are discarded. HTML uses native details/summary for
offline explanations, contains no script or external resources, and cannot
recompute formulas.
