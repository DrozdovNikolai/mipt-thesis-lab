package training

import (
	"context"
	"net/http"

	"north55/backend/internal/platform"
)

// Collection selects server-owned table names. Element and block folders share
// tree/aircraft rules; only block folders persist and enforce library_kind.
type libraryCollection bool

const (
	elementLibrary libraryCollection = false
	blockLibrary   libraryCollection = true
)

func (c libraryCollection) folderTable() string {
	if c == blockLibrary {
		return "block_folder"
	}
	return "element_folder"
}
func (c libraryCollection) itemTable() string { return c.folderTable() + "_item" }
func (c libraryCollection) entityTable() string {
	if c == blockLibrary {
		return "element_block"
	}
	return "element"
}
func (c libraryCollection) entityKey() string {
	if c == blockLibrary {
		return "block_id"
	}
	return "element_id"
}
func (c libraryCollection) query(r *http.Request) (platform.Object, error) {
	fields := []platform.Field{libraryAircraftField()}
	if c == blockLibrary {
		fields = append(fields, platform.Field{Name: "library_kind", Alias: "libraryKind", Kind: "string", Nullable: true})
	}
	fields = append(fields, platform.Field{Name: "include_archived", Alias: "includeArchived", Kind: "boolean", Default: false})
	return platform.QueryObject(r.URL.Query(), fields...)
}
func libraryBlockKind(raw any) string {
	if raw == "competence" {
		return "competence"
	}
	return "exercise"
}
func libraryParseBlockKind(raw any) (string, error) {
	kind := libraryBlockKind(raw)
	if raw != nil && raw != kind {
		return "", platform.Error(400, "Invalid block folder library kind")
	}
	return kind, nil
}

// Validate query kind only after airline/aircraft scope, like the source service.
func (c libraryCollection) kindFilter(q platform.Object) (string, []any, error) {
	if c == blockLibrary && q["library_kind"] != nil {
		kind, err := libraryParseBlockKind(q["library_kind"])
		return " AND f.library_kind=$4", []any{kind}, err
	}
	return "", nil, nil
}
func libraryMatchBlockFolder(ctx context.Context, db runtimeDB, folder record, blockID any) error {
	var hasCompetence bool
	if err := db.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM element_block_competence WHERE block_id=$1)`, blockID).Scan(&hasCompetence); err != nil {
		return err
	}
	kind := "exercise"
	if hasCompetence {
		kind = "competence"
	}
	if kind != libraryBlockKind(folder["library_kind"]) {
		return platform.Error(400, "Block library kind does not match destination folder")
	}
	return nil
}
