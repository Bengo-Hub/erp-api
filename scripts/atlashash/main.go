//go:build ignore

// Rehashes the ent Atlas migrations atlas.sum using the atlas version pinned in go.mod
// (the prebuilt atlas binary in this environment is the wrong arch, and `go run
// ariga.io/atlas/cmd/atlas` resolves to a stale, uncompilable cached version).
package main

import (
	"log"

	"ariga.io/atlas/sql/migrate"
)

func main() {
	dir, err := migrate.NewLocalDir("internal/ent/migrate/migrations")
	if err != nil {
		log.Fatalf("open dir: %v", err)
	}
	sum, err := dir.Checksum()
	if err != nil {
		log.Fatalf("checksum: %v", err)
	}
	if err := migrate.WriteSumFile(dir, sum); err != nil {
		log.Fatalf("write sum: %v", err)
	}
	log.Println("atlas.sum rehashed")
}
