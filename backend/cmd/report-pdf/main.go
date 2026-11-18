package main

import (
	"encoding/json"
	"fmt"
	"os"

	"north55/backend/internal/reportpdf"
)

func main() {
	if len(os.Args) != 3 {
		fmt.Fprintln(os.Stderr, "usage: report-pdf input.json output.pdf")
		os.Exit(2)
	}
	if err := render(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func render() error {
	raw, err := os.ReadFile(os.Args[1])
	if err != nil {
		return err
	}
	var report reportpdf.Report
	if err := json.Unmarshal(raw, &report); err != nil {
		return err
	}
	data, err := reportpdf.Render(report)
	if err != nil {
		return err
	}
	return os.WriteFile(os.Args[2], data, 0600)
}
