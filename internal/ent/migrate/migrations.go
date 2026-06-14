package migrate

import (
	"embed"
	"io/fs"
	"log"

	atlasmigrate "ariga.io/atlas/sql/migrate"
)

//go:embed migrations/*.sql migrations/atlas.sum
var migrations embed.FS

// Dir is the migration directory used by cmd/migrate. It prefers the on-disk directory
// during development and falls back to the embedded FS in the production container,
// mirroring inventory-service.
var Dir atlasmigrate.Dir

func init() {
	var err error
	if Dir, err = atlasmigrate.NewLocalDir("internal/ent/migrate/migrations"); err == nil {
		return
	}
	if Dir, err = newEmbedDir(migrations, "migrations"); err != nil {
		log.Fatalf("open migration directory from embedded FS: %v", err)
	}
}

// newEmbedDir creates a MemDir pre-populated from an embed.FS sub-path.
func newEmbedDir(fsys embed.FS, path string) (*atlasmigrate.MemDir, error) {
	sub, err := fs.Sub(fsys, path)
	if err != nil {
		return nil, err
	}
	md := atlasmigrate.OpenMemDir(path)
	entries, err := fs.ReadDir(sub, ".")
	if err != nil {
		return nil, err
	}
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		data, err := fs.ReadFile(sub, e.Name())
		if err != nil {
			return nil, err
		}
		md.WriteFile(e.Name(), data)
	}
	return md, nil
}
