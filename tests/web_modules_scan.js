// web_modules_scan.js - static scan of the editor ES modules (lot M7), run by tests/test_web_modules.py.
//
// Purpose : parse each file given on the command line as an ES module with SpiderMonkey's Reflect.parse (gjs) and
//           print one JSON object: {files: [{path, size, error, imports, exports, stars, unused, free}]}.
//           imports = [{source, imported, local}] ("*" = namespace import), exports = exported names,
//           stars = sources of `export * from`, unused = imported locals never referenced,
//           free = identifiers referenced but declared nowhere in the module (browser globals or typos).
// Boundary: reads files only, no network, no DOM; the policy (allowed globals, size limit, import resolution)
//           lives in the Python test so this scanner stays generic.
// Invariant: scope model = module, function, block, for-head, catch and class-expression scopes; `var` goes to the
//           nearest function scope, let / const / class / function declarations to their block (modules are strict).
//           Non-computed member properties, object keys, labels, private names (#x) and meta properties
//           (new.target, import.meta) are never references.
// Test    : gjs tests/web_modules_scan.js web/editor/main.js ...   (tests/test_web_modules.py drives it)

const GLib = imports.gi.GLib;
const decoder = new TextDecoder("utf-8");

function Scope(parent, isFunction) {
    this.parent = parent;
    this.isFunction = isFunction;
    this.names = new Map();   // name -> {kind, used}
}

function fnScope(scope) {
    while (!scope.isFunction) scope = scope.parent;
    return scope;
}

function scanFile(path) {
    const [ok, bytes] = GLib.file_get_contents(path);
    const src = decoder.decode(bytes);
    const res = {path, size: bytes.length, error: null, imports: [], exports: [], stars: [], unused: [], free: []};
    let ast;
    try {
        ast = Reflect.parse(src, {target: "module"});
    } catch (e) {
        res.error = String(e);
        return res;
    }
    const free = new Set();

    function declare(scope, name, kind) {
        if (!scope.names.has(name)) scope.names.set(name, {kind, used: false});
    }

    function declarePattern(scope, p, kind) {
        if (!p) return;
        switch (p.type) {
        case "Identifier": declare(scope, p.name, kind); break;
        case "ObjectPattern":
            for (const prop of p.properties) {
                if (prop.type === "Property") declarePattern(scope, prop.value, kind);
                else declarePattern(scope, prop.expression || prop.argument, kind);   // rest element
            }
            break;
        case "ArrayPattern":
            for (const el of p.elements) {
                if (el && (el.type === "SpreadExpression" || el.type === "RestElement")) declarePattern(scope, el.expression || el.argument, kind);
                else declarePattern(scope, el, kind);
            }
            break;
        case "AssignmentExpression": declarePattern(scope, p.left, kind); break;   // default value: {a = 1}
        case "AssignmentPattern": declarePattern(scope, p.left, kind); break;
        }
    }

    // Default values and computed keys inside a declared pattern are expressions to walk (names are declared already).
    function walkPatternExprs(p, scope) {
        if (!p) return;
        switch (p.type) {
        case "ObjectPattern":
            for (const prop of p.properties) {
                if (prop.type === "Property") {
                    if (prop.key && prop.key.type === "ComputedName") walk(prop.key.name, scope);
                    walkPatternExprs(prop.value, scope);
                } else walkPatternExprs(prop.expression || prop.argument, scope);
            }
            break;
        case "ArrayPattern":
            for (const el of p.elements) if (el) walkPatternExprs(el.expression && el.type !== "AssignmentExpression" ? el.expression : el, scope);
            break;
        case "AssignmentExpression":
        case "AssignmentPattern":
            walkPatternExprs(p.left, scope);
            walk(p.right, scope);
            break;
        }
    }

    function hoistLexical(stmts, scope) {
        for (let s of stmts) {
            if (s.type === "ExportDeclaration") {
                if (!s.declaration) continue;
                s = s.declaration;
            }
            if (s.type === "VariableDeclaration" && s.kind !== "var") for (const d of s.declarations) declarePattern(scope, d.id, "let");
            else if ((s.type === "FunctionDeclaration" || s.type === "ClassStatement") && s.id) declare(scope, s.id.name, "fn");
        }
    }

    function hoistVars(node, scope) {
        if (!node || typeof node !== "object") return;
        if (Array.isArray(node)) { for (const n of node) hoistVars(n, scope); return; }
        if (node.type === "FunctionDeclaration" || node.type === "FunctionExpression" || node.type === "ArrowFunctionExpression") return;
        if (node.type === "VariableDeclaration" && node.kind === "var") for (const d of node.declarations) declarePattern(scope, d.id, "var");
        for (const k in node) if (k !== "loc" && k !== "type") hoistVars(node[k], scope);
    }

    function ref(name, scope) {
        for (let s = scope; s; s = s.parent) {
            const b = s.names.get(name);
            if (b) { b.used = true; return; }
        }
        free.add(name);
    }

    function walkStatements(stmts, scope) {
        hoistLexical(stmts, scope);
        for (const s of stmts) walk(s, scope);
    }

    function walkFunction(fn, outer) {
        const scope = new Scope(outer, true);
        if (fn.type === "FunctionExpression" && fn.id) declare(scope, fn.id.name, "fn");
        for (const p of fn.params) declarePattern(scope, p, "param");
        if (fn.rest) declarePattern(scope, fn.rest, "param");
        for (const p of fn.params) walkPatternExprs(p, scope);
        for (const d of fn.defaults || []) if (d) walk(d, scope);
        if (fn.body && fn.body.type === "BlockStatement") {
            hoistVars(fn.body.body, scope);
            walkStatements(fn.body.body, scope);
        } else walk(fn.body, scope);
    }

    function walk(node, scope) {
        if (!node || typeof node !== "object") return;
        if (Array.isArray(node)) { for (const n of node) walk(n, scope); return; }
        switch (node.type) {
        case "Identifier": ref(node.name, scope); return;
        case "Literal": case "ThisExpression": case "Super": case "MetaProperty":
        case "BreakStatement": case "ContinueStatement": case "ImportDeclaration": case "DebuggerStatement":
            return;
        case "LabeledStatement": walk(node.body, scope); return;
        case "ExportDeclaration":
            if (node.declaration) walk(node.declaration, scope);
            else if (!node.moduleRequest && node.specifiers) for (const sp of node.specifiers) if (sp.id) ref(sp.id.name, scope);
            return;
        case "FunctionDeclaration": case "FunctionExpression": case "ArrowFunctionExpression":
            walkFunction(node, scope); return;
        case "BlockStatement": walkStatements(node.body, new Scope(scope, false)); return;
        case "VariableDeclaration":
            for (const d of node.declarations) { walkPatternExprs(d.id, scope); walk(d.init, scope); }
            return;
        case "ForStatement": case "ForInStatement": case "ForOfStatement": {
            const s = new Scope(scope, false);
            const head = node.init || node.left;
            if (head && head.type === "VariableDeclaration" && head.kind !== "var") for (const d of head.declarations) declarePattern(s, d.id, "let");
            for (const k of ["init", "left", "test", "update", "right", "body"]) if (node[k]) walk(node[k], s);
            return;
        }
        case "CatchClause": {
            const s = new Scope(scope, false);
            declarePattern(s, node.param, "let");
            walkPatternExprs(node.param, s);
            walk(node.guard, s);
            walk(node.body, s);
            return;
        }
        case "ClassStatement": case "ClassExpression": {
            let s = scope;
            if (node.type === "ClassExpression" && node.id) { s = new Scope(scope, false); declare(s, node.id.name, "fn"); }
            walk(node.superClass, s);
            for (const m of node.body || []) {
                if (m.name && m.name.type === "ComputedName") walk(m.name.name, s);
                if (m.type === "ClassMethod") walk(m.body, s);
                else if (m.type === "ClassField") walk(m.init, s);
                else if (m.type !== "ClassMethod" && m.type !== "ClassField") walk(m.body || m, s);   // static blocks
            }
            return;
        }
        case "MemberExpression": case "OptionalMemberExpression":
            walk(node.object, scope);
            if (node.computed && !(node.property.type === "Identifier" && node.property.name.startsWith("#"))) walk(node.property, scope);
            return;
        case "Property":
            if (node.key && node.key.type === "ComputedName") walk(node.key.name, scope);
            walk(node.value, scope);
            return;
        case "ComputedName": walk(node.name, scope); return;
        }
        for (const k in node) if (k !== "loc" && k !== "type") walk(node[k], scope);
    }

    const mod = new Scope(null, true);
    for (const s of ast.body) {
        if (s.type === "ImportDeclaration") {
            const source = s.moduleRequest.source.value;
            for (const sp of s.specifiers) {
                const imported = sp.type === "ImportNamespaceSpecifier" ? "*" : sp.id.name;
                res.imports.push({source, imported, local: sp.name.name});
                declare(mod, sp.name.name, "import");
            }
            if (!s.specifiers.length) res.imports.push({source, imported: null, local: null});   // side-effect import
        } else if (s.type === "ExportDeclaration") {
            if (s.isDefault) res.exports.push("default");
            else if (s.declaration) {
                const d = s.declaration;
                if (d.type === "VariableDeclaration") {
                    const tmp = new Scope(null, true);
                    for (const v of d.declarations) declarePattern(tmp, v.id, "let");
                    for (const n of tmp.names.keys()) res.exports.push(n);
                } else if (d.id) res.exports.push(d.id.name);
            } else for (const sp of s.specifiers || []) {
                if (sp.type === "ExportBatchSpecifier") res.stars.push(s.moduleRequest.source.value);
                else {
                    res.exports.push(sp.name.name);
                    if (s.moduleRequest) res.imports.push({source: s.moduleRequest.source.value, imported: sp.id.name, local: null});
                }
            }
        }
    }
    hoistVars(ast.body, mod);
    walkStatements(ast.body, mod);
    for (const [name, b] of mod.names) if (b.kind === "import" && !b.used) res.unused.push(name);
    res.free = [...free].sort();
    return res;
}

const files = [];
for (const p of ARGV) files.push(scanFile(p));
print(JSON.stringify({files}));
