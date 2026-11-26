package main

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"testing"
)

// The permission audit reads the code, not a hand-kept list: every permission the handlers check
// and every code a role is granted must be seeded, and (when the erp-ui source is at hand, in
// ERP_UI_DIR) every code a page gates on must be seeded too.

const handlersDir = "../../internal/http/handlers"

// permissionChecks are the handler helpers whose last argument is a permission code.
var permissionChecks = map[string]bool{"requirePermission": true, "hasPermission": true}

// passThrough are the functions allowed to hand a variable to a check: the check helpers
// themselves and the grant rules, which ask about any code they are given.
var passThrough = map[string]bool{"requirePermission": true, "hasPermission": true, "actor": true}

type use struct{ code, where string }

// handlerPermissionUses returns each permission a handler checks, resolving the perm* constants.
func handlerPermissionUses(t *testing.T) []use {
	t.Helper()
	fset := token.NewFileSet()
	files, err := filepath.Glob(filepath.Join(handlersDir, "*.go"))
	if err != nil || len(files) == 0 {
		t.Fatalf("handlers source: %v (%d files)", err, len(files))
	}
	consts := map[string]string{}
	var parsed []*ast.File
	for _, name := range files {
		if strings.HasSuffix(name, "_test.go") {
			continue
		}
		f, err := parser.ParseFile(fset, name, nil, 0)
		if err != nil {
			t.Fatal(err)
		}
		parsed = append(parsed, f)
		for _, d := range f.Decls {
			gd, ok := d.(*ast.GenDecl)
			if !ok || gd.Tok != token.CONST {
				continue
			}
			for _, s := range gd.Specs {
				vs := s.(*ast.ValueSpec)
				for i, n := range vs.Names {
					if i < len(vs.Values) {
						if lit, ok := vs.Values[i].(*ast.BasicLit); ok && lit.Kind == token.STRING {
							v, _ := strconv.Unquote(lit.Value)
							consts[n.Name] = v
						}
					}
				}
			}
		}
	}
	var out []use
	for _, f := range parsed {
		for _, d := range f.Decls {
			fn, ok := d.(*ast.FuncDecl)
			if !ok || fn.Body == nil {
				continue
			}
			ast.Inspect(fn.Body, func(n ast.Node) bool {
				call, ok := n.(*ast.CallExpr)
				if !ok {
					return true
				}
				id, ok := call.Fun.(*ast.Ident)
				if !ok || !permissionChecks[id.Name] || len(call.Args) == 0 {
					return true
				}
				where := fset.Position(call.Pos()).String()
				switch arg := call.Args[len(call.Args)-1].(type) {
				case *ast.BasicLit:
					v, _ := strconv.Unquote(arg.Value)
					out = append(out, use{v, where})
				case *ast.Ident:
					if v, ok := consts[arg.Name]; ok {
						out = append(out, use{v, where})
					} else if !passThrough[fn.Name.Name] {
						t.Errorf("%s: %s(%s) cannot be checked: pass a perm constant", where, id.Name, arg.Name)
					}
				default:
					if !passThrough[fn.Name.Name] {
						t.Errorf("%s: %s with a computed code cannot be checked: pass a perm constant", where, id.Name)
					}
				}
				return true
			})
		}
	}
	return out
}

// TestRoutesUseSeededPermissions: a route that checks a code the seed does not create can never be
// passed by anyone but the platform owner, so it fails here.
func TestRoutesUseSeededPermissions(t *testing.T) {
	seeded := map[string]bool{}
	for _, c := range permissionCodes {
		if seeded[c] {
			t.Errorf("permission %q is listed twice", c)
		}
		seeded[c] = true
	}
	uses := handlerPermissionUses(t)
	if len(uses) < 100 {
		t.Fatalf("found only %d permission checks: the scan is broken", len(uses))
	}
	used := map[string]bool{}
	for _, u := range uses {
		used[u.code] = true
		if !seeded[u.code] {
			t.Errorf("%s checks %q, which the seed does not create", u.where, u.code)
		}
	}
	for role, codes := range roleGrants {
		for _, c := range codes {
			if c != "*" && !seeded[c] {
				t.Errorf("role %s is granted %q, which the seed does not create", role, c)
			}
		}
	}
	var unused []string
	for _, c := range permissionCodes {
		if !used[c] {
			unused = append(unused, c)
		}
	}
	if len(unused) > 0 {
		t.Logf("seeded but checked by no route (granting them changes nothing): %v", unused)
	}
}

var (
	// A dotted code ends in one of the actions the seed uses; a legacy code is action_model.
	dottedCode = regexp.MustCompile(`^[a-z]+(\.[a-z_]+)*\.(view|manage|approve|process|disburse|decide)$`)
	legacyCode = regexp.MustCompile(`^(view|add|change|delete)_([a-z]+)$`)
	quoted     = regexp.MustCompile(`["']([a-z][a-z_.]*)["']`)
	mapEntry   = regexp.MustCompile(`^\s*([a-z]+):\s*"([a-z.]+)",?\s*$`)
	canCall    = regexp.MustCompile(`\bcan\(\s*["'](view|add|change|delete)["']\s*,\s*["']([a-z]+)["']\s*\)`)
)

// legacyModules reads the UI's legacy model to module table, so the audit translates a legacy code
// the way the page does.
func legacyModules(t *testing.T, src string) map[string]string {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(src, "hooks", "use-app-permissions.ts"))
	if err != nil {
		t.Fatal(err)
	}
	body := string(raw)
	start := strings.Index(body, "LEGACY_MODEL_TO_MODULE")
	if start < 0 {
		t.Fatal("LEGACY_MODEL_TO_MODULE not found in use-app-permissions.ts")
	}
	body = body[start:]
	body = body[:strings.Index(body, "};")]
	out := map[string]string{}
	for _, line := range strings.Split(body, "\n") {
		if m := mapEntry.FindStringSubmatch(line); m != nil {
			out[m[1]] = m[2]
		}
	}
	if len(out) < 10 {
		t.Fatalf("read only %d legacy models: the scan is broken", len(out))
	}
	return out
}

func translateLegacy(code string, modules map[string]string) (string, bool) {
	m := legacyCode.FindStringSubmatch(code)
	if m == nil {
		return code, true
	}
	module, ok := modules[m[2]]
	if !ok {
		return code, false
	}
	action := "manage"
	if m[1] == "view" {
		action = "view"
	}
	return module + "." + action, true
}

// TestPagesGateOnSeededPermissions: a page or menu entry gated on a code the seed does not create
// is hidden from everyone but administrators. Runs when ERP_UI_DIR names an erp-ui checkout.
func TestPagesGateOnSeededPermissions(t *testing.T) {
	dir := os.Getenv("ERP_UI_DIR")
	if dir == "" {
		t.Skip("ERP_UI_DIR not set (path of an erp-ui checkout)")
	}
	src := filepath.Join(dir, "src")
	modules := legacyModules(t, src)
	seeded := map[string]bool{}
	for _, c := range permissionCodes {
		seeded[c] = true
	}
	checked := 0
	err := filepath.WalkDir(src, func(path string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() || !(strings.HasSuffix(path, ".ts") || strings.HasSuffix(path, ".tsx")) {
			return err
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(dir, path)
		for i, line := range strings.Split(string(raw), "\n") {
			if trimmed := strings.TrimSpace(line); strings.HasPrefix(trimmed, "//") || strings.HasPrefix(trimmed, "*") || strings.HasPrefix(trimmed, "/*") {
				continue // examples in comments gate nothing
			}
			var codes []string
			for _, m := range quoted.FindAllStringSubmatch(line, -1) {
				if dottedCode.MatchString(m[1]) || legacyCode.MatchString(m[1]) {
					codes = append(codes, m[1])
				}
			}
			for _, m := range canCall.FindAllStringSubmatch(line, -1) {
				codes = append(codes, m[1]+"_"+m[2])
			}
			for _, c := range codes {
				checked++
				real, known := translateLegacy(c, modules)
				if !known {
					t.Errorf("%s:%d: legacy code %q has no module in LEGACY_MODEL_TO_MODULE", rel, i+1, c)
				} else if !seeded[real] {
					t.Errorf("%s:%d: gates on %q (%s), which the seed does not create", rel, i+1, c, real)
				}
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if checked < 20 {
		t.Fatalf("found only %d permission codes in the UI: the scan is broken", checked)
	}
}
