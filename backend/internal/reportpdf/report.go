package reportpdf

import "time"

// Report contains only visible values. Database access and authorization belong
// to the training service, so preview and stored routes share this representation.
type Report struct {
	Title        string
	TrainingID   int64
	AssessmentID int64
	Role         string
	CompletedAt  *time.Time
	GeneratedAt  time.Time
	AircraftCode string
	Trainee      Person
	Instructor   Person
	Durations    Durations
	Grades       []Grade
	Comments     []Comment
	LatestSwap   *RoleChange
	Summary      string
	Result       *bool
}

type Person struct {
	Name         string
	License      string
	Position     string
	AircraftType string
	Signature    []byte
}

type Durations struct {
	PFMs   int64
	PMMs   int64
	Source string
}

type Grade struct {
	Code       string
	Name       string
	OrderIndex int64
	ID         int64
	Label      string
	ColorHex   string
}

type Comment struct {
	CompetenceCode string
	Positive       bool
	IndicatorCode  string
	IndicatorName  string
	Text           string
}

type RoleChange struct {
	Revision      int64
	AcceptedAt    time.Time
	ExerciseLabel string
	Attempt       *int64
	OffsetMs      *int64
	Before        string
	After         string
}
